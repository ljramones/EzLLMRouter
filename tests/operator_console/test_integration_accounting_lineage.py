import json
import unittest
from unittest import mock
from .accounting_support import EXAMPLES
from . import accounting_support


class AccountingLineageTests(accounting_support.AccountingHTTPFixture, unittest.TestCase):
    @mock.patch(
        "ezllmrouter_server.integration_accounting._time", return_value="2099-01-01T00:00:00Z"
    )
    def test_correction02_lineage_both_orders_and_historical_conflict(self, _clock):
        api, did, _, base = self.correction02_fixture("lineage")
        link = {
            "integration_version": "2",
            "event_id": "event.link.orphan",
            "dataset_id": did,
            "kind": "lineage",
            "occurred_at": "2099-01-01T00:00:11Z",
            "attempt_id": "attempt.orphan",
            "logical_operation_id": "logical.c02",
            "attempt_role": "fallback",
            "predecessor_attempt_id": "attempt.future",
        }
        self.assertEqual(api("POST", "/events", link)[0], 201)
        orphan = {
            **base,
            "event_id": "event.orphan",
            "attempt_id": "attempt.orphan",
            "context_ref": "feature.orphan",
            "attempt_role": "unknown",
        }
        self.assertEqual(
            api("POST", "/events", {**orphan, "logical_operation_id": "logical.wrong"})[0], 409
        )
        self.assertEqual(api("POST", "/events", {**orphan, "attempt_role": "initial"})[0], 409)
        self.assertEqual(api("POST", "/events", orphan)[0], 201)
        self.assertEqual(
            api(
                "POST",
                "/events",
                {
                    **base,
                    "event_id": "event.future",
                    "attempt_id": "attempt.future",
                    "context_ref": "feature.future",
                    "logical_operation_id": "logical.wrong",
                },
            )[0],
            409,
        )
        self.assertEqual(
            api(
                "POST",
                "/events",
                {
                    **base,
                    "event_id": "event.future.task",
                    "attempt_id": "attempt.future",
                    "context_ref": "feature.future",
                    "task_id": "task.wrong",
                },
            )[0],
            409,
        )
        future = {
            **base,
            "event_id": "event.future",
            "attempt_id": "attempt.future",
            "context_ref": "feature.future",
        }
        self.assertEqual(api("POST", "/events", future)[0], 201)
        self.assertEqual(api("POST", "/events", future)[0], 200)
        self.assertEqual(api("POST", "/events", base)[0], 201)
        self.assertEqual(
            api(
                "POST",
                "/events",
                {
                    **link,
                    "event_id": "event.link.base",
                    "attempt_id": "attempt.base",
                    "predecessor_attempt_id": "attempt.future",
                },
            )[0],
            409,
        )
        late = {
            **base,
            "event_id": "event.late",
            "attempt_id": "attempt.late",
            "context_ref": "feature.late",
            "attempt_role": "unknown",
        }
        self.assertEqual(api("POST", "/events", late)[0], 201)
        late_link = {
            **link,
            "event_id": "event.link.late",
            "attempt_id": "attempt.late",
            "predecessor_attempt_id": "attempt.future",
        }
        self.assertEqual(api("POST", "/events", late_link)[0], 201)
        self.assertEqual(api("POST", "/events", late_link)[0], 200)
        self.assertEqual(
            api(
                "POST",
                "/events",
                {
                    **late_link,
                    "event_id": "event.link.cycle",
                    "attempt_id": "attempt.future",
                    "predecessor_attempt_id": "attempt.late",
                },
            )[0],
            409,
        )
        usage = {
            "integration_version": "2",
            "event_id": "event.usage.orphan",
            "dataset_id": did,
            "kind": "usage",
            "occurred_at": "2099-01-01T00:00:20Z",
            "attempt_id": "attempt.orphan",
            "usage_revision": 1,
            "usage_state": "unknown",
            "cost_state": "known",
            "currency": "USD",
            "amount_decimal": "0.010000000",
            "cost_basis": "provider_reported",
            "price_ref": "tariff.synthetic",
            "price_version": "v1",
        }
        self.assertEqual(api("POST", "/events", usage)[0], 201)
        self.assertEqual(api("POST", "/events", usage)[0], 200)
        report = api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]
        by_id = {row["attempt_id"]: row for row in report["attempts"]}
        self.assertEqual(by_id["attempt.orphan"]["lineage_status"], "linked")
        self.assertEqual(by_id["attempt.late"]["lineage_status"], "linked")
        self.assertEqual(report["known_total_by_currency"], {"USD": "0.010000000"})
        # An older accepted contradiction remains readable but is not a trusted link.
        with self.store._lock:
            row = self.store.db.execute(
                "SELECT record FROM integration_attempts WHERE dataset_id=? AND attempt_id=?",
                (did, "attempt.orphan"),
            ).fetchone()
            corrupted = {**json.loads(row[0]), "logical_operation_id": "logical.wrong"}
            self.store.db.execute(
                "UPDATE integration_attempts SET record=? WHERE dataset_id=? AND attempt_id=?",
                (json.dumps(corrupted), did, "attempt.orphan"),
            )
        report = api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]
        self.assertEqual(
            next(row for row in report["attempts"] if row["attempt_id"] == "attempt.orphan")[
                "lineage_status"
            ],
            "binding_conflict",
        )
        self.assertEqual(report["known_total_by_currency"], {"USD": "0.010000000"})
        unrelated = {
            **base,
            "event_id": "event.unrelated.after.conflict",
            "attempt_id": "attempt.unrelated.after.conflict",
            "context_ref": "feature.unrelated",
            "task_id": "task.unrelated",
            "run_id": "run.unrelated",
            "root_run_id": "run.unrelated",
            "logical_operation_id": "logical.unrelated",
        }
        self.assertEqual(api("POST", "/events", unrelated)[0], 201)
        self.assertEqual(api("POST", "/events", unrelated)[0], 200)
        self.assertEqual(
            api(
                "POST",
                "/events",
                {
                    **unrelated,
                    "event_id": "event.related.to.conflict",
                    "attempt_id": "attempt.related.to.conflict",
                    "context_ref": "feature.related",
                    "task_id": "task.c02",
                    "run_id": "run.c02",
                    "root_run_id": "run.c02",
                    "logical_operation_id": "logical.c02",
                    "attempt_role": "fallback",
                    "predecessor_attempt_id": "attempt.orphan",
                },
            )[0],
            409,
        )
        after = api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]
        self.assertEqual(after["attempt_count"], report["attempt_count"] + 1)
        self.assertEqual(after["known_total_by_currency"], {"USD": "0.010000000"})
        self.assertEqual(
            next(row for row in after["attempts"] if row["attempt_id"] == "attempt.orphan")[
                "lineage_status"
            ],
            "binding_conflict",
        )

    @mock.patch(
        "ezllmrouter_server.integration_accounting._time", return_value="2099-01-01T00:00:00Z"
    )
    def test_correction03_mixed_version_lineage_orders_and_unrelated_work(self, _clock):
        def old_start(did, account, event_id):
            start = {
                **EXAMPLES["events"][2],
                "dataset_id": did,
                "event_id": event_id,
                "attempt_id": "attempt.legacy",
                "occurred_at": "2099-01-01T00:00:10Z",
                "started_at": "2099-01-01T00:00:10Z",
                "task_id": "task.legacy",
                "run_id": "run.legacy",
                "root_run_id": "run.legacy",
                "provider_account_id": account["account_id"],
            }
            start.pop("parent_run_id")
            return start

        def link(did):
            return {
                "integration_version": "2",
                "event_id": "event.link.legacy",
                "dataset_id": did,
                "kind": "lineage",
                "occurred_at": "2099-01-01T00:00:11Z",
                "attempt_id": "attempt.legacy",
                "logical_operation_id": "logical.legacy",
                "attempt_role": "fallback",
                "predecessor_attempt_id": "attempt.pending",
            }

        def unrelated(base, label):
            return {
                **base,
                "event_id": "event.unrelated." + label,
                "attempt_id": "attempt.unrelated." + label,
                "context_ref": "feature.unrelated." + label,
                "task_id": "task.unrelated." + label,
                "run_id": "run.unrelated." + label,
                "root_run_id": "run.unrelated." + label,
                "logical_operation_id": "logical.unrelated." + label,
            }

        api, did, account, base = self.correction02_fixture("mixed.link.first")
        legacy = old_start(did, account, "event.legacy")
        orphan = link(did)
        v1 = lambda value: self.request("POST", "/integration/v1/events", value, version="1")
        first_link = api("POST", "/events", orphan)
        self.assertEqual(first_link[0], 201)
        self.assertEqual(v1(legacy)[0], 409)
        self.assertEqual(api("POST", "/events", orphan), (200, first_link[1]))
        self.assertEqual(
            api("GET", "/events/event.link.legacy/receipt?dataset_id=" + did)[1], first_link[1]
        )
        clean = unrelated(base, "after.rejected.start")
        self.assertEqual(api("POST", "/events", clean)[0], 201)
        self.assertEqual(
            api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]["attempt_count"], 1
        )

        api, did, account, base = self.correction02_fixture("mixed.start.first")
        legacy = old_start(did, account, "event.legacy.second")
        orphan = link(did)
        accepted = v1(legacy)
        self.assertEqual(accepted[0], 201)
        self.assertEqual(api("POST", "/events", orphan)[0], 409)
        self.assertEqual(v1(legacy), (200, accepted[1]))
        self.assertEqual(
            self.request(
                "GET",
                "/integration/v1/events/event.legacy.second/receipt?dataset_id=" + did,
                version="1",
            )[1],
            accepted[1],
        )
        self.assertEqual(api("POST", "/events", unrelated(base, "after.rejected.link"))[0], 201)
        report = api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]
        self.assertEqual(report["attempt_count"], 2)
        self.assertEqual(
            next(row for row in report["attempts"] if row["attempt_id"] == "attempt.legacy")[
                "lineage_status"
            ],
            "legacy_absent",
        )
        self.assertEqual(report["known_total_by_currency"], {})

        api, did, _, base = self.correction02_fixture("pure.v2.control")
        self.assertEqual(api("POST", "/events", base)[0], 201)
        self.assertEqual(
            api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]["attempt_count"], 1
        )

    @mock.patch(
        "ezllmrouter_server.integration_accounting._time", return_value="2099-01-01T00:00:00Z"
    )
    def test_correction03_previously_accepted_mixed_conflict_projection(self, _clock):
        api, did, account, base = self.correction02_fixture("old.mixed")
        link = {
            "integration_version": "2",
            "event_id": "event.old.link",
            "dataset_id": did,
            "kind": "lineage",
            "occurred_at": "2099-01-01T00:00:11Z",
            "attempt_id": "attempt.old.legacy",
            "logical_operation_id": "logical.old",
            "attempt_role": "fallback",
            "predecessor_attempt_id": "attempt.old.pending",
        }
        self.assertEqual(api("POST", "/events", link)[0], 201)
        legacy = {
            **EXAMPLES["events"][2],
            "dataset_id": did,
            "event_id": "event.old.legacy",
            "attempt_id": "attempt.old.legacy",
            "occurred_at": "2099-01-01T00:00:10Z",
            "started_at": "2099-01-01T00:00:10Z",
            "task_id": "task.old",
            "run_id": "run.old",
            "root_run_id": "run.old",
            "provider_account_id": account["account_id"],
        }
        legacy.pop("parent_run_id")
        # Reproduce the predecessor's v1 admission gap through normal HTTP.
        with mock.patch.object(self.registry.integration, "_check_lineage"):
            accepted = self.request("POST", "/integration/v1/events", legacy, version="1")
        self.assertEqual(accepted[0], 201)
        before = list(
            self.store.db.execute(
                "SELECT event_id,digest,record FROM integration_events "
                "WHERE dataset_id=? ORDER BY event_id",
                (did,),
            )
        )
        report = api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]
        self.assertEqual(report["attempts"][0]["lineage_status"], "binding_conflict")
        unrelated = {
            **base,
            "event_id": "event.new.unrelated",
            "attempt_id": "attempt.new.unrelated",
            "context_ref": "feature.new.unrelated",
            "task_id": "task.new",
            "run_id": "run.new",
            "root_run_id": "run.new",
            "logical_operation_id": "logical.new",
        }
        self.assertEqual(api("POST", "/events", unrelated)[0], 201)
        self.assertEqual(api("POST", "/events", unrelated)[0], 200)
        report = api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]
        self.assertEqual(report["attempt_count"], 2)
        self.assertEqual(
            next(row for row in report["attempts"] if row["attempt_id"] == "attempt.old.legacy")[
                "lineage_status"
            ],
            "binding_conflict",
        )
        export = api("GET", "/reports/dataset?dataset_id=" + did, admin=True)[1]
        self.assertEqual(len(export["attempts"]), 2)
        after = list(
            self.store.db.execute(
                "SELECT event_id,digest,record FROM integration_events "
                "WHERE dataset_id=? AND event_id IN ('event.old.link','event.old.legacy') "
                "ORDER BY event_id",
                (did,),
            )
        )
        self.assertEqual(before, after)
