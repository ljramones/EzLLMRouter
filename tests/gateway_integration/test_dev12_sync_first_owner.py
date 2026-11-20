"""Offline normal-HTTP discriminator for the prepared first-owner barrier."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import http.client
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ezllmrouter_server.canonical import ContractError
from ezllmrouter_server.core import Coordinator
from ezllmrouter_server.store import SQLiteStore
from tools.synthetic.successor_authority import SyntheticSuccessorAuthority
from tools.synthetic.successor_campaign import FiniteSuccessorCampaign
from tools.synthetic.successor_service import SuccessorService
from ezllmrouter_server.web import serve
from dev12_completion_sync_first_owner import synchronized_pair

VECTORS = json.loads(
    (ROOT / "tests/fixtures/contracts/dev12-successor-01/vectors.json").read_text()
)


class NoSendExecutor:
    def execute(self, *_args):
        raise ContractError("FDC_REJECTED", 409)


class SynchronizedOwnershipTests(unittest.TestCase):
    def test_two_normal_http_contenders_reach_unowned_boundary(self):
        example = next(row for row in VECTORS["examples"] if row["id"] == "DIRECT_DOCUMENT")
        now = datetime.now(timezone.utc).replace(microsecond=0)
        fmt = lambda value: value.strftime("%Y-%m-%dT%H:%M:%SZ")
        context = deepcopy(example["trusted_context"])
        context["authenticated_at"] = fmt(now - timedelta(minutes=1))
        context["expires_at"] = fmt(now + timedelta(hours=1))
        request = deepcopy(example["request"])
        request["deadline"] = fmt(now + timedelta(minutes=30))
        request["work_selector"]["step_id"] = "step.ct02.synchronized.offline"
        contender = deepcopy(request)
        contender["input"]["items"][0]["text"] = "River"
        trusted = {
            **context["identity"],
            "task_id": request["work_selector"]["task_id"],
            "expires_at": context["expires_at"],
        }
        token = "test.dev12.offline." + "x" * 32
        with TemporaryDirectory(dir=os.environ.get("DEV12_TEST_SCRATCH", ROOT)) as directory:
            store = SQLiteStore(Path(directory) / "offline.sqlite")
            authority = SyntheticSuccessorAuthority(
                store, Ed25519PrivateKey.generate(), "key.offline", "v1"
            )
            campaign = FiniteSuccessorCampaign(
                store,
                "campaign.offline",
                "budget.offline",
                financial_owner_id=context["identity"]["charging_owner_id"],
            )
            campaign.start({}, [], max_attempts=2, ceiling_decimal="0.010000000")
            service = SuccessorService(
                store,
                {token: context},
                authority,
                NoSendExecutor(),
                campaign,
                read_allowed=lambda _who, _record: True,
                usage_write_allowed=lambda _who, _record: True,
            )
            coordinator = Coordinator(None, {token: trusted}, {}, {}, {}, None, None, {}, {}, None)
            coordinator.successor = service
            web = serve("127.0.0.1", 0, coordinator)
            thread = threading.Thread(target=web.serve_forever, daemon=True)
            thread.start()
            key = {"principal_id": trusted["principal_id"], **request["work_selector"]}

            def post(value):
                connection = http.client.HTTPConnection(
                    "127.0.0.1", web.server_address[1], timeout=10
                )
                body = json.dumps(value, separators=(",", ":")).encode()
                connection.request(
                    "POST",
                    "/v1/submissions",
                    body,
                    {
                        "Authorization": "Bearer " + token,
                        "EzLLMRouter-Contract-Version": "0.3",
                        "Content-Type": "application/json",
                        "EzLLMRouter-Wait-Ms": "0",
                    },
                )
                response = connection.getresponse()
                result = {
                    "http_status": response.status,
                    "body": json.loads(response.read()),
                    "contract_header": response.getheader("EzLLMRouter-Contract-Version"),
                }
                connection.close()
                return result

            try:
                replies, boundary = synchronized_pair(
                    store,
                    service,
                    key,
                    lambda: post(request),
                    lambda: post(contender),
                    trace_path=Path(directory) / "barrier.jsonl",
                )
                traces = [
                    json.loads(line)
                    for line in (Path(directory) / "barrier.jsonl").read_text().splitlines()
                ]
                self.assertEqual([row["kind"] for row in traces].count("ct02b_barrier_arrival"), 2)
                self.assertEqual(traces[-1]["kind"], "ct02b_barrier_release")
                owner = store.work_owner(key)
                winner = next(row for row in replies if "handle" in row["body"])
                loser = next(row for row in replies if row["body"].get("code") == "WORK_CONFLICT")
                self.assertTrue(boundary["owner_absent_when_both_arrived"])
                self.assertEqual(len(boundary["arrivals"]), 2)
                self.assertEqual(
                    owner,
                    {
                        "contract_version": "0.3",
                        "submission_id": winner["body"]["handle"]["submission_id"],
                    },
                )
                self.assertEqual(
                    (
                        loser["http_status"],
                        loser["body"]["retry_guidance"],
                        loser["contract_header"],
                    ),
                    (409, "never", "0.3"),
                )
                self.assertEqual(campaign.inspect()["attempt_count"], 1)
                self.assertEqual(campaign.inspect()["possible_send_count"], 0)
                self.assertEqual(
                    store.db.execute("SELECT COUNT(*) FROM work_key_owners").fetchone()[0], 1
                )
                self.assertEqual(
                    store.db.execute("SELECT COUNT(*) FROM dev12_submissions").fetchone()[0], 1
                )
                self.assertEqual(
                    store.db.execute("SELECT COUNT(*) FROM dev12_send_ownership").fetchone()[0], 0
                )
            finally:
                web.shutdown()
                web.server_close()
                thread.join(timeout=5)
                service.pool.shutdown(wait=True)
                coordinator.pool.shutdown(wait=True)
                store.close()


if __name__ == "__main__":
    unittest.main()
