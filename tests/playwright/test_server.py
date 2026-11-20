"""Socket-free checks of the real browser fixture's data and HTTP application."""

from email.message import Message
from email.parser import BytesParser
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests.playwright import server as fixture


class MemoryServer:
    def __init__(self, address, handler):
        self.server_port = address[1] or 48761
        self.server_address = (address[0], self.server_port)
        self.handler = handler
        self.stopped = threading.Event()

    def serve_forever(self):
        self.stopped.wait()

    def shutdown(self):
        self.stopped.set()

    def get_request(self):
        return self.pending_request, ("127.0.0.1", 12345)

    def shutdown_request(self, request):
        request.close()

    def server_close(self):
        pass


class BrowserFixtureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        environment = patch.dict(
            os.environ,
            {
                "EZLLMROUTER_ADMIN_USERNAME": "admin",
            },
        )
        environment.start()
        self.addCleanup(environment.stop)
        replacement = patch("ezllmrouter_server.operator_web.ThreadingHTTPServer", MemoryServer)
        replacement.start()
        self.addCleanup(replacement.stop)
        self.instance = fixture.Instance(Path(temporary.name), {})
        self.instance.start(initial=True)
        self.addCleanup(self.instance.close)
        self.cookie = self.csrf = None

    def request(self, path, method="GET", body=None):
        handler = self.instance.server.handler.__new__(self.instance.server.handler)
        handler.server, handler.path, handler.command = self.instance.server, path, method
        handler.request_version = "HTTP/1.1"
        handler.requestline = method + " " + path + " HTTP/1.1"
        handler.client_address = ("127.0.0.1", 12345)
        handler.headers = Message()
        handler.headers["Host"] = "127.0.0.1:48761"
        handler.headers["Origin"] = "http://127.0.0.1:48761"
        if self.cookie:
            handler.headers["Cookie"] = self.cookie
        if self.csrf:
            handler.headers["X-EzLLMRouter-CSRF"] = self.csrf
        raw = json.dumps(body).encode() if body is not None else b""
        if body is not None:
            handler.headers["Content-Type"] = "application/json"
            handler.headers["Content-Length"] = str(len(raw))
        handler.rfile, handler.wfile = io.BytesIO(raw), io.BytesIO()
        getattr(handler, "do_" + method)()
        headers, data = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
        status = int(headers.split(b" ", 2)[1])
        parsed = BytesParser().parsebytes(headers.split(b"\r\n", 1)[1])
        return status, parsed, json.loads(data)

    def login(self, name="admin", password=fixture.ADMIN):
        status, headers, data = self.request(
            "/operator/v1/login", "POST", {"username": name, "password": password}
        )
        self.assertEqual(status, 200, data)
        self.cookie, self.csrf = headers["Set-Cookie"].split(";", 1)[0], data["csrf"]
        return data

    def test_seeded_pages_use_real_http_handlers_and_readable_metadata(self):
        self.login()
        for path in (
            "overview",
            "activity",
            "usage",
            "usage-costs",
            "models",
            "principals",
            "users",
            "connections",
            "config",
            "build",
            "local-connectors",
            "integration/datasets",
            "integration/connections?dataset_id=dataset.synthetic.v2",
            "integration/report?dataset_id=dataset.synthetic.v2",
        ):
            with self.subTest(path=path):
                status, _, body = self.request("/operator/v1/" + path)
                self.assertEqual(status, 200, body)
        self.assertEqual(self.instance.runner.calls, 0)

    def test_seeded_external_costs_are_replacements_and_unknown_remains_explicit(self):
        self.login()
        status, _, report = self.request(
            "/operator/v1/integration/report?dataset_id=dataset.synthetic.v2"
        )
        self.assertEqual(status, 200, report)
        self.assertEqual(report["attempt_count"], 2)
        self.assertEqual(report["known_total_by_currency"], {"USD": "0.020000000"})
        self.assertEqual(report["unknown_cost_attempts"], 1)

    def test_reader_and_member_sessions_are_ready_and_isolated(self):
        self.assertFalse(self.login("reader", fixture.USER)["must_change_password"])
        self.assertEqual(self.request("/operator/v1/users")[0], 403)
        self.login("member", fixture.USER)
        status, _, activity = self.request("/operator/v1/activity")
        self.assertEqual(status, 200)
        self.assertEqual(
            [item["submission_id"] for item in activity["items"]], ["submission.browser.1"]
        )

    def test_usage_control_appends_a_replacement_without_another_attempt(self):
        self.instance.correct_usage()
        self.login()
        status, _, report = self.request(
            "/operator/v1/integration/report?dataset_id=dataset.synthetic.v2"
        )
        self.assertEqual(status, 200, report)
        self.assertEqual(report["attempt_count"], 2)
        self.assertEqual(report["known_total_by_currency"], {"USD": "0.030000000"})

    def test_restart_preserves_real_user_catalogue_and_keyring_bindings(self):
        ids = dict(self.instance.identities)
        self.instance.close()
        self.instance.start()
        self.login()
        self.assertEqual(self.instance.state()["submissions"], 3)
        self.assertEqual(
            self.instance.users.authenticate("member", fixture.USER)["principal_id"], ids["member"]
        )
        self.assertEqual(len(self.instance.registry.list_models()), 13)

    def test_restart_closes_established_connections_and_invalidates_old_sessions(self):
        self.login()
        connection, peer = socket.socketpair()
        self.addCleanup(connection.close)
        self.addCleanup(peer.close)
        peer.settimeout(1)
        self.instance.server.pending_request = connection
        self.assertIs(self.instance.server.get_request()[0], connection)
        self.instance.close()
        self.assertEqual(peer.recv(1), b"")
        self.instance.start()
        self.assertEqual(self.request("/operator/v1/session")[0], 401)
        self.login()

    def test_accounting_connection_uses_encrypted_storage_and_fixture_discovery(self):
        self.login()
        status, _, pending = self.request(
            "/operator/v1/integration/connections",
            "POST",
            {
                "dataset_id": "dataset.synthetic.v2",
                "provider": "openai",
                "friendly_name": "Browser fixture",
                "api_key": "sk-browser-fixture-encrypted-key-000000000",
                "operation_id": "op.browser.connect",
            },
        )
        self.assertEqual(status, 201, pending)
        self.assertEqual(pending["discovery"]["models"], ["browser.text.v1"])
        self.assertNotIn("api_key", pending)
        account_id = pending["account_id"]
        status, _, saved = self.request(
            "/operator/v1/integration/connections/" + account_id + "/save",
            "POST",
            {
                "dataset_id": "dataset.synthetic.v2",
                "expected_revision": pending["revision"],
                "selected_models": ["browser.text.v1"],
                "allowed_operations": [],
            },
        )
        self.assertEqual(status, 200, saved)
        self.assertEqual(saved["state"], "connected")
        self.assertEqual(self.instance.metadata_probes, 1)
        self.instance.close()
        self.instance.start()
        binding = self.instance.registry.integration_credentials._binding(account_id)
        self.assertEqual(binding["selected_models"], ["browser.text.v1"])
        self.assertEqual(
            self.instance.registry.integration_credentials._discover(binding)["state"], "observed"
        )
        self.assertEqual(self.instance.metadata_probes, 2)

    def test_model_execution_is_a_hard_failure_in_the_fixture(self):
        with self.assertRaisesRegex(AssertionError, "must not execute"):
            self.instance.runner.run("text")
        self.assertEqual(self.instance.runner.calls, 1)

    def test_inventory_fixture_only_exposes_fixed_metadata_and_records_inference(self):
        handler = fixture.Inventory.__new__(fixture.Inventory)
        handler.server = SimpleNamespace(mode="ready", requests=[], inference_requests=0)
        handler.send_response = lambda status: statuses.append(status)
        handler.send_header = lambda *_args: None
        handler.end_headers = lambda: None
        for path in ("/api/tags", "/api/ps", "/api/version", "/v1/models", "/unexpected"):
            with self.subTest(path=path):
                statuses = []
                handler.path, handler.wfile = path, io.BytesIO()
                handler.do_GET()
                self.assertEqual(statuses, [404 if path == "/unexpected" else 200])
                self.assertIsInstance(json.loads(handler.wfile.getvalue()), dict)
        handler.send_error = lambda status: self.assertEqual(status, 405)
        handler.do_POST()
        self.assertEqual(handler.server.inference_requests, 1)
