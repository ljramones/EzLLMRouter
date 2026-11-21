import csv
import io
import json
import unittest
from unittest import mock
from . import accounting_support


class AccountingEligibilityTests(accounting_support.AccountingHTTPFixture, unittest.TestCase):
    def test_correction02_eligibility_same_second_and_unambiguous(self):
        with mock.patch(
            "ezllmrouter_server.integration_accounting._time", return_value="2099-01-01T00:00:00Z"
        ):
            api, did, account, base = self.correction02_fixture("eligibility")
            answer = api(
                "GET",
                "/accounts/"
                + account["account_id"]
                + "/eligibility?dataset_id="
                + did
                + "&model_id=model.synthetic",
            )[1]
            first = {
                **base,
                "event_id": "event.first",
                "attempt_id": "attempt.first",
                "context_ref": "feature.first",
                "started_at": "2099-01-01T00:00:01Z",
                "occurred_at": "2099-01-01T00:00:01Z",
            }
            second = {
                **first,
                "event_id": "event.second",
                "attempt_id": "attempt.second",
                "context_ref": "feature.second",
            }
            for item in (first, second):
                self.assertEqual(api("POST", "/events", item)[0], 201)
            decision = {
                "integration_version": "2",
                "event_id": "event.decision.first",
                "dataset_id": did,
                "kind": "decision",
                "occurred_at": "2099-01-01T00:00:00Z",
                "attempt_id": "attempt.first",
                "decision_ref": "decision.first",
                "selected_account_id": account["account_id"],
                "selected_model_id": "model.synthetic",
                "policy_version": "policy.synthetic",
                "eligibility_evidence": {
                    "status": "verified",
                    "eligibility_id": answer["eligibility_id"],
                },
            }
            self.assertEqual(api("POST", "/events", decision)[0], 201)
            self.assertEqual(
                api(
                    "POST",
                    "/accounts/" + account["account_id"] + "/state",
                    {"dataset_id": did, "expected_revision": 1, "state": "disabled"},
                    True,
                )[0],
                200,
            )
            delayed = {
                **decision,
                "event_id": "event.decision.second",
                "attempt_id": "attempt.second",
                "decision_ref": "decision.second",
            }
            self.assertEqual(api("POST", "/events", delayed)[0], 201)
            self.assertEqual(api("POST", "/events", delayed)[0], 200)
            self.assertEqual(
                api("GET", "/events/event.decision.second/receipt?dataset_id=" + did)[0], 200
            )
            report = api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]
            self.assertEqual(
                {row["eligibility_assessment"] for row in report["attempts"]}, {"indeterminate"}
            )
            self.assertEqual(
                {row["eligibility_evidence_status"] for row in report["attempts"]}, {"verified"}
            )
            exported = api("GET", "/reports/dataset?dataset_id=" + did, admin=True)[1]
            self.assertEqual(
                {row["assessment"] for row in exported["eligibility_assessments"]},
                {"indeterminate"},
            )
            self.assertEqual(len(exported["eligibility_reads"]), 1)
            csv_rows = list(
                csv.DictReader(
                    io.StringIO(
                        api("GET", "/reports/usage?dataset_id=" + did + "&export=csv", admin=True)[
                            1
                        ]
                    )
                )
            )
            self.assertEqual({row["eligibility_assessment"] for row in csv_rows}, {"indeterminate"})
        with mock.patch(
            "ezllmrouter_server.integration_accounting._time", return_value="2099-01-01T00:00:01Z"
        ):
            denied = api(
                "GET",
                "/accounts/"
                + account["account_id"]
                + "/eligibility?dataset_id="
                + did
                + "&model_id=model.synthetic",
            )[1]
        stale_start = {
            **first,
            "event_id": "event.stale",
            "attempt_id": "attempt.stale",
            "context_ref": "feature.stale",
            "started_at": "2099-01-01T00:00:03Z",
            "occurred_at": "2099-01-01T00:00:03Z",
        }
        self.assertEqual(api("POST", "/events", stale_start)[0], 201)
        stale = {
            **decision,
            "event_id": "event.decision.stale",
            "attempt_id": "attempt.stale",
            "decision_ref": "decision.stale",
            "occurred_at": "2099-01-01T00:00:02Z",
            "eligibility_evidence": {"status": "stale", "eligibility_id": answer["eligibility_id"]},
        }
        self.assertEqual(api("POST", "/events", stale)[0], 201)
        false_start = {
            **stale_start,
            "event_id": "event.false.start",
            "attempt_id": "attempt.false",
            "context_ref": "feature.false",
        }
        self.assertEqual(api("POST", "/events", false_start)[0], 201)
        self.assertEqual(
            api(
                "POST",
                "/events",
                {
                    **stale,
                    "event_id": "event.false.verified",
                    "attempt_id": "attempt.false",
                    "decision_ref": "decision.false",
                    "eligibility_evidence": {
                        "status": "verified",
                        "eligibility_id": answer["eligibility_id"],
                    },
                },
            )[0],
            400,
        )
        self.assertEqual(
            api(
                "POST",
                "/events",
                {
                    **stale,
                    "event_id": "event.false.model",
                    "attempt_id": "attempt.false",
                    "decision_ref": "decision.false",
                    "selected_model_id": "model.other",
                },
            )[0],
            409,
        )
        denied_start = {
            **stale_start,
            "event_id": "event.denied",
            "attempt_id": "attempt.denied",
            "context_ref": "feature.denied",
        }
        self.assertEqual(api("POST", "/events", denied_start)[0], 201)
        denial = {
            **stale,
            "event_id": "event.decision.denied",
            "attempt_id": "attempt.denied",
            "decision_ref": "decision.denied",
            "eligibility_evidence": {
                "status": "denied",
                "eligibility_id": denied["eligibility_id"],
            },
        }
        self.assertEqual(api("POST", "/events", denial)[0], 201)
        report = api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]
        assessments = {
            row["attempt_id"]: row["eligibility_assessment"] for row in report["attempts"]
        }
        self.assertEqual(assessments["attempt.stale"], "stale")
        self.assertEqual(assessments["attempt.denied"], "denied")

    @mock.patch(
        "ezllmrouter_server.integration_accounting._time", return_value="2099-01-01T00:00:00Z"
    )
    def test_correction02_snapshot_binding_both_orders_and_old_mismatches(self, clock):
        api, did, account, base = self.correction02_fixture("snapshots")
        self.assertEqual(api("POST", "/events", base)[0], 201)
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
        self.assertEqual(api("POST", "/snapshots", feature)[0], 200)
        self.assertEqual(
            api("POST", "/snapshots", {**feature, "features": {"task_category": "different"}})[0],
            409,
        )
        other = {
            **base,
            "event_id": "event.other",
            "attempt_id": "attempt.other",
            "context_ref": "feature.base",
        }
        self.assertEqual(api("POST", "/events", other)[0], 409)
        other["context_ref"] = "feature.pending"
        self.assertEqual(api("POST", "/events", other)[0], 201)
        self.assertEqual(
            api(
                "POST",
                "/snapshots",
                {**feature, "snapshot_id": "feature.pending", "attempt_id": "attempt.foreign"},
            )[0],
            409,
        )
        decision = {
            "integration_version": "2",
            "event_id": "event.decision.other",
            "dataset_id": did,
            "kind": "decision",
            "occurred_at": "2099-01-01T00:00:09Z",
            "attempt_id": "attempt.other",
            "decision_ref": "feature.base",
            "selected_account_id": account["account_id"],
            "selected_model_id": "model.synthetic",
            "policy_version": "policy.synthetic",
            "eligibility_evidence": {"status": "unavailable"},
        }
        self.assertEqual(api("POST", "/events", decision)[0], 409)
        decision["decision_ref"] = "decision.pending"
        self.assertEqual(api("POST", "/events", decision)[0], 201)
        late = {
            **feature,
            "snapshot_id": "decision.pending",
            "attempt_id": "attempt.foreign",
            "snapshot_kind": "decision",
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
        late.pop("features")
        self.assertEqual(api("POST", "/snapshots", late)[0], 409)
        late["attempt_id"] = "attempt.other"
        self.assertEqual(api("POST", "/snapshots", late)[0], 201)
        self.assertEqual(
            api(
                "POST",
                "/snapshots",
                {**feature, "snapshot_id": "feature.pending", "attempt_id": "attempt.other"},
            )[0],
            201,
        )
        wrong_kind_start = {
            **base,
            "event_id": "event.kind",
            "attempt_id": "attempt.kind",
            "context_ref": "feature.kind",
        }
        self.assertEqual(api("POST", "/events", wrong_kind_start)[0], 201)
        self.assertEqual(
            api(
                "POST",
                "/snapshots",
                {**feature, "snapshot_id": "feature.kind", "attempt_id": "attempt.kind"},
            )[0],
            201,
        )
        self.assertEqual(
            api(
                "POST",
                "/events",
                {
                    **decision,
                    "event_id": "event.kind.decision",
                    "attempt_id": "attempt.kind",
                    "decision_ref": "feature.kind",
                },
            )[0],
            409,
        )
        before_start = {**late, "snapshot_id": "feature.wrong.kind", "attempt_id": "attempt.future"}
        self.assertEqual(api("POST", "/snapshots", before_start)[0], 201)
        self.assertEqual(
            api(
                "POST",
                "/events",
                {
                    **base,
                    "event_id": "event.future",
                    "attempt_id": "attempt.future",
                    "context_ref": "feature.wrong.kind",
                },
            )[0],
            409,
        )
        report = api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]
        rows = {row["attempt_id"]: row for row in report["attempts"]}
        self.assertEqual(rows["attempt.other"]["decision_snapshot_status"], "captured")
        self.assertEqual(rows["attempt.other"]["feature_snapshot_status"], "captured")
        # Model an immutable mismatch accepted by the predecessor build.
        with self.store._lock:
            raw = self.store.db.execute(
                "SELECT record FROM integration_attempts WHERE dataset_id=? AND attempt_id=?",
                (did, "attempt.other"),
            ).fetchone()[0]
            old = {**json.loads(raw), "context_ref": "feature.base"}
            self.store.db.execute(
                "UPDATE integration_attempts SET record=? WHERE dataset_id=? AND attempt_id=?",
                (json.dumps(old), did, "attempt.other"),
            )
            raw = self.store.db.execute(
                "SELECT record FROM integration_events WHERE dataset_id=? AND event_id=?",
                (did, "event.decision.other"),
            ).fetchone()[0]
            old_decision = {**json.loads(raw), "decision_ref": "feature.base"}
            self.store.db.execute(
                "UPDATE integration_events SET record=? WHERE dataset_id=? AND event_id=?",
                (json.dumps(old_decision), did, "event.decision.other"),
            )
        report = api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]
        row = next(row for row in report["attempts"] if row["attempt_id"] == "attempt.other")
        self.assertEqual(row["feature_snapshot_status"], "binding_conflict")
        self.assertEqual(row["decision_snapshot_status"], "binding_conflict")
        self.assertIsNone(row["feature_snapshot_digest"])
        self.assertIsNone(row["decision_snapshot_digest"])
        csv_rows = list(
            csv.DictReader(
                io.StringIO(
                    api("GET", "/reports/usage?dataset_id=" + did + "&export=csv", admin=True)[1]
                )
            )
        )
        self.assertEqual(
            next(row for row in csv_rows if row["attempt_id"] == "attempt.other")[
                "decision_snapshot_status"
            ],
            "binding_conflict",
        )
        exported = api("GET", "/reports/dataset?dataset_id=" + did, admin=True)[1]
        self.assertEqual(
            {
                item["status"]
                for item in exported["snapshot_reference_assessments"]
                if item["attempt_id"] == "attempt.other"
            },
            {"binding_conflict"},
        )
        clock.return_value = "2099-01-03T00:00:00Z"
        report = api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]
        self.assertEqual(
            next(row for row in report["attempts"] if row["attempt_id"] == "attempt.base")[
                "feature_snapshot_status"
            ],
            "expired",
        )
