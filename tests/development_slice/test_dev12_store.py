"""Additive successor migration and unbounded product revision readback."""

from copy import deepcopy
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/src"))
from ezllmrouter_server.store import SQLiteStore  # noqa: E402
from ezllmrouter_server.successor_campaign import FiniteSuccessorCampaign  # noqa: E402
from ezllmrouter_server.successor_contract import native_usage_row, work_projection, work_digest  # noqa: E402

VECTORS = json.loads(
    (ROOT / "tests/fixtures/contracts/dev12-successor-01/vectors.json").read_text()
)


class SuccessorStoreTests(unittest.TestCase):
    def test_finite_allowance_and_guard_commit_atomicity(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "campaign.sqlite3"
            store = SQLiteStore(path)
            clock = lambda: datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
            campaign = FiniteSuccessorCampaign(
                store, "campaign.test", "budget.test", wall_clock=clock
            )
            campaign.start(
                ["https://synthetic.invalid/synthetic/v1/embeddings"],
                ["dev12-owned-test"],
                max_attempts=1,
                max_concurrent=1,
                ceiling_decimal="0.001000000",
            )
            key = {
                "principal_id": "user.demo",
                "task_id": "task.test",
                "step_id": "step.test",
                "step_revision": 1,
                "execution_generation": "gen.1",
            }
            record = {
                "submission_id": "submission.one",
                "attempt_id": "attempt.one",
                "work_key": key,
                "work_digest": "sha256:test",
                "reservation": {
                    "max_exposure_decimal": "0.000600000",
                    "budget_account_id": "budget.test",
                    "financial_owner_id": "team.demo",
                    "currency": "USD",
                },
                "signed_plan": {"plan_id": "plan.one"},
                "status_revision": 1,
            }
            store.successor_create(record, reserve=campaign.reserve)
            receipt = {
                "attempt_id": "attempt.one",
                "plan_id": "plan.one",
                "work_digest": "sha256:test",
            }
            store.successor_guard_commit(
                "submission.one", "attempt.one", receipt, "2026-10-26T12:00:01Z", campaign
            )
            with self.assertRaises(Exception):
                store.successor_guard_commit(
                    "submission.one", "attempt.one", receipt, "2026-10-26T12:00:02Z", campaign
                )
            campaign.finish("attempt.one")
            campaign.store._transaction(
                lambda: campaign.pause_in_transaction(campaign.store.database, "unknown_cost")
            )
            self.assertTrue(campaign.inspect()["paused"])
            self.assertEqual(campaign.inspect()["pause_reason"], "unknown_cost")
            self.assertEqual(campaign.inspect()["attempt_count"], 1)
            self.assertEqual(campaign.inspect()["possible_send_count"], 1)
            self.assertEqual(campaign.inspect()["inflight_count"], 0)
            store.close()
            reopened = SQLiteStore(path)
            same_campaign = FiniteSuccessorCampaign(
                reopened, "campaign.test", "budget.test", wall_clock=clock
            )
            self.assertEqual(same_campaign.inspect()["possible_send_count"], 1)
            with self.assertRaises(ValueError):
                same_campaign.start([], [])
            second = deepcopy(record)
            second["submission_id"] = "submission.two"
            second["attempt_id"] = "attempt.two"
            second["work_key"]["step_id"] = "step.two"
            with self.assertRaises(PermissionError):
                reopened.successor_create(second, reserve=same_campaign.reserve)
            self.assertIsNone(reopened.successor_get("submission.two"))
            reopened.close()

    def test_legacy_preserved_and_33rd_correction_effective_once(self):
        example = next(x for x in VECTORS["examples"] if x["id"] == "DIRECT_DOCUMENT")
        request = example["request"]
        work = work_projection(request, example["trusted_context"])
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "ledger.sqlite3"
            db = SQLiteStore(path)
            legacy = {
                "submission_id": "submission.legacy",
                "attempt_id": "attempt.legacy",
                "principal_id": "user.demo",
                "task_id": "task.legacy",
                "work_key": {
                    "principal_id": "user.demo",
                    "task_id": "task.legacy",
                    "step_id": "step.legacy",
                    "step_revision": 1,
                    "execution_generation": "gen.legacy",
                },
                "work_digest": "sha256:legacy",
                "status_revision": 1,
            }
            db.create(deepcopy(legacy))
            before = db.db.execute(
                "SELECT record FROM submissions WHERE submission_id='submission.legacy'"
            ).fetchone()[0]
            record = {
                "submission_id": "submission.new",
                "attempt_id": "attempt.new",
                "contract_version": "0.3",
                "request": request,
                "canonical_work": work,
                "work_key": work["work_key"],
                "work_digest": work_digest(work),
                "reservation": {
                    "price_ref": "tariff.synthetic.embedding.document@1",
                    "usage_ref": "dev12-native-usage@1",
                    "max_exposure_decimal": "0.000600000",
                },
                "status_revision": 1,
                "settlement_state": "pending",
                "updated_at": "2030-01-01T00:00:01Z",
            }
            # Resolve the actual bound refs rather than trusting this test's spelling.
            from ezllmrouter_server.successor_contract import price_for

            price = price_for(request)
            record["reservation"]["price_ref"] = price["price_ref"]
            record["reservation"]["usage_ref"] = price["usage_ref"]
            db.successor_create(record)
            with self.assertRaises(Exception):
                db.successor_create(record)
            for ordinal in range(1, 34):
                component = {
                    "component": price["component"],
                    "presence": "known",
                    "quantity": 3,
                    "evidence": "reported",
                    "source_ref": f"receiver.{ordinal}",
                }
                usage = native_usage_row(
                    request,
                    "attempt.new",
                    ordinal,
                    component,
                    "0.000600000",
                    ordinal - 1 if ordinal > 1 else None,
                )
                self.assertEqual(
                    db.successor_append_usage(
                        "submission.new", usage, "2030-01-01T00:01:00Z", write_allowed=True
                    ),
                    "accepted",
                )
            self.assertEqual(db.successor_latest_usage("attempt.new")["revision"], 33)
            self.assertEqual(
                db.successor_totals("user.demo"),
                {
                    "known_amount_decimal": "0.000600000",
                    "unknown_attempts": 0,
                    "distinct_attempts": 1,
                },
            )
            self.assertEqual(
                db.successor_append_usage(
                    "submission.new", usage, "2030-01-01T00:01:00Z", write_allowed=True
                ),
                "duplicate",
            )
            conflict = deepcopy(usage)
            conflict["components"][0]["source_ref"] = "receiver.conflict"
            with self.assertRaises(ValueError):
                db.successor_append_usage(
                    "submission.new", conflict, "2030-01-01T00:01:00Z", write_allowed=True
                )
            with self.assertRaises(PermissionError):
                db.successor_append_usage(
                    "submission.new", usage, "2030-01-01T00:01:00Z", write_allowed=False
                )
            self.assertEqual(
                db.db.execute(
                    "SELECT record FROM submissions WHERE submission_id='submission.legacy'"
                ).fetchone()[0],
                before,
            )
            self.assertEqual(
                db.db.execute("SELECT COUNT(*) FROM dev12_usage_revisions").fetchone()[0], 33
            )
            db.close()
            reopened = SQLiteStore(path)
            self.assertEqual(
                reopened.successor_by_work(work["work_key"])["submission_id"], "submission.new"
            )
            self.assertEqual(
                reopened.successor_totals("user.demo")["known_amount_decimal"], "0.000600000"
            )
            self.assertEqual(
                reopened.db.execute(
                    "SELECT record FROM submissions WHERE submission_id='submission.legacy'"
                ).fetchone()[0],
                before,
            )
            reopened.close()


if __name__ == "__main__":
    unittest.main()
