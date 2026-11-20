"""Actual stdlib HTTP handler, authentication and browser API boundary tests."""

import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from tests.support import wait_for_value
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]

from ezllmrouter_server.operator_projection import OperatorProjection
from ezllmrouter_server.operator_web import serve
from ezllmrouter_server.store import SQLiteStore


from deploy.local import check as check
from deploy.local import console_ingress as console_ingress


class Runner:
    def __init__(self):
        self.calls = []

    def run(self, kind, on_handle):
        self.calls.append(kind)
        on_handle("submission.demo")
        return {"submission_ids": ["submission.demo"], "caller_lookups": 0}


class WebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SQLiteStore(Path(self.tmp.name) / "state.sqlite")
        self.projection = OperatorProjection(self.store, "svc.demo")
        self.runner = Runner()
        fixture = json.loads((ROOT / "tools/gateway/evidence/dev05_fixture.json").read_text())
        self.port = 0
        self.origin = f"http://127.0.0.1:{self.port}"
        self.server = serve(
            "127.0.0.1",
            self.port,
            projection=self.projection,
            runner=self.runner,
            password="p" * 40,
            fixture=fixture,
            build={"commit": "test", "dirty": True, "fingerprint": "f" * 64},
            web_root=Path(os.environ.get("EZLLMROUTER_OPERATOR_WEB_ROOT", str(ROOT / "web"))),
            worker_probe=lambda: {"state": "live"},
            sender_status=lambda: {"state": "live"},
        )
        self.port = self.server.server_port
        self.origin = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.server.operator_jobs.shutdown(wait=True)
        self.store.close()
        self.tmp.cleanup()

    def request(self, method, path, body=None, *, host=None, origin=None, cookie=None, csrf=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        headers = {"Host": host or f"127.0.0.1:{self.port}"}
        if origin is not None:
            headers["Origin"] = origin
        if cookie:
            headers["Cookie"] = cookie
        if csrf:
            headers["X-EzLLMRouter-CSRF"] = csrf
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        try:
            conn.request(method, path, data, headers)
            reply = conn.getresponse()
            raw = reply.read()
            return reply.status, dict(reply.getheaders()), raw
        finally:
            conn.close()

    def login(self):
        status, headers, raw = self.request(
            "POST", "/operator/v1/login", {"password": "p" * 40}, origin=self.origin
        )
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";", 1)[0], json.loads(raw)["csrf"]

    def test_auth_origin_csrf_and_exact_mutation_schema(self):
        self.assertEqual(self.request("GET", "/operator/v1/overview")[0], 401)
        self.assertEqual(self.request("GET", "/operator/v1/overview", host="evil.example")[0], 403)
        self.assertEqual(
            self.request(
                "POST", "/operator/v1/login", {"password": "p" * 40}, origin="http://evil.example"
            )[0],
            403,
        )
        cookie, csrf = self.login()
        self.assertEqual(self.request("GET", "/operator/v1/overview", cookie=cookie)[0], 200)
        self.assertEqual(
            self.request(
                "POST",
                "/operator/v1/demos/text",
                {"operation_id": "operation.demo"},
                origin=self.origin,
                cookie=cookie,
            )[0],
            403,
        )
        self.assertEqual(
            self.request(
                "POST",
                "/operator/v1/demos/text",
                {"operation_id": "operation.demo", "provider_url": "http://evil"},
                origin=self.origin,
                cookie=cookie,
                csrf=csrf,
            )[0],
            400,
        )
        self.assertEqual(
            self.request(
                "POST",
                "/operator/v1/demos/text",
                {"operation_id": "operation.demo"},
                origin=self.origin,
                cookie=cookie,
                csrf=csrf,
            )[0],
            202,
        )
        self.assertEqual(
            self.request(
                "POST",
                "/operator/v1/demos/text",
                {"operation_id": "operation.demo"},
                origin=self.origin,
                cookie=cookie,
                csrf=csrf,
            )[0],
            202,
        )
        status, _, raw = wait_for_value(
            lambda: self.request("GET", "/operator/v1/launch/operation.demo", cookie=cookie),
            lambda response: json.loads(response[2])["state"] == "completed",
        )
        self.assertEqual(status, 200)
        self.assertEqual(self.runner.calls, ["text"])
        self.assertEqual(
            self.request(
                "POST", "/operator/v1/logout", {}, origin=self.origin, cookie=cookie, csrf=csrf
            )[0],
            200,
        )
        self.assertEqual(self.request("GET", "/operator/v1/overview", cookie=cookie)[0], 401)

    def test_static_console_and_rejected_selectors(self):
        status, headers, raw = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"LOCAL DEVELOPMENT", raw)
        self.assertIn(b"/activity_usage_view.js", raw)
        self.assertEqual(self.request("GET", "/activity_usage_view.js")[0], 200)
        self.assertIn(b"/crud_view.js", raw)
        self.assertEqual(self.request("GET", "/crud_view.js")[0], 200)
        self.assertIn(b"/source_pages.js", raw)
        self.assertEqual(self.request("GET", "/source_pages.js")[0], 200)
        self.assertEqual(headers["Cache-Control"], "no-store, max-age=0")
        cookie, _ = self.login()
        self.assertEqual(self.request("GET", "/operator/v1/activity?page=0", cookie=cookie)[0], 400)
        self.assertEqual(
            self.request("GET", "/operator/v1/activity?state=evil", cookie=cookie)[0], 400
        )
        self.assertEqual(
            self.request("GET", "/operator/v1/activity/../store.sqlite", cookie=cookie)[0], 400
        )

    def test_actual_host_consumer_parses_login_health_and_launch(self):
        with patch.object(check, "PORT", self.port), patch.object(check, "ORIGIN", self.origin):
            client = check.OperatorClient("p" * 40)
            client.login()
            self.assertEqual(client.health()["worker"]["state"], "live")
            launch = client.launch("text")
            self.assertEqual(launch["state"], "completed")
            self.assertEqual(launch["submission_ids"], ["submission.demo"])
        self.assertEqual(self.runner.calls, ["text"])

    def test_unix_console_through_fixed_loopback_relay(self):
        path = Path(self.tmp.name) / "operator.sock"
        fixture = json.loads((ROOT / "tools/gateway/evidence/dev05_fixture.json").read_text())
        uds = serve(
            "127.0.0.1",
            8780,
            socket_path=str(path),
            projection=self.projection,
            runner=self.runner,
            password="p" * 40,
            fixture=fixture,
            build={"commit": "test", "dirty": True, "fingerprint": "f" * 64},
            web_root=ROOT / "web",
            worker_probe=lambda: {"state": "live"},
            sender_status=lambda: {"state": "live"},
        )
        thread = threading.Thread(target=uds.serve_forever)
        thread.start()
        try:
            with patch.object(console_ingress, "TARGET", path):
                with console_ingress.Server(("127.0.0.1", 0), console_ingress.Handler) as ingress:
                    relay = threading.Thread(target=ingress.serve_forever)
                    relay.start()
                    try:
                        conn = http.client.HTTPConnection(
                            "127.0.0.1", ingress.server_address[1], timeout=2
                        )
                        conn.request("GET", "/", headers={"Host": "127.0.0.1:8780"})
                        response = conn.getresponse()
                        self.assertEqual(response.status, 200)
                        self.assertIn(b"LOCAL DEVELOPMENT", response.read())
                        conn.close()
                        conn = http.client.HTTPConnection(
                            "127.0.0.1", ingress.server_address[1], timeout=2
                        )
                        conn.request(
                            "POST",
                            "/operator/v1/login",
                            body=json.dumps({"password": "p" * 40}),
                            headers={
                                "Host": "127.0.0.1:8780",
                                "Origin": "http://127.0.0.1:8780",
                                "Content-Type": "application/json",
                            },
                        )
                        response = conn.getresponse()
                        self.assertEqual(response.status, 200)
                        self.assertTrue(json.loads(response.read())["authenticated"])
                        conn.close()
                    finally:
                        ingress.shutdown()
                        relay.join(timeout=3)
        finally:
            uds.shutdown()
            uds.server_close()
            thread.join(timeout=3)
            uds.operator_jobs.shutdown(wait=True)

    def test_duplicate_json_and_injected_identifier_are_rejected_or_redacted(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        raw = b'{"password":"' + b"p" * 40 + b'","password":"' + b"p" * 40 + b'"}'
        try:
            conn.request(
                "POST",
                "/operator/v1/login",
                raw,
                {
                    "Host": f"127.0.0.1:{self.port}",
                    "Origin": self.origin,
                    "Content-Type": "application/json",
                },
            )
            response = conn.getresponse()
            response.read()
            self.assertEqual(response.status, 400)
        finally:
            conn.close()
        malicious = "<script>alert(1)</script>"
        self.store.create(
            {
                "submission_id": "submission.bad",
                "attempt_id": "attempt.bad",
                "principal_id": "svc.demo",
                "task_id": "task.demo",
                "work_key": {
                    "principal_id": "svc.demo",
                    "task_id": "task.demo",
                    "step_id": malicious,
                    "step_revision": 1,
                    "execution_generation": "gen.1",
                },
                "work_digest": "sha256:" + "1" * 64,
                "submission_state": "completed",
                "dispatch_state": "response_observed",
                "candidate_access": "present",
                "content_store_allowed": True,
                "updated_at": "2026-10-21T00:00:00Z",
            }
        )
        cookie, _ = self.login()
        status, _, body = self.request("GET", "/operator/v1/activity", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertNotIn(malicious.encode(), body)


if __name__ == "__main__":
    unittest.main()
