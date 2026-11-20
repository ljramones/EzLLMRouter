"""Login, transport, socket-order and secret-injection regressions without listeners."""

from email.message import Message
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import httpx

from ezllmrouter_server import operator_web
from ezllmrouter_server.gateway import guard
from ezllmrouter_server.observability import EventFormatter
from ezllmrouter_server.operator_http.policy import OperatorPolicy
from ezllmrouter_server.private_files import read_private, write_private
from ezllmrouter_server.user_management import LoginThrottle, UserError, UserManager
from tests.gateway_integration import test_guard as guard_fixtures
from tests.operator_console.test_user_management import (
    DEFAULT_ADMIN_PASSWORD,
    PASSWORD,
    UserFixture,
)
from tests.operator_console.test_user_management_web import MemoryServer, UserHTTPFixture


class ThrottleTests(unittest.TestCase):
    def test_pending_attempts_reserve_the_remaining_failure_budget(self):
        clock = [0]
        throttle = LoginThrottle(clock=lambda: clock[0])
        for _ in range(19):
            throttle.finish(throttle.begin("local", "admin"), failed=True)
            clock[0] += 2
        ticket = throttle.begin("local", "admin")
        self.assertIsNotNone(ticket)
        self.assertIsNone(throttle.begin("local", "admin"))
        other = throttle.begin("other-peer", "admin")
        self.assertIsNotNone(other)
        throttle.finish(other, success=True)
        throttle.finish(ticket, success=True)
        self.assertIsNotNone(throttle.begin("other-peer", "admin"))

    def test_successes_do_not_consume_the_failed_login_budget(self):
        throttle = LoginThrottle()
        for _ in range(100):
            ticket = throttle.begin("local", "admin")
            self.assertIsNotNone(ticket)
            throttle.finish(ticket, success=True)
        self.assertFalse(throttle.attempts)
        self.assertFalse(throttle.pending)

    def test_failure_budget_is_per_peer_and_account(self):
        clock = [0]
        throttle = LoginThrottle(clock=lambda: clock[0])
        for _ in range(20):
            ticket = throttle.begin("first-peer", "alice")
            throttle.finish(ticket, failed=True)
            clock[0] += 2
        self.assertIsNone(throttle.begin("first-peer", "alice"))
        other_peer = throttle.begin("second-peer", "alice")
        self.assertIsNotNone(other_peer)
        throttle.finish(other_peer, success=True)
        other = throttle.begin("first-peer", "bob")
        self.assertIsNotNone(other)
        throttle.finish(other, success=True)

    def test_inflight_work_is_bounded_globally_and_per_identity(self):
        throttle = LoginThrottle()
        first, second = throttle.begin("local", "alice"), throttle.begin("local", "alice")
        self.assertIsNone(throttle.begin("local", "alice"))
        tickets = [first, second, *(throttle.begin("local", str(i)) for i in range(6))]
        self.assertIsNone(throttle.begin("local", "another"))
        for ticket in tickets:
            throttle.finish(ticket)
        self.assertIsNotNone(throttle.begin("local", "another"))

    def test_old_failures_expire_and_success_clears_prior_failures(self):
        clock = [0]
        throttle = LoginThrottle(clock=lambda: clock[0])
        throttle.finish(throttle.begin("local", "alice"), failed=True)
        throttle.finish(throttle.begin("local", "alice"), success=True)
        self.assertFalse(throttle.attempts)
        for _ in range(20):
            throttle.finish(throttle.begin("local", "alice"), failed=True)
            clock[0] += 2
        self.assertIsNone(throttle.begin("local", "alice"))
        clock[0] += 60
        self.assertIsNotNone(throttle.begin("local", "alice"))

    def test_failure_identity_memory_is_bounded_and_contains_no_username(self):
        clock = [0]
        throttle = LoginThrottle(clock=lambda: clock[0])
        for i in range(512):
            throttle.finish(throttle.begin("local", "private-user-" + str(i)), failed=True)
        self.assertEqual(len(throttle.attempts), 512)
        fresh = throttle.begin("local", "new-user")
        self.assertIsNotNone(fresh)
        throttle.finish(fresh, failed=True)
        self.assertEqual(len(throttle.attempts), 512)
        admin = throttle.begin("local", "admin")
        self.assertIsNotNone(admin)
        throttle.finish(admin, success=True)
        self.assertNotIn("private-user", repr(throttle.attempts))
        clock[0] = 60
        self.assertIsNotNone(throttle.begin("local", "new-user"))

    def test_backoff_and_unknown_names_have_independent_bounded_capacity(self):
        now = [0]
        throttle = LoginThrottle(clock=lambda: now[0])
        for index in range(5):
            ticket = throttle.begin("untrusted", "unknown-" + str(index), known=False)
            self.assertIsNotNone(ticket)
            throttle.finish(ticket, failed=True)
        self.assertEqual(len(throttle.unknown_attempts), 1)
        self.assertFalse(throttle.attempts)
        self.assertIsNone(throttle.begin("untrusted", "another-name", known=False))
        admin = throttle.begin("untrusted", "admin")
        self.assertIsNotNone(admin)
        throttle.finish(admin, success=True)
        now[0] = 0.05
        pending = throttle.begin("untrusted", "unknown-again", known=False)
        self.assertIsNotNone(pending)
        self.assertIsNone(throttle.begin("other-peer", "also-unknown", known=False))
        known = throttle.begin("other-peer", "known-user")
        self.assertIsNotNone(known)
        throttle.finish(known, success=True)
        throttle.finish(pending, failed=True)
        now[0] = 0.10
        self.assertIsNone(throttle.begin("untrusted", "unknown-again", known=False))
        now[0] = 0.16
        self.assertIsNotNone(throttle.begin("untrusted", "unknown-again", known=False))


class ExposurePolicyTests(unittest.TestCase):
    def test_tcp_bindings_and_http_authorities_are_loopback_only(self):
        for host in ("0.0.0.0", "192.168.1.4", "example.test"):
            with self.subTest(host=host), self.assertRaises(ValueError):
                OperatorPolicy.build(host, 8080, None, unix_socket=False, public_origin=None)
        with self.assertRaises(ValueError):
            OperatorPolicy.build(
                "127.0.0.1", 8080, {"console.example.test"}, unix_socket=False, public_origin=None
            )
        policy = OperatorPolicy.build(
            "127.0.0.1", 8080, None, unix_socket=False, public_origin=None
        )
        self.assertEqual(policy.origins, {"http://127.0.0.1:8080", "http://localhost:8080"})
        self.assertFalse(policy.secure_cookies)

    def test_https_origins_require_the_explicit_unix_proxy_boundary(self):
        for origin in (
            "http://console.example.test",
            "https://console.example.test/path",
            "https://user:password@console.example.test",
            "https://console.example.test#part",
        ):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                OperatorPolicy.build(
                    "127.0.0.1", 8080, None, unix_socket=True, public_origin=origin
                )
        with self.assertRaises(ValueError):
            OperatorPolicy.build(
                "127.0.0.1",
                8080,
                None,
                unix_socket=False,
                public_origin="https://console.example.test",
            )
        policy = OperatorPolicy.build(
            "127.0.0.1", 8080, None, unix_socket=True, public_origin="https://console.example.test"
        )
        self.assertEqual(policy.hosts, {"console.example.test"})
        self.assertEqual(policy.origins, {"https://console.example.test"})
        self.assertTrue(policy.secure_cookies)

    def test_unix_permissions_are_set_before_listening(self):
        stream, events = Mock(), []
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "operator.sock")
            stream.getsockname.return_value = path
            stream.bind.side_effect = lambda _path: events.append("bind")
            stream.listen.side_effect = lambda _size: events.append("listen")
            with (
                patch.object(operator_web.socket, "socket", return_value=stream),
                patch.object(
                    operator_web.os, "chmod", side_effect=lambda *_args: events.append("chmod")
                ),
            ):
                server = operator_web.UnixOperatorServer(path, operator_web.OperatorHandler, 8080)
                server.server_close()
        self.assertEqual(events, ["bind", "chmod", "listen"])

    def test_unix_socket_rejects_a_directory_writable_by_other_users(self):
        stream = Mock()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unsafe"
            path.mkdir(mode=0o777)
            path.chmod(0o777)
            with patch.object(operator_web.socket, "socket", return_value=stream):
                with self.assertRaises(ValueError):
                    operator_web.UnixOperatorServer(
                        str(path / "operator.sock"), operator_web.OperatorHandler, 8080
                    )
        stream.bind.assert_not_called()
        stream.listen.assert_not_called()
        stream.close.assert_called_once()


class LoginHTTPTests(UserHTTPFixture):
    def test_expected_credential_rejections_do_not_log_errors(self):
        with self.assertNoLogs("ezllmrouter", level="ERROR"):
            status, _, body = self.request(
                "POST", "/operator/v1/login", {"password": "wrong-credential"}
            )
        self.assertEqual((status, body), (401, {"error": "AUTH_FAILED"}))
        self.assertFalse(self.server.application.login_throttle.pending)

    def test_unexpected_authentication_faults_remain_visible_without_secret_messages(self):
        secret = "SYNTHETIC_PRIVATE_EXCEPTION_CONTENT"
        with (
            patch.object(self.registry, "credential_principal", side_effect=RuntimeError(secret)),
            self.assertLogs("ezllmrouter", level="ERROR") as captured,
        ):
            status, _, body = self.request(
                "POST", "/operator/v1/login", {"password": "wrong-credential"}
            )
        self.assertEqual((status, body), (503, {"error": "AUTH_UNAVAILABLE"}))
        self.assertEqual(captured.records[0].event, "operator_http.authentication.unavailable")
        self.assertNotIn(secret, EventFormatter().format(captured.records[0]))
        self.assertFalse(self.server.application.login_throttle.attempts)

    def test_local_failed_account_does_not_lock_out_another_account(self):
        self.server.application.login_throttle = LoginThrottle(clock=lambda: 0)
        with patch.object(self.users, "authenticate", side_effect=UserError("AUTH_FAILED", 401)):
            for _ in range(5):
                self.assertEqual(
                    self.request(
                        "POST", "/operator/v1/login", {"username": "blocked", "password": "wrong"}
                    )[0],
                    401,
                )
            self.assertEqual(
                self.request(
                    "POST", "/operator/v1/login", {"username": " BLOCKED ", "password": "wrong"}
                )[0],
                429,
            )
        self.login()

    def test_repeated_successes_do_not_trigger_the_failure_limit(self):
        account = self.users.authenticate("admin", DEFAULT_ADMIN_PASSWORD)
        with patch.object(self.users, "authenticate", return_value=account):
            for _ in range(25):
                self.login()
        self.assertFalse(self.server.application.login_throttle.attempts)

    def test_invalid_login_values_are_rejected_without_hashing_or_error_logs(self):
        with (
            patch.object(self.users, "authenticate") as authenticate,
            self.assertNoLogs("ezllmrouter", level="ERROR"),
        ):
            for body in (
                {"username": [], "password": "valid-string"},
                {"username": "admin", "password": "\ud800"},
            ):
                self.assertEqual(self.request("POST", "/operator/v1/login", body)[0], 400)
        authenticate.assert_not_called()
        self.assertFalse(self.server.application.login_throttle.pending)

    def test_https_login_password_change_and_logout_all_use_secure_cookies(self):
        origin = "https://127.0.0.1:48761"
        old = self.server
        with patch.object(
            operator_web,
            "UnixOperatorServer",
            side_effect=lambda address, handler, port: MemoryServer(address, handler),
        ):
            self.server = operator_web.serve(
                "127.0.0.1",
                48761,
                projection=old.application.projection,
                runner=None,
                password="p" * 40,
                fixture={},
                build={},
                web_root=old.application.root,
                worker_probe=lambda: {},
                sender_status=lambda: {},
                registry=self.registry,
                socket_path=str(Path(self.tmp.name) / "operator.sock"),
                public_origin=origin,
            )
        self.addCleanup(self.server.server_close)
        self.assertEqual(self.request("POST", "/operator/v1/login", {"password": "p" * 40})[0], 403)

        def login(password):
            status, headers, body = self.request(
                "POST",
                "/operator/v1/login",
                {"username": "admin", "password": password},
                origin=origin,
            )
            self.assertEqual(status, 200)
            self.assertIn("; Secure", headers["Set-Cookie"])
            self.cookie = headers["Set-Cookie"].split(";", 1)[0]
            self.csrf = body["csrf"]

        login(DEFAULT_ADMIN_PASSWORD)
        status, headers, _ = self.request(
            "POST",
            "/operator/v1/account/password",
            {"current_password": DEFAULT_ADMIN_PASSWORD, "new_password": PASSWORD},
            origin=origin,
        )
        self.assertEqual(status, 200)
        self.assertIn("Max-Age=0; Secure", headers["Set-Cookie"])
        login(PASSWORD)
        status, headers, _ = self.request("POST", "/operator/v1/logout", {}, origin=origin)
        self.assertEqual(status, 200)
        self.assertIn("Max-Age=0; Secure", headers["Set-Cookie"])

    def test_forwarded_protocol_does_not_grant_an_https_origin(self):
        handler = self.server.handler.__new__(self.server.handler)
        handler.server = self.server
        handler.headers = Message()
        handler.headers["Host"] = "127.0.0.1:48761"
        handler.headers["Origin"] = "https://127.0.0.1:48761"
        handler.headers["X-Forwarded-Proto"] = "https"
        self.assertFalse(handler._origin_ok(mutation=True))


class SecretInjectionTests(UserFixture):
    def test_bootstrap_file_preserves_unicode_and_password_whitespace(self):
        self.store.db.execute("DELETE FROM console_users")
        path = Path(self.tmp.name) / "bootstrap/admin.password"
        path.parent.mkdir(mode=0o700)
        password = "  private café passphrase \t"
        write_private(path, (password + "\n").encode())
        users = UserManager(self.registry, bootstrap_password_file=path)
        self.assertTrue(users.authenticate("admin", password)["must_change_password"])
        with self.assertRaises(UserError):
            users.authenticate("admin", password.strip())
        self.assertEqual(read_private(path), (password + "\n").encode())

    def test_bootstrap_ignores_environment_passwords(self):
        self.store.db.execute("DELETE FROM console_users")
        path = Path(self.tmp.name) / "bootstrap/admin.password"
        with patch.dict(os.environ, {"EZLLMROUTER_ADMIN_PASSWORD": "SYNTHETIC_ENVIRONMENT_SECRET"}):
            users = UserManager(self.registry, bootstrap_password_file=path)
        generated = read_private(path).decode().strip()
        self.assertNotEqual(generated, "SYNTHETIC_ENVIRONMENT_SECRET")
        self.assertTrue(users.authenticate("admin", generated)["must_change_password"])

    def test_guard_uses_only_the_invocation_credential(self):
        invocation = guard_fixtures.invocation()
        body = json.dumps(
            guard.provider_expectation(invocation.projection), separators=(",", ":")
        ).encode()
        request = httpx.Request(
            "POST",
            guard.PROVIDER_URL,
            content=body,
            extensions={"timeout": {"read": 1.0, "connect": 1.0, "write": 1.0, "pool": 1.0}},
            headers={
                "content-type": "application/json",
                "authorization": "Bearer " + invocation.provider_key,
                "x-ezllmrouter-attempt": invocation.attempt_id,
            },
        )
        with patch.dict(os.environ, {"EZLLMROUTER_DEV04_PROVIDER_KEY": "poisoned-environment"}):
            guard.check_request(request, invocation, body)
        invocation.provider_key = None
        with (
            patch.dict(os.environ, {"EZLLMROUTER_DEV04_PROVIDER_KEY": "sk-" + "x" * 40}),
            self.assertRaises(guard.GuardRejected),
        ):
            guard.check_request(request, invocation, body)
