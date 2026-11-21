"""Release fixture inventory, exact historical preservation and public keyring vectors."""

from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from ezllmrouter_server import schema
from ezllmrouter_server.secret_box import SecretBox, SecretBoxError
from ezllmrouter_server.store import SQLiteStore
from tests.fixtures import schema_upgrades as fixtures


class SchemaUpgradeFixtures(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.manifests = [
            json.loads(path.read_text()) for path in sorted(fixtures.FIXTURES.glob("v*.json"))
        ]

    def test_every_schema_resource_requires_a_release_fixture_and_immutable_checksums(self):
        self.assertEqual(
            [row["version"] for row in self.manifests], list(range(1, schema.VERSION + 1))
        )
        resources = sorted((fixtures.ROOT / "server/src/ezllmrouter_server/schema").glob("v*.sql"))
        self.assertEqual([path.name for path in resources], list(schema.MIGRATIONS))
        for row in self.manifests:
            self.assertEqual(row["seed_sha256"], fixtures.digest(fixtures.seed_rows()))
            self.assertEqual(
                row["migrations"],
                {
                    name: schema.migration(i)[1]
                    for i, name in enumerate(schema.MIGRATIONS[: row["version"]], 1)
                },
            )

    def test_all_releases_upgrade_and_restart_without_changing_retained_history_or_reports(self):
        for manifest in self.manifests:
            with self.subTest(version=manifest["version"]):
                path = self.root / f"v{manifest['version']}.sqlite"
                fixtures.build(path, manifest["version"])
                with closing(sqlite3.connect(path)) as connection:
                    self.assertEqual(fixtures.table_manifest(connection), manifest["source_tables"])
                for _ in range(2):
                    with closing(SQLiteStore(path)) as store:
                        self.assertEqual(schema.validate(store.db), schema.VERSION)
                        self.assertEqual(fixtures.table_manifest(store.db), manifest["head_tables"])
                        actual = fixtures.report(store)
                        self.assertEqual(actual, manifest["head_report"])
                        self.assertEqual(
                            actual["usage"]["cost"]["known_subtotals"], {"USD": "0.325000001"}
                        )
                        self.assertEqual(actual["usage"]["attempts"], 3)
                        self.assertEqual(actual["usage"]["cost"]["unknown_attempts"], 1)
                        self.assertEqual(
                            actual["external"]["known_total_by_currency"], {"USD": "0.020000000"}
                        )
                        self.assertEqual(actual["external"]["attempt_count"], 1)
                        self.assertEqual(
                            actual["external"]["attempts"][0]["feature_snapshot_status"], "expired"
                        )
                        self.assertEqual(
                            store.db.execute("PRAGMA quick_check").fetchall(), [("ok",)]
                        )
                        self.assertEqual(
                            store.db.execute("PRAGMA foreign_key_check").fetchall(), []
                        )
                        kept = {
                            row[0]
                            for row in store.db.execute(
                                "SELECT operation_id FROM registry_observations"
                            )
                        }
                        self.assertEqual(
                            kept,
                            {"probe.00", "probe.01", "probe.02"}
                            | {f"probe.{i:02}" for i in range(10, 30)},
                        )
                        self.assertEqual(
                            store.db.execute(
                                "SELECT content,digest FROM integration_snapshots"
                            ).fetchall(),
                            [(None, "sha256:" + "b" * 64)],
                        )

    def test_failed_upgrade_preserves_the_original_database_bytes_and_remains_retryable(self):
        original = schema.migration
        for manifest in self.manifests[:-1]:
            for failed_version in range(manifest["version"] + 1, schema.VERSION + 1):
                with self.subTest(source=manifest["version"], failed=failed_version):
                    path = self.root / f"failed-{manifest['version']}-{failed_version}.sqlite"
                    fixtures.build(path, manifest["version"])
                    before = path.read_bytes()

                    def broken(number, failed_version=failed_version):
                        source, checksum = original(number)
                        return (
                            (source + "\nTHIS IS NOT SQL;\n", checksum)
                            if number == failed_version
                            else (source, checksum)
                        )

                    with patch.object(schema, "migration", side_effect=broken):
                        with self.assertRaises(sqlite3.Error):
                            SQLiteStore(path)
                    self.assertEqual(path.read_bytes(), before)
                    self.assertFalse(Path(str(path) + "-wal").exists())
                    with closing(SQLiteStore(path)) as store:
                        self.assertEqual(fixtures.table_manifest(store.db), manifest["head_tables"])

    def test_a_future_schema_is_refused_without_rewriting_any_database_byte(self):
        path = self.root / "future.sqlite"
        fixtures.build(path, schema.VERSION)
        with closing(sqlite3.connect(path, isolation_level=None)) as connection:
            connection.execute(f"PRAGMA user_version={schema.VERSION + 1}")
        before = path.read_bytes()
        with self.assertRaises(RuntimeError):
            SQLiteStore(path)
        self.assertEqual(path.read_bytes(), before)

    def test_public_keyring_fixture_reads_rotates_and_refuses_unknown_formats(self):
        vectors = [
            json.loads(path.read_text())
            for path in sorted(fixtures.FIXTURES.glob("keyring-v*.json"))
        ]
        self.assertTrue(vectors)
        for vector in vectors:
            with self.subTest(version=vector["keyring"]["version"]):
                path = self.root / f"ring-{vector['keyring']['version']}.json"
                path.write_text(json.dumps(vector["keyring"]))
                path.chmod(0o600)
                before = path.read_bytes()
                box = SecretBox(path, vector["keyring"]["purpose"], required=True)
                context = vector["context"].encode()
                self.assertEqual(box.open(vector["envelope"], context), vector["plaintext"])
                self.assertEqual(path.read_bytes(), before)
                current = box.seal(vector["plaintext"], context)
                self.assertIn(current["version"], [row["envelope"]["version"] for row in vectors])
                box.rotate()
                restarted = SecretBox(path, vector["keyring"]["purpose"], required=True)
                self.assertEqual(restarted.open(vector["envelope"], context), vector["plaintext"])
                invalid = deepcopy(vector["envelope"])
                invalid["version"] = max(row["envelope"]["version"] for row in vectors) + 1
                with self.assertRaises(SecretBoxError):
                    restarted.open(invalid, context)
                future = deepcopy(vector["keyring"])
                future["version"] = max(row["keyring"]["version"] for row in vectors) + 1
                path.write_text(json.dumps(future))
                before = path.read_bytes()
                with self.assertRaises(SecretBoxError):
                    SecretBox(path, future["purpose"], required=True)
                self.assertEqual(path.read_bytes(), before)
