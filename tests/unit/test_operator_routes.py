"""Real route dispatch and application isolation using in-memory HTTP streams."""
import json
from email.message import Message
from pathlib import Path
import threading
from unittest.mock import patch

from duranki_server.operator_projection import OperatorProjection
from duranki_server.operator_web import serve
from tests.operator_console.test_user_management_web import MemoryServer, UserHTTPFixture


class OperatorRouteTests(UserHTTPFixture):
    def test_account_registry_and_report_routes_use_current_server_context(self):
        self.ready_admin()
        self.server.application.integration_only = False
        self.server.application.fixture = json.loads((Path(__file__).resolve().parents[1] /
            "gateway_integration/dev05_fixture.json").read_text())
        for path in ("/operator/v1/users", "/operator/v1/local-connectors", "/operator/v1/models",
                     "/operator/v1/principals", "/operator/v1/connections", "/operator/v1/overview",
                     "/operator/v1/activity", "/operator/v1/usage", "/operator/v1/build"):
            with self.subTest(path=path):
                status, headers, _ = self.request("GET", path)
                self.assertEqual(status, 200)
                self.assertEqual(headers["Cache-Control"], "no-store, max-age=0")

    def test_two_servers_never_share_sessions(self):
        self.ready_admin()
        first = self.server
        with patch("duranki_server.operator_web.ThreadingHTTPServer", MemoryServer):
            second = serve("127.0.0.1", 48761, projection=OperatorProjection(self.store, "svc.demo"),
                runner=None, password="synthetic-operator-password-000000000000000", fixture={}, build={},
                web_root=Path(__file__).resolve().parents[2] / "web", worker_probe=lambda: {},
                sender_status=lambda: {}, registry=self.registry, integration_only=True)
        self.addCleanup(second.server_close)
        self.server = second
        try:
            self.assertEqual(self.request("GET", "/operator/v1/session")[0], 401)
        finally:
            self.server = first
        self.assertEqual(self.request("GET", "/operator/v1/session")[0], 200)
        self.assertIsNot(first.application.sessions, second.application.sessions)

    def test_background_execution_uses_the_injected_runner_and_records_completion(self):
        calls = []
        class Runner:
            def run(self, kind, record):
                calls.append(kind)
                record("submission.synthetic")
                return {"submission_ids": ["submission.synthetic"], "caller_lookups": 1}
        application = self.server.application
        application.runner = Runner()
        application.projection.begin_launch("op.route.test", "text")
        application.execute("op.route.test", "text")
        self.assertEqual(calls, ["text"])
        result = application.projection.launch("op.route.test")
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["submission_ids"], ["submission.synthetic"])

    def test_unknown_routes_and_invalid_origin_keep_their_public_errors(self):
        self.ready_admin()
        self.assertEqual(self.request("GET", "/operator/v1/unknown")[0], 404)
        self.assertEqual(self.request("GET", "/operator/v1/session", origin="https://example.test")[0], 403)

    def test_bind_failure_closes_application_and_executor(self):
        class FailedServer:
            def __init__(self, *_args):
                raise OSError("injected bind failure")
        with patch("duranki_server.operator_web.ThreadingHTTPServer", FailedServer), patch(
                "duranki_server.operator_web.OperatorApplication.close", autospec=True) as closed:
            with self.assertRaises(OSError):
                serve("127.0.0.1", 48761, projection=self.server.application.projection, runner=None,
                    password="synthetic-operator-password-000000000000000", fixture={}, build={},
                    web_root=Path(__file__).resolve().parents[2] / "web", worker_probe=lambda: {},
                    sender_status=lambda: {}, registry=self.registry)
            self.assertEqual(closed.call_count, 1)
            self.assertTrue(closed.call_args.args[0].jobs._shutdown)

    def test_ambiguous_framing_and_oversize_bodies_are_rejected_before_read(self):
        for headers in (("Transfer-Encoding", ""), ("Content-Length", "2"), ("oversize", "8193")):
            with self.subTest(header=headers[0]):
                handler = self.server.handler.__new__(self.server.handler)
                handler.server, handler.path = self.server, "/operator/v1/login"
                handler.headers = Message()
                handler.headers["Content-Type"] = "application/json"
                handler.headers["Content-Length"] = headers[1] if headers[0] == "oversize" else "2"
                if headers[0] != "oversize":
                    handler.headers[headers[0]] = headers[1]
                with patch.object(handler, "read_body", side_effect=AssertionError("body was read")):
                    with self.assertRaises(ValueError):
                        handler._body()

    def test_shutdown_waits_for_inflight_application_jobs(self):
        started, release, closed = threading.Event(), threading.Event(), threading.Event()
        def job():
            started.set()
            return release.wait(2)
        future = self.server.operator_jobs.submit(job)
        self.assertTrue(started.wait(1))
        def close():
            self.server.server_close()
            closed.set()
        closer = threading.Thread(target=close)
        closer.start()
        try:
            self.assertFalse(closed.wait(0.05))
        finally:
            release.set()
            closer.join(2)
        self.assertTrue(closed.is_set())
        self.assertTrue(future.result())

    def test_background_thread_start_failure_closes_bound_server_and_jobs(self):
        with patch("duranki_server.operator_web.ThreadingHTTPServer", MemoryServer), patch.object(
                threading.Thread, "start", side_effect=RuntimeError("injected thread failure")), patch.object(
                MemoryServer, "server_close", autospec=True) as closed:
            with self.assertRaises(RuntimeError):
                serve("127.0.0.1", 48761, projection=self.server.application.projection, runner=None,
                    password="synthetic-operator-password-000000000000000", fixture={}, build={},
                    web_root=Path(__file__).resolve().parents[2] / "web", worker_probe=lambda: {},
                    sender_status=lambda: {}, registry=self.registry)
            self.assertEqual(closed.call_count, 1)
            self.assertTrue(closed.call_args.args[0].application.jobs._shutdown)
