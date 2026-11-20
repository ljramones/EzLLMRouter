"""Local connector HTTP authorization and discovery through actual operator handlers."""

import copy
from types import SimpleNamespace

from tests.operator_console.test_user_management_web import UserHTTPFixture
from tests.operator_console.test_local_connectors import INVENTORY
from tests.operator_console.test_user_management import PASSWORD
from ezllmrouter_server.local_connectors import ConnectorError, discover
from tests.operator_console.test_connector_availability import drain


class LocalConnectorHTTPTests(UserHTTPFixture):
    def setUp(self):
        super().setUp()
        self.registry.provider_vault = SimpleNamespace(key=b"h" * 32)
        self.calls = []

        def read(url, path, key):
            self.calls.append(path)
            if path == "/api/tags":
                return copy.deepcopy(INVENTORY)
            if path == "/api/ps":
                return {"models": []}
            if path == "/v1/models":
                return {"data": []}
            return {"version": "0.12.0"}

        self.registry.local_connectors.discover_fn = lambda kind, url, key: discover(
            kind, url, key, read=read
        )
        self.registry.local_connectors.availability_read = lambda url, path, key, **_: read(
            url, path, key
        )

    def add_connector(self):
        status, _, item = self.request(
            "POST",
            "/operator/v1/local-connectors",
            {
                "display_name": "Local Ollama",
                "kind": "ollama",
                "base_url": "http://localhost:11434",
            },
        )
        self.assertEqual(status, 201, item)
        return item

    def test_full_connection_lifecycle_in_accounting_profile(self):
        self.ready_admin()
        item = self.add_connector()
        path = "/operator/v1/local-connectors/" + item["connector_id"]
        self.assertEqual(self.calls, [])
        self.assertIn("ollama", self.request("GET", "/operator/v1/local-connectors")[2]["kinds"])
        self.assertEqual(self.request("GET", path)[0], 200)
        self.assertEqual(self.calls, [])
        status, _, item = self.request(
            "POST", path + "/discover", {"expected_revision": item["revision"]}
        )
        self.assertEqual(status, 200, item)
        self.assertEqual(len(item["discovery"]["models"]), 2)
        self.assertEqual(self.calls, ["/api/tags", "/api/ps", "/api/version"])
        status, _, item = self.request(
            "POST",
            path + "/models",
            {
                "expected_revision": item["revision"],
                "selected_models": ["llama3.2:latest"],
                "enabled": True,
            },
        )
        self.assertEqual(status, 200, item)
        self.assertTrue(item["usable"])
        self.assertEqual(
            self.request("DELETE", path, {"expected_revision": item["revision"]})[0], 200
        )
        self.assertEqual(self.request("GET", path)[0], 404)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0], 0)

    def test_discovery_requires_origin_csrf_and_admin(self):
        self.ready_admin()
        item = self.add_connector()
        path = "/operator/v1/local-connectors/" + item["connector_id"]
        body = {"expected_revision": item["revision"]}
        self.assertEqual(self.request("POST", path + "/discover", body, csrf=False)[0], 403)
        self.assertEqual(self.request("DELETE", path, body, csrf=False)[0], 403)
        self.assertEqual(
            self.request("POST", path + "/discover", body, origin="http://evil.example")[0], 403
        )
        self.assertEqual(self.calls, [])
        viewer = self.create("viewer", "read_only_operator")
        self.users.change_password(
            viewer["principal_id"],
            {"current_password": PASSWORD, "new_password": "Viewer private replacement password"},
        )
        self.login("viewer", "Viewer private replacement password")
        self.assertEqual(self.request("GET", "/operator/v1/local-connectors")[0], 200)
        self.assertEqual(self.request("POST", path + "/discover", body)[0], 403)
        self.assertEqual(self.request("POST", "/operator/v1/local-connectors", {})[0], 403)
        self.assertEqual(self.request("DELETE", path, body)[0], 403)
        self.assertEqual(self.calls, [])

    def test_failed_server_auth_does_not_sign_out_operator(self):
        self.ready_admin()
        item = self.add_connector()
        self.registry.local_connectors.discover_fn = lambda *_: (_ for _ in ()).throw(
            ConnectorError("SERVER_AUTHENTICATION_REQUIRED", 502)
        )
        status, _, item = self.request(
            "POST",
            "/operator/v1/local-connectors/" + item["connector_id"] + "/discover",
            {"expected_revision": item["revision"]},
        )
        self.assertEqual(status, 200)
        self.assertEqual(item["discovery"]["reason"], "SERVER_AUTHENTICATION_REQUIRED")
        self.assertEqual(self.request("GET", "/operator/v1/session")[0], 200)

    def test_ordinary_and_password_changing_accounts_cannot_read_or_discover(self):
        self.login()
        self.assertEqual(self.request("GET", "/operator/v1/local-connectors")[0], 403)
        self.ready_admin()
        user = self.create()
        self.users.change_password(
            user["principal_id"],
            {"current_password": PASSWORD, "new_password": "Ordinary user private password"},
        )
        self.login("alice", "Ordinary user private password")
        self.assertEqual(self.request("GET", "/operator/v1/local-connectors")[0], 403)
        self.assertEqual(self.request("POST", "/operator/v1/local-connectors", {})[0], 403)

    def test_connector_script_is_served_as_a_static_asset(self):
        status, headers, body = self.request("GET", "/local_connectors_view.js")
        self.assertEqual(status, 200)
        self.assertIn("text/javascript", headers["Content-Type"])
        self.assertIn(b"localConnectorsView", body)

    def test_availability_routes_are_cached_then_async_and_do_not_change_revision(self):
        self.ready_admin()
        item = self.add_connector()
        status, _, cached = self.request("GET", "/operator/v1/local-connectors/availability")
        self.assertEqual(status, 200)
        self.assertEqual(cached["items"][0]["availability"]["state"], "unknown")
        self.assertEqual(self.calls, [])
        body = {"connector_ids": [item["connector_id"]]}
        self.assertEqual(
            self.request("POST", "/operator/v1/local-connectors/check", body, csrf=False)[0], 403
        )
        self.assertEqual(
            self.request(
                "POST", "/operator/v1/local-connectors/check", body, origin="http://evil.example"
            )[0],
            403,
        )
        self.assertEqual(self.calls, [])
        self.assertEqual(self.request("POST", "/operator/v1/local-connectors/check", body)[0], 200)
        drain(self.registry.local_connectors.monitor)
        status, _, cached = self.request("GET", "/operator/v1/local-connectors/availability")
        self.assertEqual(cached["items"][0]["availability"]["state"], "online")
        self.assertEqual(self.calls, ["/api/version"])
        saved = self.request("GET", "/operator/v1/local-connectors/" + item["connector_id"])[2]
        self.assertEqual(saved["revision"], item["revision"])
        self.assertEqual(saved["discovery"]["state"], "not_checked")

    def test_find_routes_are_explicit_and_readonly_cannot_scan(self):
        self.ready_admin()
        self.add_connector()
        self.assertEqual(self.request("GET", "/operator/v1/local-connectors/nearby")[0], 200)
        self.assertEqual(self.calls, [])
        self.assertEqual(
            self.request("POST", "/operator/v1/local-connectors/find", {}, csrf=False)[0], 403
        )
        self.assertEqual(self.request("POST", "/operator/v1/local-connectors/find", {})[0], 200)
        drain(self.registry.local_connectors.monitor)
        self.assertEqual(len(self.calls), 7)
        self.assertEqual(len(self.request("GET", "/operator/v1/local-connectors")[2]["items"]), 1)
        viewer = self.create("viewer", "read_only_operator")
        self.users.change_password(
            viewer["principal_id"],
            {"current_password": PASSWORD, "new_password": "Viewer private replacement password"},
        )
        self.login("viewer", "Viewer private replacement password")
        self.assertEqual(self.request("GET", "/operator/v1/local-connectors/availability")[0], 200)
        self.assertEqual(self.request("POST", "/operator/v1/local-connectors/check", {})[0], 200)
        self.assertEqual(self.request("GET", "/operator/v1/local-connectors/nearby")[0], 403)
        self.assertEqual(self.request("POST", "/operator/v1/local-connectors/find", {})[0], 403)

    def test_ordinary_and_temporary_password_accounts_cannot_probe(self):
        self.login()
        for path in ("availability", "nearby"):
            self.assertEqual(self.request("GET", "/operator/v1/local-connectors/" + path)[0], 403)
        for path in ("check", "find"):
            self.assertEqual(
                self.request("POST", "/operator/v1/local-connectors/" + path, {})[0], 403
            )
        self.ready_admin()
        user = self.create()
        self.users.change_password(
            user["principal_id"],
            {"current_password": PASSWORD, "new_password": "Ordinary user private password"},
        )
        self.login("alice", "Ordinary user private password")
        self.assertEqual(self.request("GET", "/operator/v1/local-connectors/availability")[0], 403)
        self.assertEqual(self.request("POST", "/operator/v1/local-connectors/check", {})[0], 403)
