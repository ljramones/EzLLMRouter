"""Real SIGKILL during migrations and backup; repeated recovery of WAL snapshots."""

from contextlib import closing, redirect_stdout
import io
import sqlite3
import unittest

from ezllmrouter_server import schema
from ezllmrouter_server.store import SQLiteStore
from tests.fixtures import schema_upgrades as fixtures
from tests.unit import test_process_durability as support


class MaintenanceCrashTests(unittest.TestCase):
    setUp = support.ProcessDurabilityTests.setUp
    stopped_at = support.ProcessDurabilityTests.stopped_at
    kill = staticmethod(support.ProcessDurabilityTests.kill)

    def test_killed_upgrades_preserve_old_wal_snapshot_or_complete_new_schema(self):
        for version in (1, 2):
            for target in range(version + 1, schema.VERSION + 1):
                for point in ("statement.1", "statement.3", "before_commit", "after_commit"):
                    with self.subTest(version=version, target=target, point=point):
                        root = self.root / f"migrate-{version}-{target}-{point}"
                        root.mkdir()
                        path = root / "store.sqlite"
                        with fixtures.release(path, version) as source:
                            before = fixtures.table_manifest(source)
                            child = self.stopped_at(root, f"migration.{target}", point)
                            self.kill(child)
                            self.assertLess(child.returncode, 0)
                            committed = point == "after_commit"
                            self.assertEqual(
                                schema.validate(source), schema.VERSION if committed else version
                            )
                            if not committed:
                                self.assertEqual(fixtures.table_manifest(source), before)
                            for _ in range(2):
                                with closing(SQLiteStore(path)) as store:
                                    self.assertEqual(schema.validate(store.db), schema.VERSION)
                                    fixtures.assert_unaffected(
                                        before,
                                        fixtures.table_manifest(store.db),
                                        version,
                                        schema.VERSION,
                                    )
                                    self.assertEqual(
                                        store.db.execute("PRAGMA quick_check").fetchone()[0], "ok"
                                    )
                                    self.assertEqual(
                                        fixtures.report(store)["usage"]["cost"]["known_subtotals"],
                                        {"USD": "0.325000001"},
                                    )

    def test_backup_kill_exposes_no_destination_or_a_complete_snapshot_and_can_retry(self):
        for point in ("copy", "published"):
            with self.subTest(point=point):
                root = self.root / point
                root.mkdir()
                with fixtures.release(root / "store.sqlite", schema.VERSION) as source:
                    before = fixtures.table_manifest(source)
                    child = self.stopped_at(root, "backup", point)
                    self.kill(child)
                    target = root / "backup.sqlite"
                    self.assertEqual(target.exists(), point == "published")
                    if point == "copy":
                        # Abandoned private staging files are never used as backups.
                        self.assertTrue(list(root.glob(".*.partial")))
                        from ezllmrouter_server.integration_local import main as backup_main

                        with redirect_stdout(io.StringIO()):
                            backup_main(
                                ["--db", str(root / "store.sqlite"), "--backup", str(target)]
                            )
                    with closing(sqlite3.connect(target)) as backup:
                        self.assertEqual(fixtures.table_manifest(backup), before)
                        self.assertEqual(backup.execute("PRAGMA quick_check").fetchone()[0], "ok")
                    self.assertEqual(fixtures.table_manifest(source), before)

    def test_kills_at_wal_checkpoint_boundaries_retain_all_committed_rows(self):
        for point in ("before_checkpoint", "after_checkpoint"):
            root = self.root / point
            root.mkdir()
            with fixtures.release(root / "store.sqlite", schema.VERSION) as source:
                before = fixtures.table_manifest(source)
                child = self.stopped_at(root, "wal", point)
                self.kill(child)
                for _ in range(2):
                    with closing(SQLiteStore(root / "store.sqlite")) as store:
                        self.assertEqual(fixtures.table_manifest(store.db), before)
                        self.assertEqual(store.db.execute("PRAGMA quick_check").fetchone()[0], "ok")
