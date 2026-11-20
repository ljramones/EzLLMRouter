"""Session publication races through the real operator handlers, without sockets."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from email.message import Message
import threading
import time
from unittest.mock import Mock, patch

from ezllmrouter_server.canonical import ContractError
from tests.operator_console.test_user_management import PASSWORD
from tests.operator_console.test_user_management_web import UserHTTPFixture


class OperatorSessionTests(UserHTTPFixture):
    def setUp(self):
        super().setUp()
        self.ready_admin()

    def handler(self):
        handler = self.server.handler.__new__(self.server.handler)
        handler.server = self.server
        handler.headers = Message()
        handler.headers["Cookie"] = self.cookie
        return handler

    @contextmanager
    def held(self, owner, name):
        original = getattr(owner, name)
        entered, release = threading.Event(), threading.Event()

        def wait(*args, **kwargs):
            entered.set()
            if not release.wait(10):
                raise AssertionError("test did not release the held operation")
            return original(*args, **kwargs)

        with patch.object(owner, name, side_effect=wait):
            try:
                yield entered, release
            finally:
                release.set()

    def logout(self, session):
        handler = self.handler()
        handler.path = "/operator/v1/logout"
        handler._send = Mock(return_value="logged out")
        result = handler.post_operator_v1_logout(None, session, {}, None)
        handler._send.assert_called_once()
        self.assertEqual(handler._send.call_args.args[0], 200)
        return result

    def test_held_account_lookup_does_not_block_logout_or_resurrect_session(self):
        handler = self.handler()
        session = handler._session()
        with ThreadPoolExecutor(max_workers=2) as executor:
            with self.held(self.registry, "principal") as (entered, release):
                pending = executor.submit(handler._session)
                try:
                    self.assertTrue(entered.wait(3))
                    logged_out = executor.submit(self.logout, session)
                    self.assertEqual(logged_out.result(timeout=3), "logged out")
                finally:
                    release.set()
                self.assertIsNone(pending.result(timeout=3))
        self.assertNotIn(session[0], self.server.application.sessions)

    def test_expiry_during_account_lookup_cannot_be_refreshed(self):
        handler = self.handler()
        token = handler._session()[0]
        with ThreadPoolExecutor(max_workers=2) as executor:
            with self.held(self.registry, "principal") as (entered, release):
                pending = executor.submit(handler._session)

                def expire():
                    with self.server.application.session_lock:
                        self.server.application.sessions[token]["expires"] = 0

                try:
                    self.assertTrue(entered.wait(3))
                    executor.submit(expire).result(timeout=3)
                finally:
                    release.set()
                self.assertIsNone(pending.result(timeout=3))
        self.assertNotIn(token, self.server.application.sessions)

    def test_replaced_session_does_not_receive_an_old_lookup_result(self):
        handler = self.handler()
        token, item = handler._session()
        replacement = {**item, "csrf": "replacement-csrf"}
        with ThreadPoolExecutor(max_workers=2) as executor:
            with self.held(self.registry, "principal") as (entered, release):
                pending = executor.submit(handler._session)

                def replace():
                    with self.server.application.session_lock:
                        self.server.application.sessions[token] = replacement

                try:
                    self.assertTrue(entered.wait(3))
                    executor.submit(replace).result(timeout=3)
                finally:
                    release.set()
                self.assertIsNone(pending.result(timeout=3))
        self.assertIs(self.server.application.sessions[token], replacement)

    def test_request_receives_a_session_snapshot(self):
        token, item = self.handler()._session()
        item.update(role="ordinary", csrf="caller-mutation")
        current = self.server.application.sessions[token]
        self.assertEqual(current["role"], "registry_admin")
        self.assertNotEqual(current["csrf"], "caller-mutation")

    def test_password_only_console_still_supports_session_and_logout(self):
        self.server.application.registry = None
        self.server.application.accounts = None
        status, headers, body = self.request(
            "POST", "/operator/v1/login", {"password": self.server.application.password}
        )
        self.assertEqual(status, 200)
        self.cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.csrf = body["csrf"]
        self.assertEqual(self.handler()._session()[1]["role"], "registry_admin")
        self.assertEqual(self.request("POST", "/operator/v1/logout", {})[0], 200)
        self.assertIsNone(self.handler()._session())

    def test_database_calls_and_response_writes_never_hold_session_lock(self):
        from contextlib import ExitStack

        application = self.server.application
        self.registry.personal_campaign = object()

        def checked(original):
            def call(*args, **kwargs):
                self.assertFalse(application.session_lock.locked())
                return original(*args, **kwargs)

            return call

        with ExitStack() as stack:
            for owner, name in (
                (self.registry, "principal"),
                (self.users, "context"),
                (self.registry, "issue_local_operator_token"),
                (self.registry, "revoke_local_operator_token"),
                (self.server.handler, "_send"),
            ):
                stack.enter_context(patch.object(owner, name, checked(getattr(owner, name))))
            self.login(password=PASSWORD)
            self.assertIsNotNone(self.handler()._session())
            user = self.users.get("owner.local", "owner.local")
            self.users.reset_password(
                "owner.local",
                "owner.local",
                {"expected_revision": user["revision"], "password": "Reset checks token cleanup"},
            )
            self.assertIsNone(self.handler()._session())

    def test_reset_after_password_check_prevents_login_publication(self):
        user = self.users.get("owner.local", "owner.local")
        existing = set(self.server.application.sessions)
        with ThreadPoolExecutor(max_workers=1) as executor:
            with self.held_secrets() as (entered, release):
                pending = executor.submit(
                    self.request,
                    "POST",
                    "/operator/v1/login",
                    {"username": "admin", "password": PASSWORD},
                )
                try:
                    self.assertTrue(entered.wait(3))
                    self.users.reset_password(
                        "owner.local",
                        "owner.local",
                        {
                            "expected_revision": user["revision"],
                            "password": "Replacement password during login",
                        },
                    )
                finally:
                    release.set()
                status, headers, body = pending.result(timeout=3)
        self.assertEqual(status, 401)
        self.assertEqual(body["error"], "AUTH_FAILED")
        self.assertIsNone(headers["Set-Cookie"])
        self.assertEqual(set(self.server.application.sessions), existing)
        self.assertIsNone(self.handler()._session())

    @contextmanager
    def held_secrets(self):
        # Pause after password verification, before a session or wire token exists.
        from ezllmrouter_server.operator_http import authentication

        with self.held(authentication.secrets, "token_urlsafe") as events:
            yield events

    def test_role_and_disable_reenable_changes_prevent_login_publication(self):
        for change in ("role", "status"):
            with self.subTest(change=change):
                name = "race-" + change
                user = self.create(name, "read_only_operator")
                with ThreadPoolExecutor(max_workers=1) as executor:
                    with self.held_secrets() as (entered, release):
                        pending = executor.submit(
                            self.request,
                            "POST",
                            "/operator/v1/login",
                            {"username": name, "password": PASSWORD},
                        )
                        try:
                            self.assertTrue(entered.wait(3))
                            if change == "role":
                                self.update(user, role="ordinary")
                            else:
                                self.update(self.update(user, status="suspended"), status="active")
                        finally:
                            release.set()
                        status, headers, _ = pending.result(timeout=3)
                self.assertEqual(status, 401)
                self.assertIsNone(headers["Set-Cookie"])

    def test_password_change_wins_while_session_waits_for_database(self):
        handler = self.handler()
        database = self.store.database
        original = database.read
        entered, release = threading.Event(), threading.Event()

        @contextmanager
        def read():
            if not entered.is_set():
                entered.set()
                if not release.wait(10):
                    raise AssertionError("test did not release the database reader")
            with original() as db:
                yield db

        with ThreadPoolExecutor(max_workers=2) as executor:
            with patch.object(database, "read", side_effect=read):
                pending = executor.submit(handler._session)
                try:
                    self.assertTrue(entered.wait(3))
                    changed = executor.submit(
                        self.request,
                        "POST",
                        "/operator/v1/account/password",
                        {
                            "current_password": PASSWORD,
                            "new_password": "Changed during lookup password",
                        },
                    )
                    self.assertEqual(changed.result(timeout=3)[0], 200)
                finally:
                    release.set()
                self.assertIsNone(pending.result(timeout=3))

    def test_current_permissions_and_disabled_account_are_rechecked(self):
        user = self.create("session-reader", "read_only_operator")
        self.login("session-reader", PASSWORD)
        self.assertEqual(self.handler()._session()[1]["role"], "read_only_operator")
        user = self.update(user, role="ordinary")
        self.assertIsNone(self.handler()._session())
        self.login("session-reader", PASSWORD)
        self.assertEqual(self.handler()._session()[1]["role"], "ordinary")
        user = self.update(user, status="suspended")
        self.update(user, status="active")
        self.assertIsNone(self.handler()._session())

    def test_held_wire_token_creation_does_not_block_logout(self):
        session = self.handler()._session()
        self.registry.personal_campaign = object()
        with ThreadPoolExecutor(max_workers=2) as executor:
            with self.held(self.registry, "issue_local_operator_token") as (entered, release):
                pending = executor.submit(
                    self.request,
                    "POST",
                    "/operator/v1/login",
                    {"username": "admin", "password": PASSWORD},
                )
                try:
                    self.assertTrue(entered.wait(3))
                    self.assertEqual(
                        executor.submit(self.logout, session).result(timeout=3), "logged out"
                    )
                finally:
                    release.set()
                self.assertEqual(pending.result(timeout=3)[0], 200)
        self.assertNotIn(session[0], self.server.application.sessions)

    def test_expired_and_invalid_sessions_revoke_their_wire_tokens(self):
        self.registry.personal_campaign = object()
        for expire in (True, False):
            with self.subTest(expire=expire):
                self.login(password=PASSWORD)
                handler = self.handler()
                token, item = handler._session()
                wire = item["wire_token"]
                self.assertEqual(
                    self.registry.credential_principal(wire)["principal_id"], "owner.local"
                )
                if expire:
                    with self.server.application.session_lock:
                        self.server.application.sessions[token]["expires"] = 0
                else:
                    item = self.users.get("owner.local", "owner.local")
                    self.users.reset_password(
                        "owner.local",
                        "owner.local",
                        {
                            "expected_revision": item["revision"],
                            "password": "Reset revokes wire password",
                        },
                    )
                self.assertIsNone(handler._session())
                with self.assertRaises(ContractError):
                    self.registry.credential_principal(wire)

    def test_login_pruning_revokes_expired_wire_tokens(self):
        self.registry.personal_campaign = object()
        self.login(password=PASSWORD)
        token, item = self.handler()._session()
        with self.server.application.session_lock:
            self.server.application.sessions[token]["expires"] = 0
        self.login(password=PASSWORD)
        with self.assertRaises(ContractError):
            self.registry.credential_principal(item["wire_token"])

    def test_session_limit_discards_new_wire_token_and_sends_outside_lock(self):
        application = self.server.application
        self.registry.personal_campaign = object()
        template = self.handler()._session()[1]
        for index in range(63):
            application.sessions["limit." + str(index)] = {
                **template,
                "wire_token": None,
                "expires": time.monotonic() + 1800,
            }
        issued = []
        issue, send = self.registry.issue_local_operator_token, self.server.handler._send

        def issue_token(*args):
            self.assertFalse(application.session_lock.locked())
            value = issue(*args)
            issued.append(value)
            return value

        def respond(handler, *args, **kwargs):
            self.assertFalse(application.session_lock.locked())
            return send(handler, *args, **kwargs)

        with (
            patch.object(self.registry, "issue_local_operator_token", side_effect=issue_token),
            patch.object(self.server.handler, "_send", respond),
        ):
            status, _, _ = self.request(
                "POST", "/operator/v1/login", {"username": "admin", "password": PASSWORD}
            )
        self.assertEqual(status, 429)
        self.assertEqual(len(application.sessions), 64)
        self.assertEqual(len(issued), 1)
        with self.assertRaises(ContractError):
            self.registry.credential_principal(issued[0])
