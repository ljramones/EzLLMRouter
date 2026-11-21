"""Prove lock auditing fails hostile scope and permits the documented hash limiter."""

from contextlib import ExitStack
import hashlib
import io
import os
import socket
import threading
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from contextlib import redirect_stderr

from tools.lock_audit import LockAuditor, auditing
from tests.operator_console.test_user_management import UserFixture, PASSWORD


class LockAuditInstrumentTests(unittest.TestCase):
    def test_module_runner_activates_and_restores_the_requested_instrument(self):
        from tools.check import run_module
        from ezllmrouter_server.store import SQLiteStore
        import time

        class Case(unittest.TestCase):
            def test_shared_gate(self):
                store = SQLiteStore(":memory:")
                try:
                    with store._lock, self.assertRaisesRegex(AssertionError, "sleep"):
                        time.sleep(0)
                finally:
                    store.close()

        suite = unittest.TestSuite([Case("test_shared_gate")])
        with (
            patch.dict(os.environ, {"EZLLMROUTER_LOCK_AUDIT": "1", "EZLLMROUTER_TEST_HEALTH": ""}),
            patch("tools.lock_audit.auditing", wraps=auditing) as activated,
            patch.object(unittest.defaultTestLoader, "loadTestsFromName", return_value=suite),
            redirect_stderr(io.StringIO()),
        ):
            self.assertFalse(run_module("synthetic", loopback=False))
            self.assertEqual(activated.call_count, 1)

    def test_loop_wakeup_is_nonblocking_and_does_not_allow_arbitrary_socket_sends(self):
        from ezllmrouter_server.runtime_resources import LoopThread
        from ezllmrouter_server.gateway.owned_sender_transport import LocalSendAuthority

        async def result():
            return 7

        with auditing():
            authority = LocalSendAuthority()
            runtime = LoopThread("audited-synthetic-loop")
            try:
                with authority.gate:
                    future = runtime.submit(result())
                    left, right = socket.socketpair()
                    with left, right:
                        left.setblocking(False)
                        with self.assertRaisesRegex(AssertionError, "send"):
                            left.send(b"forbidden")
                self.assertEqual(future.result(timeout=2), 7)
            finally:
                runtime.close()

    def test_stress_failure_stops_without_a_passing_retry_and_keeps_its_record(self):
        from tools.concurrency_stress import run

        called = []

        def failed(command, **_kwargs):
            called.append(command)
            return SimpleNamespace(returncode=1)

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.assertFalse(run(5, 17, directory, offline_only=True, invoke=failed))
            summary = json.loads((directory / "summary.json").read_text())
            self.assertFalse(summary["passed"])
            self.assertEqual(len(called), 1)
            self.assertEqual(summary["runs"][0]["round"], 0)
            self.assertFalse(summary["runs"][0]["passed"])

            def timed_out(*_args, **_kwargs):
                raise subprocess.TimeoutExpired("synthetic", 90)

            with self.assertRaises(subprocess.TimeoutExpired):
                run(1, 17, directory, invoke=timed_out)
            self.assertFalse(json.loads((directory / "summary.json").read_text())["passed"])

    def test_nested_depth_cross_thread_ownership_and_failed_acquires(self):
        auditor = LockAuditor()
        lock = auditor.watch(threading.RLock(), "database")
        outcomes = []
        with lock, lock:
            with self.assertRaisesRegex(AssertionError, "database"):
                auditor.check("connect")

            def other_thread():
                outcomes.append(lock.acquire(blocking=False))
                auditor.check("connect")

            thread = threading.Thread(target=other_thread)
            thread.start()
            thread.join(2)
            self.assertFalse(thread.is_alive())
        self.assertEqual(outcomes, [False])
        self.assertEqual(auditor.held(), {})
        auditor.check("connect")

    def test_conditional_wait_releases_and_restores_tracking(self):
        auditor = LockAuditor()
        lock = auditor.watch(threading.RLock(), "database")
        with lock, lock:
            saved = lock._release_save()
            auditor.check("sleep")
            lock._acquire_restore(saved)
            with self.assertRaises(AssertionError):
                auditor.check("sleep")
        self.assertEqual(auditor.held(), {})

    def test_password_limiter_is_allowed_but_not_with_a_send_or_database_gate(self):
        auditor = LockAuditor()
        slots = auditor.watch(threading.BoundedSemaphore(2), "password_slots")
        gate = auditor.watch(threading.RLock(), "authority")
        with slots:
            auditor.check("scrypt")
            with gate, self.assertRaisesRegex(AssertionError, "authority"):
                auditor.check("scrypt")
        with gate, self.assertRaisesRegex(AssertionError, "password slot wait"):
            slots.acquire()
        with auditing() as installed:
            lock = installed.watch(threading.RLock(), "database")
            with lock:
                with self.assertRaisesRegex(AssertionError, "scrypt"):
                    hashlib.scrypt(b"synthetic", salt=b"synthetic", n=2, r=1, p=1)
                left, right = socket.socketpair()
                with left, right, self.assertRaisesRegex(AssertionError, "send"):
                    left.send(b"test")


class PasswordLockScopeTests(unittest.TestCase):
    def test_actual_password_authentication_and_change_run_outside_shared_gates(self):
        with ExitStack() as stack:
            stack.enter_context(auditing())
            fixture = UserFixture()
            fixture.setUp()
            stack.callback(fixture.doCleanups)
            user = fixture.create()
            self.assertEqual(
                fixture.users.authenticate("alice", PASSWORD)["principal_id"], user["principal_id"]
            )
            fixture.users.change_password(
                user["principal_id"],
                {"current_password": PASSWORD, "new_password": "New synthetic audited passphrase"},
            )
            self.assertEqual(
                fixture.users.authenticate("alice", "New synthetic audited passphrase")[
                    "principal_id"
                ],
                user["principal_id"],
            )
