"""Independent route expectations through the real handlers and disposable database."""

from copy import deepcopy
from email.parser import BytesParser
import io
import json
import time
from unittest.mock import patch

from ezllmrouter_server.operator_http.routing import ROUTES
from ezllmrouter_server.personal_campaign import PersonalCampaign
from tests.operator_console.test_user_management import PASSWORD, ROOT
from tests.operator_console.test_user_management_web import UserHTTPFixture

POLICY = json.loads((ROOT / "tests/fixtures/operator_authorization.json").read_text())


def policy_routes():
    return [
        ("GET", path, path, 200, 200, 200, 200, False) for path in POLICY["public_assets"]
    ] + POLICY["routes"]


class AuthorizationMatrixTests(UserHTTPFixture):
    def setUp(self):
        super().setUp()
        application = self.server.application
        application.integration_only = False
        application.successor_store = self.store
        application.fixture = json.loads(
            (ROOT / "tools/gateway/evidence/dev05_fixture.json").read_text()
        )
        self.registry.personal_campaign = PersonalCampaign(self.store, self.registry)
        self.ready_admin()
        self.admin = (self.cookie, self.csrf)
        user = self.create()
        self.users.change_password(
            user["principal_id"],
            {"current_password": PASSWORD, "new_password": "Matrix user replacement password"},
        )
        self.login("alice", "Matrix user replacement password")
        self.ordinary = (self.cookie, self.csrf)
        reader = self.create("matrix.reader", role="read_only_operator")
        self.users.change_password(
            reader["principal_id"],
            {"current_password": PASSWORD, "new_password": "Matrix reader replacement password"},
        )
        self.login("matrix.reader", "Matrix reader replacement password")
        self.readonly = (self.cookie, self.csrf)
        self.create("matrix.pending", role="registry_admin")
        pending = self.login("matrix.pending", PASSWORD)
        self.assertTrue(pending["must_change_password"])
        self.password_change = (self.cookie, self.csrf)

    def exchange(self, method, path, *, host=None, origin=None, csrf=True, body=None):
        # Exercise actual framing/headers, without mocking authentication or dispatch.
        handler = self.server.handler.__new__(self.server.handler)
        handler.server = self.server
        handler.path, handler.command = path, method
        handler.request_version = "HTTP/1.1"
        handler.requestline = method + " " + path + " HTTP/1.1"
        handler.client_address = ("127.0.0.1", 12345)
        from email.message import Message

        handler.headers = Message()
        handler.headers["Host"] = host or "127.0.0.1:48761"
        handler.headers["Origin"] = origin or "http://127.0.0.1:48761"
        if self.cookie:
            handler.headers["Cookie"] = self.cookie
        if csrf and self.csrf:
            handler.headers["X-EzLLMRouter-CSRF"] = self.csrf
        raw = json.dumps(body if body is not None else {}).encode() if method != "GET" else b""
        if raw:
            handler.headers["Content-Type"] = "application/json"
            handler.headers["Content-Length"] = str(len(raw))
        handler.rfile, handler.wfile = io.BytesIO(raw), io.BytesIO()
        operation = getattr(handler, "do_" + method, None)
        if operation is None:
            handler.send_error(501, "Unsupported method")
        else:
            operation()
        head, body = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
        headers = BytesParser().parsebytes(head.split(b"\r\n", 1)[1])
        return int(head.split(b" ")[1]), headers, body

    def test_every_registered_route_has_an_independent_policy_row(self):
        expected = [(method, path) for method, path, *_ in policy_routes()]
        actual = [(route.method, route.path + ("*" if route.family else "")) for route in ROUTES]
        self.assertEqual(len(expected), len(set(expected)), "duplicate policy row")
        self.assertCountEqual(expected, actual, "new routes need an explicit authorization policy")

    def test_every_route_rejects_bad_browser_authority_before_any_body_or_send(self):
        for method, registered, path, admin, *_ in policy_routes():
            public = registered in POLICY["public_assets"]
            login = path == "/operator/v1/login"
            for scenario in (
                "anonymous",
                "expired",
                "wrong_host",
                "wrong_origin",
                "missing_csrf",
                "wrong_csrf",
            ):
                with self.subTest(route=registered, method=method, scenario=scenario):
                    self.cookie, self.csrf = self.admin
                    sessions = deepcopy(self.server.application.sessions)
                    try:
                        options = {}
                        if scenario == "anonymous":
                            self.cookie = None
                        elif scenario == "expired":
                            for session in self.server.application.sessions.values():
                                session["expires"] = time.monotonic() - 1
                        elif scenario == "wrong_host":
                            options["host"] = "untrusted.test"
                        elif scenario == "wrong_origin":
                            options["origin"] = "https://untrusted.test"
                        elif scenario == "missing_csrf":
                            options["csrf"] = False
                        else:
                            self.csrf = "wrong-token"
                        if scenario in ("wrong_host", "wrong_origin"):
                            expected = 403
                        elif scenario in ("anonymous", "expired"):
                            expected = 200 if public else 400 if login else 401
                        elif method != "GET" and not login:
                            expected = 403
                        else:
                            # GET and login use the normal policy result when CSRF is absent/wrong.
                            expected = admin
                        status, _, _ = self.exchange(method, path, **options)
                        self.assertEqual(status, expected)
                    finally:
                        self.server.application.sessions.clear()
                        self.server.application.sessions.update(sessions)

    def test_admin_and_ordinary_route_results_match_reviewed_expectations(self):
        # Keep the historical test identity; this now covers all four session
        # states and both console modes, with expectations from the policy file.
        for integration_only in (False, True):
            self.server.application.integration_only = integration_only
            for (
                method,
                registered,
                path,
                admin,
                ordinary,
                readonly,
                pending,
                hidden,
            ) in policy_routes():
                identities = (
                    ("admin", self.admin, admin),
                    ("ordinary", self.ordinary, ordinary),
                    ("readonly", self.readonly, readonly),
                    ("password_change", self.password_change, pending),
                )
                for role, identity, expected in identities:
                    with self.subTest(
                        route=registered,
                        method=method,
                        role=role,
                        integration_only=integration_only,
                    ):
                        self.cookie, self.csrf = identity
                        if integration_only and hidden and role != "password_change":
                            expected = 404
                        if integration_only:
                            expected = (
                                POLICY["integration_status_overrides"]
                                .get(method + " " + registered, {})
                                .get(role, expected)
                            )
                        sessions = deepcopy(self.server.application.sessions)
                        try:
                            status, _, _ = self.exchange(method, path)
                            self.assertEqual(status, expected)
                        finally:
                            self.server.application.sessions.clear()
                            self.server.application.sessions.update(sessions)

    def test_valid_mutation_bodies_are_denied_without_changes_for_nonwriters(self):
        before = self.registry.version()
        for integration_only in (False, True):
            self.server.application.integration_only = integration_only
            for (
                method,
                registered,
                path,
                _admin,
                _ordinary,
                _readonly,
                _pending,
                hidden,
            ) in policy_routes():
                if method == "GET" or path in (
                    "/operator/v1/login",
                    "/operator/v1/logout",
                    "/operator/v1/account/password",
                ):
                    continue
                body = POLICY["valid_mutations"][method + " " + registered]["body"]
                for role, identity in (
                    ("readonly", self.readonly),
                    ("ordinary", self.ordinary),
                    ("password_change", self.password_change),
                ):
                    with self.subTest(
                        role=role, route=registered, integration_only=integration_only
                    ):
                        self.cookie, self.csrf = identity
                        # A valid set_grant is the one operation retained by the
                        # accounting console; the empty-body row remains hidden.
                        masked = hidden and path != "/operator/v1/registry"
                        expected = (
                            404
                            if integration_only and masked and role != "password_change"
                            else 403
                        )
                        self.assertEqual(self.exchange(method, path, body=body)[0], expected)
        self.assertEqual(self.registry.version(), before)

    def test_valid_administrator_user_and_connector_bodies_reach_real_writes(self):
        self.cookie, self.csrf = self.admin
        for path in ("/operator/v1/users", "/operator/v1/local-connectors"):
            body = POLICY["valid_mutations"]["POST " + path]["body"]
            status, _, _ = self.exchange("POST", path, body=body)
            self.assertEqual(status, 201)

    def test_valid_login_logout_and_own_password_change_work_for_every_role(self):
        credentials = [
            ("admin", PASSWORD),
            ("alice", "Matrix user replacement password"),
            ("matrix.reader", "Matrix reader replacement password"),
            ("matrix.pending", PASSWORD),
        ]
        for integration_only in (False, True):
            self.server.application.integration_only = integration_only
            changed = f"Synthetic changed matrix password! {integration_only}"
            for index, (username, password) in enumerate(credentials):
                with self.subTest(username=username, integration_only=integration_only):
                    status, headers, raw = self.exchange(
                        "POST",
                        "/operator/v1/login",
                        body={"username": username, "password": password},
                    )
                    self.assertEqual(status, 200)
                    self.cookie = headers["Set-Cookie"].split(";", 1)[0]
                    self.csrf = json.loads(raw)["csrf"]
                    self.assertEqual(self.exchange("POST", "/operator/v1/logout", body={})[0], 200)
                    self.login(username, password)
                    status, _, _ = self.exchange(
                        "POST",
                        "/operator/v1/account/password",
                        body={"current_password": password, "new_password": changed},
                    )
                    self.assertEqual(status, 200)
                    credentials[index] = (username, changed)

    def test_wrong_methods_cannot_dispatch_routes_or_mutate_authority(self):
        self.cookie, self.csrf = self.admin
        before = self.registry.version()
        rows = policy_routes()
        for _, registered, sample, *_ in rows:
            path = sample.split("?", 1)[0]
            allowed = {
                method
                for method, route, *_ in rows
                if (path.startswith(route[:-1]) if route.endswith("*") else route == path)
            }
            for method in {"GET", "POST", "DELETE", "PUT", "PATCH", "HEAD", "OPTIONS"} - allowed:
                with self.subTest(route=registered, method=method):
                    expected = 501 if method in {"PUT", "PATCH", "HEAD", "OPTIONS"} else 404
                    self.assertEqual(self.exchange(method, path)[0], expected)
        self.assertEqual(self.registry.version(), before)

    def test_other_users_resources_remain_hidden_and_writes_do_not_mutate(self):
        self.cookie, self.csrf = self.ordinary
        before = self.registry.version()
        for path in (
            "/operator/v1/principals/owner.local",
            "/operator/v1/activity?principal_id=owner.local",
            "/operator/v1/usage?principal_id=owner.local",
        ):
            self.assertEqual(self.exchange("GET", path)[0], 404)
        for method, path in (
            ("POST", "/operator/v1/users/owner.local"),
            ("DELETE", "/operator/v1/users/owner.local"),
            ("POST", "/operator/v1/provider-credential"),
            ("POST", "/operator/v1/provision"),
        ):
            self.assertEqual(self.exchange(method, path)[0], 403)
        self.assertEqual(self.registry.version(), before)

    def test_header_rejections_never_read_the_mutation_body(self):
        self.cookie, self.csrf = self.admin
        with patch.object(
            self.server.handler,
            "_body",
            side_effect=AssertionError("read before browser authority"),
        ):
            for method, _, path, *_ in policy_routes():
                if method != "GET" and path != "/operator/v1/login":
                    self.assertEqual(self.exchange(method, path, csrf=False)[0], 403)
