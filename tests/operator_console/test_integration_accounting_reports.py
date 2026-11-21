import csv
from decimal import Decimal
import io
import unittest
from unittest import mock
from .accounting_support import EXAMPLES
from . import accounting_support


class AccountingReportTests(accounting_support.AccountingHTTPFixture, unittest.TestCase):
    @mock.patch(
        "ezllmrouter_server.integration_accounting._time", return_value="2099-01-01T00:00:00Z"
    )
    def test_correction02_usage_state_json_csv_and_export(self, _clock):
        api, did, _, base = self.correction02_fixture("usage")
        for suffix in ("both", "units", "cost", "unknown", "absent"):
            item = {
                **base,
                "event_id": "event.start." + suffix,
                "attempt_id": "attempt." + suffix,
                "context_ref": "feature." + suffix,
            }
            self.assertEqual(api("POST", "/events", item)[0], 201)
        template = {
            "integration_version": "2",
            "dataset_id": did,
            "kind": "usage",
            "occurred_at": "2099-01-01T00:00:20Z",
            "usage_revision": 1,
        }
        units = {
            "usage_state": "known",
            "native_units": [{"unit": "input_tokens", "quantity_decimal": "8"}],
            "usage_provenance": "provider_reported",
        }
        cost = {
            "cost_state": "known",
            "currency": "USD",
            "amount_decimal": "0.010000000",
            "cost_basis": "provider_reported",
            "price_ref": "tariff.synthetic",
            "price_version": "v1",
        }
        for suffix, fields in (
            ("both", {**units, **cost}),
            ("units", {**units, "cost_state": "unknown"}),
            ("cost", {"usage_state": "unknown", **cost}),
            ("unknown", {"usage_state": "unknown", "cost_state": "unknown"}),
        ):
            event = {
                **template,
                "event_id": "event.usage." + suffix,
                "attempt_id": "attempt." + suffix,
                **fields,
            }
            self.assertEqual(api("POST", "/events", event)[0], 201)
            self.assertEqual(api("POST", "/events", event)[0], 200)
        report = api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]
        rows = {row["attempt_id"]: row for row in report["attempts"]}
        self.assertEqual(
            {aid: row["usage_state"] for aid, row in rows.items()},
            {
                "attempt.both": "known",
                "attempt.units": "known",
                "attempt.cost": "unknown",
                "attempt.unknown": "unknown",
                "attempt.absent": "not_observed",
            },
        )
        self.assertEqual(
            {aid: row["cost_status"] for aid, row in rows.items()},
            {
                "attempt.both": "known",
                "attempt.units": "unknown",
                "attempt.cost": "known",
                "attempt.unknown": "unknown",
                "attempt.absent": "not_observed",
            },
        )
        self.assertEqual(report["known_total_by_currency"], {"USD": "0.020000000"})
        self.assertEqual(report["unknown_cost_attempts"], 3)
        self.assertEqual(rows["attempt.units"]["native_units"], units["native_units"])
        self.assertEqual(rows["attempt.units"]["usage_observed_at"], "2099-01-01T00:00:20Z")
        self.assertIsNone(rows["attempt.absent"]["usage_observed_at"])
        csv_rows = {
            row["attempt_id"]: row
            for row in csv.DictReader(
                io.StringIO(
                    api("GET", "/reports/usage?dataset_id=" + did + "&export=csv", admin=True)[1]
                )
            )
        }
        self.assertEqual(
            {aid: row["usage_state"] for aid, row in csv_rows.items()},
            {aid: row["usage_state"] for aid, row in rows.items()},
        )
        self.assertEqual(csv_rows["attempt.units"]["usage_observed_at"], "2099-01-01T00:00:20Z")
        self.assertEqual(
            sum(
                (
                    Decimal(row["amount_decimal"])
                    for row in csv_rows.values()
                    if row["amount_decimal"]
                ),
                Decimal(0),
            ),
            Decimal("0.020000000"),
        )
        exported = api("GET", "/reports/dataset?dataset_id=" + did, admin=True)[1]
        effective = {
            e["attempt_id"]: e["usage_state"] for e in exported["events"] if e["kind"] == "usage"
        }
        self.assertEqual(
            effective,
            {
                aid: row["usage_state"]
                for aid, row in rows.items()
                if row["usage_state"] != "not_observed"
            },
        )

    @mock.patch(
        "ezllmrouter_server.integration_accounting._time", return_value="2099-01-01T00:00:00Z"
    )
    def test_correction_v2_accounting_lineage_snapshots_and_export(self, _clock):
        dataset = {**self.dataset, "dataset_id": "dataset.correction.01"}
        account = {
            **self.account,
            "dataset_id": dataset["dataset_id"],
            "account_id": "account:correct:01",
        }
        did = dataset["dataset_id"]
        api = lambda method, path, body=None, admin=False: self.request(
            method, "/integration/v2" + path, body, admin=admin, version="2"
        )
        self.assertEqual(api("POST", "/datasets", dataset, True)[0], 201)
        self.assertEqual(api("POST", "/accounts", account, True)[0], 201)
        eligibility = api(
            "GET",
            "/accounts/account%3Acorrect%3A01/eligibility?dataset_id="
            + did
            + "&model_id=model.synthetic",
        )[1]
        self.assertTrue(eligibility["usable"])
        self.assertEqual(
            api(
                "GET",
                "/accounts/account%3Acorrect%3A01/eligibility?dataset_id="
                + did
                + "&model_id=model.synthetic",
            )[0],
            200,
        )
        start = {
            **EXAMPLES["events"][2],
            "integration_version": "2",
            "dataset_id": did,
            "event_id": "event.TimeZ",
            "attempt_id": "attempt.base",
            "started_at": "2099-01-01T00:00:10Z",
            "occurred_at": "2099-01-01T00:00:10Z",
            "run_id": "run.correction",
            "root_run_id": "run.correction",
            "task_id": "task.correction",
            "context_ref": "feature.base",
            "provider_account_id": account["account_id"],
            "operation_family_version": "1",
            "operation_family": "generation",
            "model_identity_state": "known",
            "logical_operation_id": "logical.one",
            "attempt_role": "initial",
        }
        start.pop("parent_run_id")
        self.assertEqual(api("POST", "/events", start)[0], 201)
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
            "retention_until": "2099-12-31T00:00:00Z",
            "source_expires_at": "2099-12-31T00:00:00Z",
            "features": {
                "task_category": "briefing",
                "modalities": ["text"],
                "input_size": {
                    "unit": "tokens",
                    "quantity_decimal": "10",
                    "provenance": "estimated",
                },
            },
        }
        self.assertEqual(api("POST", "/snapshots", feature)[0], 201)
        self.assertEqual(api("POST", "/snapshots", feature)[0], 200)
        self.assertEqual(
            api("GET", "/snapshots/feature.base?dataset_id=" + did)[1]["features"],
            feature["features"],
        )
        self.assertEqual(
            api(
                "POST",
                "/snapshots",
                {**feature, "snapshot_id": "feature.bad", "features": {"raw_prompt": "secret"}},
            )[0],
            400,
        )
        decision = {
            "integration_version": "2",
            "event_id": "event.decision.base",
            "dataset_id": did,
            "kind": "decision",
            "occurred_at": "2099-01-01T00:00:09Z",
            "attempt_id": "attempt.base",
            "decision_ref": "decision.base",
            "selected_account_id": account["account_id"],
            "selected_model_id": "model.synthetic",
            "policy_version": "policy.synthetic",
            "eligibility_evidence": {
                "status": "verified",
                "eligibility_id": eligibility["eligibility_id"],
            },
        }
        self.assertEqual(api("POST", "/events", decision)[0], 201)
        decision_snapshot = {
            **feature,
            "snapshot_id": "decision.base",
            "snapshot_kind": "decision",
            "available_at": "2099-01-01T00:00:09Z",
            "selected_action": {
                key: decision[key]
                for key in (
                    "selected_account_id",
                    "selected_model_id",
                    "policy_version",
                    "eligibility_evidence",
                )
            },
        }
        decision_snapshot.pop("features")
        self.assertEqual(api("POST", "/snapshots", decision_snapshot)[0], 201)
        usage = {
            "integration_version": "2",
            "event_id": "event.usage.base.1",
            "dataset_id": did,
            "kind": "usage",
            "occurred_at": "2099-01-01T00:00:20Z",
            "attempt_id": "attempt.base",
            "usage_revision": 1,
            "usage_state": "known",
            "cost_state": "unknown",
            "native_units": [{"unit": "input_tokens", "quantity_decimal": "10"}],
            "usage_provenance": "provider_reported",
        }
        self.assertEqual(api("POST", "/events", usage)[0], 201)
        report = api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]
        self.assertEqual(report["attempts"][0]["native_units"], usage["native_units"])
        self.assertEqual(report["unknown_cost_attempts"], 1)
        self.assertIsNone(report["attempts"][0]["amount_decimal"])
        second = {
            **usage,
            "event_id": "event.usage.base.2",
            "usage_revision": 2,
            "cost_state": "known",
            "currency": "USD",
            "amount_decimal": "0.020000000",
            "cost_basis": "provider_reported",
            "price_ref": "tariff.synthetic",
            "price_version": "v1",
        }
        self.assertEqual(api("POST", "/events", second)[0], 201)
        self.assertEqual(api("POST", "/events", second)[0], 200)
        self.assertEqual(
            api("POST", "/events", {**second, "event_id": "event.gap", "usage_revision": 4})[0], 201
        )
        report = api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]
        self.assertEqual(report["known_total_by_currency"], {"USD": "0.020000000"})
        self.assertEqual(report["attempts"][0]["usage_revision"], 2)
        self.assertEqual(
            report["attempts"][0]["eligibility_record"]["eligibility_id"],
            eligibility["eligibility_id"],
        )
        self.assertEqual(report["attempts"][0]["feature_snapshot_status"], "captured")
        self.assertEqual(report["attempts"][0]["decision_snapshot_status"], "captured")
        retry = {
            **start,
            "event_id": "event.retry",
            "attempt_id": "attempt.retry",
            "context_ref": "feature.retry",
            "started_at": "2099-01-01T00:00:11Z",
            "attempt_role": "retry",
            "predecessor_attempt_id": "attempt.base",
        }
        self.assertEqual(api("POST", "/events", retry)[0], 201)
        self.assertEqual(
            api(
                "POST",
                "/events",
                {
                    **retry,
                    "event_id": "event.self",
                    "attempt_id": "attempt.self",
                    "predecessor_attempt_id": "attempt.self",
                },
            )[0],
            400,
        )
        unresolved = {
            **start,
            "event_id": "event.unresolved",
            "attempt_id": "attempt.unresolved",
            "provider_account_id": "account.unregistered",
            "model_identity_state": "not_applicable",
            "operation_family": "search",
            "logical_operation_id": "logical.other",
            "attempt_role": "fanout",
            "context_ref": "feature.unavailable",
        }
        unresolved.pop("model_id")
        self.assertEqual(api("POST", "/events", unresolved)[0], 201)
        unpriced = {
            **usage,
            "event_id": "event.unresolved.usage",
            "attempt_id": "attempt.unresolved",
            "usage_state": "unknown",
            "cost_state": "known",
            "currency": "USD",
            "amount_decimal": "0.010000000",
            "cost_basis": "provider_reported",
            "price_ref": "tariff.synthetic",
            "price_version": "v1",
        }
        unpriced.pop("native_units")
        unpriced.pop("usage_provenance")
        self.assertEqual(api("POST", "/events", unpriced)[0], 201)
        report = api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]
        self.assertEqual(report["known_total_by_currency"], {"USD": "0.030000000"})
        self.assertEqual(
            next(x for x in report["attempts"] if x["attempt_id"] == "attempt.unresolved")[
                "account_resolution_status"
            ],
            "unresolved",
        )
        self.assertEqual(
            next(x for x in report["attempts"] if x["attempt_id"] == "attempt.retry")[
                "lineage_status"
            ],
            "linked",
        )
        exported = api("GET", "/reports/dataset?dataset_id=" + did, admin=True)[1]
        self.assertEqual(len(exported["attempts"]), 3)
        self.assertEqual(len(exported["eligibility_reads"]), 1)
        self.assertEqual(len(exported["snapshots"]), 2)
        status, csv_data = api(
            "GET", "/reports/usage?dataset_id=" + did + "&export=csv", admin=True
        )
        self.assertEqual(status, 200)
        csv_rows = list(csv.DictReader(io.StringIO(csv_data)))
        self.assertEqual(
            sum(
                (Decimal(x["amount_decimal"]) for x in csv_rows if x["amount_decimal"]), Decimal(0)
            ),
            Decimal("0.03"),
        )
