#!/usr/bin/env python3
"""Component reproduction; no LiteLLM/SDK import or network.

Run in the existing service image with its frozen HTTPX/cryptography closure.

Uses the actual Coordinator, SQLite, Ed25519 authority, adapter._send and guard.
A named ASGI double models an SDK that retries guarded exceptions. It is NOT
an independent receiver or proof that the proposed max_retries reaches LiteLLM.
"""

from __future__ import annotations
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

parser = argparse.ArgumentParser()
parser.add_argument("--source-root", required=True, type=Path)
args, remaining = parser.parse_known_args()
ROOT = args.source_root.resolve()
if (ROOT / "server/src").is_dir():
    source_paths = ("server/src", "tests/development_slice", "tests/gateway_integration")
    data_dir = ROOT / "tests/development_slice"
else:
    source_paths = ("server", "dev_slice", "gateway")
    data_dir = ROOT / "dev_slice"
for path in source_paths:
    sys.path.insert(0, str(ROOT / path))
# Host preflight uses the staged frozen pure-Python wheels without installing them.
# The local macOS cryptography build supplies Ed25519 for this source-copy test;
# the target container still runs this suite with its pinned installed ARM64 wheel.
if (ROOT / "wheels").is_dir():
    import sysconfig

    sys.path.insert(0, sysconfig.get_paths()["platlib"])
    for name in (
        "anyio",
        "certifi",
        "h11",
        "httpcore",
        "httpx",
        "idna",
        "sniffio",
        "typing_extensions",
    ):
        matches = list((ROOT / "wheels").glob(name + "-*.whl"))
        if len(matches) != 1:
            raise RuntimeError("staged retry dependency count: " + name)
        sys.path.insert(0, str(matches[0]))
import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ezllmrouter_server.core import Coordinator
from ezllmrouter_server.runtime_resources import LoopThread
from ezllmrouter_server.plans import PlanAuthority
from ezllmrouter_server.store import SQLiteStore
from ezllmrouter_server.gateway.adapter import LiteLLMAsgiAdapter
from ezllmrouter_server.gateway.guard import (
    ACTIVE,
    GuardRejected,
    GuardTransport,
    PROVIDER_URL,
    provider_expectation,
)
from ezllmrouter_server.gateway.proxy_recipe import (
    GatewayProxyRecipe,
    public_destination,
    proxy_policy,
)

FIXTURE = json.loads((data_dir / "fixture.json").read_text())
REQUEST = json.loads((data_dir / "request.json").read_text())


class FaultStore(SQLiteStore):
    def __init__(self, path, fail=False):
        super().__init__(path)
        self.fail = fail
        self.commit_calls = 0

    def guard_commit(self, *args):
        self.commit_calls += 1
        if self.fail:
            raise OSError("injected final guard commit failure")
        return super().guard_commit(*args)


class RetryASGIDouble:
    """A controlled retry driver, NOT LiteLLM or the OpenAI SDK."""

    def __init__(self, owner, forced_retries=None):
        self.owner = owner
        self.forced_retries = forced_retries

    async def __call__(self, scope, receive, send):
        raw = b""
        while True:
            event = await receive()
            raw += event.get("body", b"")
            if not event.get("more_body", False):
                break
        payload = json.loads(raw)
        configured = payload.pop("max_retries", 2)
        # v4 makes timeout an SDK control, not provider JSON. No fake default.
        timeout = payload.pop("timeout")
        self.owner.private_requests.append(deepcopy(payload))
        self.owner.retry_settings.append(configured)
        payload["model"] = "model.demo"
        retries = configured if self.forced_retries is None else self.forced_retries
        invocation = ACTIVE.get()
        self.owner.invocations.append(invocation)
        for attempt in range(retries + 1):
            self.owner.guard_calls += 1
            try:
                response = await self.owner.guarded_client.post(
                    PROVIDER_URL,
                    json=payload,
                    timeout=timeout,
                    headers={"Authorization": "Bearer " + self.owner.provider_key},
                )
                await send(
                    {
                        "type": "http.response.start",
                        "status": response.status_code,
                        "headers": [(b"content-type", b"application/json")],
                    }
                )
                await send({"type": "http.response.body", "body": response.content})
                return
            except Exception as exc:
                self.owner.rejections.append(getattr(exc, "code", type(exc).__name__))
                if attempt == retries:
                    await send({"type": "http.response.start", "status": 500, "headers": []})
                    await send(
                        {
                            "type": "http.response.body",
                            "body": b'{"error":"controlled upstream wrapping"}',
                        }
                    )
                    return


class TestAdapter(LiteLLMAsgiAdapter):
    def __init__(self, forced_retries=None, mutation="", lower_mode="ok"):
        self.provider_key = "sk-" + "r" * 40
        self._runtime = LoopThread("ezllmrouter-fixture-loop")
        self.loop, self.thread = self._runtime.loop, self._runtime.thread
        self.proxy_mutation = mutation
        self.lower_calls = []
        self.lower_timeouts = []
        self.guard_calls = 0
        self.rejections = []
        self.invocations = []
        self.private_requests = []
        self.retry_settings = []

        def lower(request):
            self.lower_calls.append(json.loads(request.content))
            self.lower_timeouts.append(deepcopy(request.extensions["timeout"]))
            if lower_mode == "uncertain":
                raise OSError("controlled lost lower response")
            if lower_mode == "remote_failure":
                return httpx.Response(422, json={"error": "controlled rejected provider input"})
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "Hello."}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 2},
                },
            )

        self.guarded_client = httpx.AsyncClient(
            transport=GuardTransport(httpx.MockTransport(lower)), trust_env=False, timeout=1.0
        )
        self.proxy = RetryASGIDouble(self, forced_retries)

    async def _send(self, prepared, timeout_ms, invocation):
        if self.proxy_mutation:
            changed = json.loads(prepared)
            changed["messages"][1]["content"] = "Changed after binding."
            prepared = self.prepare(changed)
        return await super()._send(prepared, timeout_ms, invocation)

    def close(self):
        super().close()
        self.loop.close()


class RetryCauseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_env = {k: os.environ.get(k) for k in ("EZLLMROUTER_DEV04_GUARD_EVENTS",)}
        os.environ["EZLLMROUTER_DEV04_GUARD_EVENTS"] = str(Path(self.temp.name) / "events.jsonl")
        self.coordinator = None
        self.adapter = None
        self.store = None

    def tearDown(self):
        if self.coordinator:
            self.coordinator.pool.shutdown(wait=True)
        if self.adapter:
            self.adapter.close()
        if self.store:
            self.store.close()
        for k, v in self.old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.temp.cleanup()

    def execute(self, fail=False, retries=None, mutation="", lower_mode="ok", timeout_ms=1000):
        self.store = FaultStore(Path(self.temp.name) / "store.sqlite", fail)
        self.adapter = TestAdapter(retries, mutation, lower_mode)
        self.trusted = deepcopy(FIXTURE["trusted_context"])
        self.coordinator = Coordinator(
            self.store,
            {"token": self.trusted},
            public_destination(FIXTURE),
            deepcopy(FIXTURE["prompt_blocks"]),
            deepcopy(FIXTURE["allowed_lineages"]),
            PlanAuthority(Ed25519PrivateKey.generate(), proxy_policy(FIXTURE)),
            self.adapter,
            deepcopy(FIXTURE["retention"]),
            deepcopy(FIXTURE["classification"]),
            GatewayProxyRecipe(),
            trusted_source_labels=deepcopy(FIXTURE["trusted_source_labels"]),
        )
        request = deepcopy(REQUEST)
        request["generation_settings"]["total_timeout_ms"] = timeout_ms
        status, reply = self.coordinator.submit(
            request, self.trusted, wait_ms=3000, credential="token"
        )
        self.sid = reply["handle"]["submission_id"]
        self.record = self.store.get(self.sid)
        return status, reply

    def assert_not_sent(self):
        self.assertEqual(self.adapter.lower_calls, [])
        self.assertEqual(self.store.intent_count(self.sid), 1)
        self.assertIsNone(self.store.guard_record(self.record["attempt_id"]))

    def test_fault_with_one_guard_call_preserves_503(self):
        status, reply = self.execute(fail=True, retries=0)
        self.assertEqual((status, reply["error"]["code"]), (503, "INTENT_PERSIST_FAILED"))
        self.assert_not_sent()

    def test_fault_with_forced_reentries_preserves_first_cause_and_status(self):
        status, reply = self.execute(fail=True, retries=2)
        self.assertEqual(
            self.adapter.rejections,
            ["INTENT_PERSIST_FAILED", "SECOND_SEND_REJECTED", "SECOND_SEND_REJECTED"],
        )
        self.assertEqual(self.adapter.guard_calls, 3)
        self.assertEqual(self.store.commit_calls, 1)
        self.assert_not_sent()
        self.assertEqual((status, reply["error"]["code"]), (503, "INTENT_PERSIST_FAILED"))
        snapshot = self.coordinator.status(self.sid, self.trusted)
        self.assertEqual(snapshot["submission_state"], "failed_before_transmit")
        self.assertEqual(snapshot["terminal_failure"]["code"], "INTENT_PERSIST_FAILED")
        self.assertEqual(self.adapter.invocations[0].guard_error, "INTENT_PERSIST_FAILED")

    def test_fault_respects_explicit_private_zero_retry_setting(self):
        status, reply = self.execute(fail=True)
        self.assert_not_sent()
        self.assertEqual(self.adapter.retry_settings, [0])
        self.assertEqual(self.adapter.guard_calls, 1)
        self.assertEqual((status, reply["error"]["code"]), (503, "INTENT_PERSIST_FAILED"))

    def test_mutation_reentries_still_block_without_commit(self):
        status, reply = self.execute(retries=2, mutation="content")
        self.assertEqual((status, reply["error"]["code"]), (409, "FDC_REJECTED"))
        self.assertEqual(self.store.commit_calls, 0)
        self.assertEqual(self.adapter.invocations[0].guard_error, "FDC_REJECTED")
        self.assert_not_sent()

    def test_positive_single_send_keeps_public_identity(self):
        status, reply = self.execute()
        self.assertEqual((status, reply["state"]), (200, "delivered"))
        self.assertEqual(reply["candidate"]["served_destination"]["model"], "model.demo")
        self.assertEqual(len(self.adapter.lower_calls), 1)
        self.assertNotIn("max_retries", self.adapter.lower_calls[0])
        self.assertNotIn("timeout", self.adapter.lower_calls[0])
        self.assertEqual(
            self.adapter.lower_timeouts, [dict.fromkeys(("connect", "read", "write", "pool"), 1.0)]
        )
        self.assertEqual(self.adapter.lower_calls[0]["model"], "model.demo")
        self.assertEqual(self.store.commit_calls, 1)
        self.assertIsNotNone(self.store.guard_record(self.record["attempt_id"]))

    def test_known_remote_failure_is_not_reclassified_pretransmit(self):
        status, reply = self.execute(lower_mode="remote_failure")
        self.assertEqual((status, reply["error"]["code"]), (502, "REMOTE_EXECUTION_FAILED"))
        self.assertEqual(len(self.adapter.lower_calls), 1)
        self.assertEqual(self.record["submission_state"], "failed_after_transmit")

    def test_lower_uncertainty_and_reentries_remain_unknown(self):
        status, reply = self.execute(retries=2, lower_mode="uncertain")
        self.assertEqual((status, reply["state"]), (202, "pending"))
        self.assertEqual(len(self.adapter.lower_calls), 1)
        self.assertEqual(self.record["submission_state"], "outcome_unknown")
        self.assertTrue(self.adapter.invocations[0].released)

    def test_private_retry_setting_and_digest_are_bound_without_work_mutation(self):
        status, reply = self.execute()
        invocation = self.adapter.invocations[0]
        before = deepcopy(invocation.projection)
        raw, controls = GatewayProxyRecipe().expected(invocation.projection, 1000)
        body = json.loads(raw)
        self.assertIs(type(body.get("max_retries")), int)
        self.assertEqual(body["max_retries"], 0)
        self.assertEqual(controls["body_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(controls["content_length"], len(raw))
        self.assertEqual(invocation.projection, before)
        self.assertNotIn("max_retries", provider_expectation(before))
        self.assertEqual(body["timeout"], 1.0)
        self.assertNotIn("timeout", provider_expectation(before))
        self.assertEqual(proxy_policy(FIXTURE)["adapter_recipe_ref"], "recipe.dev04.proxy.text.v4")
        self.assertEqual(
            proxy_policy(FIXTURE)["tool_adapter_recipe_ref"], "recipe.dev04.proxy.tool.v4"
        )

    def test_provider_field_leak_remains_rejected(self):
        self.execute()
        invocation = deepcopy(self.adapter.invocations[0].projection)
        from ezllmrouter_server.gateway.guard import Invocation, check_request

        context = Invocation(
            "submission.test",
            "attempt.test",
            {
                "plan_id": "plan.test",
                "work_digest": "sha256:test",
                "per_attempt_total_timeout_ms": 1000,
            },
            invocation,
            lambda: None,
            lambda _: None,
            provider_key="sk-" + "r" * 40,
        )
        # Both private controls must be consumed by the SDK, never by the provider.
        for field, value in (("max_retries", 0), ("timeout", 1.0)):
            with self.subTest(field=field):
                body = {**provider_expectation(invocation), field: value}
                request = httpx.Request(
                    "POST",
                    PROVIDER_URL,
                    json=body,
                    headers={
                        "Authorization": "Bearer " + self.adapter.provider_key,
                        "x-ezllmrouter-attempt": "attempt.test",
                    },
                    extensions={"timeout": {"read": 1.0}},
                )
                with self.assertRaises(GuardRejected):
                    check_request(request, context, request.content)

    def test_signed_thirty_second_timeout_reaches_fake_lower_as_control(self):
        status, reply = self.execute(timeout_ms=30000)
        self.assertEqual((status, reply["state"]), (200, "delivered"))
        expected = dict.fromkeys(("connect", "read", "write", "pool"), 30.0)
        self.assertEqual(self.adapter.lower_timeouts, [expected])
        self.assertEqual(self.adapter.retry_settings, [0])
        self.assertEqual(self.adapter.guard_calls, 1)
        self.assertNotIn("timeout", self.adapter.lower_calls[0])
        self.assertNotIn("max_retries", self.adapter.lower_calls[0])
        receipt = self.store.guard_record(self.record["attempt_id"])
        self.assertEqual(receipt["timeout_seconds"], expected)

    def test_timeout_over_signed_budget_still_rejects(self):
        self.execute()
        from ezllmrouter_server.gateway.guard import Invocation, check_request

        context = Invocation(
            "submission.timeout",
            "attempt.timeout",
            {
                "plan_id": "plan.timeout",
                "work_digest": "sha256:test",
                "per_attempt_total_timeout_ms": 1000,
            },
            self.adapter.invocations[0].projection,
            lambda: None,
            lambda _: None,
            provider_key="sk-" + "r" * 40,
        )
        request = httpx.Request(
            "POST",
            PROVIDER_URL,
            json=provider_expectation(context.projection),
            headers={
                "Authorization": "Bearer " + self.adapter.provider_key,
                "x-ezllmrouter-attempt": context.attempt_id,
            },
            extensions={"timeout": dict.fromkeys(("connect", "read", "write", "pool"), 30.0)},
        )
        with self.assertRaises(GuardRejected):
            check_request(request, context, request.content)

    def test_timeout_changes_private_binding_without_changing_work(self):
        self.execute()
        projected = deepcopy(self.adapter.invocations[0].projection)
        before = deepcopy(projected)
        body1, controls1 = GatewayProxyRecipe().expected(projected, 1000)
        body30, controls30 = GatewayProxyRecipe().expected(projected, 30000)
        self.assertEqual(projected, before)
        self.assertEqual(json.loads(body1)["timeout"], 1.0)
        self.assertEqual(json.loads(body30)["timeout"], 30.0)
        self.assertNotEqual(body1, body30)
        self.assertNotEqual(controls1["body_sha256"], controls30["body_sha256"])
        for body, controls in ((body1, controls1), (body30, controls30)):
            self.assertEqual(controls["body_sha256"], hashlib.sha256(body).hexdigest())
            self.assertEqual(controls["content_length"], len(body))
            self.assertEqual(json.loads(body)["max_retries"], 0)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0], *remaining], verbosity=2)
