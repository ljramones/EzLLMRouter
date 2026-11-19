"""Late native settlement, over-bound pause, and seven-day content expiry."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/src"))
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from ezllmrouter_server.store import SQLiteStore  # noqa: E402
from ezllmrouter_server.successor_authority import SyntheticSuccessorAuthority  # noqa: E402
from ezllmrouter_server.successor_campaign import FiniteSuccessorCampaign  # noqa: E402
from ezllmrouter_server.successor_contract import native_usage_row, price_for, work_projection, work_digest  # noqa: E402
from ezllmrouter_server.successor_service import SuccessorService  # noqa: E402

VECTORS = json.loads((ROOT / "tests/fixtures/contracts/dev12-successor-01/vectors.json").read_text())


class LateAccountingTests(unittest.TestCase):
    def test_historical_over_bound_and_unknown_survive_expiry(self):
        case = next(row for row in VECTORS["examples"] if row["id"] == "DIRECT_DOCUMENT")
        with TemporaryDirectory() as temporary:
            store = SQLiteStore(Path(temporary) / "history.sqlite")
            key = Ed25519PrivateKey.generate()
            authority = SyntheticSuccessorAuthority(store, key, "key.synthetic.test", "v1")
            campaign = FiniteSuccessorCampaign(store, "campaign.history", "budget.history",
                wall_clock=lambda: datetime(2026, 10, 26, 12, tzinfo=timezone.utc))
            campaign.start({}, [], max_attempts=5)
            records = []
            for index in (1, 2):
                request = deepcopy(case["request"])
                request["work_selector"]["step_id"] = f"step.history.{index}"
                work = work_projection(request, case["trusted_context"])
                price = price_for(request)
                record = {"submission_id": f"submission.history.{index}",
                    "attempt_id": f"attempt.history.{index}", "contract_version": "0.3",
                    "work_key": work["work_key"], "work_digest": work_digest(work),
                    "request": request, "trusted_identity": case["trusted_context"]["identity"],
                    "reservation": {"price_ref": price["price_ref"], "usage_ref": price["usage_ref"],
                                    "max_exposure_decimal": "0.000500000",
                                    "budget_account_id": "budget.history",
                                    "financial_owner_id": "team.demo", "currency": "USD"},
                    "signed_plan": {"expires_at": "2030-01-01T00:30:00Z"},
                    "created_at": "2030-01-01T00:00:00Z", "updated_at": "2030-01-01T00:00:10Z",
                    "submission_state": "completed", "dispatch_state": "sent", "delivery_state": "valid",
                    "candidate_access": "present", "result_available_at": "2030-01-01T00:00:10Z",
                    "result": {"fictional": "synthetic content"}, "status_revision": 1,
                    "exposure_state": "outstanding", "settlement_state": "pending"}
                store.successor_create(record, reserve=campaign.reserve)
                records.append(record)
            trusted = {**case["trusted_context"]["identity"], "task_id": "task.demo"}
            authority.set_historical_access(case["trusted_context"]["identity"],
                read=True, write=True, resume=True, observed_at="2030-01-01T00:00:00Z")
            allow = lambda current, original: current["principal_id"] == original["work_key"]["principal_id"]
            service = SuccessorService(store, {}, authority, None, campaign,
                clock=lambda: "2030-01-08T00:00:10Z", read_allowed=allow, usage_write_allowed=allow)
            try:
                # Revocation/plan expiry restrict unsent execution, not late evidence.
                authority.revoke_key_version("key.synthetic.test", "v1", "2030-01-02T00:00:00Z")
                first = records[0]
                absent = {"component": "document_units", "presence": "absent"}
                unknown1 = native_usage_row(first["request"], first["attempt_id"], 1, absent,
                                             first["reservation"]["max_exposure_decimal"])
                self.assertEqual(service.ingest_usage_revision(first["submission_id"], unknown1, trusted), "accepted")
                known = {"component": "document_units", "presence": "known", "quantity": 3,
                         "evidence": "reported", "source_ref": "receiver.late.synthetic"}
                corrected = native_usage_row(first["request"], first["attempt_id"], 2, known,
                                               first["reservation"]["max_exposure_decimal"], 1)
                self.assertEqual(service.ingest_usage_revision(first["submission_id"], corrected, trusted), "accepted")
                self.assertEqual(service.ingest_usage_revision(first["submission_id"], corrected, trusted), "duplicate")
                second = records[1]
                unknown2 = native_usage_row(second["request"], second["attempt_id"], 1, absent,
                                             second["reservation"]["max_exposure_decimal"])
                self.assertEqual(service.ingest_usage_revision(second["submission_id"], unknown2, trusted), "accepted")
                known_status = service.status(first["submission_id"], trusted)
                unknown_status = service.status(second["submission_id"], trusted)
                self.assertEqual(known_status["candidate_access"], "expired")
                self.assertEqual(known_status["submission_state"], "completed")
                self.assertEqual(known_status["attempts"][0]["usage_revision"]["cost_status"], "over_bound")
                self.assertEqual(known_status["attempts"][0]["usage_revision"]["amount_decimal"], "0.000600000")
                self.assertNotIn("result", known_status["attempts"][0])
                self.assertEqual(unknown_status["candidate_access"], "expired")
                self.assertEqual(unknown_status["attempts"][0]["usage_revision"]["cost_status"], "unknown")
                self.assertTrue(campaign.inspect()["paused"])
                self.assertEqual(store.successor_totals("user.demo"),
                    {"known_amount_decimal": "0.000600000", "unknown_attempts": 1, "distinct_attempts": 2})
                self.assertEqual(len(store.successor_expire_results("2030-01-08T00:00:10Z")), 2)
                self.assertNotIn("result", store.successor_get(first["submission_id"]))
                self.assertEqual(store.db.execute("SELECT COUNT(*) FROM dev12_usage_revisions").fetchone()[0], 3)
            finally:
                service.pool.shutdown(wait=True)
                store.close()


if __name__ == "__main__":
    unittest.main()
