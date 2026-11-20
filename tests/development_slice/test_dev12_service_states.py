"""Composed service settlement states without a transport or provider request."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
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
from ezllmrouter_server.successor_service import SuccessorService  # noqa: E402

VECTORS = json.loads(
    (ROOT / "tests/fixtures/contracts/dev12-successor-01/vectors.json").read_text()
)


class RecordedOutcomeExecutor:
    """No network: only checks product settlement after a durable guard record."""

    def execute(self, record, _authority, store, campaign):
        plan = record["signed_plan"]
        receipt = {
            "attempt_id": record["attempt_id"],
            "plan_id": plan["plan_id"],
            "work_digest": record["work_digest"],
        }
        store.successor_guard_commit(
            record["submission_id"], record["attempt_id"], receipt, record["created_at"], campaign
        )
        result = deepcopy(
            next(
                row["value"]
                for row in VECTORS["result_examples"]
                if row["id"] == "EMBEDDING_RESULT"
            )
        )
        result["attempt_id"] = record["attempt_id"]
        if record["work_key"]["step_id"] == "step.invalidresult":
            result["vectors"][0]["item_id"] = "wrong.item"
            component = {
                "component": "document_units",
                "presence": "known",
                "quantity": 3,
                "evidence": "reported",
                "source_ref": "receiver.test",
            }
        else:
            component = {"component": "document_units", "presence": "null"}
        return {"state": "observed", "result": result, "usage_component": component}


class ServiceSettlementTests(unittest.TestCase):
    def test_failure_keeps_reported_charge_and_valid_result_keeps_unknown(self):
        example = next(row for row in VECTORS["examples"] if row["id"] == "DIRECT_DOCUMENT")
        now = datetime.now(timezone.utc).replace(microsecond=0)
        fmt = lambda moment: moment.strftime("%Y-%m-%dT%H:%M:%SZ")
        context = deepcopy(example["trusted_context"])
        context["authenticated_at"] = fmt(now - timedelta(minutes=1))
        context["expires_at"] = fmt(now + timedelta(hours=1))
        trusted = {**context["identity"], "task_id": "task.demo"}
        token = "test.synthetic.service.token." + "x" * 32
        with TemporaryDirectory() as temporary:
            store = SQLiteStore(Path(temporary) / "service.sqlite")
            authority = SyntheticSuccessorAuthority(
                store, Ed25519PrivateKey.generate(), "key.synthetic.test", "v1"
            )
            campaign = FiniteSuccessorCampaign(store, "campaign.settlement", "budget.settlement")
            campaign.start({}, [], max_attempts=3)
            authority.set_historical_access(
                context["identity"], read=True, write=True, resume=True, observed_at=fmt(now)
            )
            permitted = (
                lambda current, record: current["principal_id"]
                == record["work_key"]["principal_id"]
            )
            service = SuccessorService(
                store,
                {token: context},
                authority,
                RecordedOutcomeExecutor(),
                campaign,
                read_allowed=permitted,
                usage_write_allowed=permitted,
            )
            try:
                for step, expected_state, expected_cost in (
                    ("step.invalidresult", "failed", "calculated"),
                    ("step.unknowncost", "completed", "unknown"),
                ):
                    request = deepcopy(example["request"])
                    request["deadline"] = fmt(now + timedelta(minutes=30))
                    request["work_selector"]["step_id"] = step
                    _code, reply = service.submit(request, trusted, 5000, credential=token)
                    status = service.status(reply["handle"]["submission_id"], trusted)
                    self.assertEqual(status["submission_state"], expected_state)
                    self.assertEqual(
                        status["attempts"][0]["usage_revision"]["cost_status"], expected_cost
                    )
                    if step == "step.invalidresult":
                        self.assertEqual(
                            status["attempts"][0]["usage_revision"]["amount_decimal"], "0.000600000"
                        )
                    else:
                        self.assertIn("result", status["attempts"][0])
                self.assertEqual(
                    store.successor_totals("user.demo"),
                    {
                        "known_amount_decimal": "0.000600000",
                        "unknown_attempts": 1,
                        "distinct_attempts": 2,
                    },
                )
                self.assertTrue(campaign.inspect()["paused"])
            finally:
                service.pool.shutdown(wait=True)
                store.close()


if __name__ == "__main__":
    unittest.main()
