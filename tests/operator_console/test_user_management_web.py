"""Actual operator handlers with in-memory HTTP streams; no socket permission required."""
from email.message import Message
from email.parser import BytesParser
import io
import json
import unittest
from unittest.mock import patch

from tests.operator_console.test_user_management import UserFixture, DEFAULT_ADMIN_PASSWORD, PASSWORD, ROOT
from duranki_server.operator_projection import OperatorProjection
from duranki_server.operator_web import serve


class MemoryServer:
    def __init__(self, address, handler):
        self.address, self.handler = address, handler

    def server_close(self):
        pass


class UserHTTPFixture(UserFixture):
    def setUp(self):
        super().setUp()
        with patch("duranki_server.operator_web.ThreadingHTTPServer", MemoryServer):
            self.server = serve("127.0.0.1", 48761,
                projection=OperatorProjection(self.store, "svc.demo"), runner=None,
                password="legacy-operator-credential-0000000000000000", fixture={}, build={},
                web_root=ROOT / "web", worker_probe=lambda: {}, sender_status=lambda: {},
                registry=self.registry, integration_only=True)
        self.addCleanup(self.server.operator_jobs.shutdown, wait=True)
        self.addCleanup(self.server.server_close)
        self.cookie, self.csrf = None, None

    def request(self, method, path, body=None, *, csrf=True, origin="http://127.0.0.1:48761"):
        handler = self.server.handler.__new__(self.server.handler)
        handler.path, handler.command = path, method
        handler.request_version = "HTTP/1.1"
        handler.requestline = method + " " + path + " HTTP/1.1"
        handler.client_address = ("127.0.0.1", 12345)
        handler.headers = Message()
        handler.headers["Host"] = "127.0.0.1:48761"
        if origin:
            handler.headers["Origin"] = origin
        if self.cookie:
            handler.headers["Cookie"] = self.cookie
        if csrf and self.csrf:
            handler.headers["X-Duranki-CSRF"] = self.csrf
        raw = json.dumps(body).encode() if body is not None else b""
        if body is not None:
            handler.headers["Content-Type"] = "application/json"
            handler.headers["Content-Length"] = str(len(raw))
        handler.rfile, handler.wfile = io.BytesIO(raw), io.BytesIO()
        getattr(handler, "do_" + method)()
        head, data = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
        status = int(head.split(b" ", 2)[1])
        headers = BytesParser().parsebytes(head.split(b"\r\n", 1)[1])
        payload = json.loads(data) if headers["Content-Type"].startswith("application/json") else data
        return status, headers, payload

    def login(self, name="admin", password=DEFAULT_ADMIN_PASSWORD):
        status, headers, data = self.request("POST", "/operator/v1/login", {"username": name, "password": password})
        self.assertEqual(status, 200, data)
        self.cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.csrf = data["csrf"]
        return data

    def ready_admin(self):
        self.login()
        status, _, data = self.request("POST", "/operator/v1/account/password", {
            "current_password": DEFAULT_ADMIN_PASSWORD, "new_password": PASSWORD})
        self.assertEqual(status, 200, data)
        self.login(password=PASSWORD)

class UserHTTPTests(UserHTTPFixture):
    def test_unauthenticated_mutations_are_rejected_before_reading_body(self):
        with patch.object(self.server.handler, "_body", side_effect=AssertionError("body read before authentication")):
            for method in ("POST", "DELETE"):
                with self.subTest(method=method):
                    status, headers, _ = self.request(method, "/operator/v1/users", {"anything": "ignored"})
                    self.assertEqual(status, 401)
                    self.assertTrue(headers["X-Request-ID"].startswith("request."))

    def test_http_first_login_allows_only_password_change_and_logout(self):
        session = self.login()
        self.assertTrue(session["must_change_password"])
        self.assertIn("users.manage", session["permissions"])
        self.assertEqual(self.request("GET", "/operator/v1/users")[0], 403)
        self.assertEqual(self.request("GET", "/operator/v1/models")[0], 403)
        self.assertEqual(self.request("POST", "/operator/v1/users", {})[0], 403)
        self.assertEqual(self.request("DELETE", "/operator/v1/users/owner.local", {"expected_revision": 1})[0], 403)
        self.assertEqual(self.request("GET", "/operator/v1/session")[0], 200)
        self.assertEqual(self.request("POST", "/operator/v1/account/password", {
            "current_password": "wrong", "new_password": PASSWORD})[0], 400)
        self.assertEqual(self.request("GET", "/operator/v1/session")[0], 200)

    def test_http_crud_and_permissions_work_in_accounting_only_console(self):
        self.ready_admin()
        status, _, user = self.request("POST", "/operator/v1/users", {
            "username": "reader", "display_name": "Report reader", "role": "read_only_operator",
            "status": "active", "password": PASSWORD})
        self.assertEqual(status, 201, user)
        path = "/operator/v1/users/" + user["principal_id"]
        self.assertEqual(self.request("GET", path)[2]["username"], "reader")
        data = {key: user[key] for key in ("username", "display_name", "role", "status")}
        data.update(expected_revision=user["revision"], status="suspended")
        status, _, user = self.request("POST", path, data)
        self.assertEqual(status, 200, user)
        self.assertEqual(user["status"], "suspended")
        status, _, user = self.request("DELETE", path, {"expected_revision": user["revision"]})
        self.assertEqual(status, 200, user)
        self.assertEqual(user["status"], "revoked")
        listing = self.request("GET", "/operator/v1/users")[2]
        self.assertEqual([row["username"] for row in listing["items"]], ["admin"])

    def test_http_user_writes_require_origin_and_csrf(self):
        self.ready_admin()
        self.assertEqual(self.request("POST", "/operator/v1/users", {}, csrf=False)[0], 403)
        self.assertEqual(self.request("DELETE", "/operator/v1/users/owner.local", {}, csrf=False)[0], 403)
        self.assertEqual(self.request("POST", "/operator/v1/users", {}, origin="http://evil.example")[0], 403)
        self.assertEqual(self.request("POST", "/operator/v1/users?bypass=1", {})[0], 403)
        self.assertEqual(self.request("DELETE", "/operator/v1/users/owner.local?bypass=1", {})[0], 403)

    def test_http_ordinary_user_cannot_manage_users(self):
        self.ready_admin()
        self.create()
        self.login("alice", PASSWORD)
        self.assertEqual(self.request("POST", "/operator/v1/account/password", {
            "current_password": PASSWORD, "new_password": "Alice's replacement passphrase"})[0], 200)
        self.login("alice", "Alice's replacement passphrase")
        self.assertEqual(self.request("GET", "/operator/v1/users")[0], 403)
        self.assertEqual(self.request("POST", "/operator/v1/users", {})[0], 403)
        self.assertEqual(self.request("DELETE", "/operator/v1/users/owner.local", {"expected_revision": 1})[0], 403)
        self.assertNotIn("users.manage", self.request("GET", "/operator/v1/session")[2]["permissions"])

    def test_http_password_reset_invalidates_all_existing_user_sessions(self):
        self.ready_admin()
        user = self.create()
        admin = self.cookie, self.csrf
        self.login("alice", PASSWORD)
        old_user = self.cookie, self.csrf
        self.cookie, self.csrf = admin
        path = "/operator/v1/users/" + user["principal_id"] + "/password"
        self.assertEqual(self.request("POST", path, {"expected_revision": user["revision"],
            "password": "Another temporary test password"})[0], 200)
        self.cookie, self.csrf = old_user
        self.assertEqual(self.request("GET", "/operator/v1/session")[0], 401)
        self.assertEqual(self.request("POST", "/operator/v1/login", {"username": "alice", "password": PASSWORD})[0], 401)
        self.assertTrue(self.login("alice", "Another temporary test password")["must_change_password"])

    def test_http_disabling_then_reenabling_does_not_resurrect_session(self):
        self.ready_admin()
        user = self.create()
        admin = self.cookie, self.csrf
        self.login("alice", PASSWORD)
        old_user = self.cookie, self.csrf
        self.cookie, self.csrf = admin
        disabled = self.update(user, status="suspended")
        self.update(disabled, status="active")
        self.cookie, self.csrf = old_user
        self.assertEqual(self.request("GET", "/operator/v1/session")[0], 401)

    def test_http_last_admin_is_protected_and_passwords_never_returned(self):
        self.ready_admin()
        user = self.request("GET", "/operator/v1/users/owner.local")[2]
        self.assertEqual(self.request("DELETE", "/operator/v1/users/owner.local", {
            "expected_revision": user["revision"]})[0], 409)
        listing = json.dumps(self.request("GET", "/operator/v1/users")[2])
        self.assertNotIn(PASSWORD, listing)
        self.assertNotIn("scrypt$", listing)
        self.assertNotIn("password_hash", listing)

    def test_http_readonly_cannot_write_and_grants_remain_explicit(self):
        self.ready_admin()
        user = self.create()
        path = "/operator/v1/principals/" + user["principal_id"]
        self.assertEqual(self.request("GET", path)[2]["grants"], [])
        self.assertEqual(self.request("GET", "/operator/v1/connections")[0], 200)
        status, _, data = self.request("POST", "/operator/v1/registry", {
            "operation_id": "op.named-user-grant", "action": "set_grant", "subject": user["principal_id"],
            "expected_revision": 0, "data": {"configuration_ref": "cfg.demo", "status": "active",
                "purposes": ["execution"], "task_classes": ["class.demo"]}})
        self.assertEqual(status, 200, data)
        self.assertEqual(self.request("GET", path)[2]["grants"][0]["status"], "active")
        viewer = self.create("viewer", "read_only_operator")
        self.users.change_password(viewer["principal_id"], {"current_password": PASSWORD,
            "new_password": "Viewer private replacement password"})
        self.login("viewer", "Viewer private replacement password")
        self.assertEqual(self.request("GET", "/operator/v1/models")[0], 200)
        self.assertEqual(self.request("GET", "/operator/v1/users")[0], 403)
        self.assertEqual(self.request("POST", "/operator/v1/registry", {"action": "set_grant"})[0], 403)
        self.assertEqual(self.request("POST", "/operator/v1/integration/datasets", {})[0], 403)

    def test_http_self_password_change_revokes_other_sessions(self):
        self.ready_admin()
        first = self.cookie, self.csrf
        self.login(password=PASSWORD)
        second = self.cookie, self.csrf
        self.assertEqual(self.request("POST", "/operator/v1/account/password", {
            "current_password": PASSWORD, "new_password": "Another admin private password"})[0], 200)
        for cookie, csrf in (first, second):
            self.cookie, self.csrf = cookie, csrf
            self.assertEqual(self.request("GET", "/operator/v1/session")[0], 401)

    def test_http_legacy_operator_token_remains_distinct_from_temporary_password(self):
        self.assertEqual(self.request("POST", "/operator/v1/login", {"password": DEFAULT_ADMIN_PASSWORD})[0], 401)
        status, headers, data = self.request("POST", "/operator/v1/login", {
            "password": "legacy-operator-credential-0000000000000000"})
        self.assertEqual(status, 200, data)
        self.assertFalse(data["must_change_password"])
        self.cookie, self.csrf = headers["Set-Cookie"].split(";", 1)[0], data["csrf"]
        self.assertEqual(self.request("GET", "/operator/v1/users")[0], 200)

    def test_http_full_length_unicode_password_round_trip(self):
        self.login()
        password = "🔐" * 256
        status, _, data = self.request("POST", "/operator/v1/account/password", {
            "current_password": DEFAULT_ADMIN_PASSWORD, "new_password": password})
        self.assertEqual(status, 200, data)
        self.assertFalse(self.login(password=password)["must_change_password"])
