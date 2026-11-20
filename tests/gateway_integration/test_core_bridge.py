"""Domain integration controls for DEV-04's private guard callback boundary."""

from copy import deepcopy
from pathlib import Path
import hashlib
import json
import sys
import tempfile
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/src"))
sys.path.insert(0, str(ROOT / "tests/development_slice"))

from ezllmrouter_server.core import Coordinator
from ezllmrouter_server.plans import PlanAuthority
from ezllmrouter_server.store import SQLiteStore
from recipe import SyntheticDevelopmentRecipe


FIXTURE = json.loads((ROOT / "tests/development_slice/fixture.json").read_text())
REQUEST = json.loads((ROOT / "tests/development_slice/request.json").read_text())


class GatewayAdapterStub:
    def __init__(self, fail_commit=False, revoke=None):
        self.sends = 0
        self.fail_commit = fail_commit
        self.revoke = revoke

    def prepare(self, body):
        return json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()

    def describe(self, prepared, timeout_ms, destination):
        return {
            "method": "POST",
            "url": "http://receiver:8766/v1/chat/completions",
            "content_type": "application/json",
            "content_length": len(prepared),
            "body_sha256": hashlib.sha256(prepared).hexdigest(),
            "timeout_ms": timeout_ms,
            "processing_region": destination["processing_region"],
        }

    def send_with_context(self, prepared, timeout_ms, expected, context):
        assert self.describe(prepared, timeout_ms, context["plan"]["destination"]) == expected
        if self.revoke:
            self.revoke()
        context["fresh_check"]()
        if self.fail_commit:
            from ezllmrouter_server.canonical import ContractError

            raise ContractError("INTENT_PERSIST_FAILED", 503)
        context["commit"](
            {
                "attempt_id": context["attempt_id"],
                "plan_id": context["plan"]["plan_id"],
                "work_digest": context["plan"]["work_digest"],
                "body_sha256": hashlib.sha256(prepared).hexdigest(),
            }
        )
        self.sends += 1
        return {
            "status": 200,
            "body": {"text": "Hello.", "usage": {"input_tokens": 3, "output_tokens": 1}},
        }


class CoreBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = SQLiteStore(Path(self.temp.name) / "store.sqlite")
        self.identity = {"token": deepcopy(FIXTURE["trusted_context"])}

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def coordinator(self, adapter):
        return Coordinator(
            self.store,
            self.identity,
            deepcopy(FIXTURE["destination"]),
            deepcopy(FIXTURE["prompt_blocks"]),
            deepcopy(FIXTURE["allowed_lineages"]),
            PlanAuthority(Ed25519PrivateKey.generate(), deepcopy(FIXTURE["policy"])),
            adapter,
            deepcopy(FIXTURE["retention"]),
            deepcopy(FIXTURE["classification"]),
            SyntheticDevelopmentRecipe(),
            trusted_source_labels=deepcopy(FIXTURE["trusted_source_labels"]),
        )

    def test_signed_work_same_attempt_guard_commit_then_send(self):
        adapter = GatewayAdapterStub()
        coordinator = self.coordinator(adapter)
        try:
            status, reply = coordinator.submit(
                deepcopy(REQUEST), self.identity["token"], wait_ms=3000, credential="token"
            )
            self.assertEqual((status, reply["state"], adapter.sends), (200, "delivered", 1))
            attempt = reply["candidate"]["attempt_id"]
            self.assertEqual(self.store.intent_count(reply["handle"]["submission_id"]), 1)
            self.assertEqual(self.store.guard_record(attempt)["attempt_id"], attempt)
        finally:
            coordinator.pool.shutdown(wait=True)

    def test_guard_commit_failure_retains_preparatory_intent_without_send(self):
        adapter = GatewayAdapterStub(fail_commit=True)
        coordinator = self.coordinator(adapter)
        try:
            status, reply = coordinator.submit(
                deepcopy(REQUEST), self.identity["token"], wait_ms=3000, credential="token"
            )
            self.assertEqual(
                (status, reply["state"], reply["error"]["code"], adapter.sends),
                (503, "failed", "INTENT_PERSIST_FAILED", 0),
            )
            self.assertEqual(self.store.intent_count(reply["handle"]["submission_id"]), 1)
            self.assertIsNone(self.store.guard_record(reply["attempt_id"]))
        finally:
            coordinator.pool.shutdown(wait=True)

    def test_late_current_authority_change_blocks_guard(self):
        adapter = GatewayAdapterStub(
            revoke=lambda: self.identity["token"].update(principal_id="svc.changed")
        )
        coordinator = self.coordinator(adapter)
        try:
            status, reply = coordinator.submit(
                deepcopy(REQUEST), self.identity["token"], wait_ms=3000, credential="token"
            )
            self.assertEqual(
                (status, reply["error"]["code"], adapter.sends), (409, "FDC_REJECTED", 0)
            )
            self.assertIsNone(self.store.guard_record(reply["attempt_id"]))
        finally:
            coordinator.pool.shutdown(wait=True)


if __name__ == "__main__":
    unittest.main()
