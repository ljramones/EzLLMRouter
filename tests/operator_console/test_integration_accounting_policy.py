from pathlib import Path
import sqlite3
import unittest
from unittest import mock
from ezllmrouter_server.integration_accounting import IntegrationError
from ezllmrouter_server.registry import Registry
from ezllmrouter_server.store import SQLiteStore
from .accounting_support import EXAMPLES, Authority
from . import accounting_support


class AccountingPolicyTests(accounting_support.AccountingHTTPFixture, unittest.TestCase):
    @mock.patch(
        "ezllmrouter_server.integration_accounting._time", return_value="2099-01-01T00:00:00Z"
    )
    def test_correction_v2_negative_policy_lineage_and_expiry(self, clock):
        did = "dataset.correction.negative"
        dataset = {**self.dataset, "dataset_id": did}
        api = lambda method, path, body=None, admin=False: self.request(
            method, "/integration/v2" + path, body, admin=admin, version="2"
        )
        self.assertEqual(api("POST", "/datasets", dataset, True)[0], 201)
        account = {**self.account, "dataset_id": did, "account_id": "account:negative"}
        self.assertEqual(api("POST", "/accounts", account, True)[0], 201)
        pending, start = _check_negative_event_and_lineage_validation(account, api, did, self)
        _check_foreign_and_denied_accounting_bindings(
            account, api, dataset, did, pending, self, start
        )
        report = api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]
        self.assertEqual(
            next(x for x in report["attempts"] if x["attempt_id"] == "attempt.denied")[
                "eligibility_evidence_status"
            ],
            "denied",
        )
        self.assertEqual(
            next(x for x in report["attempts"] if x["attempt_id"] == "attempt.pending")[
                "lineage_status"
            ],
            "pending_predecessor",
        )
        self.assertEqual(api("GET", "/reports/dataset?dataset_id=" + did)[0], 404)
        _check_expired_accounting_snapshots(api, did, self)


def _check_negative_event_and_lineage_validation(account, api, did, self):
    invalid_date = {
        **EXAMPLES["events"][0],
        "integration_version": "2",
        "dataset_id": did,
        "event_id": "event.invalid.date",
        "occurred_at": "2099-02-30T00:00:00Z",
    }
    self.assertEqual(api("POST", "/events", invalid_date)[0], 400)
    missing_outcome = {
        **invalid_date,
        "occurred_at": "2099-01-01T00:00:05Z",
        "activity_kind": "outcome",
    }
    self.assertEqual(api("POST", "/events", missing_outcome)[0], 400)
    start = {
        **EXAMPLES["events"][2],
        "integration_version": "2",
        "dataset_id": did,
        "event_id": "event.start.base",
        "attempt_id": "attempt.base",
        "started_at": "2099-01-01T00:00:10Z",
        "occurred_at": "2099-01-01T00:00:10Z",
        "run_id": "run.negative",
        "root_run_id": "run.negative",
        "task_id": "task.negative",
        "provider_account_id": account["account_id"],
        "context_ref": "feature.base",
        "operation_family_version": "1",
        "operation_family": "embedding",
        "model_identity_state": "known",
        "logical_operation_id": "logical.negative",
        "attempt_role": "initial",
    }
    start.pop("parent_run_id")
    self.assertEqual(api("POST", "/events", start)[0], 201)
    for family in (
        "speech_input",
        "speech_output",
        "search",
        "realtime",
        "rerank",
        "other",
        "unknown",
    ):
        item = {
            **start,
            "event_id": "event." + family,
            "attempt_id": "attempt." + family,
            "context_ref": "feature." + family,
            "operation_family": family,
            "logical_operation_id": "logical." + family,
            "model_identity_state": "not_applicable",
            "attempt_role": "fanout",
        }
        item.pop("model_id")
        self.assertEqual(api("POST", "/events", item)[0], 201)
    zero = {
        "integration_version": "2",
        "event_id": "event.zero",
        "dataset_id": did,
        "kind": "usage",
        "occurred_at": "2099-01-01T00:00:21Z",
        "attempt_id": "attempt.rerank",
        "usage_revision": 1,
        "usage_state": "unknown",
        "cost_state": "known",
        "currency": "USD",
        "amount_decimal": "0",
        "cost_basis": "provider_reported",
        "price_ref": "tariff.synthetic",
        "price_version": "v1",
    }
    self.assertEqual(api("POST", "/events", zero)[0], 400)
    self.assertEqual(
        api("POST", "/events", {**zero, "zero_basis": "provider.reported.free"})[0], 201
    )
    self.assertEqual(
        api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]["known_total_by_currency"],
        {"USD": "0.000000000"},
    )
    unknown = {
        **start,
        "event_id": "event.late",
        "attempt_id": "attempt.late",
        "context_ref": "feature.late",
        "attempt_role": "unknown",
    }
    self.assertEqual(api("POST", "/events", unknown)[0], 201)
    late_link = {
        "integration_version": "2",
        "event_id": "event.link.late",
        "dataset_id": did,
        "kind": "lineage",
        "occurred_at": "2099-01-01T00:00:30Z",
        "attempt_id": "attempt.late",
        "logical_operation_id": "logical.negative",
        "attempt_role": "retry",
        "predecessor_attempt_id": "attempt.base",
    }
    self.assertEqual(api("POST", "/events", late_link)[0], 201)
    self.assertEqual(
        api("POST", "/events", {**late_link, "event_id": "event.duplicate.link"})[0], 409
    )
    self.assertEqual(
        api(
            "POST",
            "/events",
            {
                **late_link,
                "event_id": "event.cross.logical",
                "attempt_id": "attempt.search",
                "logical_operation_id": "logical.search",
            },
        )[0],
        409,
    )
    pending = {
        **start,
        "event_id": "event.pending",
        "attempt_id": "attempt.pending",
        "context_ref": "feature.pending",
        "attempt_role": "retry",
        "predecessor_attempt_id": "attempt.future",
    }
    self.assertEqual(api("POST", "/events", pending)[0], 201)
    self.assertEqual(
        api(
            "POST",
            "/events",
            {
                **pending,
                "event_id": "event.future",
                "attempt_id": "attempt.future",
                "predecessor_attempt_id": "attempt.pending",
            },
        )[0],
        400,
    )
    return pending, start


def _check_foreign_and_denied_accounting_bindings(account, api, dataset, did, pending, self, start):
    other_dataset = {**dataset, "dataset_id": "dataset.other.owner"}
    self.assertEqual(api("POST", "/datasets", other_dataset, True)[0], 201)
    foreign = {
        **start,
        "dataset_id": other_dataset["dataset_id"],
        "event_id": "event.foreign",
        "attempt_id": "attempt.foreign",
        "context_ref": "feature.foreign",
    }
    self.assertEqual(api("POST", "/events", foreign)[0], 201)
    self.assertEqual(
        api(
            "POST",
            "/events",
            {
                **pending,
                "event_id": "event.cross.dataset",
                "attempt_id": "attempt.cross",
                "predecessor_attempt_id": "attempt.foreign",
            },
        )[0],
        409,
    )
    foreign_account = {
        **account,
        "dataset_id": other_dataset["dataset_id"],
        "account_id": "account.other.dataset",
    }
    self.assertEqual(api("POST", "/accounts", foreign_account, True)[0], 201)
    foreign_start = {
        **start,
        "event_id": "event.foreign.account",
        "attempt_id": "attempt.foreign.account",
        "provider_account_id": foreign_account["account_id"],
        "context_ref": "feature.foreign.account",
    }
    self.assertEqual(api("POST", "/events", foreign_start)[0], 201)
    self.assertEqual(
        api(
            "POST",
            "/events",
            {
                "integration_version": "2",
                "event_id": "event.false.resolve",
                "dataset_id": did,
                "kind": "account_resolution",
                "occurred_at": "2099-01-01T00:00:31Z",
                "attempt_id": "attempt.foreign.account",
                "resolved_account_id": foreign_account["account_id"],
            },
        )[0],
        409,
    )
    with self.assertRaises(IntegrationError):
        self.registry.integration.report(
            {"principal_id": "owner.other", "owner": "owner.other", "role": "registry_admin"},
            did,
            version="2",
        )
    denied = api(
        "GET",
        "/accounts/account%3Anegative/eligibility?dataset_id=" + did + "&model_id=model.disallowed",
    )[1]
    self.assertEqual(denied["reason"], "model_not_permitted")
    denied_start = {
        **start,
        "event_id": "event.denied.start",
        "attempt_id": "attempt.denied",
        "model_id": "model.disallowed",
        "context_ref": "feature.denied",
    }
    self.assertEqual(api("POST", "/events", denied_start)[0], 201)
    denied_decision = {
        "integration_version": "2",
        "event_id": "event.denied.decision",
        "dataset_id": did,
        "kind": "decision",
        "occurred_at": "2099-01-01T00:00:09Z",
        "attempt_id": "attempt.denied",
        "decision_ref": "decision.denied",
        "selected_account_id": account["account_id"],
        "selected_model_id": "model.disallowed",
        "policy_version": "policy.synthetic",
        "eligibility_evidence": {
            "status": "denied",
            "eligibility_id": denied["eligibility_id"],
        },
    }
    self.assertEqual(api("POST", "/events", denied_decision)[0], 201)
    self.assertEqual(
        api(
            "POST",
            "/events",
            {
                **denied_decision,
                "event_id": "event.forged",
                "attempt_id": "attempt.base",
                "eligibility_evidence": {
                    "status": "verified",
                    "eligibility_id": denied["eligibility_id"],
                },
            },
        )[0],
        409,
    )
    self.assertEqual(
        api(
            "POST",
            "/accounts/account%3Anegative/state",
            {"dataset_id": did, "expected_revision": 1, "state": "disabled"},
            True,
        )[0],
        200,
    )


def _check_expired_accounting_snapshots(api, did, self):
    feature = {
        "integration_version": "2",
        "snapshot_id": "feature.base",
        "dataset_id": did,
        "attempt_id": "attempt.base",
        "snapshot_kind": "feature",
        "status": "captured",
        "schema_version": "1",
        "producer_version": "producer.synthetic.1",
        "provenance": "synthetic",
        "source_at": "2099-01-01T00:00:01Z",
        "available_at": "2099-01-01T00:00:02Z",
        "classification": "low",
        "retention_until": "2099-01-02T00:00:00Z",
        "source_expires_at": "2099-01-02T00:00:00Z",
        "features": {"task_category": "briefing"},
    }
    self.assertEqual(api("POST", "/snapshots", feature)[0], 201)
    self.assertEqual(
        api(
            "POST",
            "/snapshots",
            {
                **feature,
                "snapshot_id": "feature.long",
                "retention_until": "2101-01-01T00:00:00Z",
                "source_expires_at": "2101-01-01T00:00:00Z",
            },
        )[0],
        403,
    )
    self.assertEqual(
        api(
            "POST",
            "/snapshots",
            {**feature, "snapshot_id": "feature.real", "provenance": "platform"},
        )[0],
        403,
    )
    backup = Path(self.tmp.name) / "before-expiry.sqlite"
    with self.store._lock, sqlite3.connect(backup) as destination:
        self.store.db.backup(destination)
    with mock.patch(
        "ezllmrouter_server.integration_accounting._time", return_value="2099-01-03T00:00:00Z"
    ):
        expired = api("GET", "/snapshots/feature.base?dataset_id=" + did)[1]
        self.assertEqual(expired["status"], "expired")
        self.assertNotIn("features", expired)
        self.assertEqual(
            api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]["attempts"][0][
                "feature_snapshot_status"
            ],
            "expired",
        )
        copied = SQLiteStore(backup)
        self.addCleanup(copied.close)
        restored = Registry(copied, Authority())
        self.assertEqual(
            restored.integration.snapshot(restored.principal("owner.local"), did, "feature.base")[
                "status"
            ],
            "expired",
        )
        self.assertIsNone(
            copied.db.execute(
                "SELECT content FROM integration_snapshots "
                "WHERE dataset_id=? AND snapshot_id='feature.base'",
                (did,),
            ).fetchone()[0]
        )
