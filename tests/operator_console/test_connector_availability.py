"""Cached metadata probes, concurrent checks, and model-inventory separation."""
import json
import threading
import unittest
from unittest.mock import patch

from tests.operator_console.test_local_connectors import LocalFixture, FakeSocket
from duranki_server.connector_availability import AvailabilityMonitor
from duranki_server.local_connectors import ConnectorError, _read_json


def drain(monitor):
    with monitor._lock:
        futures = list(monitor._futures)
    for future in futures:
        future.result(timeout=3)


class MonitorTests(unittest.TestCase):
    def monitor(self, **options):
        monitor = AvailabilityMonitor(**options)
        self.addCleanup(monitor.close)
        return monitor

    def test_cache_cooldown_staleness_and_config_change(self):
        now, calls = [0], []
        monitor = self.monitor(clock=lambda: now[0])
        def check():
            calls.append(True)
            return {"state": "online", "reason": "API_RESPONDED", "reachable": True}
        monitor.request("one", "config1", check)
        drain(monitor)
        self.assertEqual(monitor.get("one", "config1")["state"], "online")
        self.assertIsNotNone(monitor.get("one", "config1")["latency_ms"])
        monitor.request("one", "config1", check, force=True)
        self.assertEqual(len(calls), 1)
        now[0] = 3
        monitor.request("one", "config1", check)
        self.assertEqual(len(calls), 1)
        monitor.request("one", "config1", check, force=True)
        drain(monitor)
        self.assertEqual(len(calls), 2)
        now[0] = 50
        self.assertTrue(monitor.get("one", "config1")["stale"])
        self.assertEqual(monitor.get("one", "config2")["state"], "unknown")

    def test_concurrent_requests_coalesce_and_queue_is_bounded(self):
        monitor = self.monitor(max_workers=1, max_pending=1)
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        calls = []
        def check():
            calls.append(True)
            entered.set()
            release.wait(3)
            return {"state": "online"}
        monitor.request("one", "config", check)
        self.assertTrue(entered.wait(1))
        self.assertEqual(monitor.request("one", "config", check, force=True)["state"], "checking")
        self.assertEqual(monitor.request("two", "config", check)["reason"], "CHECK_QUEUE_FULL")
        release.set()
        drain(monitor)
        self.assertEqual(len(calls), 1)

    def test_late_results_cannot_replace_changed_configuration(self):
        monitor = self.monitor()
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def old():
            entered.set()
            release.wait(3)
            return {"state": "offline"}
        monitor.request("one", "old", old)
        self.assertTrue(entered.wait(1))
        monitor.request("one", "new", lambda: {"state": "online"})
        release.set()
        drain(monitor)
        self.assertEqual(monitor.get("one", "new")["state"], "online")
        self.assertEqual(monitor.get("one", "old")["state"], "unknown")

    def test_unexpected_errors_are_redacted_and_closed_monitor_rejects_work(self):
        monitor = self.monitor()
        def fail():
            raise RuntimeError("private-token-and-server-body")
        monitor.request("one", "config", fail)
        drain(monitor)
        self.assertEqual(monitor.get("one", "config")["reason"], "CHECK_FAILED")
        self.assertNotIn("private-token", json.dumps(monitor.get("one", "config")))
        monitor.close()
        self.assertEqual(monitor.request("two", "config", fail)["reason"], "CHECK_STOPPED")


class AvailabilityTests(LocalFixture):
    def setUp(self):
        super().setUp()
        self.connectors.availability_read = lambda url, path, key, **_: self.reader(url, path, key)

    def check(self, item):
        self.connectors.availability("owner.local", {"connector_ids": [item["connector_id"]]})
        drain(self.connectors.monitor)
        return self.connectors.availability("owner.local")["items"][0]["availability"]

    def test_probes_do_not_change_records_audit_authority_or_model_selections(self):
        item = self.select(self.discover_connector(self.connector(api_key="local-private-token")))
        before = list(self.store.db.iterdump())
        epoch = self.registry.send_authority.epoch
        self.calls.clear()
        self.assertEqual(self.connectors.availability("owner.local")["items"][0]["availability"]["state"], "unknown")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.check(item)["state"], "online")
        self.assertEqual(self.calls, [(item["base_url"], "/api/version", "local-private-token")])
        self.assertEqual(list(self.store.db.iterdump()), before)
        self.assertEqual(self.registry.send_authority.epoch, epoch)
        status = self.connectors.get("owner.local", item["connector_id"])
        self.assertEqual(status["selected_models"], item["selected_models"])
        self.assertEqual(status["revision"], item["revision"])
        self.assertNotIn("local-private-token", json.dumps(status))

    def test_empty_inventory_is_online_without_creating_discovery(self):
        item = self.connector(kind="localai", base_url="http://localhost:8081/v1")
        calls = []
        def read(url, path, key, **options):
            calls.append((url, path, key, options))
            return {"data": []}
        self.connectors.availability_read = read
        status = self.check(item)
        self.assertEqual((status["state"], status["model_count"]), ("online", 0))
        self.assertEqual(calls, [(item["base_url"], "/v1/models", "", {"timeout": 1.5})])
        self.assertEqual(self.connectors.get("owner.local", item["connector_id"])["discovery"]["state"], "not_checked")

    def test_old_ollama_version_falls_back_to_installed_inventory_only_on_404(self):
        item = self.connector()
        def read(url, path, key, **_):
            self.calls.append(path)
            if path == "/api/version":
                raise ConnectorError("DISCOVERY_ENDPOINT_NOT_FOUND", 502)
            return {"models": []}
        self.connectors.availability_read = read
        self.assertEqual(self.check(item)["state"], "online")
        self.assertEqual(self.calls, ["/api/version", "/api/tags"])

    def test_errors_distinguish_offline_auth_tls_blocked_and_wrong_api(self):
        for reason, state, reached in (("SERVER_UNREACHABLE", "offline", False),
                ("SERVER_TIMEOUT", "offline", False), ("SERVER_AUTHENTICATION_REQUIRED", "attention", True),
                ("SERVER_TLS_FAILED", "attention", True), ("INVALID_SERVER_RESPONSE", "attention", True),
                ("SERVER_CHECK_BLOCKED", "blocked", None)):
            with self.subTest(reason=reason):
                def read(*_, **__):
                    raise ConnectorError(reason, 502)
                self.connectors.availability_read = read
                item = self.connector()
                self.connectors.availability("owner.local", {"connector_ids": [item["connector_id"]]})
                drain(self.connectors.monitor)
                status = self.connectors.get("owner.local", item["connector_id"])["availability"]
                self.assertEqual((status["state"], status["reason"], status["reachable"]), (state, reason, reached))

    def test_scan_is_explicit_fixed_loopback_and_does_not_save_connectors(self):
        item = self.connector(kind="localai", base_url="http://127.0.0.1:8081/v1")
        before = list(self.store.db.iterdump())
        candidates = self.connectors.nearby("owner.local")["items"]
        self.assertEqual(self.calls, [])
        self.assertEqual(next(row for row in candidates if row["base_url"].endswith(":8081"))["saved_connector_id"], item["connector_id"])
        self.connectors.nearby("owner.local", {})
        drain(self.connectors.monitor)
        candidates = self.connectors.nearby("owner.local")["items"]
        self.assertEqual(len(self.calls), 7)
        self.assertTrue(all(url.startswith("http://localhost:") for url, _, _ in self.calls))
        self.assertEqual({path for _, path, _ in self.calls}, {"/api/version", "/v1/models"})
        self.assertTrue(all(row["availability"]["state"] == "online" for row in candidates))
        self.assertEqual(list(self.store.db.iterdump()), before)

    def test_readonly_can_check_saved_servers_but_cannot_scan_or_change_settings(self):
        viewer = self.create("viewer", "read_only_operator")["principal_id"]
        item = self.connector()
        self.connectors.availability(viewer, {})
        drain(self.connectors.monitor)
        self.assertEqual(self.connectors.get(viewer, item["connector_id"])["availability"]["state"], "online")
        for actor, method in ((viewer, self.connectors.nearby), (self.create()["principal_id"], self.connectors.availability)):
            with self.assertRaises(ConnectorError) as exc:
                method(actor, {})
            self.assertEqual(exc.exception.status, 403)

    def test_settings_changes_invalidate_health_and_reject_invalid_check_requests(self):
        item = self.connector()
        self.assertEqual(self.check(item)["state"], "online")
        item = self.connectors.update("owner.local", item["connector_id"], {
            "expected_revision": item["revision"], "display_name": item["display_name"],
            "kind": item["kind"], "base_url": "http://localhost:11435"})
        self.assertEqual(item["availability"]["state"], "unknown")
        for body in ({"force": 1}, {"connector_ids": [item["connector_id"]]*2}, {"connector_ids": "all"},
                     {"connector_ids": ["no-such-connector"]}, {"base_url": "http://evil.example"}):
            with self.assertRaises(ConnectorError):
                self.connectors.availability("owner.local", body)

    def test_transport_permission_error_is_not_reported_as_server_offline(self):
        raw = FakeSocket()
        raw.connect = lambda _: (_ for _ in ()).throw(PermissionError("sandbox private diagnostic"))
        with patch("duranki_server.local_connectors.socket.getaddrinfo", return_value=[
                (2, 1, 6, "", ("127.0.0.1", 8081))]), \
                patch("duranki_server.local_connectors.socket.socket", return_value=raw):
            with self.assertRaises(ConnectorError) as exc:
                _read_json("http://localhost:8081", "/v1/models", "")
        self.assertEqual(exc.exception.code, "SERVER_CHECK_BLOCKED")
        self.assertTrue(raw.closed)
