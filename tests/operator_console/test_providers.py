"""DEV-08: real TLS wire shapes and additive provider authority, without live accounts."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import pathlib
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/src"))
from duranki_server.provider_adapters import probe, validate_settings
from duranki_server.registry import Registry, RegistryConflict
from duranki_server.store import SQLiteStore
from duranki_server.provider_vault import ProviderVault


DEST = {"configuration_ref": "cfg.demo", "service": "litellm.dev04", "endpoint": "127.0.0.1",
        "model": "model.demo", "model_version": "v1", "processing_region": "local"}
TRUSTED = {"principal_id": "svc.demo", "charging_owner_id": "team.demo"}


class Authority:
    def __init__(self):
        self.gate = threading.RLock()
        self.epoch = 0


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.requests.append((self.path, dict(self.headers)))
        if self.headers.get("x-api-key") in ("page-key", "page-fail-key"):
            if "after_id=" in self.path:
                return self._reply(500 if self.headers["x-api-key"] == "page-fail-key" else 200,
                    {"data": [{"id": "claude-page-2"}], "has_more": False})
            return self._reply(200, {"data": [{"id": "claude-page-1"}],
                                     "has_more": True, "last_id": "claude-page-1"})
        if self.headers.get("x-goog-api-key") in ("page-key", "page-fail-key"):
            if "pageToken=" in self.path:
                return self._reply(500 if self.headers["x-goog-api-key"] == "page-fail-key" else 200,
                    {"models": [{"name": "models/gemini-page-2"}]})
            return self._reply(200, {"models": [{"name": "models/gemini-page-1"}],
                                     "nextPageToken": "page-2"})
        if self.headers.get("Authorization") == "Bearer rate-limit-key":
            return self._reply(429, {"error": "rate limit"})
        if self.headers.get("Authorization") == "Bearer xai-incorrect-key":
            return self._reply(400, {"code": "invalid-argument", "error": "Incorrect API key"})
        if (self.headers.get("Authorization", "").startswith("Bearer invalid-key") or
                self.headers.get("x-api-key", "").startswith("invalid-key")):
            return self._reply(401, {"error": "invalid"})
        if self.headers.get("Authorization", "").startswith("Bearer forbidden-key"):
            return self._reply(403, {"error": "forbidden"})
        if self.headers.get("Authorization") == "Bearer slow-test-key":
            time.sleep(0.25)
        if self.path == "/health":
            return self._reply(200, {})
        if self.headers.get("x-goog-api-key"):
            return self._reply(200, {"models": [{"name": "models/gemini-test"}]})
        if self.headers.get("anthropic-version"):
            return self._reply(200, {"data": [{"id": "claude-test"}], "has_more": False})
        if self.headers.get("Authorization") == "Bearer wrong-family-key":
            return self._reply(200, {"models": [{"name": "wrong-family"}]})
        return self._reply(200, {"data": [{"id": "model-test"}]})

    def _reply(self, status, value):
        data = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ssl.SSLError):
            pass

    def log_message(self, *_args):
        pass


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = pathlib.Path(self.temp.name)
        cert, key = root / "cert.pem", root / "key.pem"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(key), "-out", str(cert), "-days", "1", "-subj", "/CN=localhost",
            "-addext", "subjectAltName=DNS:localhost"], stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, check=True)
        self.cert = cert.read_text()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.requests = []
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(cert), str(key))
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.origin = f"https://localhost:{self.server.server_port}"
        self.store = SQLiteStore(root / "metadata.sqlite")
        self.addCleanup(self.store.close)
        self.authority = Authority()
        self.vault = ProviderVault(root / "provider-vault")
        self.registry = Registry(self.store, self.authority, legacy_destination=DEST,
            legacy_token="synthetic-local-service-token-only-for-test-000001",
            legacy_trusted=TRUSTED, provider_vault=self.vault)

    def settings(self, lab=False):
        return {"origin": self.origin, "location": "office_lab" if lab else "commercial",
                "site": "Controlled TLS test", "ca_pem": self.cert}

    def change(self, action, subject, expected, data, operation):
        return self.registry.mutate("owner.local", {"operation_id": operation, "action": action,
            "subject": subject, "expected_revision": expected, "data": data})

    def test_distinct_native_tls_inventory_and_readiness(self):
        profiles = [("openai.responses.v1", "Bearer test-key", None, None, "model-test"),
            ("anthropic.messages.2023-06-01", None, "test-key", "2023-06-01", "claude-test"),
            ("gemini.developer.v1beta", None, None, None, "models/gemini-test"),
            ("vllm.openai-compatible.v1", "Bearer test-key", None, None, "model-test"),
            ("xai.responses.v1", "Bearer test-key", None, None, "model-test")]
        for adapter, bearer, anthropic, version, expected in profiles:
            with self.subTest(adapter=adapter):
                lab = adapter.startswith("vllm")
                settings = self.settings(lab)
                result = probe(adapter, settings, "test-key", "inventory", controlled=True)
                self.assertEqual(result["state"], "observed", result)
                self.assertEqual(result["models"], [expected])
                path, headers = self.server.requests[-1]
                self.assertEqual(path, "/v1beta/models" if adapter.startswith("gemini") else "/v1/models")
                self.assertEqual(headers.get("Authorization"), bearer)
                self.assertEqual(headers.get("x-api-key"), anthropic)
                self.assertEqual(headers.get("anthropic-version"), version)
                self.assertEqual(headers.get("x-goog-api-key"), "test-key" if adapter.startswith("gemini") else None)
        result = probe("vllm.openai-compatible.v1", self.settings(True), None, "readiness", controlled=True)
        self.assertEqual(result["state"], "reachable")
        self.assertEqual(self.server.requests[-1][0], "/health")
        self.assertEqual(probe("anthropic.messages.2023-06-01", self.settings(), "test-key", "readiness", controlled=True)["state"], "unsupported")
        scoped = {**self.settings(), "project": "proj_test-123"}
        self.assertEqual(probe("openai.responses.v1", scoped, "test-key", "access", controlled=True)["state"], "observed")
        self.assertEqual(self.server.requests[-1][1].get("OpenAI-Project"), "proj_test-123")

    def test_protocol_and_failure_negatives(self):
        settings = self.settings()
        self.assertEqual(probe("openai.responses.v1", settings, "wrong-family-key", "inventory", controlled=True)["reason"], "malformed_response")
        self.assertEqual(probe("openai.responses.v1", settings, "invalid-key", "inventory", controlled=True)["reason"], "credential_rejected")
        self.assertEqual(probe("openai.responses.v1", settings, "forbidden-key", "access", controlled=True)["reason"], "access_forbidden")
        self.assertEqual(probe("openai.responses.v1", settings, "rate-limit-key", "inventory", controlled=True)["reason"], "rate_limited")
        self.assertEqual(probe("openai.responses.v1", settings, "slow-test-key", "inventory", controlled=True, timeout=0.05)["reason"], "timeout")
        with self.assertRaises(ValueError):
            validate_settings("openai.responses.v1", {**settings, "origin": "https://127.0.0.1"})
        with self.assertRaises(ValueError):
            validate_settings("vllm.openai-compatible.v1", {**self.settings(True), "origin": "http://localhost"})
        with self.assertRaises(ValueError):
            validate_settings("openai.responses.v1", {**settings, "project": "bad\r\nHeader: value"}, controlled=True)
        self.assertEqual(probe("xai.responses.v1", settings, "test-key", "inventory", controlled=True)["state"], "observed")
        self.assertEqual(probe("xai.responses.v1", settings, "xai-incorrect-key", "inventory", controlled=True)["reason"], "credential_rejected")

    def test_paginated_inventory_is_complete_or_partial_without_inference(self):
        for adapter, expected in (("anthropic.messages.2023-06-01", ["claude-page-1", "claude-page-2"]),
                                  ("gemini.developer.v1beta", ["models/gemini-page-1", "models/gemini-page-2"])):
            with self.subTest(adapter=adapter):
                complete = probe(adapter, self.settings(), "page-key", "inventory", controlled=True)
                self.assertEqual(complete["state"], "observed")
                self.assertEqual(complete["models"], expected)
                self.assertEqual(complete["pages"], 2)
                partial = probe(adapter, self.settings(), "page-fail-key", "inventory", controlled=True)
                self.assertEqual(partial["state"], "partial")
                self.assertEqual(partial["models"], expected[:1])
                self.assertEqual(partial["reason"], "later_page_provider_unavailable")
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0], 0)

    def test_failed_refresh_retains_stored_inventory_and_denial(self):
        self.change("create_connection", "conn.retained", 0,
            {"display_name": "Retained lab", "adapter_id": "vllm.openai-compatible.v1",
             "settings": self.settings(True), "owner": "owner.local"}, "op.retained.create")
        self.registry.set_provider_credential("owner.local", "conn.retained", 1,
            "op.retained.key", "replace", "test-provider-key-123456")
        observed = self.registry.probe_connection("owner.local", "conn.retained", 2,
            "op.retained.inventory", "inventory")
        self.assertEqual(observed["state"], "observed")
        first = self.registry.source_inventory("conn.retained")
        self.assertEqual(first["count"], 1)
        self.assertFalse(first["items"][0]["allowed"])
        self.assertEqual(first["discovery"]["state"], "complete")
        self.registry.set_provider_credential("owner.local", "conn.retained", 2,
            "op.retained.remove", "remove")
        failed = self.registry.probe_connection("owner.local", "conn.retained", 3,
            "op.retained.failed", "inventory")
        self.assertEqual(failed["state"], "failed")
        before = len(self.server.requests)
        retained = self.registry.source_inventory("conn.retained")
        self.assertEqual(len(self.server.requests), before)
        self.assertEqual(retained["count"], 1)
        self.assertEqual(retained["discovery"]["state"], "failed")
        self.assertEqual(retained["discovery"]["retained_snapshot_at"], observed["observed_at"])
        self.assertFalse(retained["items"][0]["allowed"])
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0], 0)

    def test_partial_refresh_retains_prior_complete_rows(self):
        self.change("create_connection", "conn.partial", 0,
            {"display_name": "Partial lab", "adapter_id": "vllm.openai-compatible.v1",
             "settings": self.settings(True), "owner": "owner.local"}, "op.partial.create")
        self.registry.set_provider_credential("owner.local", "conn.partial", 1,
            "op.partial.key", "replace", "test-provider-key-123456")
        observed = self.registry.probe_connection("owner.local", "conn.partial", 2,
            "op.partial.complete", "inventory")
        partial = {**observed, "operation_id": "op.partial.later", "state": "partial",
                   "reason": "later_page_rate_limited", "models": ["new-page-model"], "has_more": True}
        self.store._transaction(lambda: self.store.db.execute(
            "INSERT INTO registry_observations VALUES (?,?,?)",
            (partial["operation_id"], "conn.partial", json.dumps(partial))))
        inventory = self.registry.source_inventory("conn.partial")
        self.assertEqual(inventory["discovery"]["state"], "partial")
        self.assertEqual([item["serving_id"] for item in inventory["items"]],
                         ["model-test", "new-page-model"])
        self.assertEqual(inventory["items"][0]["inventory_provenance"],
                         "retained_previous_snapshot")
        self.assertFalse(any(item["allowed"] for item in inventory["items"]))
        bulk = self.change("set_source_permissions", "conn.partial", 0,
            {"allowed": True, "items": [{"serving_id": item["serving_id"], "expected_revision": 0}
                                        for item in inventory["items"]]}, "op.partial.bulk")
        self.assertEqual(len(bulk["record"]["items"]), 2)
        self.assertTrue(all(item["allowed"] for item in self.registry.source_inventory("conn.partial")["items"]))
        self.change("set_source_permissions", "conn.partial", 0,
            {"allowed": False, "items": [{"serving_id": "model-test", "expected_revision": 1}]},
            "op.partial.disallow")
        self.assertFalse(self.registry.source_model_allowed("conn.partial", "model-test"))
        self.assertTrue(self.registry.source_model_allowed("conn.partial", "new-page-model"))
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0], 0)

    def test_connection_vault_rotation_association_and_restart(self):
        create = self.change("create_connection", "conn.lab", 0,
            {"display_name": "Lab fixture", "adapter_id": "vllm.openai-compatible.v1",
             "settings": self.settings(True), "owner": "owner.local"}, "op.conn.create")
        self.assertEqual(create["record"]["status"], "draft")
        self.assertEqual(self.registry.explain("svc.demo", "cfg.demo", "execution", "class.demo")["reason"], "ALLOWED")
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0], 0)
        first = self.registry.set_provider_credential("owner.local", "conn.lab", 1, "op.cred.1",
            "replace", "test-provider-key-123456")
        self.assertEqual(first["record"]["credential_state"], "present")
        self.assertEqual(self.vault.resolve("conn.lab", 1), "test-provider-key-123456")
        second = self.registry.set_provider_credential("owner.local", "conn.lab", 2, "op.cred.2",
            "replace", "test-provider-key-654321")
        self.assertEqual(second["record"]["credential_version"], 2)
        with self.assertRaises(FileNotFoundError):
            self.vault.resolve("conn.lab", 1)
        self.assertNotIn("test-provider-key", " ".join(self.store.db.iterdump()))
        self.assertEqual(self.registry.probe_connection("owner.local", "conn.lab", 3,
            "op.probe.inventory", "inventory")["state"], "observed")
        self.assertEqual(self.registry.probe_connection("owner.local", "conn.lab", 3,
            "op.probe.health", "readiness")["state"], "reachable")
        reopened = Registry(self.store, self.authority, provider_vault=ProviderVault(pathlib.Path(self.temp.name) / "provider-vault"))
        self.assertEqual(reopened.connection("conn.lab")["credential_version"], 2)
        self.assertEqual(reopened.observations("conn.lab")[0]["operation"], "readiness")
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0], 0)
        self.registry.set_provider_credential("owner.local", "conn.lab", 3, "op.cred.remove", "remove")
        self.assertEqual(self.registry.connection("conn.lab")["credential_state"], "absent")
        with self.assertRaises(FileNotFoundError):
            self.vault.resolve("conn.lab", 2)
        self.change("connection_state", "conn.lab", 4,
            {"status": "archived", "reason": "Disposable test"}, "op.conn.archive")
        with self.assertRaises(RegistryConflict):
            self.change("edit_connection", "conn.lab", 5,
                {"display_name": "Resurrection"}, "op.conn.resurrect")

    def test_opt_in_check_schedule_is_bounded_and_reads_do_not_probe(self):
        self.change("create_connection", "conn.schedule", 0,
            {"display_name": "Schedule fixture", "adapter_id": "vllm.openai-compatible.v1",
             "settings": self.settings(True), "owner": "owner.local"}, "op.schedule.create")
        self.assertFalse(self.registry.connection("conn.schedule")["checks_scheduled"])
        self.registry.list_connections()
        self.registry.observations("conn.schedule")
        self.assertEqual(self.server.requests, [])
        with self.assertRaises(ValueError):
            self.change("probe_schedule", "conn.schedule", 1,
                {"enabled": True, "operation": "readiness", "interval_seconds": 10}, "op.schedule.short")
        enabled = self.change("probe_schedule", "conn.schedule", 1,
            {"enabled": True, "operation": "readiness", "interval_seconds": 300}, "op.schedule.on")
        self.assertTrue(enabled["record"]["checks_scheduled"])
        self.assertEqual(self.server.requests, [])
        self.change("probe_schedule", "conn.schedule", 2,
            {"enabled": False, "operation": None, "interval_seconds": None}, "op.schedule.off")
        self.assertFalse(self.registry.connection("conn.schedule")["checks_scheduled"])


if __name__ == "__main__":
    unittest.main()
