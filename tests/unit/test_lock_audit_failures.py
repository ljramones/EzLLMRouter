"""Bad-code probes must fail the module even when the bad code catches the error."""

import asyncio
from contextlib import closing, redirect_stderr
import io
import json
import os
from pathlib import Path
import socket
import sqlite3
import ssl
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from ezllmrouter_server.database import Query
from ezllmrouter_server.runtime_resources import LoopThread
from ezllmrouter_server.store import SQLiteStore
from tools.check import run_module
from tools.lock_audit import WatchedLock, auditing


class LockAuditFailureTests(unittest.TestCase):
    def rejected(self, action):
        class Probe(unittest.TestCase):
            def test_bad_code(self):
                action()

        with tempfile.TemporaryDirectory() as temporary:
            suite = unittest.TestSuite([Probe("test_bad_code")])
            with (
                patch.dict(
                    os.environ,
                    {"EZLLMROUTER_LOCK_AUDIT": "1", "EZLLMROUTER_TEST_HEALTH": temporary},
                ),
                patch.object(unittest.defaultTestLoader, "loadTestsFromName", return_value=suite),
                redirect_stderr(io.StringIO()),
            ):
                passed = run_module("synthetic.bad_code", loopback=False)
            self.assertFalse(
                passed, "the module passed after its code swallowed an audit violation"
            )
            health = json.loads(next(Path(temporary).glob("module-*.json")).read_text())
            self.assertFalse(health["passed"])
            self.assertTrue(health["audit_violations"])
            self.assertNotIn("PRIVATE_CANARY", json.dumps(health))

    def test_swallowed_violations_on_test_worker_and_event_loop_threads_fail_the_module(self):
        for mode in ("test", "worker", "loop"):
            with self.subTest(mode=mode):

                def action(mode=mode):
                    with closing(SQLiteStore(":memory:")) as store:

                        def violate():
                            with store._lock:
                                try:
                                    time.sleep(0)
                                except Exception:
                                    pass

                        if mode == "test":
                            violate()
                        elif mode == "worker":
                            thread = threading.Thread(target=violate)
                            thread.start()
                            thread.join(2)
                            self.assertFalse(thread.is_alive())
                        else:

                            async def work():
                                violate()

                            with closing(LoopThread("synthetic-audit-probe")) as runtime:
                                runtime.call(work(), timeout=2)

                self.rejected(action)

    def test_raw_repository_and_store_sql_on_an_async_loop_fail_without_a_held_lock(self):
        for mode in ("raw", "cursor", "repository", "store", "connect"):
            with self.subTest(mode=mode):

                def action(mode=mode):
                    with closing(SQLiteStore(":memory:")) as store:

                        async def work():
                            try:
                                if mode == "raw":
                                    store.db.execute("SELECT 'PRIVATE_CANARY'")
                                elif mode == "cursor":
                                    with closing(store.db.cursor()) as cursor:
                                        cursor.execute("SELECT 1")
                                elif mode == "repository":
                                    store.database.execute(Query("SELECT 1"))
                                elif mode == "store":
                                    store.get("submission.absent")
                                else:
                                    with closing(sqlite3.connect(":memory:")) as connection:
                                        connection.execute("SELECT 1")
                            except Exception:
                                pass

                        asyncio.run(work())

                self.rejected(action)

    def test_tls_data_methods_are_guarded_before_the_lower_operation(self):
        with auditing() as auditor:
            lock = auditor.watch(threading.RLock(), "database")
            left, right = socket.socketpair()
            with right:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                with context.wrap_socket(
                    left, server_hostname="synthetic.invalid", do_handshake_on_connect=False
                ) as stream:
                    stream.setblocking(False)
                    for method, arguments in (
                        ("send", (b"x",)),
                        ("sendall", (b"x",)),
                        ("recv", (1,)),
                        ("recv_into", (bytearray(1),)),
                        ("read", (1,)),
                        ("write", (b"x",)),
                    ):
                        with self.subTest(method=method), lock, self.assertRaises(AssertionError):
                            getattr(stream, method)(*arguments)

    def test_offline_store_and_other_shared_gates_are_watched(self):
        from ezllmrouter_server.connector_availability import AvailabilityMonitor
        from ezllmrouter_server.provider_vault import ProviderVault
        from tests.operator_console.test_integration_credentials import CredentialTests

        with auditing():
            fixture = CredentialTests()
            fixture.setUp()
            try:
                with closing(AvailabilityMonitor()) as monitor:
                    vault = ProviderVault(fixture.root / "probe-vault")
                    for lock in (
                        fixture.registry._probe_lock,
                        fixture.credentials._gate,
                        monitor._lock,
                        vault._gate,
                    ):
                        self.assertIsInstance(lock, WatchedLock)
                path = fixture.root / "offline.sqlite"
                SQLiteStore(path).close()
                with closing(SQLiteStore.open_existing(path, read_only=True)) as store:
                    self.assertIsInstance(store._lock, WatchedLock)
            finally:
                fixture.doCleanups()
