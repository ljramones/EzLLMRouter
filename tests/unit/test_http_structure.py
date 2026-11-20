"""HTTP refactor regressions through real handlers, without binding listeners."""

import csv
import io
import json
import socket
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ezllmrouter_server.observability import EventFormatter
from ezllmrouter_server.operator_http import reports
from ezllmrouter_server.operator_http.routing import Route, Router
from ezllmrouter_server.web import serve as serve_wire

from tests.operator_console.test_user_management import PASSWORD
from tests.operator_console.test_user_management_web import MemoryServer, UserHTTPFixture


class HTTPFramingTests(UserHTTPFixture):
    def exchange(self, server, request):
        client, peer = socket.socketpair()
        errors = []

        def handle():
            try:
                with peer:
                    server.handler(peer, ("127.0.0.1", 12345), server)
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=handle)
        thread.start()
        try:
            with client:
                client.settimeout(3)
                client.sendall(request)
                client.shutdown(socket.SHUT_WR)
                chunks = []
                while chunk := client.recv(65536):
                    chunks.append(chunk)
            return b"".join(chunks)
        finally:
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])

    def test_operator_unread_body_is_never_parsed_as_another_request(self):
        inner = b"GET /operator/v1/session HTTP/1.1\r\nHost: 127.0.0.1:48761\r\n\r\n"
        cases = (
            ("POST /operator/v1/login", "Content-Type: text/plain\r\n"),
            ("POST /operator/v1/users", "Content-Type: application/json\r\n"),
            ("GET /operator/v1/session", ""),
            ("POST /operator/v1/login", "Content-Type: application/json\r\nContent-Length: 1\r\n"),
            (
                "POST /operator/v1/login",
                "Content-Type: application/json\r\nTransfer-Encoding: chunked\r\n",
            ),
        )
        for route, headers in cases:
            with self.subTest(route=route, headers=headers):
                request = (
                    route + " HTTP/1.1\r\nHost: 127.0.0.1:48761\r\n"
                    "Origin: http://127.0.0.1:48761\r\n"
                    + headers
                    + f"Content-Length: {len(inner)}\r\n\r\n"
                ).encode() + inner
                reply = self.exchange(self.server, request)
                self.assertEqual(reply.count(b"HTTP/1.1 "), 1, reply)
                self.assertIn(b"Connection: close\r\n", reply)

    def test_wire_early_rejections_and_get_bodies_close_before_the_next_request(self):
        capabilities = Mock(return_value={"contract_version": "0.2"})
        coordinator = SimpleNamespace(
            registry=None, authenticate=lambda _: {}, capabilities=capabilities
        )
        with patch("ezllmrouter_server.web.ThreadingHTTPServer", MemoryServer):
            server = serve_wire("127.0.0.1", 48761, coordinator)
        headers = (
            "Host: 127.0.0.1:48761\r\nEzLLMRouter-Contract-Version: 0.2\r\n"
            "Authorization: Bearer synthetic\r\n"
        )
        inner = ("GET /v1/capabilities HTTP/1.1\r\n" + headers + "\r\n").encode()
        for route, extra in (
            ("POST /v1/unknown", ""),
            ("POST /v1/submissions", "EzLLMRouter-Wait-Ms: invalid\r\n"),
            ("POST /v1/submissions", "Content-Type: text/plain\r\n"),
            ("GET /v1/capabilities", ""),
        ):
            with self.subTest(route=route, extra=extra):
                capabilities.reset_mock()
                request = (
                    route
                    + " HTTP/1.1\r\n"
                    + headers
                    + extra
                    + f"Content-Length: {len(inner)}\r\n\r\n"
                ).encode() + inner
                reply = self.exchange(server, request)
                self.assertEqual(reply.count(b"HTTP/1.1 "), 1, reply)
                self.assertIn(b"Connection: close\r\n", reply)
                self.assertEqual(capabilities.call_count, int(route.startswith("GET")))

    def test_fully_consumed_invalid_json_keeps_legitimate_pipelining(self):
        request = (
            b"POST /operator/v1/login HTTP/1.1\r\nHost: 127.0.0.1:48761\r\n"
            b"Origin: http://127.0.0.1:48761\r\nContent-Type: application/json\r\n"
            b"Content-Length: 1\r\n\r\n{"
            b"GET /operator/v1/session HTTP/1.1\r\nHost: 127.0.0.1:48761\r\n\r\n"
        )
        reply = self.exchange(self.server, request)
        self.assertEqual(reply.count(b"HTTP/1.1 "), 2, reply)


class RouterTests(unittest.TestCase):
    def test_specific_paths_win_independently_of_registration_order(self):
        exact = Route("GET", "/items/availability", "availability", "account", query=False)
        family = Route("GET", "/items/", "detail", "account", family=True, query=False)
        nested = Route("GET", "/items/nested/", "nested", "account", family=True, query=False)
        for routes in ((family, exact, nested), (nested, exact, family)):
            router = Router(routes)
            for path, expected in (
                ("/items/availability", exact),
                ("/items/nested/id", nested),
                ("/items/id", family),
            ):
                self.assertEqual(router.resolve("GET", path, query=False, available=()), expected)
            self.assertIsNone(router.resolve("POST", "/items/id", query=False, available=()))
            self.assertIsNone(router.resolve("GET", "/items/id", query=True, available=()))

    def test_duplicate_paths_fail_at_registration(self):
        for family in (False, True):
            with self.subTest(family=family), self.assertRaises(ValueError):
                Router(
                    (
                        Route("GET", "/same", "first", "account", family=family),
                        Route("GET", "/same", "second", "resource", family=family),
                    )
                )


class HTTPStructureTests(UserHTTPFixture):
    def test_public_assets_keep_exact_bytes_types_and_security_headers(self):
        root = Path(__file__).resolve().parents[2] / "web"
        for path, filename, mime in (
            ("/", "index.html", "text/html"),
            ("/integration", "index.html", "text/html"),
            ("/app.js", "app.js", "text/javascript"),
            ("/integration_console.css", "integration_console.css", "text/css"),
        ):
            with self.subTest(path=path):
                status, headers, body = self.request("GET", path)
                self.assertEqual(status, 200)
                self.assertEqual(body, (root / filename).read_bytes())
                self.assertEqual(headers["Content-Type"], mime + "; charset=utf-8")
                self.assertEqual(headers["Content-Length"], str(len(body)))
                self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
                self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
                self.assertEqual(headers["Cache-Control"], "no-store, max-age=0")

    def test_filesystem_contents_and_queries_do_not_create_public_assets(self):
        root = Path(self.tmp.name) / "web"
        root.mkdir()
        (root / "private.txt").write_text("private synthetic material")
        self.server.application.root = root
        paths = (
            "/private.txt",
            "/../users.sqlite",
            "/%2e%2e/users.sqlite",
            "/app.js/extra",
            "/app.js?download=1",
            "/index.html",
            "/dev09_demo_fixture.json",
        )
        for path in paths:
            with self.subTest(path=path):
                status, _, body = self.request("GET", path)
                self.assertEqual((status, body), (401, {"error": "AUTH_REQUIRED"}))
        self.ready_admin()
        self.server.application.integration_only = False
        for path in paths:
            with self.subTest(authenticated=path):
                self.assertEqual(self.request("GET", path)[0], 404)
        self.assertEqual(self.request("GET", "/app.js#fragment")[0], 400)

    def test_connector_collection_actions_do_not_resolve_as_connector_ids(self):
        self.ready_admin()
        connectors = self.server.application.local_connectors
        with (
            patch.object(connectors, "availability", return_value={"source": "availability"}),
            patch.object(connectors, "nearby", return_value={"source": "nearby"}),
            patch.object(connectors, "get", return_value={"source": "detail"}) as detail,
        ):
            for suffix, expected in (
                ("availability", "availability"),
                ("nearby", "nearby"),
                ("id", "detail"),
            ):
                self.assertEqual(
                    self.request("GET", "/operator/v1/local-connectors/" + suffix)[2],
                    {"source": expected},
                )
            detail.assert_called_once_with("owner.local", "id")
            self.assertEqual(self.request("GET", "/operator/v1/local-connectors/id/extra")[0], 404)
            self.assertEqual(
                self.request("GET", "/operator/v1/local-connectors/id?extra=1")[0], 404
            )

    def test_integration_only_and_ordinary_user_boundaries_survive_route_selection(self):
        self.ready_admin()
        for path, expected in (
            ("/operator/v1/users", 200),
            ("/operator/v1/models", 200),
            ("/operator/v1/usage", 200),
            ("/operator/v1/overview", 404),
            ("/operator/v1/build", 404),
            ("/operator/v1/providers", 404),
        ):
            self.assertEqual(self.request("GET", path)[0], expected, path)
        user = self.create()
        replacement = "Another synthetic test passphrase!"
        self.users.change_password(
            user["principal_id"],
            {
                "current_password": PASSWORD,
                "new_password": replacement,
            },
        )
        self.login("alice", replacement)
        self.server.application.integration_only = False
        for path, expected in (
            ("/operator/v1/session", 200),
            ("/operator/v1/models", 200),
            ("/operator/v1/usage", 200),
            ("/operator/v1/activity", 200),
            ("/operator/v1/users", 403),
            ("/operator/v1/build", 403),
            ("/operator/v1/providers", 403),
            ("/operator/v1/unknown", 403),
        ):
            self.assertEqual(self.request("GET", path)[0], expected, path)

    def test_query_policies_and_missing_collaborators_keep_public_errors(self):
        self.ready_admin()
        self.server.application.integration_only = False
        for path in (
            "/operator/v1/session?extra=1",
            "/operator/v1/build?extra=1",
            "/operator/v1/users?extra=1",
            "/operator/v1/local-connectors?extra=1",
        ):
            self.assertEqual(self.request("GET", path)[0], 404)
        with patch.object(self.server.application, "registry", None):
            for path in (
                "/operator/v1/models",
                "/operator/v1/usage-costs",
                "/operator/v1/integration/datasets",
            ):
                self.assertEqual(self.request("GET", path)[0], 404)
        self.assertEqual(self.request("GET", "/operator/v1/retrieval-usage")[0], 404)
        self.assertEqual(self.request("GET", "/operator/v1/activity?limit=2&limit=3")[0], 400)
        self.assertEqual(self.request("GET", "/operator/v1/integration/identity?extra=1")[0], 400)

    def test_display_identity_route_requires_authentication_and_integration_profile(self):
        path = "/operator/v1/integration/identity"
        self.assertEqual(self.request("GET", path)[0], 401)
        self.ready_admin()
        status, _, body = self.request("GET", path)
        self.assertEqual((status, body), (200, {"user": None}))
        self.server.application.integration_only = False
        self.assertEqual(self.request("GET", path)[0], 404)

    def test_mutation_rejections_precede_body_read_for_resolved_and_unknown_routes(self):
        paths = (
            ("POST", "/operator/v1/users"),
            ("DELETE", "/operator/v1/users/id"),
            ("POST", "/unknown"),
        )
        with patch.object(self.server.handler, "_body", side_effect=AssertionError("body read")):
            for method, path in paths:
                self.assertEqual(self.request(method, path, {})[0], 401)
        self.ready_admin()
        with patch.object(self.server.handler, "_body", side_effect=AssertionError("body read")):
            for method, path in paths:
                self.assertEqual(self.request(method, path, {}, csrf=False)[0], 403)
                self.assertEqual(
                    self.request(method, path, {}, origin="https://example.test")[0], 403
                )

    def test_four_csv_exports_preserve_strings_json_fields_and_attachment_contracts(self):
        self.ready_admin()
        application = self.server.application
        application.integration_only = False
        application.successor_store = self.store
        attempt = {
            "attempt_id": 'attempt,"quoted"\nsecond line é',
            "amount_decimal": "0.000000001",
            "currency": None,
            "native_units": {"z": 2, "a": 1},
            "native_components": [{"tokens": 3}],
            "eligibility_record": {"answer": True},
            "selected_action": {"a": "hello"},
            "not_a_column": "discard me",
        }
        report = {"attempts": [attempt]}
        application.scripted_demo = SimpleNamespace(
            meta={"required_banner": "DEMO, synthetic only"},
            report=Mock(return_value=report),
        )
        with (
            patch.object(reports, "usage_report", return_value=report),
            patch.object(reports, "usage_costs", return_value=report),
            patch.object(self.registry.integration, "report", return_value=report),
        ):
            for path, filename in (
                (
                    "/operator/v1/retrieval-usage?export=csv",
                    "ezllmrouter-retrieval-synthetic-usage.csv",
                ),
                ("/operator/v1/usage-costs?export=csv", "ezllmrouter-usage-costs.csv"),
                (
                    "/operator/v1/integration/report?dataset_id=demo&export=csv",
                    "ezllmrouter-integration-report.csv",
                ),
                (
                    "/operator/v1/scripted-demo/report?export=csv",
                    "ezllmrouter-scripted-demo-report.csv",
                ),
            ):
                with self.subTest(path=path):
                    status, headers, body = self.request("GET", path)
                    self.assertEqual(status, 200)
                    self.assertEqual(headers["Content-Type"], "text/csv; charset=utf-8")
                    self.assertEqual(
                        headers["Content-Disposition"], "attachment; filename=" + filename
                    )
                    self.assertEqual(headers["Content-Length"], str(len(body)))
                    self.assertIn(b"\r\n", body)
                    rows = list(csv.DictReader(io.StringIO(body.decode("utf-8"))))
                    self.assertEqual(len(rows), 1)
                    row = rows[0]
                    self.assertEqual(row["attempt_id"], attempt["attempt_id"])
                    self.assertEqual(row["amount_decimal"], "0.000000001")
                    self.assertEqual(row["currency"], "")
                    self.assertNotIn("not_a_column", row)
                    if "integration/report" in path:
                        self.assertEqual(row["native_units"], '{"a": 1, "z": 2}')
                        self.assertEqual(json.loads(row["eligibility_record"]), {"answer": True})
                        self.assertEqual(json.loads(row["selected_action"]), {"a": "hello"})
                    if "scripted-demo" in path:
                        self.assertEqual(row["demo_provenance"], "DEMO, synthetic only")

    def test_json_export_keeps_attachment_and_object_values(self):
        self.ready_admin()
        report = {"attempts": [{"amount_decimal": "123456789.000000001", "currency": None}]}
        with patch.object(reports, "usage_costs", return_value=report):
            status, headers, body = self.request("GET", "/operator/v1/usage-costs?export=json")
        self.assertEqual((status, body), (200, report))
        self.assertEqual(
            headers["Content-Disposition"], "attachment; filename=ezllmrouter-usage-costs.json"
        )

    def test_failures_identify_operations_without_logging_exception_values(self):
        self.ready_admin()
        self.server.application.integration_only = False
        secret = "SYNTHETIC_PRIVATE_EXCEPTION_CONTENT"
        with (
            patch.object(self.registry, "mutate", side_effect=RuntimeError(secret)),
            self.assertLogs("ezllmrouter", level="ERROR") as captured,
        ):
            self.assertEqual(self.request("POST", "/operator/v1/registry", {})[0], 503)
        self.assertEqual(
            captured.records[0].event,
            "operator_http.registry_routes.post_operator_v1_registry.failed",
        )
        self.assertNotIn(secret, EventFormatter().format(captured.records[0]))
        with (
            patch.object(
                self.server.application.projection, "activity", side_effect=RuntimeError(secret)
            ),
            self.assertLogs("ezllmrouter", level="ERROR") as captured,
        ):
            self.assertEqual(self.request("GET", "/operator/v1/activity?state=private")[0], 503)
        encoded = EventFormatter().format(captured.records[0])
        self.assertEqual(captured.records[0].event, "operator_http.get_operator_v1_activity.failed")
        self.assertNotIn(secret, encoded)
        self.assertNotIn("state=private", encoded)

    def test_no_registry_starts_no_background_threads_and_cleanup_can_precede_start(self):
        application = self.server.application
        jobs = Mock()
        unstarted = replace(
            application, registry=None, local_connectors=None, sessions={}, jobs=jobs
        )
        unstarted.close()
        jobs.shutdown.assert_called_once_with(wait=True, cancel_futures=False)
        self.assertTrue(unstarted.scheduler_stop.is_set())
        self.assertTrue(unstarted.maintenance_stop.is_set())
        application.scheduler_stop.set()
        application.maintenance_stop.set()
        application.scheduler_thread.join()
        application.maintenance_thread.join()
        with patch.object(application, "registry", None), patch("threading.Thread.start") as start:
            application.start(lambda _accounting, _stop: None)
        start.assert_not_called()
        self.assertIsNone(application.scheduler_thread)
        self.assertIsNone(application.maintenance_thread)
