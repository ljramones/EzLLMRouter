"""Real child kills, SQLite faults and resumed key rotation on disposable data."""

from contextlib import closing
from pathlib import Path
import queue
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from ezllmrouter_server.database import Database
from ezllmrouter_server.provider_vault import ProviderVault
from ezllmrouter_server.repositories import store as queries
from ezllmrouter_server.secret_box import SecretBoxError
from ezllmrouter_server.store import SQLiteStore
from tests.fixtures.crash_store import sample, SECRET, NEXT_SECRET


class ProcessDurabilityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def stopped_at(self, directory, phase, point):
        process = subprocess.Popen(
            [
                sys.executable,
                "-B",
                "-m",
                "tests.fixtures.crash_store",
                str(directory),
                phase,
                point,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(self.kill, process)
        messages = queue.Queue()
        reader = threading.Thread(
            target=lambda: messages.put(process.stdout.readline()), daemon=True
        )
        reader.start()
        try:
            marker = messages.get(timeout=10)
        except queue.Empty:
            self.kill(process)
            self.fail("child did not reach the named crash checkpoint")
        reader.join(1)
        if marker.strip() != "CHECKPOINT":
            self.kill(process)
            self.fail("child exited before its checkpoint")
        return process

    @staticmethod
    def kill(process):
        if process.poll() is None:
            process.kill()
        process.wait(timeout=3)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()

    def test_kills_before_begin_before_commit_and_after_commit_preserve_atomic_work_and_usage(self):
        for phase in ("create", "intent", "guard", "usage"):
            for point in ("before_begin", "before_commit", "after_commit"):
                with self.subTest(phase=phase, point=point):
                    directory = self.root / phase / point
                    process = self.stopped_at(directory, phase, point)
                    self.kill(process)
                    self.assertNotEqual(process.returncode, 0)
                    for _ in range(2):
                        with closing(SQLiteStore(directory / "store.sqlite")) as store:
                            committed = point == "after_commit"
                            value = store.get("submission.crash")
                            self.assertEqual(value is not None, phase != "create" or committed)
                            expected_work = int(phase != "create" or committed)
                            self.assertEqual(
                                store.db.execute("SELECT count(*) FROM work_key_owners").fetchone()[
                                    0
                                ],
                                expected_work,
                            )
                            if phase == "intent":
                                self.assertEqual(
                                    store.intent_count("submission.crash"), int(committed)
                                )
                            elif phase == "guard":
                                self.assertEqual(
                                    store.guard_record("attempt.crash") is not None, committed
                                )
                            elif phase == "usage":
                                self.assertEqual(
                                    store.db.execute(
                                        "SELECT count(*) FROM usage_revisions"
                                    ).fetchone()[0],
                                    int(committed),
                                )
                                self.assertEqual(
                                    value["submission_state"],
                                    "completed" if committed else "admitted",
                                )
                                if committed:
                                    self.assertEqual(
                                        value["usage"]["revision"]["cost"]["amount_decimal"],
                                        "0.125000001",
                                    )
                            self.assertEqual(
                                store.db.execute("PRAGMA quick_check").fetchone()[0], "ok"
                            )

    def test_a_second_process_is_refused_and_killing_the_owner_releases_the_lease(self):
        directory = self.root / "lease"
        owner = self.stopped_at(directory, "hold", "ready")
        probe = subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "tests.fixtures.crash_store",
                str(directory),
                "probe",
                "unused",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(probe.returncode, 73)
        self.assertEqual(probe.stdout.strip(), "INSTANCE_IN_USE")
        self.kill(owner)
        with closing(SQLiteStore(directory / "store.sqlite")) as store:
            self.assertEqual(store.get("submission.crash")["dispatch_state"], "prepared")
            self.assertEqual(store.db.execute("SELECT count(*) FROM submissions").fetchone()[0], 1)

    def test_killed_secret_publication_and_rotation_remain_readable_and_resumable(self):
        for phase in ("seal", "rotate"):
            for point in ("before_publish", "after_publish", "after_complete"):
                with self.subTest(phase=phase, point=point):
                    directory = self.root / phase / point
                    self.kill(self.stopped_at(directory, phase, point))
                    vault = ProviderVault(directory / "vault", require_existing=True)
                    self.assertEqual(vault.resolve("conn.crash", 1), SECRET)
                    if phase == "seal":
                        self.assertEqual(
                            vault._path("conn.crash", 2).exists(), point != "before_publish"
                        )
                        vault.seal("conn.crash", 2, NEXT_SECRET, committed_version=1)
                        self.assertEqual(vault.resolve("conn.crash", 2), NEXT_SECRET)
                    vault.reencrypt_secrets(["conn.crash"])
                    self.assertEqual(vault.resolve("conn.crash", 1), SECRET)
                    # A copied ciphertext without its keyring must fail closed.
                    vault.key_path.unlink()
                    with self.assertRaises(SecretBoxError):
                        ProviderVault(directory / "vault", require_existing=True)


class SQLiteFaultTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = SQLiteStore(Path(temporary.name) / "fault.sqlite")
        self.addCleanup(self.store.close)

    def test_busy_writer_does_not_begin_or_partially_claim_work(self):
        self.store.db.execute("PRAGMA busy_timeout=0")
        with closing(
            sqlite3.connect(self.store.path, isolation_level=None, timeout=0)
        ) as competitor:
            competitor.execute("BEGIN IMMEDIATE")
            try:
                with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                    self.store.create(sample())
                self.assertFalse(self.store.db.in_transaction)
                self.assertIsNone(self.store.work_owner(sample()["work_key"]))
            finally:
                competitor.execute("ROLLBACK")
        self.store.create(sample())
        self.assertIsNotNone(self.store.get("submission.crash"))

    def test_disk_full_inside_nested_savepoint_preserves_error_and_rolls_back(self):
        self.store.db.execute("CREATE TABLE fault_input (value BLOB)")
        pages = self.store.db.execute("PRAGMA page_count").fetchone()[0]
        self.store.db.execute(f"PRAGMA max_page_count={pages}")
        with self.assertRaisesRegex(sqlite3.OperationalError, "full") as failed:
            self.store.database.transaction(
                lambda: self.store.database.transaction(
                    lambda: self.store.db.execute(
                        "INSERT INTO fault_input VALUES (zeroblob(1048576))"
                    )
                )
            )
        self.assertTrue(failed.exception.ezllmrouter_definite_rollback)
        self.assertFalse(self.store.db.in_transaction)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM fault_input").fetchone()[0], 0)
        self.assertEqual(self.store.db.execute("PRAGMA quick_check").fetchone()[0], "ok")

    def test_io_error_after_work_claim_keeps_original_error_and_no_orphan_owner(self):
        execute = Database.execute
        original = sqlite3.OperationalError("synthetic disk I/O error")

        def fail_insert(database, query, parameters=()):
            if query == queries.ACTION_INSERT_SUBMISSIONS:
                raise original
            return execute(database, query, parameters)

        with (
            patch.object(Database, "execute", fail_insert),
            self.assertRaises(sqlite3.OperationalError) as failed,
        ):
            self.store.create(sample())
        self.assertIs(failed.exception, original)
        self.assertFalse(self.store.db.in_transaction)
        self.assertIsNone(self.store.work_owner(sample()["work_key"]))
        self.assertIsNone(self.store.get("submission.crash"))
        self.store.create(sample())
        self.assertIsNotNone(self.store.work_owner(sample()["work_key"]))
