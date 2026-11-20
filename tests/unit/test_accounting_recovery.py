"""Read-only retention projection and campaign-scoped recovery without transport."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tests.operator_console import test_integration_credentials as credential_fixtures
from tests.operator_console import test_personal_campaign as personal_fixtures
from tests.operator_console.test_projection import record as legacy_record
from ezllmrouter_server.canonical import ContractError
from ezllmrouter_server.integration_accounting import IntegrationError
from ezllmrouter_server.operator_projection import OperatorProjection
from ezllmrouter_server.operator_web import _accounting_maintenance
from ezllmrouter_server.personal_campaign import PersonalCampaign
from ezllmrouter_server.registry import Registry
from ezllmrouter_server.store import SQLiteStore, encode
from ezllmrouter_server.successor_authority import SyntheticSuccessorAuthority
from ezllmrouter_server.successor_campaign import FiniteSuccessorCampaign
from ezllmrouter_server.successor_service import SuccessorService

ROOT = Path(__file__).resolve().parents[2]
EXTERNAL = json.loads(
    (ROOT / "tests/fixtures/contracts/integration-readiness-v2/examples.json").read_text()
)
SUCCESSOR = json.loads(
    (ROOT / "tests/fixtures/contracts/dev12-successor-01/vectors.json").read_text()
)


class RetentionReadTests(unittest.TestCase):
    setUp = credential_fixtures.CredentialTests.setUp

    def real_dataset(self, suffix, *, valid=True):
        accounting = self.registry.integration
        accounting.accounting_retention_days = 1
        record = {
            **accounting._dataset(self.dataset),
            "dataset_id": "dataset.local.real." + suffix,
            "activated_at": "2026-11-03T00:00:00Z",
        }
        accounting.create_dataset(self.owner, record)
        if not valid:
            self.store.db.execute(
                "DELETE FROM integration_dataset_retention WHERE dataset_id=?",
                (record["dataset_id"],),
            )
        return record

    def test_unmanaged_cohort_does_not_block_unrelated_reads_or_maintenance(self):
        with patch(
            "ezllmrouter_server.integration_accounting._time", return_value="2026-11-03T12:00:00Z"
        ) as clock:
            invalid = self.real_dataset("unmanaged", valid=False)
            expired = self.real_dataset("managed")
            accounting = self.registry.integration
            before = self.store.db.total_changes
            self.store.db.execute("PRAGMA query_only=ON")
            try:
                self.assertEqual(accounting._dataset(self.dataset)["dataset_id"], self.dataset)
                self.assertEqual(accounting.accounts(self.owner, self.dataset)["items"], [])
                self.assertNotIn(
                    invalid["dataset_id"],
                    [item["dataset_id"] for item in accounting.datasets(self.owner)["items"]],
                )
                with self.assertRaises(IntegrationError):
                    accounting._dataset(invalid["dataset_id"])
            finally:
                self.store.db.execute("PRAGMA query_only=OFF")
            self.assertEqual(self.store.db.total_changes, before)
            clock.return_value = "2026-11-04T00:00:00Z"
            self.assertEqual(accounting.expire_datasets(), 1)
            self.assertIsNotNone(
                self.store.db.execute(
                    "SELECT 1 FROM integration_datasets WHERE id=?", (invalid["dataset_id"],)
                ).fetchone()
            )
            self.assertIsNone(
                self.store.db.execute(
                    "SELECT 1 FROM integration_datasets WHERE id=?", (expired["dataset_id"],)
                ).fetchone()
            )
            restarted = Registry(self.store, credential_fixtures.Authority())
            self.assertEqual(
                restarted.integration._dataset(self.dataset)["dataset_id"], self.dataset
            )

    def test_expiry_is_enforced_on_reads_before_physical_cleanup(self):
        with patch(
            "ezllmrouter_server.integration_accounting._time", return_value="2026-11-03T12:00:00Z"
        ) as clock:
            record = self.real_dataset("deadline")
            clock.return_value = "2026-11-04T00:00:00Z"
            accounting = self.registry.integration
            before = self.store.db.total_changes
            with self.assertRaises(IntegrationError) as denied:
                accounting._dataset(record["dataset_id"])
            self.assertEqual(denied.exception.status, 404)
            self.assertNotIn(
                record["dataset_id"],
                [row["dataset_id"] for row in accounting.datasets(self.owner)["items"]],
            )
            self.assertEqual(self.store.db.total_changes, before)
            self.assertIsNotNone(
                self.store.db.execute(
                    "SELECT 1 FROM integration_datasets WHERE id=?", (record["dataset_id"],)
                ).fetchone()
            )
            with self.assertRaises(IntegrationError) as duplicate:
                accounting.create_dataset(self.owner, record)
            self.assertEqual(duplicate.exception.code, "DATASET_EXPIRED")
            self.assertEqual(accounting.maintain()["expired_datasets"], 1)
            with self.assertRaises(IntegrationError) as recreate:
                accounting.create_dataset(self.owner, record)
            self.assertEqual(recreate.exception.code, "DATASET_EXPIRED")

    def test_snapshot_report_and_export_hide_expired_content_without_writes(self):
        accounting = self.registry.integration
        with patch(
            "ezllmrouter_server.integration_accounting._time", return_value="2026-10-27T00:00:40Z"
        ) as clock:
            accounting.create_dataset(self.owner, EXTERNAL["dataset"], "2")
            accounting.create_account(self.owner, EXTERNAL["account"], "2")
            ingest = self.registry.principal("svc.integration")
            for event in EXTERNAL["events"]:
                accounting.append_event(ingest, event)
            for snapshot in EXTERNAL["snapshots"]:
                accounting.append_snapshot(ingest, snapshot)
            dataset = EXTERNAL["dataset"]["dataset_id"]
            self.assertIn("features", accounting.snapshot(self.owner, dataset, "feature.synthetic"))
            clock.return_value = "2027-10-27T00:00:00Z"
            before = self.store.db.total_changes
            self.store.db.execute("PRAGMA query_only=ON")
            try:
                snapshot = accounting.snapshot(self.owner, dataset, "feature.synthetic")
                exported = accounting.dataset_export(self.owner, dataset)
                report = accounting.report(self.owner, dataset, version="2")
            finally:
                self.store.db.execute("PRAGMA query_only=OFF")
            self.assertEqual(snapshot["status"], "expired")
            self.assertNotIn("features", snapshot)
            exported_snapshot = next(
                row for row in exported["snapshots"] if row["snapshot_id"] == "feature.synthetic"
            )
            self.assertEqual(exported_snapshot["status"], "expired")
            self.assertNotIn("features", exported_snapshot)
            self.assertEqual(
                next(row for row in report["attempts"] if row["attempt_id"] == "attempt.synthetic")[
                    "feature_snapshot_status"
                ],
                "expired",
            )
            self.assertEqual(self.store.db.total_changes, before)
            self.assertIsNotNone(
                self.store.db.execute(
                    "SELECT content FROM integration_snapshots WHERE snapshot_id='feature.synthetic'"
                ).fetchone()[0]
            )
            self.assertEqual(accounting.maintain()["expired_snapshots"], 1)
            self.assertIsNone(
                self.store.db.execute(
                    "SELECT content FROM integration_snapshots WHERE snapshot_id='feature.synthetic'"
                ).fetchone()[0]
            )

    def test_periodic_maintenance_retries_failure_and_honors_stop(self):
        accounting, stopped = Mock(), Mock()
        stopped.wait.side_effect = [False, False, True]
        accounting.maintain.side_effect = [RuntimeError("private diagnostic"), {}]
        with patch("ezllmrouter_server.operator_web.log_failure") as logged:
            _accounting_maintenance(accounting, stopped)
        self.assertEqual(accounting.maintain.call_count, 2)
        logged.assert_called_once_with("accounting_maintenance_failed")
        self.assertEqual([call.args for call in stopped.wait.call_args_list], [(60,), (60,), (60,)])


class SuccessorRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = SQLiteStore(Path(temporary.name) / "ledger.sqlite")
        self.addCleanup(self.store.close)
        self.authority = SimpleNamespace(gate=threading.RLock())

    def campaign(self, name):
        campaign = FiniteSuccessorCampaign(self.store, "campaign." + name, "budget." + name)
        campaign.start({}, [], max_attempts=10)
        return campaign

    def pending(self, name, campaign, *, committed):
        record = {
            "submission_id": "submission." + name,
            "attempt_id": "attempt." + name,
            "work_key": {
                "principal_id": "user.demo",
                "task_id": "task.test",
                "step_id": "step." + name,
                "step_revision": 1,
                "execution_generation": "gen.1",
            },
            "work_digest": "sha256:" + "a" * 64,
            "status_revision": 1,
            "submission_state": "pending",
            "dispatch_state": "intent_persisted",
            "delivery_state": "pending",
            "candidate_access": "not_yet_available",
            "reservation": {
                "max_exposure_decimal": "0.000600000",
                "budget_account_id": campaign.budget_account_id,
                "financial_owner_id": "team.demo",
                "currency": "USD",
            },
            "signed_plan": {"plan_id": "plan." + name},
        }
        self.store.successor_create(record, reserve=campaign.reserve)
        if committed:
            self.store.successor_guard_commit(
                record["submission_id"],
                record["attempt_id"],
                {
                    "attempt_id": record["attempt_id"],
                    "plan_id": record["signed_plan"]["plan_id"],
                    "work_digest": record["work_digest"],
                },
                "2026-11-19T00:00:00Z",
                campaign,
            )
        return record

    def service(self, campaign):
        service = SuccessorService(
            self.store,
            {},
            self.authority,
            None,
            campaign,
            read_allowed=lambda *_: True,
            usage_write_allowed=lambda *_: True,
        )
        self.addCleanup(service.pool.shutdown, wait=True)
        return service

    def test_recovery_never_changes_another_campaign(self):
        other, current = self.campaign("other"), self.campaign("current")
        foreign = self.pending("foreign", other, committed=True)
        sent = self.pending("sent", current, committed=True)
        unsent = self.pending("unsent", current, committed=False)
        untouched = encode(self.store.successor_get(foreign["submission_id"]))
        other_before = other.inspect()
        reserved = current.inspect()["cumulative_reserved_decimal"]
        service = self.service(current)
        service.recover_incomplete()
        self.assertEqual(encode(self.store.successor_get(foreign["submission_id"])), untouched)
        self.assertEqual(other.inspect(), other_before)
        self.assertEqual(
            self.store.successor_get(sent["submission_id"])["dispatch_state"], "possible_send"
        )
        self.assertEqual(
            self.store.successor_get(unsent["submission_id"])["failure_stage"], "before_send"
        )
        self.assertEqual(current.inspect()["inflight_count"], 0)
        self.assertTrue(current.inspect()["paused"])
        self.assertEqual(current.inspect()["cumulative_reserved_decimal"], reserved)
        revisions = [
            self.store.successor_get(item["submission_id"])["status_revision"]
            for item in (sent, unsent)
        ]
        service.recover_incomplete()
        self.assertEqual(
            revisions,
            [
                self.store.successor_get(item["submission_id"])["status_revision"]
                for item in (sent, unsent)
            ],
        )

    def test_recovery_and_campaign_bookkeeping_roll_back_together(self):
        campaign = self.campaign("atomic")
        record = self.pending("atomic", campaign, committed=True)
        before = encode(self.store.successor_get(record["submission_id"]))
        with patch.object(campaign, "finish", side_effect=RuntimeError("interrupted finish")):
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                self.service(campaign).recover_incomplete()
        self.assertEqual(encode(self.store.successor_get(record["submission_id"])), before)
        self.assertFalse(campaign.inspect()["paused"])
        self.assertEqual(campaign.inspect()["inflight_count"], 1)
        self.service(campaign).recover_incomplete()
        self.assertEqual(campaign.inspect()["inflight_count"], 0)

    def test_operator_projection_preserves_before_send_failure_state(self):
        item = legacy_record(
            "submission.failed", "attempt.failed", "step.failed", state="failed_before_transmit"
        )
        item["dispatch_state"] = "failed_before_dispatch"
        self.store.create(item)
        projection = OperatorProjection(self.store, "svc.demo")
        self.assertEqual(
            projection.detail(item["submission_id"])["dispatch_state"], "failed_before_dispatch"
        )


class ContractFailureTests(unittest.TestCase):
    def test_committed_contract_failure_is_unknown_without_no_send_evidence(self):
        example = next(row for row in SUCCESSOR["examples"] if row["id"] == "DIRECT_DOCUMENT")
        now = datetime.now(timezone.utc).replace(microsecond=0)
        fmt = lambda value: value.strftime("%Y-%m-%dT%H:%M:%SZ")
        context = deepcopy(example["trusted_context"])
        context["authenticated_at"] = fmt(now - timedelta(minutes=1))
        context["expires_at"] = fmt(now + timedelta(hours=1))
        request = deepcopy(example["request"])
        request["deadline"] = fmt(now + timedelta(minutes=30))
        trusted = {**context["identity"], "task_id": request["work_selector"]["task_id"]}
        for committed, code, status in (
            (False, "PLAN_INVALID_OR_STALE", 409),
            (True, "PLAN_INVALID_OR_STALE", 409),
            (True, "FDC_REJECTED", 409),
            (True, "INTENT_PERSIST_FAILED", 503),
            (True, "RESULT_INVALID", 502),
        ):
            with (
                self.subTest(committed=committed, code=code),
                tempfile.TemporaryDirectory() as directory,
            ):
                store = SQLiteStore(Path(directory) / "state.sqlite")
                self.addCleanup(store.close)
                authority = SyntheticSuccessorAuthority(
                    store, Ed25519PrivateKey.generate(), "key.test", "v1"
                )
                authority.set_historical_access(
                    context["identity"], read=True, write=True, resume=True, observed_at=fmt(now)
                )
                campaign = FiniteSuccessorCampaign(store, "campaign.failure", "budget.failure")
                campaign.start({}, [], max_attempts=2)
                calls = []

                def execute(record, _authority, _store, _campaign):
                    calls.append(record)
                    if committed:
                        store.successor_guard_commit(
                            record["submission_id"],
                            record["attempt_id"],
                            {
                                "attempt_id": record["attempt_id"],
                                "plan_id": record["signed_plan"]["plan_id"],
                                "work_digest": record["work_digest"],
                            },
                            fmt(now),
                            campaign,
                        )
                    raise ContractError(code, status)

                service = SuccessorService(
                    store,
                    {"synthetic-token": context},
                    authority,
                    SimpleNamespace(execute=execute),
                    campaign,
                    read_allowed=lambda *_: True,
                    usage_write_allowed=lambda *_: True,
                )
                try:
                    returned, reply = service.submit(
                        request, trusted, 5000, credential="synthetic-token"
                    )
                    record = store.successor_get(reply["handle"]["submission_id"])
                    self.assertEqual(
                        record["dispatch_state"], "possible_send" if committed else "blocked"
                    )
                    self.assertEqual(
                        record["submission_state"], "unknown" if committed else "failed"
                    )
                    self.assertEqual(returned, 202 if committed else 409)
                    self.assertEqual(campaign.inspect()["paused"], committed)
                    service.submit(request, trusted, 5000, credential="synthetic-token")
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(campaign.inspect()["inflight_count"], 0)
                finally:
                    service.pool.shutdown(wait=True)


class PersonalCampaignHistoryTests(unittest.TestCase):
    setUp = personal_fixtures.CampaignTests.setUp
    _record = personal_fixtures.CampaignTests._record
    _reserve = personal_fixtures.CampaignTests._reserve

    def test_late_reconciliation_keeps_closed_history_and_audits_its_campaign(self):
        original = self.campaign.configure("owner.local", self.config)
        self.campaign.transition("owner.local", "active")
        attempt = self._reserve("historical")
        self.campaign.settle(
            attempt["attempt_id"],
            {"revision": 1, "cost": {"status": "calculated", "amount_decimal": "0.00002"}},
        )
        closed = self.campaign.transition("owner.local", "closed")
        current = self.campaign.configure("owner.local", self.config)
        self.assertNotEqual(current["id"], closed["id"])
        corrected = {
            "revision": 2,
            "cost": {"status": "calculated", "currency": "USD", "amount_decimal": "0.002"},
        }
        self.store.db.execute(
            "INSERT INTO usage_revisions VALUES (?,?,?,?)",
            (attempt["attempt_id"], 2, attempt["submission_id"], encode(corrected)),
        )
        self.assertEqual(self.campaign.reconcile_recorded_usage("owner.local"), 1)
        historical = json.loads(
            self.store.db.execute(
                "SELECT record FROM personal_campaigns WHERE id=?", (original["id"],)
            ).fetchone()[0]
        )
        self.assertEqual(historical, closed)
        self.assertEqual(self.campaign.summary()["id"], current["id"])
        self.assertEqual(self.campaign.summary()["state"], "draft")
        self.assertEqual(
            self.store.db.execute(
                "SELECT campaign_id FROM personal_campaign_audit WHERE action='reconcile_recorded_usage'"
            ).fetchall(),
            [(original["id"],)],
        )
        self.assertEqual(self.campaign.reconcile_recorded_usage("owner.local"), 0)
        state, amount = self.store.db.execute(
            "SELECT state,cost_decimal FROM personal_campaign_attempts WHERE attempt_id=?",
            (attempt["attempt_id"],),
        ).fetchone()
        self.assertEqual(state, "over_bound")
        self.assertEqual(Decimal(amount), Decimal("0.002"))

    def test_recovery_and_late_settlement_do_not_reopen_a_closed_campaign(self):
        self.campaign.configure("owner.local", self.config)
        self.campaign.transition("owner.local", "active")
        attempt = self._reserve("closed-inflight")
        closed = self.campaign.transition("owner.local", "closed")
        self.campaign = PersonalCampaign(self.store, self.registry)
        self.assertEqual(self.campaign.summary()["state"], "closed")
        self.campaign.settle(
            attempt["attempt_id"],
            {
                "revision": 1,
                "cost": {"status": "calculated", "currency": "USD", "amount_decimal": "0.002"},
            },
        )
        self.assertEqual(self.campaign.summary()["state"], "closed")
        self.assertEqual(self.campaign.summary()["revision"], closed["revision"])
        self.assertEqual(Decimal(self.campaign.summary()["incurred_decimal"]), Decimal("0.002"))
