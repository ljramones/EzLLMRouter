"""Local source, sender-admission and Unix-record gates before target execution."""

import base64
from concurrent.futures import Future
import json
from pathlib import Path
import shlex
import shutil
import socket
import struct
import tempfile
import threading
import unittest


ROOT = Path(__file__).resolve().parents[2]

from ezllmrouter_server.gateway.choice_b_wire import LIMIT, receive, send  # noqa: E402
from tools.gateway.stage import source_mapping
from ezllmrouter_server.runtime_resources import LoopThread


WORKER_SOURCE_FILES = {
    "choice_b_worker.py",
    "choice_b_wire.py",
    "worker_logging.py",
    "runtime_resources.py",
}


def stage_worker_source_context(root, destination, *, fixtures=False):
    """Replay the worker source map without frozen wheels or Docker."""
    mappings = source_mapping(root, fixtures=fixtures)
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


def validate_worker_source_context(context, *, fixtures=False):
    """Check the runtime worker modules; fixture probes are staged separately."""
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
    if len(sources) != 4 or set(sources) != WORKER_SOURCE_FILES:
        raise AssertionError(
            "worker COPY must name exactly the runtime, wire, safe logger and resource helpers"
        )
    observed = {
        path.relative_to(context).as_posix() for path in context.rglob("*") if path.is_file()
    }
    expected = WORKER_SOURCE_FILES | {"Dockerfile"}
    if fixtures:
        expected.add("fixture/worker_fixture.py")
    if observed != expected:
        raise AssertionError("unexpected worker source content")
    return dockerfile


class ChoiceBComponentTests(unittest.TestCase):
    def test_worker_probe_requires_an_explicit_fixture_context(self):
        with tempfile.TemporaryDirectory() as directory:
            context = stage_worker_source_context(ROOT, Path(directory), fixtures=True)
            validate_worker_source_context(context, fixtures=True)
            self.assertTrue((context / "fixture/worker_fixture.py").is_file())
            with self.assertRaisesRegex(AssertionError, "unexpected worker source content"):
                validate_worker_source_context(context)

    def test_verifier_parses_pretty_single_document_and_jsonl_rows(self):
        from tools.gateway.evidence.verify_choice_b import one, rows

        modules = """{
  "boundary": "separate trusted Choice B sender",
  "litellm_imported": false,
  "provider_key_in_trusted_process": true,
  "worker_socket": "/link/worker.sock",
  "sender_socket": "/link/sender.sock"
}
"""
        with tempfile.TemporaryDirectory(prefix="dev04-verifier-json-") as tmp:
            run = Path(tmp)
            (run / "choice-b-modules.stdout").write_text(modules)
            (run / "choice-b-receiver.stdout").write_text(
                '{"attempt_id":"attempt.first"}\n{"attempt_id":"attempt.second"}\n'
            )
            self.assertEqual(one(run, "choice-b-modules"), json.loads(modules))
            self.assertEqual(
                [item["attempt_id"] for item in rows(run, "choice-b-receiver")],
                ["attempt.first", "attempt.second"],
            )
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
            changed = current.replace(
                "COPY choice_b_worker.py choice_b_wire.py worker_logging.py runtime_resources.py /app/worker/",
                "COPY worker/ /app/worker/",
            )
            self.assertNotEqual(current, changed)
            path.write_text(changed)
            with self.assertRaisesRegex(AssertionError, "not a staged file: worker/"):
                validate_worker_source_context(context)

    def test_worker_layout_rejects_broad_copy(self):
        with tempfile.TemporaryDirectory(prefix="dev04-worker-source-") as tmp:
            context = stage_worker_source_context(ROOT, Path(tmp))
            path = context / "Dockerfile"
            current = path.read_text()
            changed = current.replace(
                "COPY choice_b_worker.py choice_b_wire.py worker_logging.py runtime_resources.py /app/worker/",
                "COPY . /app/worker/",
            )
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
        compose = (ROOT / "tools/gateway/evidence/compose.yaml").read_text()
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
        from ezllmrouter_server.gateway.choice_b_sender import ChoiceBSenderAdapter, WORKER_KEY
        from ezllmrouter_server.gateway.guard import Invocation

        adapter = object.__new__(ChoiceBSenderAdapter)
        adapter.provider_key = "sk-trusted-synthetic-provider-key-000000000000"
        adapter.registry = {}
        adapter.claimed = set()
        adapter.lock = threading.Lock()
        attempt = "attempt.choice-b.local"
        invocation = Invocation(
            "submission.local",
            attempt,
            {
                "per_attempt_total_timeout_ms": 1000,
                "work_key": {
                    "principal_id": "principal.test",
                    "task_id": "task.test",
                    "step_id": "step.test",
                    "step_revision": 1,
                    "execution_generation": "gen.1",
                },
            },
            {},
            lambda: None,
            lambda _receipt: None,
        )
        adapter.registry[attempt] = invocation
        inspected = []

        def no_network(coroutine):
            inspected.append(coroutine.cr_frame.f_locals["request"])
            coroutine.close()
            future = Future()
            future.set_result({"status": 200, "body_b64": "e30=", "headers": []})
            return future

        adapter._call = no_network
        envelope = {
            "kind": "final_request",
            "attempt_id": attempt,
            "method": "POST",
            "url": "http://127.0.0.1:8766/v1/chat/completions",
            "headers": [
                ["authorization", "Bearer " + WORKER_KEY],
                ["accept-encoding", "gzip, deflate"],
                ["x-stainless-lang", "worker-controlled-value"],
            ],
            "body_b64": base64.b64encode(b"{}").decode("ascii"),
            "timeout": {"connect": 1, "read": 1, "write": 1, "pool": 1},
        }
        with self.assertRaisesRegex(ValueError, "unregistered attempt"):
            adapter.process_relay({**envelope, "attempt_id": "attempt.forged"})
        self.assertEqual(adapter.process_relay(envelope)["status"], 200)
        self.assertEqual(inspected[0].headers["authorization"], "Bearer " + adapter.provider_key)
        self.assertEqual(inspected[0].headers["accept-encoding"], "identity")
        self.assertNotIn("x-stainless-lang", inspected[0].headers)
        self.assertEqual(inspected[0].headers["user-agent"], "EzLLMRouter/trusted-sender")
        with self.assertRaisesRegex(ValueError, "replayed attempt authority"):
            adapter.process_relay(envelope)

    def test_trusted_relay_checks_and_commits_one_exact_request(self):
        import httpx
        from ezllmrouter_server.gateway.choice_b_sender import ChoiceBSenderAdapter, WORKER_KEY
        from ezllmrouter_server.gateway.guard import (
            GuardRejected,
            GuardTransport,
            PROVIDER_URL,
            provider_expectation,
        )
        from tests.gateway_integration.test_guard import invocation

        arrivals, receipts = [], []

        def lower(request):
            arrivals.append(request)
            return httpx.Response(200, json={"synthetic": True})

        adapter = object.__new__(ChoiceBSenderAdapter)
        adapter.provider_key = "sk-" + "t" * 40
        adapter.registry = {}
        adapter.claimed = set()
        adapter.lock = threading.Lock()
        adapter._runtime = LoopThread("ezllmrouter-relay-fixture")
        adapter.loop = adapter._runtime.loop
        adapter.guard = GuardTransport(httpx.MockTransport(lower))
        context = invocation(aid="attempt.choice-b.exact", commit=receipts.append)
        adapter.registry[context.attempt_id] = context
        prepared = httpx.Request(
            "POST",
            PROVIDER_URL,
            json=provider_expectation(context.projection),
            headers={"Authorization": "Bearer " + WORKER_KEY},
        )
        envelope = {
            "kind": "final_request",
            "attempt_id": context.attempt_id,
            "method": prepared.method,
            "url": str(prepared.url),
            "headers": [[key, value] for key, value in prepared.headers.items()],
            "body_b64": base64.b64encode(prepared.content).decode("ascii"),
            "timeout": {"connect": 1.0, "read": 1.0, "write": 1.0, "pool": 1.0},
        }
        try:
            result = adapter.process_relay(envelope)
            self.assertEqual(result["status"], 200)
            self.assertEqual(len(arrivals), 1)
            self.assertEqual(arrivals[0].headers["authorization"], "Bearer " + adapter.provider_key)
            self.assertEqual(len(receipts), 1)
            self.assertEqual(receipts[0]["attempt_id"], context.attempt_id)
            with self.assertRaisesRegex(ValueError, "replayed attempt authority"):
                adapter.process_relay(envelope)
            self.assertEqual(len(arrivals), 1)
            changed = invocation(aid="attempt.choice-b.changed", commit=receipts.append)
            adapter.registry[changed.attempt_id] = changed
            altered_body = prepared.content.replace(b"model.demo", b"model.evil")
            self.assertNotEqual(altered_body, prepared.content)
            altered = {
                **envelope,
                "attempt_id": changed.attempt_id,
                "body_b64": base64.b64encode(altered_body).decode("ascii"),
            }
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
                requested_features=["tools"],
                tool_choice="auto",
                tool_definitions=[
                    {
                        "name": "lookup",
                        "description": "Synthetic lookup",
                        "input_schema": {"type": "object", "properties": {}},
                    }
                ],
            )
            adapter.registry[mutation.attempt_id] = mutation
            tool_request = httpx.Request(
                "POST",
                PROVIDER_URL,
                json=provider_expectation(mutation.projection),
                headers={"Authorization": "Bearer " + WORKER_KEY},
            )
            mutation_envelope = {
                **envelope,
                "attempt_id": mutation.attempt_id,
                "headers": [[key, value] for key, value in tool_request.headers.items()],
                "body_b64": base64.b64encode(tool_request.content).decode("ascii"),
            }
            with tempfile.TemporaryDirectory() as tmp:
                from tools.gateway.fixture_adapters import ToolMutationTransport

                guard = adapter.guard
                adapter.guard = ToolMutationTransport(guard, Path(tmp) / "mutation.jsonl")
                try:
                    with self.assertRaises(GuardRejected):
                        adapter.process_relay(mutation_envelope)
                finally:
                    adapter.guard = guard
                event = json.loads((Path(tmp) / "mutation.jsonl").read_text())
                self.assertEqual(event["attempt_id"], mutation.attempt_id)
                self.assertTrue(event["same_length"])
            self.assertEqual(len(arrivals), 1)
            self.assertEqual(len(receipts), 1)
        finally:
            adapter._runtime.close(adapter.guard.aclose())


if __name__ == "__main__":
    unittest.main(verbosity=2)
