"""Local source, sender-admission and Unix-record gates before target execution."""
import base64
import asyncio
from concurrent.futures import Future
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import struct
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests/gateway_integration"))
from choice_b_wire import LIMIT, receive, send  # noqa: E402
from tools.gateway.stage import source_mapping


WORKER_SOURCE_FILES = {"choice_b_worker.py", "choice_b_wire.py"}


def stage_worker_source_context(root, destination):
    """Replay the worker source map without frozen wheels or Docker."""
    mappings = source_mapping(root)
    targets = set()
    for source, target in mappings:
        if not target.startswith("worker/"):
            continue
        relative = Path(target).relative_to("worker")
        if relative.is_absolute() or ".." in relative.parts or relative in targets:
            raise AssertionError("invalid/duplicate worker staging target")
        targets.add(relative)
        dest = destination / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / source, dest)
    return destination


def validate_worker_source_context(context):
    """Fixed two-module worker check, not a general Dockerfile interpreter."""
    dockerfile = (context / "Dockerfile").read_text()
    app_copies = []
    for line in dockerfile.splitlines():
        if not line.lstrip().upper().startswith("COPY "):
            continue
        fields = shlex.split(line, comments=True)
        if fields and fields[0].upper() == "COPY" and fields[-1] == "/app/worker/":
            app_copies.append(fields[1:-1])
    if len(app_copies) != 1:
        raise AssertionError("expected one explicit worker code COPY")
    sources = app_copies[0]
    for name in sources:
        if not (context / name).is_file():
            raise AssertionError("worker COPY source is not a staged file: " + name)
    if len(sources) != 2 or set(sources) != WORKER_SOURCE_FILES:
        raise AssertionError("worker COPY must name exactly the two worker modules")
    observed = {path.relative_to(context).as_posix()
                for path in context.rglob("*") if path.is_file()}
    if observed != WORKER_SOURCE_FILES | {"Dockerfile"}:
        raise AssertionError("unexpected worker source content")
    return dockerfile


class ChoiceBComponentTests(unittest.TestCase):
    def test_verifier_parses_pretty_single_document_and_jsonl_rows(self):
        from verify_choice_b import one, rows

        modules = '''{
  "boundary": "separate trusted Choice B sender",
  "litellm_imported": false,
  "provider_key_in_trusted_process": true,
  "worker_socket": "/link/worker.sock",
  "sender_socket": "/link/sender.sock"
}
'''
        with tempfile.TemporaryDirectory(prefix="dev04-verifier-json-") as tmp:
            run = Path(tmp)
            (run / "choice-b-modules.stdout").write_text(modules)
            (run / "choice-b-receiver.stdout").write_text(
                '{"attempt_id":"attempt.first"}\n{"attempt_id":"attempt.second"}\n')
            self.assertEqual(one(run, "choice-b-modules"), json.loads(modules))
            self.assertEqual([item["attempt_id"] for item in rows(run, "choice-b-receiver")],
                             ["attempt.first", "attempt.second"])
            with self.assertRaises(json.JSONDecodeError):
                one(run, "choice-b-receiver")

    def test_bounded_unix_record_round_trip(self):
        first, second = socket.socketpair()
        try:
            original = {"kind": "final_request", "attempt_id": "attempt.synthetic"}
            send(first, original)
            self.assertEqual(receive(second), original)
        finally:
            first.close()
            second.close()

    def test_oversized_record_rejected_before_payload(self):
        first, second = socket.socketpair()
        try:
            first.sendall(struct.pack("!I", LIMIT + 1))
            with self.assertRaises(ValueError):
                receive(second)
        finally:
            first.close()
            second.close()

    def test_worker_image_excludes_trusted_code(self):
        with tempfile.TemporaryDirectory(prefix="dev04-worker-source-") as tmp:
            context = stage_worker_source_context(ROOT, Path(tmp))
            dockerfile = validate_worker_source_context(context)
        self.assertIn("USER 10001:10001", dockerfile)
        self.assertIn("chmod 0555", dockerfile)
        self.assertIn("chmod 0444", dockerfile)
        self.assertIn("test ! -e /app/server", dockerfile)
        self.assertIn("test ! -e /app/dev_slice", dockerfile)
        self.assertIn("test ! -e /app/gateway", dockerfile)
        self.assertNotIn("COPY server/", dockerfile)
        self.assertNotIn("COPY gateway/", dockerfile)

    def test_worker_layout_rejects_original_nested_copy(self):
        with tempfile.TemporaryDirectory(prefix="dev04-worker-source-") as tmp:
            context = stage_worker_source_context(ROOT, Path(tmp))
            path = context / "Dockerfile"
            current = path.read_text()
            changed = current.replace("COPY choice_b_worker.py choice_b_wire.py /app/worker/",
                                      "COPY worker/ /app/worker/")
            self.assertNotEqual(current, changed)
            path.write_text(changed)
            with self.assertRaisesRegex(AssertionError, "not a staged file: worker/"):
                validate_worker_source_context(context)

    def test_worker_layout_rejects_broad_copy(self):
        with tempfile.TemporaryDirectory(prefix="dev04-worker-source-") as tmp:
            context = stage_worker_source_context(ROOT, Path(tmp))
            path = context / "Dockerfile"
            current = path.read_text()
            changed = current.replace("COPY choice_b_worker.py choice_b_wire.py /app/worker/",
                                      "COPY . /app/worker/")
            self.assertNotEqual(current, changed)
            path.write_text(changed)
            with self.assertRaisesRegex(AssertionError, "not a staged file"):
                validate_worker_source_context(context)

    def test_worker_layout_rejects_missing_wire_module(self):
        with tempfile.TemporaryDirectory(prefix="dev04-worker-source-") as tmp:
            context = stage_worker_source_context(ROOT, Path(tmp))
            (context / "choice_b_wire.py").unlink()
            with self.assertRaisesRegex(AssertionError, "not a staged file: choice_b_wire.py"):
                validate_worker_source_context(context)

    def test_worker_layout_rejects_extra_trusted_source(self):
        with tempfile.TemporaryDirectory(prefix="dev04-worker-source-") as tmp:
            context = stage_worker_source_context(ROOT, Path(tmp))
            (context / "authority.py").write_text("# Inert forbidden-source sentinel.\n")
            with self.assertRaisesRegex(AssertionError, "unexpected worker source content"):
                validate_worker_source_context(context)

    def test_worker_has_separate_network_and_no_trusted_environment(self):
        compose = (ROOT / "tests/gateway_integration/compose.yaml").read_text()
        worker = compose.split("  worker_choice_b:", 1)[1].split("  service_choice_b:", 1)[0]
        sender = compose.split("  service_choice_b:", 1)[1].split("  python_choice_b:", 1)[0]
        self.assertIn("network_mode: none", worker)
        self.assertIn('user: "10001:10001"', worker)
        self.assertIn("read_only: true", worker)
        self.assertIn("choice_b_link:/link", worker)
        self.assertNotIn("EZLLMROUTER_DEV_TOKEN", worker)
        self.assertNotIn("EZLLMROUTER_DEV04_PROVIDER_KEY", worker)
        self.assertNotIn("choice_b_data", worker)
        self.assertIn("EZLLMROUTER_DEV04_PROVIDER_KEY", sender)
        self.assertIn("choice_b_data:/data", sender)

    def test_sender_claims_one_registered_attempt_and_rejects_forgery(self):
        for source in (ROOT / "server/src", ROOT / "tests/development_slice"):
            sys.path.insert(0, str(source))
        from ezllmrouter_server.gateway.choice_b_sender import ChoiceBSenderAdapter, WORKER_KEY
        from ezllmrouter_server.gateway.guard import Invocation

        adapter = object.__new__(ChoiceBSenderAdapter)
        adapter.provider_key = "sk-trusted-synthetic-provider-key-000000000000"
        adapter.registry = {}
        adapter.claimed = set()
        adapter.lock = threading.Lock()
        attempt = "attempt.choice-b.local"
        invocation = Invocation("submission.local", attempt,
                                {"per_attempt_total_timeout_ms": 1000,
                                 "work_key": {"principal_id": "principal.test",
                                              "task_id": "task.test", "step_id": "step.test",
                                              "step_revision": 1,
                                              "execution_generation": "gen.1"}}, {},
                                lambda: None, lambda _receipt: None)
        adapter.registry[attempt] = invocation
        inspected = []

        def no_network(coroutine):
            inspected.append(coroutine.cr_frame.f_locals["request"])
            coroutine.close()
            future = Future()
            future.set_result({"status": 200, "body_b64": "e30=", "headers": []})
            return future

        adapter._call = no_network
        envelope = {"kind": "final_request", "attempt_id": attempt,
                    "method": "POST", "url": "http://127.0.0.1:8766/v1/chat/completions",
                    "headers": [["authorization", "Bearer " + WORKER_KEY]],
                    "body_b64": base64.b64encode(b"{}").decode("ascii"),
                    "timeout": {"connect": 1, "read": 1, "write": 1, "pool": 1}}
        with self.assertRaisesRegex(ValueError, "unregistered attempt"):
            adapter.process_relay({**envelope, "attempt_id": "attempt.forged"})
        self.assertEqual(adapter.process_relay(envelope)["status"], 200)
        self.assertEqual(inspected[0].headers["authorization"],
                         "Bearer " + adapter.provider_key)
        with self.assertRaisesRegex(ValueError, "replayed attempt authority"):
            adapter.process_relay(envelope)

    def test_trusted_relay_checks_and_commits_one_exact_request(self):
        for source in (ROOT / "server/src", ROOT / "tests/development_slice"):
            sys.path.insert(0, str(source))
        import httpx
        from ezllmrouter_server.gateway.choice_b_sender import ChoiceBSenderAdapter, WORKER_KEY
        from ezllmrouter_server.gateway.guard import GuardRejected, GuardTransport, PROVIDER_URL, provider_expectation
        from test_guard import invocation

        arrivals, receipts = [], []

        def lower(request):
            arrivals.append(request)
            return httpx.Response(200, json={"synthetic": True})

        adapter = object.__new__(ChoiceBSenderAdapter)
        adapter.provider_key = "sk-" + "t" * 40
        adapter.registry = {}
        adapter.claimed = set()
        adapter.lock = threading.Lock()
        adapter.loop = asyncio.new_event_loop()
        thread = threading.Thread(target=lambda: (asyncio.set_event_loop(adapter.loop),
                                  adapter.loop.run_forever()), daemon=True)
        thread.start()
        adapter.guard = GuardTransport(httpx.MockTransport(lower))
        context = invocation(aid="attempt.choice-b.exact", commit=receipts.append)
        adapter.registry[context.attempt_id] = context
        prepared = httpx.Request("POST", PROVIDER_URL,
            json=provider_expectation(context.projection),
            headers={"Authorization": "Bearer " + WORKER_KEY})
        envelope = {"kind": "final_request", "attempt_id": context.attempt_id,
            "method": prepared.method, "url": str(prepared.url),
            "headers": [[key, value] for key, value in prepared.headers.items()],
            "body_b64": base64.b64encode(prepared.content).decode("ascii"),
            "timeout": {"connect": 1.0, "read": 1.0, "write": 1.0, "pool": 1.0}}
        original_provider_key = os.environ.get("EZLLMROUTER_DEV04_PROVIDER_KEY")
        os.environ["EZLLMROUTER_DEV04_PROVIDER_KEY"] = adapter.provider_key
        try:
            result = adapter.process_relay(envelope)
            self.assertEqual(result["status"], 200)
            self.assertEqual(len(arrivals), 1)
            self.assertEqual(arrivals[0].headers["authorization"],
                             "Bearer " + adapter.provider_key)
            self.assertEqual(len(receipts), 1)
            self.assertEqual(receipts[0]["attempt_id"], context.attempt_id)
            with self.assertRaisesRegex(ValueError, "replayed attempt authority"):
                adapter.process_relay(envelope)
            self.assertEqual(len(arrivals), 1)
            changed = invocation(aid="attempt.choice-b.changed", commit=receipts.append)
            adapter.registry[changed.attempt_id] = changed
            altered_body = prepared.content.replace(b"model.demo", b"model.evil")
            self.assertNotEqual(altered_body, prepared.content)
            altered = {**envelope, "attempt_id": changed.attempt_id,
                       "body_b64": base64.b64encode(altered_body).decode("ascii")}
            with self.assertRaises(GuardRejected):
                adapter.process_relay(altered)
            self.assertEqual(len(arrivals), 1)
            self.assertEqual(len(receipts), 1)
            missing = invocation(aid="attempt.choice-b.missing", commit=receipts.append)
            del missing.plan["work_key"]
            adapter.registry[missing.attempt_id] = missing
            with self.assertRaisesRegex(ValueError, "required work identity"):
                adapter.process_relay({**envelope, "attempt_id": missing.attempt_id})
            malformed = invocation(aid="attempt.choice-b.malformed", commit=receipts.append)
            malformed.plan["work_key"]["step_id"] = None
            adapter.registry[malformed.attempt_id] = malformed
            with self.assertRaisesRegex(ValueError, "required work identity"):
                adapter.process_relay({**envelope, "attempt_id": malformed.attempt_id})
            self.assertEqual(len(arrivals), 1)
            self.assertEqual(len(receipts), 1)
            mutation = invocation(aid="attempt.choice-b.mutation", commit=receipts.append)
            mutation.plan["work_key"]["step_id"] = "step.dev03.mutation"
            mutation.projection["work"].update(
                requested_features=["tools"], tool_choice="auto",
                tool_definitions=[{"name": "lookup", "description": "Synthetic lookup",
                                   "input_schema": {"type": "object", "properties": {}}}])
            adapter.registry[mutation.attempt_id] = mutation
            tool_request = httpx.Request("POST", PROVIDER_URL,
                json=provider_expectation(mutation.projection),
                headers={"Authorization": "Bearer " + WORKER_KEY})
            mutation_envelope = {**envelope, "attempt_id": mutation.attempt_id,
                "headers": [[key, value] for key, value in tool_request.headers.items()],
                "body_b64": base64.b64encode(tool_request.content).decode("ascii")}
            with tempfile.TemporaryDirectory() as tmp:
                with patch.dict(os.environ, {"EZLLMROUTER_DEV05_TEST_TOOL_MUTATION": "1"}), \
                     patch("choice_b_sender.Path", side_effect=lambda _path: Path(tmp) / "mutation.jsonl"):
                    with self.assertRaises(GuardRejected):
                        adapter.process_relay(mutation_envelope)
                event = json.loads((Path(tmp) / "mutation.jsonl").read_text())
                self.assertEqual(event["attempt_id"], mutation.attempt_id)
                self.assertTrue(event["same_length"])
            self.assertEqual(len(arrivals), 1)
            self.assertEqual(len(receipts), 1)
        finally:
            if original_provider_key is None:
                os.environ.pop("EZLLMROUTER_DEV04_PROVIDER_KEY", None)
            else:
                os.environ["EZLLMROUTER_DEV04_PROVIDER_KEY"] = original_provider_key
            asyncio.run_coroutine_threadsafe(adapter.guard.aclose(), adapter.loop).result(timeout=3)
            adapter.loop.call_soon_threadsafe(adapter.loop.stop)
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())
            adapter.loop.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
