"""Actual HTTP boundary with a local fake adapter; no external provider call."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

TEST_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TEST_DIR))
REPO_SERVER = TEST_DIR.parents[1] / "server/src"
if REPO_SERVER.exists():
    sys.path.insert(0, str(REPO_SERVER))
from duranki_server.core import Coordinator
from duranki_server.store import SQLiteStore
from duranki_server.web import serve
from recipe import SyntheticDevelopmentRecipe

FIXTURE = json.loads((TEST_DIR / "fixture.json").read_text())
REQUEST = json.loads((TEST_DIR / "request.json").read_text())
TOOL_FILE = TEST_DIR / "scenarios.json"
if not TOOL_FILE.exists():
    TOOL_FILE = TEST_DIR.parent / "tool_cycle/scenarios.json"
TOOL_CASE = json.loads(TOOL_FILE.read_text())


class FakeAuthority:
    policy = {"policy_version": "policy.dev01"}
    def issue(self, projection, wd, key, classification, retention):
        return {"plan_id": "plan.test", "work_digest": wd, "work_key": copy.deepcopy(key),
                "destination": copy.deepcopy(projection["destination"]),
                "classification_snapshot": copy.deepcopy(classification),
                "effective_retention": copy.deepcopy(retention), "deadline": projection["work"]["deadline"],
                "per_attempt_total_timeout_ms": 1000}
    def verify(self, plan, wd, version):
        assert plan["work_digest"] == wd and version == self.policy["policy_version"]


class FakeAdapter:
    def __init__(self):
        self.sent = []
        self.body = {"text": "Hello.", "usage": {"input_tokens": 3, "output_tokens": 1}}
        self.status = 200
        self.unknown = False
        self.tool_mode = False
    def prepare(self, body):
        return json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()
    def describe(self, raw, timeout_ms, destination):
        return {"method": "POST", "url": "http://receiver:8766/v1/chat/completions",
                "content_type": "application/json", "content_length": len(raw),
                "body_sha256": hashlib.sha256(raw).hexdigest(), "timeout_ms": timeout_ms,
                "processing_region": destination["processing_region"]}
    def send(self, raw, timeout_ms, expected):
        assert self.describe(raw, timeout_ms, FIXTURE["destination"]) == expected
        self.sent.append(raw)
        if self.unknown: raise OSError("ambiguous synthetic loss")
        if self.tool_mode:
            body = json.loads(raw)
            if len(body["messages"]) == 2:
                return {"status": 200, "body": {"tool_calls": [{"id": "call.lookup.1", "name": "lookup",
                    "arguments_json": '{"key":"synthetic"}'}], "finish_reason": "tool_calls"}}
            return {"status": 200, "body": {"text": "Lookup: synthetic"}}
        return {"status": self.status, "body": self.body}


class FailFinalStore:
    def __init__(self, inner): self.inner = inner
    def __getattr__(self, name): return getattr(self.inner, name)
    def complete_candidate(self, *_args): raise OSError("synthetic committed-result failure")


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = SQLiteStore(Path(self.tmp.name) / "web.sqlite")
        self.addCleanup(self.store.close)
        self.adapter = FakeAdapter()
        self.coordinator = Coordinator(self.store, {"token.synthetic": FIXTURE["trusted_context"]},
            copy.deepcopy(FIXTURE["destination"]), FIXTURE["prompt_blocks"], FIXTURE["allowed_lineages"],
            FakeAuthority(), self.adapter, copy.deepcopy(FIXTURE["retention"]),
            copy.deepcopy(FIXTURE["classification"]), SyntheticDevelopmentRecipe(),
            trusted_source_labels=copy.deepcopy(FIXTURE["trusted_source_labels"]))
        self.addCleanup(self.coordinator.pool.shutdown, wait=True)
        self.server = serve("127.0.0.1", 0, self.coordinator)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.opener = build_opener(ProxyHandler({}))
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def request(self, method="POST", path="/v1/submissions", body=None):
        req = Request(self.base + path, method=method,
            data=json.dumps(REQUEST if body is None else body, separators=(",", ":")).encode() if method == "POST" else None,
            headers={"Authorization": "Bearer token.synthetic", "Duranki-Contract-Version": "0.2",
                     **({"Content-Type": "application/json"} if method == "POST" else {})})
        try:
            response = self.opener.open(req, timeout=3)
        except HTTPError as exc:
            response = exc
        with response:
            return response.status, json.load(response)

    def status(self, sid):
        return self.request("GET", "/v1/submissions/" + sid)

    def test_raw_http_positive_and_optional_shape(self):
        code, reply = self.request()
        self.assertEqual((code, reply["state"], len(self.adapter.sent)), (200, "delivered", 1))
        self.assertEqual(self.status(reply["handle"]["submission_id"])[1]["submission_state"], "completed")
        for key, value in [("parent_call", {}), ("construction_manifest_ref", ""),
                           ("session_id", ""), ("observed_at", "not-a-timestamp")]:
            with self.subTest(key=key):
                bad = copy.deepcopy(REQUEST)
                bad["execution_generation"] = "gen." + key
                bad[key] = value
                result, rejected = self.request(body=bad)
                self.assertEqual((result, rejected["error"]["code"], len(self.adapter.sent)),
                                 (400, "SCHEMA_INVALID", 1))

    def test_provider_decimal_usage_is_partial_and_not_caller_error(self):
        self.adapter.body = {"text": "Hello.", "usage": {"input_tokens": 3, "fee": 0.5}}
        code, reply = self.request()
        self.assertEqual((code, reply["state"], len(self.adapter.sent)), (200, "delivered", 1))
        self.assertEqual(reply["candidate"]["usage"]["revision"]["normalized_usage"]["input_uncached"]["count"], 3)
        sid = reply["handle"]["submission_id"]
        self.assertEqual(self.status(sid)[1]["submission_state"], "completed")

    def test_unusable_surrogate_is_durable_post_transmit_failure(self):
        self.adapter.body = {"text": "\ud800", "usage": {}}
        code, reply = self.request()
        self.assertEqual((code, reply["state"], reply["error"]["code"], len(self.adapter.sent)),
                         (502, "failed", "CANDIDATE_UNUSABLE", 1))
        snapshot = self.status(reply["handle"]["submission_id"])[1]
        self.assertEqual((snapshot["submission_state"], snapshot["terminal_attempt_id"]),
                         ("failed_after_transmit", reply["attempt_id"]))

    def test_malformed_usage_is_durable_post_transmit_failure(self):
        self.adapter.body = {"text": "Hello.", "usage": "bad"}
        code, reply = self.request()
        self.assertEqual((code, reply["error"]["code"], len(self.adapter.sent)),
                         (502, "CANDIDATE_UNUSABLE", 1))
        self.assertEqual(self.status(reply["handle"]["submission_id"])[1]["submission_state"],
                         "failed_after_transmit")

    def test_remote_failure_and_ambiguous_loss_stay_distinct(self):
        self.adapter.status = 502
        code, reply = self.request()
        self.assertEqual((code, reply["error"]["code"]), (502, "REMOTE_EXECUTION_FAILED"))
        self.assertEqual(self.status(reply["handle"]["submission_id"])[1]["submission_state"], "failed_after_transmit")
        self.adapter.unknown = True
        other = copy.deepcopy(REQUEST); other["execution_generation"] = "gen.unknown"
        code, reply = self.request(body=other)
        self.assertEqual((code, reply["state"]), (202, "pending"))
        self.assertEqual(self.status(reply["handle"]["submission_id"])[1]["submission_state"], "outcome_unknown")
        self.assertEqual(len(self.adapter.sent), 2)

    def test_post_response_store_failure_is_recoverable_without_false_terminal(self):
        self.coordinator.store = FailFinalStore(self.store)
        code, pending = self.request()
        self.assertEqual((code, pending["state"], len(self.adapter.sent)), (202, "pending", 1))
        selector = REQUEST
        path = (f"/v1/submissions/by-work/{selector['task_id']}/{selector['step_id']}/"
                f"{selector['step_revision']}/{selector['execution_generation']}")
        snapshot = self.request("GET", path)[1]
        self.assertEqual((snapshot["submission_state"], snapshot["attempts"][0]["dispatch_state"]),
                         ("outcome_unknown", "outcome_unknown"))
        self.assertEqual(snapshot["handle"], pending["handle"])
        self.assertEqual(snapshot["attempts"][0]["usage"]["state"], "available")
        self.assertNotIn("terminal_failure", snapshot)
        self.assertNotIn("candidate", snapshot)
        repeated_code, repeated = self.request()
        self.assertEqual((repeated_code, repeated["state"], repeated["handle"]),
                         (202, "pending", pending["handle"]))
        self.assertEqual(len(self.adapter.sent), 1)

    def test_http_live_no_store_tool_source_and_forgery(self):
        self.assertIsNotNone(TOOL_CASE)
        self.adapter.tool_mode = True
        restricted = {"lineage_ids": ["src.user.1"], "sensitivity": "confidential",
                      "restrictions": ["no.content.store"]}
        self.coordinator.trusted_source_labels["src.user.1"] = restricted
        first = copy.deepcopy(REQUEST)
        first.update(step_id="step.http.tool", requested_features=["text", "tools"],
                     tool_definitions=[TOOL_CASE["tool_definition"]], tool_choice="auto")
        first["messages"][1]["blocks"][0].update(text="Use lookup for synthetic.", source_labels=restricted)
        code, reply = self.request(body=first)
        self.assertEqual((code, reply["state"]), (200, "delivered"))
        call = reply["candidate"]["output_blocks"][0]
        first_status = self.status(reply["handle"]["submission_id"])[1]
        self.assertEqual(first_status["candidate_access"], "not_retained")
        self.assertNotIn("candidate", first_status)
        self.assertEqual(call["source_labels"]["restrictions"], ["no.content.store"])
        follow = copy.deepcopy(first)
        follow["execution_generation"] = "gen.2"
        follow["messages"].extend([
            {"role": "assistant", "blocks": [call]},
            {"role": "tool", "blocks": [{"block_id": "block.result.1", "kind": "tool_result",
                "call_id": call["call_id"], "result_value": {"value": "synthetic"},
                "source_labels": TOOL_CASE["result_source_labels"]}]},
        ])
        forged = copy.deepcopy(follow)
        forged["execution_generation"] = "gen.3"
        forged["messages"][2]["blocks"][0]["arguments"]["key"] = "forged"
        bad_code, bad = self.request(body=forged)
        self.assertEqual((bad_code, bad["error"]["code"], len(self.adapter.sent)),
                         (422, "SOURCE_INVALID", 1))
        code, final = self.request(body=follow)
        self.assertEqual((code, final["candidate"]["output_blocks"][0]["text"], len(self.adapter.sent)),
                         (200, "Lookup: synthetic", 2))
        self.assertEqual(final["candidate"]["output_blocks"][0]["source_labels"]["restrictions"],
                         ["no.content.store"])
        self.assertNotIn("candidate", self.status(final["handle"]["submission_id"])[1])


if __name__ == "__main__": unittest.main()
