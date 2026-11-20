"""Scope-first HTTP reporting, CSV/JSON parity, and read-only behavior."""

import http.client
import json
from pathlib import Path
import socket
import threading
import unittest

from ezllmrouter_server.operator_projection import OperatorProjection
from ezllmrouter_server.operator_web import serve
from tests.operator_console.test_dev09_reporting import ReportingTests, ROOT


class NeverRun:
    def run(self, *_args):
        raise AssertionError("report read launched model work")


class ReportHTTPTests(ReportingTests):
    def test_authorized_scope_and_export_consistency(self):
        self.registry.mutate(
            "owner.local",
            {
                "operation_id": "op.http.user",
                "action": "create_principal",
                "subject": "user.alpha",
                "expected_revision": 0,
                "data": {
                    "display_name": "Synthetic Alpha",
                    "kind": "human",
                    "owner": "team.fixture",
                },
            },
        )
        _, token = self.registry.provision_credential(
            "owner.local", "user.alpha", 1, "op.http.credential"
        )
        self.registry.mutate(
            "owner.local",
            {
                "operation_id": "op.http.active",
                "action": "principal_state",
                "subject": "user.alpha",
                "expected_revision": 2,
                "data": {"status": "active", "reason": "Disposable HTTP scope test"},
            },
        )
        fixture = json.loads((ROOT / "tests/gateway_integration/dev05_fixture.json").read_text())
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        server = serve(
            "127.0.0.1",
            port,
            projection=OperatorProjection(self.store, "svc.demo"),
            runner=NeverRun(),
            password="p" * 40,
            fixture=fixture,
            build={"commit": "dev09-http-disposable"},
            web_root=ROOT / "web",
            worker_probe=lambda: {"state": "live"},
            sender_status=lambda: {"state": "live"},
            registry=self.registry,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def close():
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
            server.operator_jobs.shutdown(wait=True)

        self.addCleanup(close)
        port = server.server_address[1]
        origin = f"http://127.0.0.1:{port}"

        def request(method, path, *, body=None, cookie=None):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            headers = {"Host": f"127.0.0.1:{port}", "Origin": origin}
            if cookie:
                headers["Cookie"] = cookie
            if body is not None:
                headers["Content-Type"] = "application/json"
                body = json.dumps(body)
            try:
                connection.request(method, path, body, headers)
                response = connection.getresponse()
                return response.status, dict(response.getheaders()), response.read()
            finally:
                connection.close()

        def login(password):
            status, headers, _ = request("POST", "/operator/v1/login", body={"password": password})
            self.assertEqual(status, 200)
            return headers["Set-Cookie"].split(";", 1)[0]

        before = {
            name: self.store.db.execute("SELECT COUNT(*) FROM " + name).fetchone()[0]
            for name in ("submissions", "intents", "guard_dispatches", "attribution_outcomes")
        }
        query = "cutoff=2030-01-01T00%3A00%3A20Z"
        self.assertEqual(request("GET", "/operator/v1/usage-costs?" + query)[0], 401)
        admin = login("p" * 40)
        user = login(token)
        status, _, raw = request("GET", "/operator/v1/usage-costs?" + query, cookie=admin)
        self.assertEqual(status, 200)
        full = json.loads(raw)
        self.assertEqual(full["total"]["known_subtotals"], {"EUR": "4", "USD": "32"})
        self.assertEqual(full["total"]["attempts"], 10)
        status, _, raw = request("GET", "/operator/v1/usage-costs?" + query, cookie=user)
        self.assertEqual(status, 200)
        scoped = json.loads(raw)
        self.assertLess(scoped["total"]["attempts"], full["total"]["attempts"])
        self.assertTrue(
            all(row["initiating_user_id"] == "user.alpha" for row in scoped["attempts"])
        )
        self.assertFalse(
            any(row["agent_id"] == "agent.external" for row in scoped["agents"]["items"])
        )
        for export in ("json", "csv"):
            status, headers, raw = request(
                "GET", "/operator/v1/usage-costs?" + query + "&export=" + export, cookie=user
            )
            self.assertEqual(status, 200)
            self.assertIn("attachment", headers["Content-Disposition"])
            self.assertNotIn(b"user.beta", raw)
            self.assertNotIn(b"secret", raw)
            if export == "json":
                self.assertEqual(json.loads(raw)["total"], scoped["total"])
            else:
                self.assertEqual(len(raw.decode().splitlines()), scoped["total"]["attempts"] + 1)
        self.assertEqual(
            request("GET", "/operator/v1/usage-costs?" + query + "&page=0", cookie=admin)[0], 400
        )
        self.assertEqual(
            request(
                "GET", "/operator/v1/usage-costs?" + query + "&model=%3Cscript%3E", cookie=admin
            )[0],
            200,
        )  # Filter value is data, never HTML.
        after = {
            name: self.store.db.execute("SELECT COUNT(*) FROM " + name).fetchone()[0]
            for name in before
        }
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
