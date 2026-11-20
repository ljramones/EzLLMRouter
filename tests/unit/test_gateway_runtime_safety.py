"""Runtime requests ignore fixture switches; operational failures reveal no payloads."""

import ast
import asyncio
import base64
from concurrent.futures import Future
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx

from ezllmrouter_server import observability
from tools.gateway.asgi_adapter import LiteLLMAsgiAdapter, RestrictedProxy
from ezllmrouter_server.gateway.choice_b_sender import ChoiceBSenderAdapter
from ezllmrouter_server.gateway.choice_b_wire import receive, send
from ezllmrouter_server.gateway.guard import (
    ACTIVE,
    GuardTransport,
    PROVIDER_URL,
    provider_expectation,
)
from tests.gateway_integration.test_guard import invocation
from tools.gateway.stage import source_mapping
from tools.gateway import service_fixture
from tests.worker_support import runtime as choice_b_worker

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_SWITCHES = (
    "EZLLMROUTER_DEV04_POOL_PROBE",
    "EZLLMROUTER_DEV04_PROXY_MUTATION",
    "EZLLMROUTER_DEV04_PROVIDER_BASE_OVERRIDE",
    "EZLLMROUTER_DEV04_BYPASS_PROBE",
    "EZLLMROUTER_DEV04_CONTEXT_SWAP",
    "EZLLMROUTER_DEV04_LOWER_TRACE",
    "EZLLMROUTER_DEV04_AUTHORITY_TOGGLE",
    "EZLLMROUTER_DEV04_B_PROBE",
    "EZLLMROUTER_DEV05_TEST_TOOL_MUTATION",
)
PROVIDER_KEY = "sk-" + "s" * 40
PROVIDER_REPLY = {"choices": [{"message": {"content": "unchanged"}, "finish_reason": "stop"}]}


class RecordSocket:
    def __init__(self, value):
        self.incoming = io.BytesIO()
        self.outgoing = io.BytesIO()
        send(SimpleNamespace(sendall=self.incoming.write), value)
        self.incoming.seek(0)

    def settimeout(self, timeout):
        self.timeout = timeout

    def recv(self, count):
        return self.incoming.read(count)

    def sendall(self, data):
        self.outgoing.write(data)

    def reply(self):
        self.outgoing.seek(0)
        return receive(SimpleNamespace(recv=self.outgoing.read))


class RuntimeSafetyTests(unittest.TestCase):
    def test_asgi_timeout_cancels_the_submitted_coroutine(self):
        class TimedOut(Future):
            def result(self, timeout=None):
                raise TimeoutError("controlled worker timeout")

        adapter = LiteLLMAsgiAdapter.__new__(LiteLLMAsgiAdapter)
        adapter.provider_key = PROVIDER_KEY
        adapter.describe = Mock(return_value={})
        future = TimedOut()

        def submit(coroutine):
            coroutine.close()
            return future

        adapter._call = submit
        item = invocation(
            provider_key=PROVIDER_KEY,
        )
        item.plan["destination"] = {}
        context = {
            key: getattr(item, key)
            for key in (
                "submission_id",
                "attempt_id",
                "plan",
                "projection",
                "fresh_check",
                "commit",
            )
        }
        with self.assertRaises(TimeoutError):
            adapter.send_with_context(b"{}", 1, {}, context)
        self.assertTrue(future.cancelled())

    def test_proxy_startup_ignores_environment_destination_and_pool_overrides(self):
        # Only the third-party package interfaces are doubled. The real startup
        # code still builds the guarded client and configures the proxy.
        names = (
            "litellm",
            "litellm.proxy",
            "litellm.proxy.proxy_server",
            "litellm.llms",
            "litellm.llms.openai",
            "litellm.llms.openai.common_utils",
            "litellm.llms.openai.openai",
            "openai",
        )
        modules = {name: ModuleType(name) for name in names}
        for name, module in modules.items():
            module.__file__ = __file__
            module.__path__ = []
            parent, _, child = name.rpartition(".")
            if parent:
                setattr(modules[parent], child, module)
        modules["litellm"].aclient_session = modules["litellm"].client_session = None
        proxy = modules["litellm.proxy.proxy_server"]
        proxy.initialize, proxy.app = AsyncMock(), Mock()
        adapter = LiteLLMAsgiAdapter.__new__(LiteLLMAsgiAdapter)
        adapter.provider_key = PROVIDER_KEY
        adapter.lower_transport = httpx.MockTransport(lambda _: httpx.Response(200))
        adapter.request_timeout = 1.0

        async def run():
            try:
                await adapter._start()
                self.assertIsInstance(adapter.guarded_client._transport, GuardTransport)
                self.assertEqual(adapter.guarded_client.timeout.read, 1.0)
            finally:
                await adapter.guarded_client.aclose()

        with (
            tempfile.TemporaryDirectory() as directory,
            self.environment(directory),
            patch.dict(sys.modules, modules),
        ):
            asyncio.run(run())
        self.assertEqual(proxy.initialize.await_args.kwargs["api_base"], "http://127.0.0.1:8766/v1")
        self.assertEqual(proxy.initialize.await_args.kwargs["request_timeout"], 1.0)

    def test_runtime_does_not_read_fixture_switches_or_inspect_private_pool_queues(self):
        paths = [
            *Path(ROOT / "server/src/ezllmrouter_server/gateway").glob("*.py"),
            ROOT / "worker/ezllmrouter_worker/worker.py",
        ]
        for path in paths:
            with self.subTest(path=path.name):
                for node in ast.walk(ast.parse(path.read_text())):
                    if isinstance(node, ast.Constant) and isinstance(node.value, str):
                        self.assertNotIn(node.value, FIXTURE_SWITCHES)
                    if isinstance(node, ast.Attribute):
                        self.assertNotEqual(node.attr, "_requests")

    def environment(self, directory):
        environment = dict.fromkeys(FIXTURE_SWITCHES, "1")
        environment.update(
            {
                "EZLLMROUTER_DEV04_PROVIDER_KEY": PROVIDER_KEY,
                "EZLLMROUTER_DEV04_PROVIDER_BASE_OVERRIDE": "http://forbidden.invalid/v1",
                "EZLLMROUTER_DEV04_LOWER_TRACE": str(Path(directory) / "trace.jsonl"),
                "EZLLMROUTER_DEV04_AUTHORITY_TOGGLE": str(Path(directory) / "authority"),
                "EZLLMROUTER_GATEWAY_GUARD_EVENTS": "",
                "EZLLMROUTER_GATEWAY_SEND_EVENTS": "",
            }
        )
        (Path(directory) / "authority").write_text("revoked")
        return patch.dict(os.environ, environment)

    def test_choice_b_sends_the_exact_bound_tool_request_with_all_old_switches_set(self):
        item, receipts, arrivals = (
            invocation(
                provider_key=PROVIDER_KEY,
            ),
            [],
            [],
        )
        item.commit = receipts.append
        item.plan["work_key"]["step_id"] = "step.dev03.mutation"
        item.projection["work"].update(
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
        body = provider_expectation(item.projection)

        def lower(request):
            arrivals.append(json.loads(request.content))
            return httpx.Response(200, json=PROVIDER_REPLY)

        adapter = ChoiceBSenderAdapter.__new__(ChoiceBSenderAdapter)
        adapter.provider_key = PROVIDER_KEY
        adapter.guard = GuardTransport(httpx.MockTransport(lower))
        request = httpx.Request(
            "POST",
            PROVIDER_URL,
            json=body,
            headers={"Authorization": "Bearer " + PROVIDER_KEY},
            extensions={"timeout": dict.fromkeys(("connect", "read", "write", "pool"), 1.0)},
        )
        with tempfile.TemporaryDirectory() as directory, self.environment(directory):
            result = asyncio.run(adapter._send(request, item))
            self.assertFalse((Path(directory) / "trace.jsonl").exists())
        self.assertEqual(json.loads(base64.b64decode(result["body_b64"])), PROVIDER_REPLY)
        self.assertEqual(arrivals, [body])
        self.assertEqual(len(receipts), 1)
        self.assertIsNone(ACTIVE.get())

    def test_asgi_sends_the_bound_context_and_content_with_all_old_switches_set(self):
        item = invocation(provider_key=PROVIDER_KEY, text="Simulate swapped context")
        body, arrivals, contexts = provider_expectation(item.projection), [], []
        adapter = LiteLLMAsgiAdapter.__new__(LiteLLMAsgiAdapter)
        adapter.provider_key = PROVIDER_KEY

        def lower(request):
            arrivals.append(json.loads(request.content))
            return httpx.Response(200, json=PROVIDER_REPLY)

        async def proxy(scope, receive_body, respond):
            raw = b""
            while True:
                event = await receive_body()
                raw += event.get("body", b"")
                if not event.get("more_body", False):
                    break
            contexts.append(ACTIVE.get())
            response = await adapter.guarded_client.post(
                PROVIDER_URL,
                json=json.loads(raw),
                headers={"Authorization": "Bearer " + PROVIDER_KEY},
                timeout=1,
            )
            await respond(
                {
                    "type": "http.response.start",
                    "status": response.status_code,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await respond({"type": "http.response.body", "body": response.content})

        async def run():
            async with httpx.AsyncClient(
                transport=GuardTransport(httpx.MockTransport(lower)), trust_env=False
            ) as client:
                adapter.guarded_client = client
                adapter.proxy = RestrictedProxy(proxy, lambda: ACTIVE.get() is not None)
                return await adapter._send(json.dumps(body).encode(), 1000, item)

        with tempfile.TemporaryDirectory() as directory, self.environment(directory):
            result = asyncio.run(run())
            self.assertFalse((Path(directory) / "trace.jsonl").exists())
        self.assertEqual(result["body"]["text"], "unchanged")
        self.assertEqual(arrivals, [body])
        self.assertEqual(contexts, [item])
        self.assertIsNone(ACTIVE.get())

    def test_worker_rejects_raw_probe_even_when_old_probe_switch_is_set(self):
        worker = choice_b_worker.Worker.__new__(choice_b_worker.Worker)
        with (
            patch.dict(os.environ, {"EZLLMROUTER_DEV04_B_PROBE": "1"}),
            patch.object(choice_b_worker.asyncio, "run_coroutine_threadsafe") as schedule,
        ):
            with self.assertRaisesRegex(ValueError, "unknown worker command"):
                worker.dispatch({"kind": "raw_egress_probe"})
            schedule.assert_not_called()

    def test_fixture_adapters_are_absent_from_the_deployment_source_map(self):
        sources = {target: source for source, target in source_mapping(ROOT, True)}
        self.assertNotIn("service/gateway/fixture_adapters.py", sources)
        self.assertNotIn("service/gateway/service_fixture.py", sources)
        self.assertNotIn("worker/fixture/worker_fixture.py", sources)
        compose = (ROOT / "deploy/local/compose.yaml").read_text()
        self.assertNotIn("POOL_PROBE", compose)

    def test_fixture_entry_point_explicitly_injects_the_selected_adapter(self):
        for mode, module, factory in (
            ("asgi", service_fixture.service_main, service_fixture.FixtureAsgiAdapter),
            ("sender", service_fixture.choice_b_service, service_fixture.FixtureSenderAdapter),
        ):
            with (
                self.subTest(mode=mode),
                patch.object(module, "main") as start,
                patch.object(sys, "argv", ["service_fixture.py", mode]),
            ):
                service_fixture.main()
                start.assert_called_once_with(adapter_factory=factory)


class FailureLoggingTests(unittest.TestCase):
    def setUp(self):
        logger = observability.LOGGER
        original = logger.handlers[:], logger.level, logger.propagate

        def restore():
            logger.handlers[:], logger.level, logger.propagate = original

        self.addCleanup(restore)
        self.output = io.StringIO()
        observability.configure_logging(self.output)

    def events(self):
        text = self.output.getvalue()
        self.assertNotIn("secret-canary", text)
        return [json.loads(row) for row in text.splitlines()]

    def test_worker_command_failure_logs_type_and_locations_without_exception_values(self):
        worker = SimpleNamespace(
            dispatch=Mock(side_effect=ValueError("secret-canary payload and token"))
        )
        stream = RecordSocket({"kind": "selected_request", "prepared_b64": "secret-canary"})
        choice_b_worker.handle_command(worker, stream)
        self.assertEqual(stream.reply(), {"error_type": "ValueError"})
        (event,) = self.events()
        self.assertEqual(
            (event["event"], event["exception_type"]),
            ("gateway.worker.command_failed", "ValueError"),
        )
        self.assertTrue(event["stack"])
        self.assertTrue(all(set(frame) == {"file", "function", "line"} for frame in event["stack"]))

    def test_worker_reply_failure_is_logged_without_leaking_or_retrying(self):
        worker = SimpleNamespace(dispatch=Mock(return_value={"status": 200}))
        stream = RecordSocket({"kind": "module_identity"})
        with patch.object(stream, "sendall", side_effect=OSError("secret-canary reply")) as write:
            choice_b_worker.handle_command(worker, stream)
            write.assert_called_once()
        (event,) = self.events()
        self.assertEqual(event["event"], "gateway.worker.reply_failed")

    def test_trusted_relay_logs_command_failure_without_exception_values(self):
        adapter = ChoiceBSenderAdapter.__new__(ChoiceBSenderAdapter)
        adapter.provider_key = PROVIDER_KEY
        adapter.process_relay = Mock(side_effect=KeyError("secret-canary credential"))
        stream = RecordSocket({"kind": "final_request", "body_b64": "secret-canary"})
        adapter.handle_relay(stream)
        self.assertEqual(stream.reply(), {"error_type": "KeyError"})
        (event,) = self.events()
        self.assertEqual(event["event"], "gateway.relay.command_failed")

    def test_trusted_relay_logs_reply_failure_without_retrying(self):
        adapter = ChoiceBSenderAdapter.__new__(ChoiceBSenderAdapter)
        adapter.provider_key = PROVIDER_KEY
        adapter.process_relay = Mock(return_value={"status": 200})
        stream = RecordSocket({"kind": "final_request"})
        with patch.object(stream, "sendall", side_effect=OSError("secret-canary reply")) as write:
            adapter.handle_relay(stream)
            write.assert_called_once()
        (event,) = self.events()
        self.assertEqual(event["event"], "gateway.relay.reply_failed")

    def test_worker_startup_failure_exits_without_an_uncaught_exception_message(self):
        with (
            patch.object(choice_b_worker, "configure_logging"),
            patch.object(
                choice_b_worker, "_serve", side_effect=RuntimeError("secret-canary startup")
            ),
        ):
            with self.assertRaises(SystemExit) as error:
                choice_b_worker.main()
        self.assertEqual(error.exception.code, 1)
        (event,) = self.events()
        self.assertEqual(event["event"], "gateway.worker.start_or_serve_failed")

    def test_lower_failure_is_logged_without_request_or_exception_contents(self):
        item = invocation(
            provider_key=PROVIDER_KEY,
        )
        adapter = ChoiceBSenderAdapter.__new__(ChoiceBSenderAdapter)
        adapter.provider_key = PROVIDER_KEY
        adapter.guard = Mock(
            handle_async_request=Mock(side_effect=OSError("secret-canary provider"))
        )
        with patch.dict(os.environ, {"EZLLMROUTER_GATEWAY_SEND_EVENTS": ""}):
            with self.assertRaises(OSError):
                asyncio.run(adapter._send(httpx.Request("POST", PROVIDER_URL), item))
        (event,) = self.events()
        self.assertEqual(event["event"], "gateway.sender.request_failed")


if __name__ == "__main__":
    unittest.main()
