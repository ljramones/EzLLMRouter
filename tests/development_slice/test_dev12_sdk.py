"""No-network successor SDK protocol distinctions against adopted fixtures."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import unittest

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, os.environ.get("DEV12_PY_CLIENT_TARGET", str(ROOT / "clients/python/src")))
from ezllmrouter_client import EzLLMRouterClient, EzLLMRouterError  # noqa: E402

VECTORS = json.loads((ROOT / "tests/fixtures/contracts/dev12-successor-01/vectors.json").read_text())
REQUEST = next(item["request"] for item in VECTORS["examples"] if item["id"] == "DELEGATED_RERANK")
COMPLETED = next(item["value"] for item in VECTORS["protocol_fixtures"] if item["id"] == "COMPLETED")
STATUS = next(item["value"] for item in VECTORS["protocol_fixtures"]
              if item["id"] == "STATUS_VALID_UNKNOWN_COST")
FAILED = next(item["value"] for item in VECTORS["protocol_fixtures"]
              if item["id"] == "FAILED_BEFORE_SEND")
KNOWN_STATUS = next(item["value"] for item in VECTORS["protocol_fixtures"]
                    if item["id"] == "STATUS_INVALID_OUTPUT_WITH_USAGE")


class StaticTransport:
    def __init__(self, value, status=200, raw=None):
        self.value, self.status, self.raw = value, status, raw
        self.calls = 0

    def request(self, *_args, **_kwargs):
        self.calls += 1
        raw = self.raw if self.raw is not None else json.dumps(self.value, separators=(",", ":")).encode()
        return httpx.Response(self.status, content=raw,
                              headers={"EzLLMRouter-Contract-Version": "0.3"})

    def close(self):
        pass


class SuccessorSdkTests(unittest.TestCase):
    def invoke(self, value, status=200, raw=None, *, kind="submit"):
        transport = StaticTransport(value, status, raw)
        with EzLLMRouterClient("http://synthetic.invalid", "test-only-token", transport=transport) as client:
            if kind == "submit":
                return client.submit_rerank(deepcopy(REQUEST))
            return client.get_successor_status({"submission_id": STATUS["handle"]["submission_id"]})

    def test_valid_and_http_state_mapping(self):
        self.assertEqual(self.invoke(COMPLETED)["state"], "completed")
        self.assertEqual(self.invoke(STATUS, kind="status")["submission_state"], "completed")
        for value, status, kind in ((COMPLETED, 202, "submit"),
                                    (STATUS, 202, "status")):
            with self.subTest(status=status, kind=kind), self.assertRaises(EzLLMRouterError) as error:
                self.invoke(value, status, kind=kind)
            self.assertEqual(error.exception.retry_guidance, "query_first")

    def test_semantic_and_strict_wire_negatives(self):
        foreign = deepcopy(COMPLETED)
        foreign["result"]["results"][0]["candidate_id"] = "doc.foreign"
        high_score = deepcopy(COMPLETED)
        high_score["result"]["results"][0]["score"] = "99"
        incoherent = deepcopy(STATUS)
        incoherent["attempts"][0]["settlement_state"] = "calculated"
        for value, kind in ((foreign, "submit"), (high_score, "submit"),
                            (incoherent, "status")):
            with self.subTest(kind=kind), self.assertRaises(EzLLMRouterError) as error:
                self.invoke(value, kind=kind)
            self.assertEqual(error.exception.retry_guidance, "query_first")
        duplicate = json.dumps(COMPLETED, separators=(",", ":")).replace(
            '"state":"completed"', '"state":"pending","state":"completed"', 1).encode()
        for raw in (duplicate, b"\xff", b'{"state":"\\ud800"}'):
            with self.subTest(raw=raw[:30]), self.assertRaises(EzLLMRouterError) as error:
                self.invoke(COMPLETED, raw=raw)
            self.assertEqual(error.exception.retry_guidance, "query_first")

    def test_adopted_expired_duplicate_guidance(self):
        error_body = {"contract_version": "0.3", "code": "POLICY_DENIED",
                      "correlation_id": "error.synthetic", "retry_guidance": "query_first"}
        with self.assertRaises(EzLLMRouterError) as error:
            self.invoke(error_body, 403)
        self.assertEqual((error.exception.code, error.exception.retry_guidance),
                         ("POLICY_DENIED", "query_first"))
        self.assertEqual(error.exception.selector, REQUEST["work_selector"])

    def test_selected_authentication_projection(self):
        body = {"contract_version": "0.3", "code": "POLICY_DENIED",
                "correlation_id": "error.synthetic", "retry_guidance": "never"}
        for kind in ("submit", "status"):
            with self.subTest(kind=kind), self.assertRaises(EzLLMRouterError) as error:
                self.invoke(body, 401, kind=kind)
            self.assertEqual((error.exception.code, error.exception.http_status,
                              error.exception.retry_guidance), ("POLICY_DENIED", 401, "never"))
        from ezllmrouter_client import _successor_validation as validation
        self.assertFalse(validation.error_valid({**body, "retry_guidance": "query_first"}, 401, "submit"))
        self.assertFalse(validation.error_valid({**body, "code": "INTENT_PERSIST_FAILED"}, 401, "submit"))
        self.assertFalse(validation.error_valid({**body, "extra": True}, 401, "submit"))

    def test_reordered_operation_and_native_evidence_are_consistent(self):
        reordered = deepcopy(REQUEST)
        reordered["operation"] = {"version": 1, "type": "rerank"}
        transport = StaticTransport(COMPLETED)
        with EzLLMRouterClient("http://synthetic.invalid", "test-only-token", transport=transport) as client:
            self.assertEqual(client.submit_rerank(reordered)["state"], "completed")
        components = (
            {"component": "document_units", "presence": "absent"},
            {"component": "document_units", "presence": "null"},
            {"component": "document_units", "presence": "invalid", "raw_digest": "sha256:" + "0" * 64},
            {"component": "document_units", "presence": "known", "quantity": 1,
             "evidence": "derived", "source_ref": "receiver.synthetic"},
        )
        for component in components:
            with self.subTest(component=component), self.assertRaises(EzLLMRouterError) as error:
                invalid = deepcopy(STATUS)
                usage = invalid["attempts"][0]["usage_revision"]
                usage["components"] = [component]
                usage["cost_status"] = "calculated"
                usage["amount_decimal"] = "0.000200000"
                invalid["attempts"][0]["settlement_state"] = "calculated"
                self.invoke(invalid, kind="status")
            self.assertEqual(error.exception.retry_guidance, "query_first")

    def test_exact_http_error_and_known_intent_failure(self):
        failed = deepcopy(FAILED)
        failed["error"] = {"contract_version": "0.3", "code": "INTENT_PERSIST_FAILED",
                           "correlation_id": "error.synthetic", "retry_guidance": "query_first"}
        with self.assertRaises(EzLLMRouterError) as error:
            self.invoke(failed, 503)
        self.assertEqual((error.exception.code, error.exception.attempt_id),
                         ("INTENT_PERSIST_FAILED", failed["attempt_id"]))
        wrong = {"contract_version": "0.3", "code": "WORK_VERSION_CONFLICT",
                 "correlation_id": "error.synthetic", "retry_guidance": "never"}
        with self.assertRaises(EzLLMRouterError) as error:
            self.invoke(wrong, 500)
        self.assertEqual((error.exception.code, error.exception.retry_guidance),
                         ("INTERNAL_UNAVAILABLE", "query_first"))

    def test_reported_zero_is_unknown_not_calculated_or_over_bound(self):
        self.assertEqual(self.invoke(KNOWN_STATUS, kind="status")["submission_state"], "failed")
        zero_unknown = deepcopy(KNOWN_STATUS)
        usage = zero_unknown["attempts"][0]["usage_revision"]
        usage["components"][0]["quantity"] = 0
        usage["cost_status"] = zero_unknown["attempts"][0]["settlement_state"] = "unknown"
        del usage["amount_decimal"]
        self.assertEqual(self.invoke(zero_unknown, kind="status")["submission_state"], "failed")
        for state in ("calculated", "over_bound"):
            contradictory = deepcopy(zero_unknown)
            usage = contradictory["attempts"][0]["usage_revision"]
            usage["cost_status"] = contradictory["attempts"][0]["settlement_state"] = state
            usage["amount_decimal"] = "0.000000000"
            with self.subTest(state=state), self.assertRaises(EzLLMRouterError) as error:
                self.invoke(contradictory, kind="status")
            self.assertEqual(error.exception.retry_guidance, "query_first")


if __name__ == "__main__":
    unittest.main()
