"""Offline backup publication must expose only complete, validated snapshots."""

from contextlib import closing, redirect_stdout
import io
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from ezllmrouter_server import integration_local
from ezllmrouter_server import database_backup
from ezllmrouter_server.private_files import AtomicPublicationError
from tests.fixtures import schema_upgrades as fixtures
from tools.lock_audit import AuditedConnection


class DatabaseBackupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source, self.target = self.root / "source.sqlite", self.root / "backup.sqlite"
        fixtures.build(self.source, 3)

    def backup(self):
        with redirect_stdout(io.StringIO()):
            integration_local.main(["--db", str(self.source), "--backup", str(self.target)])

    def test_interrupted_copy_does_not_publish_a_partial_backup(self):
        connect = sqlite3.connect

        class Interrupted(AuditedConnection):
            def backup(self, target, **kwargs):
                target.execute("CREATE TABLE partial(value)")
                raise OSError("synthetic interrupted backup")

        with patch.object(
            sqlite3,
            "connect",
            side_effect=lambda *args, **kwargs: connect(*args, **dict(kwargs, factory=Interrupted)),
        ):
            with self.assertRaises(OSError) as failure:
                self.backup()
        self.assertIn("interrupted backup", str(failure.exception.__cause__ or failure.exception))
        self.assertFalse(self.target.exists(), "an incomplete backup became visible")

    def test_successful_snapshot_includes_wal_rows_and_private_permissions(self):
        self.source.unlink()
        with fixtures.release(self.source, 3) as source:
            before = fixtures.table_manifest(source)
            self.backup()
            self.assertEqual(fixtures.table_manifest(source), before)
        with closing(sqlite3.connect(self.target)) as restored:
            self.assertEqual(fixtures.table_manifest(restored), before)
            self.assertEqual(restored.execute("PRAGMA quick_check").fetchone()[0], "ok")
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o600)
        self.assertFalse(list(self.root.glob(".*.partial")))

    def test_existing_destination_is_never_replaced(self):
        self.target.write_bytes(b"original backup")
        with self.assertRaises(FileExistsError):
            database_backup.backup_database(self.source, self.target)
        self.assertEqual(self.target.read_bytes(), b"original backup")
        self.assertFalse(list(self.root.glob(".*.partial")))

    def test_failed_sync_reports_whether_a_complete_backup_was_published(self):
        original = database_backup.os.fsync
        for fail_at in (1, 2):
            calls = 0

            def failing(descriptor, fail_at=fail_at):
                nonlocal calls
                calls += 1
                if calls == fail_at:
                    raise OSError("synthetic sync failure")
                return original(descriptor)

            with (
                self.subTest(fail_at=fail_at),
                patch.object(database_backup.os, "fsync", side_effect=failing),
            ):
                with self.assertRaises(AtomicPublicationError) as failure:
                    database_backup.backup_database(self.source, self.target)
            self.assertEqual(failure.exception.published, fail_at == 2)
            self.assertEqual(self.target.exists(), fail_at == 2)
            self.assertFalse(list(self.root.glob(".*.partial")))
            if self.target.exists():
                with closing(sqlite3.connect(self.target)) as complete:
                    self.assertEqual(complete.execute("PRAGMA quick_check").fetchone()[0], "ok")
                self.target.unlink()

    def test_future_schema_is_refused_without_rewriting_source_or_publishing(self):
        with closing(sqlite3.connect(self.source)) as source:
            source.execute("PRAGMA user_version=999")
        before = self.source.read_bytes()
        with self.assertRaises(RuntimeError):
            self.backup()
        self.assertEqual(self.source.read_bytes(), before)
        self.assertFalse(self.target.exists())
        self.assertFalse(list(self.root.glob(".*.partial")))
