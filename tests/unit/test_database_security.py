"""Every service-owned SQLite connection must disable unnecessary capabilities."""

from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from ezllmrouter_server.database_backup import backup_database
from ezllmrouter_server.store import SQLiteStore
from tools.lock_audit import AuditedConnection


class DatabaseSecurityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "service.sqlite"

    def assert_safe(self, connection):
        self.assertTrue(connection.getconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE))
        self.assertFalse(connection.getconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_LOAD_EXTENSION))

    def test_all_store_and_report_and_maintenance_connections_are_hardened(self):
        store = SQLiteStore(self.path)
        try:
            self.assert_safe(store.db)
            with store.database.snapshot():
                self.assertEqual(len(store._readers), 1)
                self.assert_safe(next(iter(store._readers)))
        finally:
            store.close()
        for read_only, maintenance in ((False, False), (True, False), (True, True)):
            with self.subTest(read_only=read_only, maintenance=maintenance):
                reopened = SQLiteStore.open_existing(
                    self.path, read_only=read_only, maintenance=maintenance
                )
                try:
                    self.assert_safe(reopened.db)
                finally:
                    reopened.close()
        memory = SQLiteStore(":memory:")
        try:
            self.assert_safe(memory.db)
        finally:
            memory.close()

    def test_schema_tampering_and_native_extension_loading_are_denied(self):
        store = SQLiteStore(":memory:")
        self.addCleanup(store.close)
        store.db.execute("PRAGMA writable_schema=ON")
        with self.assertRaises(sqlite3.DatabaseError):
            store.db.execute("UPDATE sqlite_schema SET sql=sql WHERE name='schema_revisions'")
        store.db.execute("PRAGMA writable_schema=OFF")
        with self.assertRaisesRegex(sqlite3.OperationalError, "not authorized"):
            store.db.load_extension("/nonexistent/ezllmrouter-synthetic-extension")
        self.assertEqual(store.db.execute("PRAGMA quick_check").fetchone(), ("ok",))

    def test_backup_source_and_destination_are_hardened_before_use(self):
        store = SQLiteStore(self.path)
        store.close()
        original = sqlite3.connect
        connections = []
        assert_safe = self.assert_safe

        class CheckBackup(AuditedConnection):
            def execute(self, *args, **kwargs):
                assert_safe(self)
                return super().execute(*args, **kwargs)

            def backup(self, target, **kwargs):
                assert_safe(self)
                assert_safe(target)
                return super().backup(target, **kwargs)

        def connect(*args, **kwargs):
            connection = original(*args, **dict(kwargs, factory=CheckBackup))
            connections.append(connection)
            return connection

        target = self.root / "backup.sqlite"
        with patch.object(sqlite3, "connect", side_effect=connect):
            backup_database(self.path, target)
        self.assertEqual(len(connections), 2)
        for connection in connections:
            with self.assertRaises(sqlite3.ProgrammingError):
                sqlite3.Connection.execute(connection, "SELECT 1")
        restored = SQLiteStore.open_existing(target, read_only=True)
        try:
            self.assert_safe(restored.db)
        finally:
            restored.close()

    def test_configuration_failure_closes_connections_and_releases_ownership(self):
        original = sqlite3.connect
        connections = []

        class FailedConfiguration(AuditedConnection):
            def setconfig(self, operation, enabled=True):
                if operation == sqlite3.SQLITE_DBCONFIG_ENABLE_LOAD_EXTENSION:
                    raise sqlite3.OperationalError("synthetic capability failure")
                return super().setconfig(operation, enabled)

        def connect(*args, **kwargs):
            connection = original(*args, **dict(kwargs, factory=FailedConfiguration))
            connections.append(connection)
            return connection

        with patch.object(sqlite3, "connect", side_effect=connect):
            with self.assertRaises(sqlite3.OperationalError):
                SQLiteStore(self.path)
        owner = SQLiteStore(self.path)
        try:
            with patch.object(sqlite3, "connect", side_effect=connect):
                with self.assertRaises(sqlite3.OperationalError):
                    with owner.database.snapshot():
                        self.fail("unsafe report connection became available")
            self.assertEqual(len(owner._readers), 0)
        finally:
            owner.close()
        for read_only in (False, True):
            with patch.object(sqlite3, "connect", side_effect=connect):
                with self.assertRaises(sqlite3.OperationalError):
                    SQLiteStore.open_existing(self.path, read_only=read_only)
        for connection in connections:
            with self.assertRaises(sqlite3.ProgrammingError):
                sqlite3.Connection.execute(connection, "SELECT 1")
        reopened = SQLiteStore(self.path)
        reopened.close()


if __name__ == "__main__":
    unittest.main()
