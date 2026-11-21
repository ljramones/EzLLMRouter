import csv
from decimal import Decimal
import io
from pathlib import Path
import sqlite3
import threading
import unittest
from ezllmrouter_server.integration_accounting import IntegrationError
from ezllmrouter_server.registry import Registry
from ezllmrouter_server.store import SQLiteStore
from .accounting_support import EXAMPLES, Authority
from . import accounting_support


class IntegrationTests(accounting_support.AccountingHTTPFixture, unittest.TestCase):
    def test_http_duplicate_conflict_late_revision_and_disabled_account(self):
        self.create()
        base = "/integration/v1/accounts/account.synthetic.01/eligibility?dataset_id=dataset.local.vega.01&model_id=model.synthetic"
        self.assertTrue(self.request("GET", base)[1]["usable"])
        self.assertEqual(self.request("POST", "/integration/v1/datasets", self.dataset)[0], 403)
        events = EXAMPLES["events"]
        # Out-of-order completion and revision 2 retain receipts without cost.
        for item in (events[6], events[5], events[3], events[2], events[0], events[1]):
            self.assertEqual(self.event(item)[0], 201)
        status, report = self.request(
            "GET", "/integration/v1/reports/usage?dataset_id=dataset.local.vega.01", admin=True
        )
        self.assertEqual(status, 200)
        self.assertEqual(report["attempt_count"], 1)
        self.assertEqual(report["unknown_cost_attempts"], 1)
        self.assertEqual(report["known_total_by_currency"], {})
        self.assertEqual(self.event(events[4])[0], 201)
        status, report = self.request(
            "GET", "/integration/v1/reports/usage?dataset_id=dataset.local.vega.01", admin=True
        )
        self.assertEqual(report["known_total_by_currency"], {"USD": "0.030000000"})
        self.assertEqual(report["attempts"][0]["result_state"], "unknown")
        self.assertEqual(self.event(events[4])[0], 200)
        self.assertEqual(
            self.event({**events[4], "usage_state": "known"})[0], 400
        )  # invalid known shape
        self.assertEqual(self.event({**events[4], "occurred_at": "2026-10-27T00:00:22Z"})[0], 409)
        self.assertEqual(
            self.request(
                "GET",
                "/integration/v1/events/event.usage.1.1/receipt?dataset_id=dataset.local.vega.01",
            )[0],
            200,
        )
        self.assertEqual(
            self.request(
                "POST",
                "/integration/v1/accounts/account.synthetic.01/state",
                {
                    "dataset_id": self.dataset["dataset_id"],
                    "expected_revision": 1,
                    "state": "disabled",
                },
                admin=True,
            )[0],
            200,
        )
        self.assertEqual(self.request("GET", base)[1]["reason"], "account_disabled")
        self.assertEqual(
            self.request("POST", "/integration/v1/accounts", self.account, admin=True)[1][
                "revision"
            ],
            1,
        )
        for item in (events[7], events[8]):
            self.assertEqual(self.event(item)[0], 201)  # late accounting remains allowed
        report = self.request(
            "GET", "/integration/v1/reports/usage?dataset_id=dataset.local.vega.01", admin=True
        )[1]
        self.assertEqual(report["known_total_by_currency"], {"USD": "0.050000000"})
        self.assertEqual(report["by_root_workflow"]["run.root"]["USD"], "0.050000000")
        self.assertEqual(report["by_run_including_descendants"]["run.child"]["USD"], "0.050000000")
        self.assertEqual(report["attempt_count"], 2)
        csv_data = self.request(
            "GET",
            "/integration/v1/reports/usage?dataset_id=dataset.local.vega.01&export=csv",
            admin=True,
        )[1]
        csv_rows = list(csv.DictReader(io.StringIO(csv_data)))
        self.assertEqual(
            sum((Decimal(row["amount_decimal"]) for row in csv_rows), Decimal(0)), Decimal("0.05")
        )
        self.assertEqual(len(csv_rows), report["attempt_count"])
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0], 0)
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM dev12_submissions").fetchone()[0], 0
        )
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM dev12_send_ownership").fetchone()[0], 0
        )

    def test_membership_scope_zero_and_noncontiguous_usage(self):
        self.create()
        early = {
            **EXAMPLES["events"][2],
            "event_id": "event.early",
            "attempt_id": "attempt.early",
            "started_at": "2026-10-26T23:59:59Z",
            "occurred_at": "2026-10-26T23:59:59Z",
        }
        self.assertEqual(
            self.event(early)[1]["membership_at_receipt"], "excluded_before_activation"
        )
        late_usage = {
            **EXAMPLES["events"][6],
            "event_id": "event.early.usage",
            "attempt_id": "attempt.early",
        }
        self.assertEqual(self.event(late_usage)[0], 201)
        second_only = {
            **EXAMPLES["events"][6],
            "event_id": "event.gap.usage",
            "attempt_id": "attempt.gap",
        }
        self.assertEqual(self.event(second_only)[0], 201)
        started = {
            **EXAMPLES["events"][2],
            "event_id": "event.gap.start",
            "attempt_id": "attempt.gap",
        }
        self.assertEqual(self.event(started)[0], 201)
        report = self.request(
            "GET", "/integration/v1/reports/usage?dataset_id=dataset.local.vega.01", admin=True
        )[1]
        self.assertEqual(report["attempt_count"], 1)
        self.assertEqual(report["known_total_by_currency"], {})
        self.assertEqual(report["unknown_cost_attempts"], 1)
        first = {
            **EXAMPLES["events"][4],
            "event_id": "event.gap.first",
            "attempt_id": "attempt.gap",
        }
        self.assertEqual(self.event(first)[0], 201)
        report = self.request(
            "GET", "/integration/v1/reports/usage?dataset_id=dataset.local.vega.01", admin=True
        )[1]
        self.assertEqual(report["known_total_by_currency"], {"USD": "0.030000000"})
        self.assertEqual(
            self.request("GET", "/integration/v1/reports/usage?dataset_id=dataset.local.vega.01")[
                0
            ],
            404,
        )
        self.assertEqual(
            self.event(
                {
                    **EXAMPLES["events"][6],
                    "event_id": "event.bad.zero",
                    "attempt_id": "attempt.gap",
                    "usage_revision": 3,
                    "amount_decimal": "0",
                }
            )[0],
            400,
        )
        self.assertEqual(
            self.event(
                {
                    **EXAMPLES["events"][6],
                    "event_id": "event.good.zero",
                    "attempt_id": "attempt.gap",
                    "usage_revision": 3,
                    "amount_decimal": "0",
                    "zero_basis": "provider.reported.free",
                }
            )[0],
            201,
        )
        report = self.request(
            "GET", "/integration/v1/reports/usage?dataset_id=dataset.local.vega.01", admin=True
        )[1]
        self.assertEqual(report["known_total_by_currency"], {"USD": "0.000000000"})
        self.assertEqual(report["attempts"][0]["usage_revision"], 3)

    def test_restart_backup_and_concurrent_duplicate(self):
        self.create()
        event = EXAMPLES["events"][2]
        results = []
        threads = [
            threading.Thread(target=lambda: results.append(self.event(event))) for _ in range(4)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(status for status, _ in results), [200, 200, 200, 201])
        self.assertEqual(len({reply["event_digest"] for _, reply in results}), 1)
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM integration_events").fetchone()[0], 1
        )
        backup = Path(self.tmp.name) / "backup.sqlite"
        with self.store._lock, sqlite3.connect(backup) as dest:
            self.store.db.backup(dest)
        copy = SQLiteStore(backup)
        self.addCleanup(copy.close)
        restored = Registry(copy, Authority())
        self.assertEqual(
            restored.integration.receipt(
                restored.principal("svc.integration"), self.dataset["dataset_id"], event["event_id"]
            ),
            results[0][1],
        )
        self.assertEqual(
            restored.integration.report(
                restored.principal("owner.local"), self.dataset["dataset_id"]
            )["attempt_count"],
            1,
        )

    def test_long_usage_history_and_attribution_conflict(self):
        self.create()
        examples = EXAMPLES["events"]
        self.assertEqual(self.event(examples[3])[1]["membership_at_receipt"], "pending_start")
        self.assertEqual(self.event(examples[0])[0], 201)
        self.assertEqual(self.event(examples[1])[0], 201)
        wrong = {**examples[1], "event_id": "event.wrong.parent", "root_run_id": "run.other"}
        self.assertEqual(self.event(wrong)[0], 409)
        self.assertEqual(self.event(examples[2])[0], 201)
        with self.assertRaises(IntegrationError):
            self.registry.integration.append_event(self.registry.principal("svc.demo"), examples[4])
        for revision in range(1, 34):
            item = {
                **examples[6],
                "event_id": f"event.long.{revision}",
                "usage_revision": revision,
                "amount_decimal": f"0.{revision:09d}",
            }
            self.assertEqual(self.event(item)[0], 201)
        report = self.request(
            "GET", "/integration/v1/reports/usage?dataset_id=dataset.local.vega.01", admin=True
        )[1]
        self.assertEqual(report["attempts"][0]["usage_revision"], 33)
        self.assertEqual(report["known_total_by_currency"], {"USD": "0.000000033"})
        self.assertEqual(
            self.store.db.execute(
                "SELECT COUNT(*) FROM integration_events WHERE kind='usage'"
            ).fetchone()[0],
            33,
        )
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM dev12_usage_revisions").fetchone()[0], 0
        )

    def test_owner_read_only_reporting_without_administration(self):
        self.create()
        self.registry.mutate(
            "owner.local",
            {
                "operation_id": "op.integration.reader.create",
                "action": "create_principal",
                "subject": "user.integration.reader",
                "expected_revision": 0,
                "data": {
                    "display_name": "Synthetic reader",
                    "kind": "human",
                    "owner": "owner.local",
                    "role": "ordinary",
                },
            },
        )
        _, credential = self.registry.provision_credential(
            "owner.local", "user.integration.reader", 1, "op.integration.reader.credential"
        )
        self.registry.mutate(
            "owner.local",
            {
                "operation_id": "op.integration.reader.activate",
                "action": "principal_state",
                "subject": "user.integration.reader",
                "expected_revision": 2,
                "data": {"status": "active", "reason": "isolated reporting test"},
            },
        )
        self.registry.mutate(
            "owner.local",
            {
                "operation_id": "op.integration.reader.role",
                "action": "set_role",
                "subject": "user.integration.reader",
                "expected_revision": 3,
                "data": {"role": "read_only_operator"},
            },
        )
        path = "/integration/v1/reports/usage?dataset_id=" + self.dataset["dataset_id"]
        self.assertEqual(self.request("GET", path, token=credential)[0], 200)
        self.assertEqual(
            self.request("POST", "/integration/v1/accounts", self.account, token=credential)[0], 404
        )

    def test_correction_ids_timestamps_and_legacy_missing_outcome(self):
        self.create()
        event = {**EXAMPLES["events"][0], "event_id": "event.TimeZ"}
        self.assertEqual(self.event(event)[0], 201)
        invalid = {**event, "event_id": "event.invalid.time", "occurred_at": "2026-02-30T00:00:00Z"}
        self.assertEqual(self.event(invalid)[0], 400)
        account = {**self.account, "account_id": "account:review:01"}
        self.assertEqual(
            self.request("POST", "/integration/v1/accounts", account, admin=True)[0], 201
        )
        self.assertEqual(
            self.request(
                "GET",
                "/integration/v1/accounts/account%3Areview%3A01/eligibility"
                "?dataset_id=dataset.local.vega.01&model_id=model.synthetic",
            )[0],
            200,
        )
        self.assertEqual(
            self.request(
                "POST",
                "/integration/v1/accounts/account%3Areview%3A01/state",
                {
                    "dataset_id": self.dataset["dataset_id"],
                    "expected_revision": 1,
                    "state": "disabled",
                },
                admin=True,
            )[0],
            200,
        )
        self.assertEqual(
            self.request(
                "GET",
                "/integration/v1/events/event%2ETimeZ/receipt?dataset_id=dataset.local.vega.01",
            )[0],
            200,
        )
        for path in (
            "/integration/v1/events/event%GG/receipt",
            "/integration/v1/events/event%2Fbad/receipt",
            "/integration/v1/events/event%252Fbad/receipt",
        ):
            self.assertEqual(
                self.request("GET", path + "?dataset_id=dataset.local.vega.01")[0], 400
            )
        start = EXAMPLES["events"][2]
        self.assertEqual(self.event(start)[0], 201)
        missing = {**EXAMPLES["events"][10], "event_id": "event.legacy.missing.outcome"}
        missing.pop("outcome")
        self.assertEqual(self.event(missing)[0], 201)
        status, report = self.request(
            "GET", "/integration/v1/reports/usage?dataset_id=dataset.local.vega.01", admin=True
        )
        self.assertEqual(status, 200)
        self.assertEqual(report["attempts"][0]["task_outcome"], "not_observed")
        status, csv_data = self.request(
            "GET",
            "/integration/v1/reports/usage?dataset_id=dataset.local.vega.01&export=csv",
            admin=True,
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            list(csv.DictReader(io.StringIO(csv_data)))[0]["task_outcome"], "not_observed"
        )
        v2_report = self.request(
            "GET",
            "/integration/v2/reports/usage?dataset_id=dataset.local.vega.01",
            admin=True,
            version="2",
        )[1]
        self.assertEqual(v2_report["attempts"][0]["usage_state"], "legacy_absent")
