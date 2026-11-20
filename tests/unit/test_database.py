"""Initial-schema ownership and real cross-repository transaction boundaries."""

import ast
from pathlib import Path
import sqlite3
import tempfile
import unittest
import threading
from unittest.mock import patch

from ezllmrouter_server import schema
from ezllmrouter_server.database import Query
from ezllmrouter_server.repositories import local_connectors, registry
from ezllmrouter_server.store import SQLiteStore

ROOT = Path(__file__).resolve().parents[2]


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "service.sqlite"

    def store(self):
        value = SQLiteStore(self.path)
        self.addCleanup(value.close)
        return value

    def test_report_snapshot_does_not_hold_writer_and_remains_consistent(self):
        store = self.store()
        with store.database.snapshot() as snapshot:
            before = snapshot.execute(Query("SELECT COUNT(*) FROM registry_meta")).fetchone()
            done = threading.Event()

            def write():
                store.database.transaction(
                    lambda: store.database.execute(
                        Query("INSERT INTO registry_meta VALUES ('report-test','1')")
                    )
                )
                done.set()

            writer = threading.Thread(target=write)
            writer.start()
            self.assertTrue(done.wait(1), "report reader blocked the writer")
            writer.join(1)
            self.assertEqual(
                snapshot.execute(Query("SELECT COUNT(*) FROM registry_meta")).fetchone(), before
            )
            with self.assertRaises(sqlite3.OperationalError):
                snapshot.execute(Query("DELETE FROM registry_meta"))
        self.assertEqual(
            store.database.execute(
                Query("SELECT value FROM registry_meta WHERE key='report-test'")
            ).fetchone(),
            ("1",),
        )

    def test_current_schema_contains_all_domains_and_records_each_revision(self):
        store = self.store()
        self.assertEqual(schema.validate(store.db), schema.VERSION)
        tables = {
            row[0] for row in store.db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        self.assertTrue(
            {
                "submissions",
                "console_users",
                "local_connectors",
                "registry_principals",
                "integration_credential_versions",
                "personal_campaigns",
                "dev12_authority",
            }
            <= tables
        )
        self.assertNotIn("integration_meta", tables)
        self.assertEqual(store.db.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(
            store.db.execute("SELECT version FROM schema_revisions ORDER BY version").fetchall(),
            [(number,) for number in range(1, schema.VERSION + 1)],
        )

    def test_unversioned_database_is_rejected_without_adopting_its_tables(self):
        with sqlite3.connect(self.path) as connection:
            connection.execute("CREATE TABLE unrelated (value TEXT)")
            connection.execute("INSERT INTO unrelated VALUES ('retained')")
        before = self.path.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "fresh"):
            SQLiteStore(self.path)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(Path(str(self.path) + "-wal").exists())
        self.assertFalse(Path(str(self.path) + "-shm").exists())
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(
                connection.execute("SELECT * FROM unrelated").fetchall(), [("retained",)]
            )
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone(), (0,))

    def test_failed_schema_install_rolls_back_every_table_and_marker(self):
        with patch(
            "ezllmrouter_server.schema.migration",
            return_value=("CREATE TABLE partial (value TEXT);\nTHIS IS NOT SQL;\n", "synthetic"),
        ):
            with self.assertRaises(sqlite3.Error):
                SQLiteStore(self.path)
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(connection.execute("SELECT name FROM sqlite_master").fetchall(), [])
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone(), (0,))

    def test_future_versions_and_changed_migration_hashes_fail_closed(self):
        store = self.store()
        store.db.execute(f"PRAGMA user_version={schema.VERSION + 1}")
        store.close()
        with self.assertRaises(RuntimeError):
            SQLiteStore(self.path)
        with sqlite3.connect(self.path) as connection:
            connection.execute(f"PRAGMA user_version={schema.VERSION}")
            connection.execute("UPDATE schema_revisions SET sha256='tampered'")
        with self.assertRaisesRegex(RuntimeError, "revision"):
            SQLiteStore(self.path)

    def test_queries_from_two_domains_roll_back_in_one_transaction(self):
        store = self.store()

        def change():
            store.database.execute(registry.ACTION_INSERT_REGISTRY_META, ("test", "1"))
            store.database.execute(
                local_connectors.TRANSACTION_INSERT_LOCAL_CONNECTORS, ("connector.test", "{}", None)
            )
            raise OSError("injected commit-boundary failure")

        with self.assertRaises(OSError):
            store.database.transaction(change)
        self.assertEqual(store.db.execute("SELECT * FROM registry_meta").fetchall(), [])
        self.assertEqual(store.db.execute("SELECT * FROM local_connectors").fetchall(), [])

    def test_query_results_survive_cursor_close_and_bind_values_exactly(self):
        store = self.store()
        value = "quoted ' ; DROP TABLE registry_meta; --"
        result = store.database.transaction(
            lambda: store.database.execute(registry.ACTION_INSERT_REGISTRY_META, ("test", value))
        )
        self.assertEqual(result.rowcount, 1)
        self.assertIsNotNone(result.lastrowid)
        rows = store.database.execute(
            Query("SELECT value FROM registry_meta WHERE key=?"), ("test",)
        )
        self.assertEqual(rows.fetchone(), (value,))
        self.assertIsNone(rows.fetchone())
        with self.assertRaises(TypeError):
            store.database.execute("DELETE FROM registry_meta")

    def test_dynamic_repository_identifiers_cannot_inject_sql(self):
        with self.assertRaises(ValueError):
            registry.RECORD_SELECT_RECORD(
                table="registry_models; DROP TABLE registry_models", where="ref=?"
            )

    def test_services_do_not_own_ddl_or_access_private_store_primitives(self):
        root = ROOT / "server/src/ezllmrouter_server"
        for path in [*root.glob("*.py"), ROOT / "deploy/local/local_service.py"]:
            if path.stem in {"database", "schema", "store"}:
                continue
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute):
                    self.assertFalse(
                        node.value.attr == "store" and node.attr in {"db", "_lock", "_transaction"},
                        path.name,
                    )
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    self.assertFalse(
                        node.value.lstrip().upper().startswith(("CREATE TABLE", "ALTER TABLE")),
                        path.name,
                    )
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "execute"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                ):
                    self.assertFalse(
                        node.args[0]
                        .value.lstrip()
                        .upper()
                        .startswith(("SELECT ", "INSERT ", "UPDATE ", "DELETE ")),
                        path.name,
                    )


if __name__ == "__main__":
    unittest.main()
