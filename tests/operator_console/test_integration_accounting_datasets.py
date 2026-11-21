import unittest
from unittest import mock
from ezllmrouter_server.integration_accounting import IntegrationError
from ezllmrouter_server.registry import Registry
from .accounting_support import Authority
from . import accounting_support


class AccountingDatasetTests(accounting_support.AccountingHTTPFixture, unittest.TestCase):
    @mock.patch(
        "ezllmrouter_server.integration_accounting._time", return_value="2026-11-03T00:00:00Z"
    )
    def test_local_real_cohort_expiry_at_t0_boundary(self, clock):
        owner = {"principal_id": "owner.local", "owner": "owner.local", "role": "registry_admin"}
        accounting = self.registry.integration
        accounting.accounting_retention_days = 1
        did = "dataset.local.real.retention.controlled"
        real = {**self.dataset, "dataset_id": did, "activated_at": "2026-11-03T00:00:00Z"}
        synthetic = {
            **self.dataset,
            "dataset_id": "dataset.synthetic.retention.controlled",
            "activated_at": "2026-11-03T00:00:00Z",
        }
        accounting.create_dataset(owner, real)
        accounting.create_dataset(owner, synthetic)
        account = {**self.account, "dataset_id": did, "account_id": "account.local.real.retention"}
        accounting.create_account(owner, account)
        self.assertEqual(accounting._dataset(did)["dataset_id"], did)
        clock.return_value = "2026-11-03T23:59:59Z"
        self.assertEqual(accounting.expire_datasets(), 0)
        self.assertIsNotNone(
            self.store.db.execute(
                "SELECT 1 FROM integration_accounts WHERE dataset_id=?", (did,)
            ).fetchone()
        )
        restarted = Registry(self.store, Authority())
        self.assertEqual(restarted.integration.expire_datasets(), 0)
        clock.return_value = "2026-11-04T00:00:00Z"
        self.assertEqual(restarted.integration.expire_datasets(), 1)
        self.assertIsNone(
            self.store.db.execute(
                "SELECT 1 FROM integration_accounts WHERE dataset_id=?", (did,)
            ).fetchone()
        )
        self.assertIsNone(
            self.store.db.execute(
                "SELECT 1 FROM integration_account_history WHERE id=?", (account["account_id"],)
            ).fetchone()
        )
        with self.assertRaisesRegex(IntegrationError, "NOT_FOUND_OR_FORBIDDEN"):
            accounting._dataset(did)
        self.assertEqual(
            accounting._dataset(synthetic["dataset_id"])["dataset_id"], synthetic["dataset_id"]
        )
        with self.assertRaisesRegex(IntegrationError, "DATASET_EXPIRED"):
            accounting.create_dataset(owner, real)

    @mock.patch(
        "ezllmrouter_server.integration_accounting._time", return_value="2099-01-01T00:00:00Z"
    )
    def test_v3_speech_opt_in_and_model_scope(self, _clock):
        def api(method, path, body=None, admin=False):
            return self.request(method, "/integration/v3" + path, body, admin=admin, version="3")

        did = "dataset.speech.v3"
        dataset = {**self.dataset, "dataset_id": did}
        account, allowed, selector = _check_speech_account_eligibility(
            _clock, api, dataset, did, self
        )
        _check_speech_decision_and_usage(account, allowed, api, did, selector, self)


def _check_speech_account_eligibility(_clock, api, dataset, did, self):
    self.assertEqual(api("POST", "/datasets", dataset, True)[0], 201)
    account = {
        **self.account,
        "dataset_id": did,
        "account_id": "account.speech.v3",
        "allowed_models": ["model.allowed"],
        "allowed_operations": [],
    }
    self.assertEqual(api("POST", "/accounts", account, True)[0], 201)
    selector = f"/accounts/{account['account_id']}/eligibility?dataset_id={did}&operation_family=speech_input&capability=transcription&selection_kind=not_applicable"
    status, denied = api("GET", selector)
    self.assertEqual(status, 200)
    self.assertEqual((denied["usable"], denied["reason"]), (False, "operation_not_permitted"))
    _clock.return_value = "2099-01-01T00:00:01Z"
    self.assertEqual(
        api(
            "POST",
            f"/accounts/{account['account_id']}/permissions",
            {
                "dataset_id": did,
                "expected_revision": 1,
                "allowed_models": ["model.allowed"],
                "allowed_operations": ["speech_input"],
            },
            True,
        )[0],
        200,
    )
    _clock.return_value = "2099-01-01T00:00:02Z"
    status, allowed = api("GET", selector)
    self.assertEqual((status, allowed["usable"], allowed["account_revision"]), (200, True, 2))
    self.assertEqual(allowed["provider_id"], account["provider_id"])
    self.assertEqual(allowed["credential_ref"], account["credential_ref"])
    self.assertEqual(
        api(
            "GET",
            selector.replace(
                "speech_input&capability=transcription", "speech_output&capability=synthesis"
            ),
        )[1]["reason"],
        "operation_not_permitted",
    )
    known = selector.replace(
        "selection_kind=not_applicable", "selection_kind=known_model&model_id=model.denied"
    )
    self.assertEqual(api("GET", known)[1]["reason"], "model_not_permitted")
    self.assertEqual(
        api("GET", selector.replace("capability=transcription", "capability=synthesis"))[0], 400
    )
    self.assertEqual(
        api(
            "GET",
            selector.replace("selection_kind=not_applicable", "selection_kind=known_model"),
        )[0],
        400,
    )
    self.assertEqual(api("GET", selector.replace(did, "dataset.other"))[0], 404)
    self.assertEqual(api("GET", selector.replace(account["account_id"], "account.other"))[0], 404)
    old = {**self.account, "dataset_id": did, "account_id": "account.legacy.v3"}
    self.assertEqual(
        self.request("POST", "/integration/v2/accounts", old, admin=True, version="2")[0], 201
    )
    self.assertEqual(
        api("GET", selector.replace(account["account_id"], old["account_id"]))[1]["reason"],
        "operation_not_permitted",
    )
    empty = {
        **account,
        "account_id": "account.empty.v3",
        "allowed_models": [],
        "allowed_operations": [],
    }
    self.assertEqual(api("POST", "/accounts", empty, True)[0], 201)
    self.assertEqual(
        api("GET", selector.replace(account["account_id"], empty["account_id"]))[1]["reason"],
        "operation_not_permitted",
    )
    _clock.return_value = "2099-01-01T00:00:04Z"
    self.assertEqual(
        api(
            "POST",
            f"/accounts/{account['account_id']}/state",
            {"dataset_id": did, "expected_revision": 2, "state": "disabled"},
            True,
        )[0],
        200,
    )
    return account, allowed, selector


def _check_speech_decision_and_usage(account, allowed, api, did, selector, self):
    self.assertEqual(api("GET", selector)[1]["reason"], "account_disabled")
    at = "2099-01-01T00:00:03Z"
    aid = "attempt.speech.v3"
    evidence = {"status": "verified", "eligibility_id": allowed["eligibility_id"]}
    action = {
        "selected_account_id": account["account_id"],
        "operation_family": "speech_input",
        "capability": "transcription",
        "selection_kind": "not_applicable",
        "policy_version": "policy.synthetic.v3",
        "eligibility_evidence": evidence,
    }
    snapshot = {
        "integration_version": "3",
        "dataset_id": did,
        "attempt_id": aid,
        "schema_version": "1",
        "producer_version": "synthetic.test.v3",
        "provenance": "synthetic",
        "source_at": "2099-01-01T00:00:02Z",
        "available_at": "2099-01-01T00:00:02Z",
        "classification": "low",
        "retention_until": "2099-01-02T00:00:00Z",
    }
    self.assertEqual(
        api(
            "POST",
            "/snapshots",
            {
                **snapshot,
                "snapshot_id": "feature.speech.v3",
                "snapshot_kind": "feature",
                "status": "not_collected",
            },
        )[0],
        201,
    )
    self.assertEqual(
        api(
            "POST",
            "/snapshots",
            {
                **snapshot,
                "snapshot_id": "decision.speech.v3",
                "snapshot_kind": "decision",
                "status": "captured",
                "selected_action": action,
            },
        )[0],
        201,
    )
    decision = {
        "integration_version": "3",
        "event_id": "event.speech.decision",
        "dataset_id": did,
        "kind": "decision",
        "occurred_at": at,
        "attempt_id": aid,
        "decision_ref": "decision.speech.v3",
        **action,
    }
    self.assertEqual(api("POST", "/events", decision)[0], 201)
    self.assertEqual(api("POST", "/events", decision)[0], 200)
    self.assertEqual(
        api(
            "POST",
            "/events",
            {
                **decision,
                "event_id": "event.speech.wrong",
                "operation_family": "speech_output",
                "capability": "synthesis",
            },
        )[0],
        409,
    )
    self.assertEqual(
        api(
            "POST",
            "/events",
            {
                **decision,
                "event_id": "event.speech.other",
                "attempt_id": "attempt.speech.other",
                "decision_ref": "decision.speech.other",
                "operation_family": "speech_output",
                "capability": "synthesis",
            },
        )[0],
        409,
    )
    start = {
        "integration_version": "3",
        "event_id": "event.speech.start",
        "dataset_id": did,
        "kind": "attempt_started",
        "occurred_at": at,
        "started_at": at,
        "attempt_id": aid,
        "task_id": "task.speech.v3",
        "step_id": "step.speech.v3",
        "run_id": "run.speech.v3",
        "root_run_id": "run.speech.v3",
        "actor_kind": "service",
        "actor_id": "service.voice.synthetic",
        "provider_account_id": account["account_id"],
        "context_ref": "feature.speech.v3",
        "operation_family_version": "1",
        "operation_family": "speech_input",
        "model_identity_state": "not_applicable",
        "logical_operation_id": "operation.speech.v3",
        "attempt_role": "initial",
    }
    self.assertEqual(api("POST", "/events", start)[0], 201)
    result = {
        "integration_version": "3",
        "event_id": "event.speech.result",
        "dataset_id": did,
        "kind": "result",
        "occurred_at": "2099-01-01T00:00:05Z",
        "attempt_id": aid,
        "result_state": "completed",
    }
    usage = {
        "integration_version": "3",
        "event_id": "event.speech.usage",
        "dataset_id": did,
        "kind": "usage",
        "occurred_at": "2099-01-01T00:00:05Z",
        "attempt_id": aid,
        "usage_revision": 1,
        "usage_state": "known",
        "cost_state": "unknown",
        "native_units": [{"unit": "bytes", "quantity_decimal": "17"}],
        "usage_provenance": "provider_reported",
    }
    self.assertEqual(api("POST", "/events", result)[0], 201)
    self.assertEqual(api("POST", "/events", usage)[0], 201)
    status, report = api("GET", f"/reports/usage?dataset_id={did}", admin=True)
    self.assertEqual(status, 200, report)
    self.assertEqual((report["attempt_count"], report["unknown_cost_attempts"]), (1, 1))
    self.assertEqual(report["attempts"][0]["eligibility_assessment"], "verified")
    export = api("GET", f"/reports/dataset?dataset_id={did}", admin=True)[1]
    self.assertEqual((len(export["attempts"]), len(export["eligibility_reads"])), (1, 1))
