"""Real loopback operator HTTP and a metadata-only synthetic model endpoint."""

from contextlib import ExitStack
import http.client
from http.server import BaseHTTPRequestHandler
import json
from pathlib import Path
import secrets
import threading
import time

from ezllmrouter_server.http_server import BoundedHTTPServer
from ezllmrouter_server.operator_projection import OperatorProjection
from ezllmrouter_server.operator_web import serve

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = "/operator/v1/usage-costs?cutoff=2030-01-01T00%3A00%3A20Z&attempt_limit=10"


class NeverRun:
    def __init__(self):
        self.calls = 0

    def run(self, *_args):
        self.calls += 1
        raise RuntimeError("performance navigation attempted model work")


class OperatorFixture:
    def __init__(self, workload):
        self.stack = ExitStack()
        self.probe_lock = threading.Lock()
        self.probes = {"metadata_gets": 0, "unexpected_requests": 0}
        self.runner = NeverRun()
        self.cookie = self.csrf = None
        try:
            self._start(workload)
        except BaseException:
            self.close()
            raise

    def _listen(self, server, name):
        self.stack.callback(server.server_close)
        thread = threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.05}, name=name, daemon=True
        )
        thread.start()

        def stop():
            server.shutdown()
            thread.join(5)
            if thread.is_alive():
                raise RuntimeError("performance HTTP listener leaked")

        self.stack.callback(stop)

    def _start(self, workload):
        owner = self

        class Metadata(BaseHTTPRequestHandler):
            def do_GET(self):
                accepted = self.path == "/api/version"
                with owner.probe_lock:
                    owner.probes["metadata_gets" if accepted else "unexpected_requests"] += 1
                data = json.dumps(
                    {"version": "synthetic.performance"} if accepted else {"error": "METADATA_ONLY"}
                ).encode()
                self.send_response(200 if accepted else 405)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                with owner.probe_lock:
                    owner.probes["unexpected_requests"] += 1
                self.send_error(405)

            def log_message(self, *_args):
                pass

        provider = BoundedHTTPServer(("127.0.0.1", 0), Metadata)
        self._listen(provider, "ezllmrouter-performance-metadata")
        password = secrets.token_urlsafe(40)
        self.server = serve(
            "127.0.0.1",
            0,
            projection=OperatorProjection(workload.store, "svc.demo"),
            runner=self.runner,
            password=password,
            fixture={},
            build={"commit": "synthetic.performance"},
            web_root=ROOT / "web",
            worker_probe=lambda: {"state": "live"},
            sender_status=lambda: {"state": "live"},
            registry=workload.registry,
        )
        self.stack.callback(self.server.operator_jobs.shutdown, wait=True, cancel_futures=True)
        self._listen(self.server, "ezllmrouter-performance-operator")
        self.port = self.server.server_address[1]
        raw, headers = self.request("POST", "/operator/v1/login", {"password": password})
        self.cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.csrf = json.loads(raw)["csrf"]
        connector = self.server.application.local_connectors.create(
            "owner.local",
            {
                "display_name": "Synthetic performance metadata",
                "kind": "ollama",
                "base_url": f"http://127.0.0.1:{provider.server_address[1]}",
            },
        )
        self.connector_id = connector["connector_id"]

    def request(self, method, path, body=None):
        # Every destination comes from this fixture's bound listener, never a URL input.
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        headers = {"Origin": f"http://127.0.0.1:{self.port}"}
        if self.cookie:
            headers["Cookie"] = self.cookie
        if self.csrf:
            headers["X-EzLLMRouter-CSRF"] = self.csrf
        if body is not None:
            headers["Content-Type"] = "application/json"
        try:
            connection.request(
                method, path, json.dumps(body) if body is not None else None, headers
            )
            response = connection.getresponse()
            raw = response.read(2 * 1024 * 1024 + 1)
            if response.status != 200 or len(raw) > 2 * 1024 * 1024:
                raise RuntimeError("performance HTTP response failed: " + str(response.status))
            return raw, dict(response.getheaders())
        finally:
            connection.close()

    def poll(self):
        self.request(
            "POST",
            "/operator/v1/local-connectors/check",
            {"connector_ids": [self.connector_id], "force": True},
        )
        raw, _ = self.request("GET", "/operator/v1/local-connectors/availability")
        state = json.loads(raw)["items"][0]["availability"]["state"]
        if state not in {"checking", "online"}:
            raise RuntimeError("synthetic metadata polling failed")

    def drain(self):
        monitor = self.server.application.local_connectors.monitor
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with monitor._lock:
                pending = list(monitor._futures)
            if not pending:
                return
            for future in pending:
                future.result(timeout=5)
        raise RuntimeError("performance probes failed to drain")

    def verify(self):
        self.drain()
        with self.probe_lock:
            result = dict(self.probes)
        if self.runner.calls or result["unexpected_requests"] or not result["metadata_gets"]:
            raise RuntimeError("performance workload dispatched unexpected work")
        return {**result, "model_runner_calls": self.runner.calls, "pending_checks": 0}

    def close(self):
        self.stack.close()
