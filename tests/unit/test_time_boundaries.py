"""Exact before/at/after deadline and expiry contracts, without wall-clock sleeps."""

from datetime import datetime, timedelta, timezone
import io
import math
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import httpcore

from ezllmrouter_client import _deadline as deadline
from ezllmrouter_server import core_policy, http_server, registry_tokens
from ezllmrouter_server.canonical import ContractError
from ezllmrouter_server.gateway import choice_b_wire as wire
from ezllmrouter_server.user_management import LoginThrottle
from tests.operator_console import test_registry_core as core
from tests.operator_console import test_user_management as users
from tests.operator_console.test_user_management_web import UserHTTPFixture


class AbsoluteTimeTests(unittest.TestCase):
    def test_http_input_stops_at_the_absolute_deadline_before_another_raw_read(self):
        for now in (math.nextafter(15, -math.inf), 15, math.nextafter(15, math.inf)):
            raw = io.BytesIO(b"x")
            handler = SimpleNamespace(
                _input_deadline=15,
                connection=SimpleNamespace(settimeout=Mock()),
                _expire_input=Mock(),
            )
            reader = http_server._InputReader(raw, handler)
            try:
                with patch.object(http_server.time, "monotonic", return_value=now):
                    if now < 15:
                        self.assertEqual(reader.readinto(bytearray(1)), 1)
                        self.assertGreater(handler.connection.settimeout.call_args.args[0], 0)
                    else:
                        with self.assertRaises(TimeoutError):
                            reader.readinto(bytearray(1))
                        self.assertEqual(raw.tell(), 0)
                        handler._expire_input.assert_called_once()
                        handler.connection.settimeout.assert_not_called()
            finally:
                reader.close()

    def test_client_total_deadline_is_exclusive_and_contexts_do_not_extend_it(self):
        now = [0.0]
        with patch.object(deadline.time, "monotonic", side_effect=lambda: now[0]):
            with deadline.deadline_scope(2):
                now[0] = math.nextafter(2, -math.inf)
                self.assertGreater(deadline.remaining(), 0)
                now[0] = 2
                with self.assertRaises(httpcore.ReadTimeout):
                    deadline.remaining()
                now[0] = math.nextafter(2, math.inf)
                with self.assertRaises(httpcore.ReadTimeout):
                    deadline.remaining()
            self.assertIsNone(deadline.remaining())

    def test_plan_expiry_and_attempt_timeout_choose_the_earlier_bound(self):
        expiry = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)
        for delta in (-1, 0, 1):

            class Clock(datetime):
                @classmethod
                def now(cls, tz=None, delta=delta):
                    return expiry + timedelta(microseconds=delta)

            with self.subTest(delta_microseconds=delta), patch.object(wire, "datetime", Clock):
                if delta < 0:
                    self.assertAlmostEqual(
                        wire.remaining_seconds(300000, expiry.isoformat()), 0.000001
                    )
                    self.assertAlmostEqual(
                        wire.remaining_seconds(1, (expiry + timedelta(seconds=1)).isoformat()),
                        0.001,
                    )
                else:
                    with self.assertRaises(TimeoutError):
                        wire.remaining_seconds(300000, expiry.isoformat())
        for value in (0, 300001, True, False):
            with self.subTest(timeout=value), self.assertRaises(ValueError):
                wire.remaining_seconds(value, "2030-01-01T00:00:00Z")

    def test_login_backoff_opens_at_its_deadline_without_sleeping(self):
        for failures in range(5, 13):
            now = [0.0]
            throttle = LoginThrottle(clock=lambda now=now: now[0])
            for index in range(failures):
                now[0] = index * 2.0
                ticket = throttle.begin("peer", "account")
                self.assertIsNotNone(ticket)
                throttle.finish(ticket, failed=True)
            opens = now[0] + min(2, 0.05 * 2 ** min(failures - 5, 6))
            now[0] = math.nextafter(opens, -math.inf)
            self.assertIsNone(throttle.begin("peer", "account"))
            now[0] = opens
            with self.subTest(failures=failures):
                ticket = throttle.begin("peer", "account")
                self.assertIsNotNone(ticket)
                if ticket is not None:
                    throttle.finish(ticket)


class TokenExpiryTests(users.UserFixture):
    def test_wire_token_lifetime_ends_at_1800_seconds_and_never_resurrects(self):
        now = [100.0]
        with patch.object(registry_tokens.time, "monotonic", side_effect=lambda: now[0]):
            token = self.registry.issue_local_operator_token("owner.local")
            now[0] = math.nextafter(1900, -math.inf)
            self.assertEqual(
                self.registry.credential_principal(token)["principal_id"], "owner.local"
            )
            for at in (1900, math.nextafter(1900, math.inf), 100):
                now[0] = at
                with self.subTest(time=at), self.assertRaises(ContractError):
                    self.registry.credential_principal(token)
            self.assertFalse(self.registry._operator_tokens)


class TrustedContextExpiryTests(unittest.TestCase):
    setUp = core.RegistryCoordinatorTests.setUp

    def test_identity_context_expiry_is_exclusive_and_timezone_offsets_are_equivalent(self):
        expiry = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)
        for stamp in ("2026-11-22T12:00:00Z", "2026-11-22T07:00:00-05:00"):
            self.coordinator.identity[core.TOKEN] = {
                **self.coordinator.identity[core.TOKEN],
                "expires_at": stamp,
            }
            for delta in (-1, 0, 1):

                class Clock(datetime):
                    @classmethod
                    def now(cls, tz=None, delta=delta):
                        return expiry + timedelta(microseconds=delta)

                with (
                    self.subTest(expiry=stamp, delta=delta),
                    patch.object(core_policy, "datetime", Clock),
                ):
                    if delta < 0:
                        self.assertEqual(
                            self.coordinator.authenticate(core.TOKEN)["principal_id"], "svc.demo"
                        )
                    else:
                        with self.assertRaises(ContractError) as error:
                            self.coordinator.authenticate(core.TOKEN)
                        self.assertEqual(error.exception.status, 401)


class BrowserExpiryTests(UserHTTPFixture):
    def test_session_expires_at_its_deadline_and_a_clock_rollback_cannot_revive_it(self):
        self.ready_admin()
        expiry = max(item["expires"] for item in self.server.application.sessions.values())
        for at, status in (
            (math.nextafter(expiry, -math.inf), 200),
            (expiry, 401),
            (math.nextafter(expiry, math.inf), 401),
            (expiry - 10, 401),
        ):
            with (
                self.subTest(time=at),
                patch(
                    "ezllmrouter_server.operator_http.authentication.time.monotonic",
                    return_value=at,
                ),
            ):
                self.assertEqual(self.request("GET", "/operator/v1/session")[0], status)
