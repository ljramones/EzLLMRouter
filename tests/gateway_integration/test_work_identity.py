#!/usr/bin/env python3
"""Source-copy regression for DEV-05 Run-15's WorkKey type mismatch.

Usage: python -I -B THIS.py --source-root /path/to/extracted/source/service
Also accepts a repository root. --observe prints the real Coordinator result.
No Docker, LiteLLM/SDK import, socket connection, or package installation.
Actual signing, Coordinator, SQLite, ChoiceBSenderAdapter and final guard run;
only the worker/SDK transformation and lower provider are controlled doubles.
"""

from __future__ import annotations
import argparse
import base64
from concurrent.futures import Future
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source-root", type=Path, required=True)
parser.add_argument("--observe", action="store_true")
args, remaining = parser.parse_known_args()
ROOT = args.source_root.resolve()
if (ROOT / "server/src").is_dir():
    source_paths = ("server/src", "tests/gateway_integration", "tests/development_slice")
    DATA = ROOT / "tests/development_slice"
else:
    source_paths = ("server", "gateway", "dev_slice")
    DATA = ROOT / "dev_slice"
for name in source_paths:
    sys.path.insert(0, str(ROOT / name))
# As in the existing retry suite, reuse staged pure-Python wheels when supplied.
# A host source-copy replay still uses its existing native cryptography build.
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
            raise RuntimeError("staged dependency count: " + name)
        sys.path.insert(0, str(matches[0]))
import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ezllmrouter_server.canonical import SAFE
from ezllmrouter_server.core import Coordinator
from ezllmrouter_server.runtime_resources import LoopThread
from ezllmrouter_server.plans import PlanAuthority
from ezllmrouter_server.store import SQLiteStore
from ezllmrouter_server.gateway.choice_b_sender import ChoiceBSenderAdapter, WORKER_KEY
from ezllmrouter_server.gateway.guard import GuardTransport, Invocation, PROVIDER_URL
from ezllmrouter_server.gateway.owned_sender_transport import LocalSendAuthority
from ezllmrouter_server.gateway.proxy_recipe import (
    GatewayProxyRecipe,
    public_destination,
    proxy_policy,
)

FIXTURE = json.loads((DATA / "fixture.json").read_text())
REQUEST = json.loads((DATA / "request.json").read_text())
PROVIDER_KEY = "sk-" + "s" * 40


class CommitStore(SQLiteStore):
    def __init__(self, path, fail=False):
        super().__init__(path)
        self.fail = fail
        self.commit_calls = 0

    def guard_commit(self, *args):
        self.commit_calls += 1
        if self.fail:
            raise OSError("controlled persistence failure")
        return super().guard_commit(*args)


class ControlledWorkerAdapter(ChoiceBSenderAdapter):
    """Keep real sender registration, process_relay, _send, guard and error mapping."""

    def __init__(self, mutation=False):
        self.authority = LocalSendAuthority()
        self.provider_key = PROVIDER_KEY
        self.registry = {}
        self.claimed = set()
        self.lock = threading.Lock()
        self._runtime = LoopThread("ezllmrouter-fixture-loop")
        self.loop, self.thread = self._runtime.loop, self._runtime.thread
        self.mutation = mutation
        self.invocations = []
        self.relay_errors = []
        self.private_controls = []
        self.lower_requests = []

        def lower(request):
            self.lower_requests.append(
                {
                    "attempt_id": request.headers["x-ezllmrouter-attempt"],
                    "body": json.loads(request.content),
                    "timeout": deepcopy(request.extensions["timeout"]),
                }
            )
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "Hello."}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 2},
                },
            )

        self.guard = GuardTransport(httpx.MockTransport(lower))

    def _worker_command(self, envelope, timeout):
        # This controlled translator is NOT LiteLLM. Sender logic below is original.
        invocation = self.registry[envelope["attempt_id"]]
        self.invocations.append(invocation)
        payload = json.loads(base64.b64decode(envelope["prepared_b64"], validate=True))
        retries = payload.pop("max_retries")
        budget = payload.pop("timeout")
        self.private_controls.append({"max_retries": retries, "timeout": budget})
        if retries != 0:
            raise AssertionError("unexpected retry setting")
        if payload["model"] != "openai/model.demo":
            raise AssertionError("unexpected model")
        payload["model"] = "model.evil" if self.mutation else "model.demo"
        req = httpx.Request(
            "POST",
            PROVIDER_URL,
            json=payload,
            headers={"Authorization": "Bearer " + WORKER_KEY},
            extensions={"timeout": dict.fromkeys(("connect", "read", "write", "pool"), budget)},
        )
        final = {
            "kind": "final_request",
            "attempt_id": invocation.attempt_id,
            "method": req.method,
            "url": str(req.url),
            "headers": [list(x) for x in req.headers.items()],
            "body_b64": base64.b64encode(req.content).decode("ascii"),
            "timeout": req.extensions["timeout"],
        }
        try:
            response = self.process_relay(final)
        except Exception as exc:
            self.relay_errors.append({"type": type(exc).__name__, "message": str(exc)})
            return {"status": 500, "body": None}
        return {
            "status": response["status"],
            "body": json.loads(base64.b64decode(response["body_b64"])),
        }

    def close(self):
        self._runtime.close(self.guard.aclose())


def integration(revision=1, mutation=False, fail_commit=False, timeout_ms=1000):
    with tempfile.TemporaryDirectory(prefix="ezllmrouter-run15-") as tmp:
        env = {
            "EZLLMROUTER_DEV04_PROVIDER_KEY": PROVIDER_KEY,
            "EZLLMROUTER_GATEWAY_GUARD_EVENTS": str(Path(tmp) / "guard.jsonl"),
            "EZLLMROUTER_GATEWAY_SEND_EVENTS": str(Path(tmp) / "send.jsonl"),
        }
        with patch.dict(os.environ, env):
            store = CommitStore(Path(tmp) / "store.sqlite", fail_commit)
            adapter = ControlledWorkerAdapter(mutation)
            trusted = deepcopy(FIXTURE["trusted_context"])
            signer = PlanAuthority(Ed25519PrivateKey.generate(), proxy_policy(FIXTURE))
            core = Coordinator(
                store,
                identity={"token": trusted},
                config=public_destination(FIXTURE),
                prompt_blocks=deepcopy(FIXTURE["prompt_blocks"]),
                allowed_lineages=deepcopy(FIXTURE["allowed_lineages"]),
                authority=signer,
                adapter=adapter,
                retention=deepcopy(FIXTURE["retention"]),
                classification=deepcopy(FIXTURE["classification"]),
                recipe=GatewayProxyRecipe(),
                trusted_source_labels=deepcopy(FIXTURE["trusted_source_labels"]),
            )
            try:
                request = deepcopy(REQUEST)
                request["step_id"] = "step.dev04.js.text"
                request["step_revision"] = revision
                request["generation_settings"]["total_timeout_ms"] = timeout_ms
                code, reply = core.submit(request, trusted, wait_ms=3000, credential="token")
                sid = reply["handle"]["submission_id"]
                record = store.get(sid)
                snapshot = core.status(sid, trusted)
                inv = adapter.invocations[0]
                signer.verify(inv.plan, record["work_digest"], signer.policy["policy_version"])

                def rows(name):
                    from ezllmrouter_server.gateway.guard import flush_events

                    if not (flush_events(timeout=2)):
                        raise AssertionError("diagnostic test events did not drain")
                    p = Path(tmp) / name
                    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

                return {
                    "http_status": code,
                    "reply_state": reply["state"],
                    "error_code": reply.get("error", {}).get("code"),
                    "submission_state": snapshot["submission_state"],
                    "candidate_access": snapshot["candidate_access"],
                    "work_key": inv.plan["work_key"],
                    "plan_signature_verified": True,
                    "intents": store.intent_count(sid),
                    "guard_receipts": store.db.execute(
                        "select count(*) from guard_dispatches"
                    ).fetchone()[0],
                    "usage_revisions": store.db.execute(
                        "select count(*) from usage_revisions"
                    ).fetchone()[0],
                    "lower_calls": len(adapter.lower_requests),
                    "lower_requests": adapter.lower_requests,
                    "relay_errors": adapter.relay_errors,
                    "guard_events": rows("guard.jsonl"),
                    "send_events": rows("send.jsonl"),
                    "private_controls": adapter.private_controls,
                    "invocation_attempted": inv.attempted,
                    "guard_error": inv.guard_error,
                }
            finally:
                core.pool.shutdown(wait=True)
                adapter.close()
                store.close()


def registry_probe(key, registered=True):
    """Test admission shape only; close coroutine before any guard or transport."""
    a = object.__new__(ChoiceBSenderAdapter)
    a.registry = {}
    a.claimed = set()
    a.lock = threading.Lock()
    a.provider_key = PROVIDER_KEY
    calls = []
    plan = {"per_attempt_total_timeout_ms": 1000}
    if key is not ABSENT:
        plan["work_key"] = deepcopy(key)
    inv = Invocation("submission.shape", "attempt.shape", plan, {}, lambda: None, lambda _: None)
    if registered:
        a.registry[inv.attempt_id] = inv

    def inspect(coro):
        calls.append(coro.cr_frame.f_locals["request"])
        coro.close()
        f = Future()
        f.set_result({"status": 200})
        return f

    a._call = inspect
    envelope = {
        "kind": "final_request",
        "attempt_id": inv.attempt_id,
        "method": "POST",
        "url": PROVIDER_URL,
        "headers": [["authorization", "Bearer " + WORKER_KEY]],
        "body_b64": "e30=",
        "timeout": dict.fromkeys(("connect", "read", "write", "pool"), 1.0),
    }
    return a, inv, envelope, calls


ABSENT = object()
KEY = {
    "principal_id": "svc.demo",
    "task_id": "task.demo",
    "step_id": "step.demo",
    "step_revision": 1,
    "execution_generation": "gen.1",
}


class WorkIdentityTests(unittest.TestCase):
    def reject(self, key):
        a, inv, envelope, calls = registry_probe(key)
        with self.assertRaisesRegex(ValueError, "required work identity"):
            a.process_relay(envelope)
        self.assertEqual(calls, [])
        self.assertFalse(inv.attempted)

    def test_real_coordinator_signed_integer_plan_completes(self):
        for revision in (1, SAFE):
            with self.subTest(revision=revision):
                r = integration(revision)
                self.assertEqual((r["http_status"], r["reply_state"]), (200, "delivered"), r)
                self.assertIs(type(r["work_key"]["step_revision"]), int)
                self.assertEqual(r["work_key"]["step_revision"], revision)
                self.assertEqual(
                    (r["intents"], r["guard_receipts"], r["lower_calls"], r["usage_revisions"]),
                    (1, 1, 1, 1),
                )
                self.assertTrue(r["plan_signature_verified"])
                self.assertEqual(r["candidate_access"], "present")
                self.assertEqual(
                    [x["stage"] for x in r["guard_events"]],
                    ["entered", "commit_acknowledged", "released_to_lower_transport"],
                )

    def test_bound_provider_mutation_still_reaches_guard_and_blocks(self):
        r = integration(mutation=True)
        self.assertEqual((r["http_status"], r["error_code"]), (409, "FDC_REJECTED"))
        self.assertTrue(r["invocation_attempted"])
        self.assertEqual(r["guard_error"], "FDC_REJECTED")
        self.assertEqual((r["intents"], r["guard_receipts"], r["lower_calls"]), (1, 0, 0))

    def test_final_commit_failure_keeps_503_not_identity_rejection(self):
        r = integration(fail_commit=True)
        self.assertEqual((r["http_status"], r["error_code"]), (503, "INTENT_PERSIST_FAILED"))
        self.assertTrue(r["invocation_attempted"])
        self.assertEqual((r["intents"], r["guard_receipts"], r["lower_calls"]), (1, 0, 0))

    def test_signed_30_second_private_control_is_preserved(self):
        r = integration(timeout_ms=30000)
        self.assertEqual(r["http_status"], 200, r)
        self.assertEqual(r["private_controls"], [{"max_retries": 0, "timeout": 30.0}])
        self.assertEqual(
            r["lower_requests"][0]["timeout"],
            dict.fromkeys(("connect", "read", "write", "pool"), 30.0),
        )
        self.assertNotIn("timeout", r["lower_requests"][0]["body"])
        self.assertNotIn("max_retries", r["lower_requests"][0]["body"])

    def test_valid_integer_boundaries_reach_sender(self):
        for revision in (1, 2, SAFE):
            with self.subTest(revision=revision):
                a, inv, e, c = registry_probe({**KEY, "step_revision": revision})
                self.assertEqual(a.process_relay(e)["status"], 200)
                self.assertEqual(len(c), 1)

    def test_string_revisions_are_not_validated_by_bad_fixture(self):
        for value in ("rev.1", "1", ""):
            with self.subTest(value=value):
                self.reject({**KEY, "step_revision": value})

    def test_boolean_revisions_are_not_integers(self):
        for value in (True, False):
            self.reject({**KEY, "step_revision": value})

    def test_float_null_and_structured_revisions_rejected(self):
        for value in (1.0, None, {}, []):
            with self.subTest(value=value):
                self.reject({**KEY, "step_revision": value})

    def test_nonpositive_and_unsafe_revisions_rejected(self):
        for value in (0, -1, SAFE + 1):
            self.reject({**KEY, "step_revision": value})

    def test_missing_key_or_revision_rejected(self):
        for key in (ABSENT, None, [], {}, {k: v for k, v in KEY.items() if k != "step_revision"}):
            self.reject(key)

    def test_missing_or_malformed_string_identity_rejected(self):
        for field in ("principal_id", "task_id", "step_id", "execution_generation"):
            for value in (None, "", 7, False):
                with self.subTest(field=field, value=value):
                    self.reject({**KEY, field: value})
            self.reject({k: v for k, v in KEY.items() if k != field})

    def test_forgery_and_reused_attempt_still_rejected(self):
        a, inv, e, c = registry_probe(KEY, registered=False)
        with self.assertRaisesRegex(ValueError, "unregistered attempt"):
            a.process_relay(e)
        self.assertEqual(c, [])
        a, inv, e, c = registry_probe(KEY)
        a.process_relay(e)
        with self.assertRaisesRegex(ValueError, "replayed attempt"):
            a.process_relay(e)
        self.assertEqual(len(c), 1)


if __name__ == "__main__":
    if args.observe:
        print(json.dumps(integration(), indent=2))
    else:
        unittest.main(argv=[sys.argv[0]] + remaining, verbosity=2)
