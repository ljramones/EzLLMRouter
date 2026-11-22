"""Production-sized quota boundaries with explicit acceptance, refusal and recovery."""

from contextlib import ExitStack
import json
from pathlib import Path
import queue
import socketserver
import sqlite3
import struct
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ezllmrouter_server import diagnostic_journal, registry_tokens
from ezllmrouter_server.connection_resources import BoundedThreadingMixIn
from ezllmrouter_server.database import Query
from ezllmrouter_server.execution_resources import BoundedExecutor
from ezllmrouter_server.gateway import choice_b_wire as wire, guard
from ezllmrouter_server.operator_http.authentication import AuthenticationRoutes
from ezllmrouter_server.user_management import LoginThrottle, validate_password, UserError
from tests.operator_console import test_user_management as users
from tests.unit.test_generated_parsers import FragmentedInput


class LimitContractsTests(unittest.TestCase):
    def test_execution_and_check_queues_accept_the_limit_refuse_one_more_and_recover(self):
        for workers, capacity in ((4, 64), (2, 64), (2, 32)):
            with self.subTest(workers=workers, capacity=capacity):
                release = threading.Event()
                pool = BoundedExecutor(
                    max_workers=workers, max_pending=capacity, thread_name_prefix="limit-contract"
                )
                try:
                    futures = [
                        pool.submit(lambda i=i, release=release: (release.wait(3), i)[1])
                        for i in range(capacity)
                    ]
                    with self.assertRaises(RuntimeError):
                        pool.submit(lambda: self.fail("refused work executed"))
                    release.set()
                    self.assertEqual(
                        [future.result(timeout=3) for future in futures], list(range(capacity))
                    )
                    self.assertEqual(
                        pool.submit(lambda: "recovered").result(timeout=3), "recovered"
                    )
                finally:
                    release.set()
                    pool.shutdown(wait=True)

    def test_default_connection_limit_rejects_the_33rd_handler_without_starting_it(self):
        entered, release = threading.Barrier(33), threading.Event()
        closed, accepted = [], []

        def handler(request, _address, _server):
            accepted.append(request)
            entered.wait(timeout=3)
            release.wait(3)

        class Request:
            def shutdown(self, _how):
                pass

            def close(self):
                pass

        class Server(BoundedThreadingMixIn, socketserver.BaseServer):
            def shutdown_request(self, request):
                closed.append(request)

        server = Server(("fixture", 0), handler)
        try:
            for _ in range(32):
                server.process_request(Request(), ("fixture", 0))
            entered.wait(timeout=3)
            extra = Request()
            server.process_request(extra, ("fixture", 0))
            self.assertEqual(len(accepted), 32)
            self.assertEqual(closed, [extra])
        finally:
            release.set()
            server.server_close()
        self.assertEqual(len(closed), 33)

    def test_login_global_and_per_identity_pending_limits_do_not_leak_slots(self):
        throttle = LoginThrottle(clock=lambda: 0)
        first, second = throttle.begin("peer", "same"), throttle.begin("peer", "same")
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertIsNone(throttle.begin("peer", "same"))
        tickets = [first, second] + [throttle.begin("peer", f"other-{i}") for i in range(6)]
        self.assertTrue(all(ticket is not None for ticket in tickets))
        self.assertIsNone(throttle.begin("peer", "ninth"))
        for ticket in tickets:
            throttle.finish(ticket)
        self.assertFalse(throttle.pending)
        ticket = throttle.begin("peer", "unknown", known=False)
        self.assertIsNotNone(ticket)
        self.assertIsNone(throttle.begin("other-peer", "unknown", known=False))
        throttle.finish(ticket)
        self.assertIsNotNone(throttle.begin("other-peer", "unknown", known=False))

    def test_failed_login_windows_allow_20_known_or_10_unknown_then_expire_exactly(self):
        for known, limit in ((True, 20), (False, 10)):
            now = [0.0]
            throttle = LoginThrottle(clock=lambda now=now: now[0])
            for index in range(limit):
                now[0] = index * 2
                ticket = throttle.begin("peer", "account", known=known)
                self.assertIsNotNone(ticket)
                throttle.finish(ticket, failed=True)
            now[0] = 59.999
            self.assertIsNone(throttle.begin("peer", "account", known=known))
            now[0] = 60
            ticket = throttle.begin("peer", "account", known=known)
            self.assertIsNotNone(ticket)
            throttle.finish(ticket, success=True)
            self.assertFalse(throttle.attempts if known else throttle.unknown_attempts)

    def test_throttle_bucket_limits_evict_inactive_entries_and_store_no_account_names(self):
        for known, limit in ((True, 512), (False, 64)):
            throttle = LoginThrottle(clock=lambda: 0)
            for index in range(limit):
                ticket = throttle.begin("peer-" + str(index), "private-account-canary", known=known)
                self.assertIsNotNone(ticket)
                throttle.finish(ticket, failed=True)
            bucket = throttle.attempts if known else throttle.unknown_attempts
            original = set(bucket)
            ticket = throttle.begin("new-peer", "private-account-canary", known=known)
            self.assertIsNotNone(ticket)
            throttle.finish(ticket, failed=True)
            self.assertEqual(len(bucket), limit)
            self.assertEqual(len(original & bucket.keys()), limit - 1)
            self.assertTrue(all(len(key) == 64 for key in bucket))
            self.assertNotIn("private-account-canary", str(bucket))

    def test_session_caps_evict_only_as_documented_and_reserve_admin_capacity(self):
        def item(principal, role="ordinary", expires=100):
            return {"principal_id": principal, "role": role, "expires": expires}

        sessions = {str(i): item("same", expires=i) for i in range(4)}
        handler = SimpleNamespace(application=SimpleNamespace(sessions=sessions))
        discarded = []
        self.assertTrue(AuthenticationRoutes._make_session_room(handler, item("same"), discarded))
        sessions["new"] = item("same")
        self.assertEqual(len(sessions), 4)
        self.assertEqual(discarded[0]["expires"], 0)
        sessions.clear()
        sessions.update({str(i): item(str(i), expires=i) for i in range(56)})
        self.assertFalse(
            AuthenticationRoutes._make_session_room(handler, item("ordinary-extra"), [])
        )
        sessions.update(
            {"admin-" + str(i): item("admin-" + str(i), "registry_admin") for i in range(8)}
        )
        discarded = []
        self.assertTrue(
            AuthenticationRoutes._make_session_room(
                handler, item("admin-extra", "registry_admin"), discarded
            )
        )
        sessions["admin-extra"] = item("admin-extra", "registry_admin")
        self.assertEqual(len(sessions), 64)
        self.assertEqual(discarded[0]["principal_id"], "0")
        sessions.clear()
        sessions.update({str(i): item(str(i), "registry_admin") for i in range(64)})
        self.assertFalse(
            AuthenticationRoutes._make_session_room(
                handler, item("admin-extra", "registry_admin"), []
            )
        )

    def test_ipc_exact_byte_and_depth_limits_are_accepted_and_one_more_is_refused(self):
        base = len(json.dumps({"x": ""}, separators=(",", ":")).encode())
        raw = json.dumps({"x": "x" * (wire.LIMIT - base)}, separators=(",", ":")).encode()
        self.assertEqual(len(raw), 262144)
        self.assertEqual(
            len(wire.receive(FragmentedInput(struct.pack("!I", len(raw)) + raw, 4096))["x"]),
            wire.LIMIT - base,
        )
        for length in (0, wire.LIMIT + 1):
            source = FragmentedInput(struct.pack("!I", length), 4)
            with self.assertRaises(ValueError):
                wire.receive(source)
            self.assertEqual(source.requested, [4])
        for depth in (64, 65):
            body = b'{"x":' + b"[" * (depth - 1) + b"0" + b"]" * (depth - 1) + b"}"
            stream = FragmentedInput(struct.pack("!I", len(body)) + body, 8)
            if depth == 64:
                self.assertIsInstance(wire.receive(stream), dict)
            else:
                with self.assertRaises(ValueError):
                    wire.receive(stream)

    def test_diagnostic_queue_drops_only_the_1025th_row_without_blocking(self):
        pending = queue.Queue(maxsize=1024)
        counts = {"written": 0, "dropped": 0, "write_errors": 0}
        with (
            patch.object(guard, "_EVENT_QUEUE", pending),
            patch.object(guard, "_EVENT_WRITER", object()),
            patch.object(guard, "_EVENT_COUNTS", counts),
        ):
            for index in range(1024):
                guard.enqueue_event("synthetic.jsonl", {"index": index})
            self.assertEqual(guard.diagnostic_status()["queued"], 1024)
            self.assertEqual(counts["dropped"], 0)
            guard.enqueue_event("synthetic.jsonl", {"index": 1024})
            self.assertEqual((pending.qsize(), counts["dropped"]), (1024, 1))

    def test_diagnostic_row_and_file_limits_preserve_exact_boundaries_and_two_backups(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            overhead = len(json.dumps({"x": ""}, separators=(",", ":"))) + 1
            diagnostic_journal.append_event(path, {"x": "x" * (65536 - overhead)})
            self.assertEqual(path.stat().st_size, 65536)
            before = path.read_bytes()
            with self.assertRaises(ValueError):
                diagnostic_journal.append_event(path, {"x": "x" * (65537 - overhead)})
            self.assertEqual(path.read_bytes(), before)
            path.write_bytes(b"x" * (4194304 - 3))
            diagnostic_journal.append_event(path, {})
            self.assertEqual(path.stat().st_size, 4194304)
            self.assertFalse(Path(str(path) + ".1").exists())
            for _ in range(3):
                diagnostic_journal.append_event(path, {})
                path.write_bytes(b"x" * 4194304)
            self.assertEqual(len(list(Path(directory).iterdir())), 3)
            self.assertTrue(Path(str(path) + ".2").exists())

    def test_password_length_boundaries_reject_before_hashing(self):
        for length in (11, 12, 256, 257):
            with self.subTest(length=length):
                if 12 <= length <= 256:
                    self.assertEqual(validate_password("p" * length), "p" * length)
                else:
                    with self.assertRaises(UserError):
                        validate_password("p" * length)


class StoredLimitContractsTests(users.UserFixture):
    def test_report_sql_budget_opens_before_ten_seconds_and_interrupts_at_the_deadline(self):
        for elapsed in (9.999999, 10, 10.000001):
            with (
                self.subTest(elapsed=elapsed),
                patch("ezllmrouter_server.store.time.monotonic", return_value=100) as clock,
            ):
                with self.store.database.snapshot() as snapshot:
                    clock.return_value = 100 + elapsed
                    query = "WITH RECURSIVE n(x) AS (VALUES(0) UNION ALL SELECT x+1 FROM n WHERE x<1000) SELECT sum(x) FROM n"
                    if elapsed < 10:
                        self.assertEqual(snapshot.execute(Query(query)).fetchone()[0], 500500)
                    else:
                        with self.assertRaises(sqlite3.OperationalError):
                            snapshot.execute(Query(query))

    def test_operator_token_capacity_keeps_live_credentials_usable(self):
        with patch.object(registry_tokens.time, "monotonic", return_value=100):
            self.registry._operator_tokens.update(
                {"fixture-" + str(i): ("owner.local", 1900) for i in range(4095)}
            )
            token = self.registry.issue_local_operator_token("owner.local")
            self.assertEqual(len(self.registry._operator_tokens), 4096)
            with self.assertRaises(RuntimeError):
                self.registry.issue_local_operator_token("owner.local")
            self.assertEqual(len(self.registry._operator_tokens), 4096)
            self.assertEqual(
                self.registry.credential_principal(token)["principal_id"], "owner.local"
            )

    def test_four_independent_report_readers_refuse_a_fifth_and_release_capacity(self):
        with ExitStack() as stack:
            for _ in range(4):
                stack.enter_context(self.store.database.snapshot())
            with self.assertRaises(RuntimeError):
                with self.store.database.snapshot():
                    self.fail("fifth reporting snapshot was admitted")
            self.assertEqual(len(self.store._readers), 4)
        with self.store.database.snapshot():
            self.assertEqual(len(self.store._readers), 1)
