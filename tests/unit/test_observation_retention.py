"""Bounded inventory reads and an atomic, data-preserving schema upgrade."""

from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ezllmrouter_server import registry as registry_module, schema
from ezllmrouter_server.database import Query
from ezllmrouter_server.registry import Registry
from ezllmrouter_server.repositories import registry as queries
from ezllmrouter_server.store import SQLiteStore, encode
from tests.operator_console.test_registry import Authority, DEST, TOKEN, TRUSTED


def observation(
    index, connection="connection.retention", operation="readiness", state="failed", models=()
):
    return {
        "operation_id": "probe.retention." + str(index),
        "connection_id": connection,
        "operation": operation,
        "state": state,
        "models": list(models),
        "reason": "synthetic_metadata",
        "observed_at": "2030-01-01T00:00:00Z",
        "connection_revision": 1,
        "credential_version": 1,
    }


def historical_rows(connection="connection.retention"):
    yield observation(0, connection, "inventory", "observed", ["model.kept"])
    yield observation(1, connection, "inventory", "partial", ["model.partial"])
    yield observation(2, connection, "inventory", "failed")
    for index in range(3, 2000):
        yield observation(index, connection)


class ObservationRetentionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = SQLiteStore(Path(temporary.name) / "registry.sqlite")
        self.addCleanup(self.store.close)
        self.registry = Registry(
            self.store,
            Authority(),
            legacy_destination=DEST,
            legacy_token=TOKEN,
            legacy_trusted=TRUSTED,
        )
        self.connection = "connection.retention"
        record = {
            "connection_id": self.connection,
            "revision": 1,
            "credential_version": 1,
            "status": "active",
            "adapter_id": "openai.responses.v1",
            "credential_state": "present",
            "settings": {"origin": "https://api.openai.com"},
        }
        self.store.database.transaction(
            lambda: self.store.database.execute(
                queries.APPLY_INSERT_REGISTRY_CONNECTIONS, (self.connection, encode(record))
            )
        )

    def seed(self):
        rows = [
            *historical_rows(),
            observation("foreign", "connection.foreign", "inventory", "observed"),
        ]
        self.store.database.transaction(
            lambda: self.store.db.executemany(
                "INSERT INTO registry_observations VALUES (?,?,?)",
                [(item["operation_id"], item["connection_id"], encode(item)) for item in rows],
            )
        )

    def test_inventory_reads_at_most_three_records_and_preserves_partial_fallback(self):
        self.seed()
        decoded = []
        original = json.loads

        def decode(raw, *args, **kwargs):
            value = original(raw, *args, **kwargs)
            if type(value) is dict and value.get("operation") == "inventory":
                decoded.append(value["operation_id"])
            return value

        with patch.object(registry_module.json, "loads", side_effect=decode):
            result = self.registry.source_inventory(self.connection)
        self.assertEqual(decoded, ["probe.retention.2", "probe.retention.1", "probe.retention.0"])
        self.assertEqual(result["discovery"]["state"], "failed")
        self.assertEqual(
            {item["serving_id"] for item in result["items"]}, {"model.kept", "model.partial"}
        )
        self.assertTrue(all(not item["allowed"] for item in result["items"]))

    def test_permission_update_uses_the_same_bounded_inventory_snapshot(self):
        self.seed()
        returned = []
        original = json.loads

        def record(raw, *args, **kwargs):
            result = original(raw, *args, **kwargs)
            if type(result) is dict and result.get("operation") == "inventory":
                returned.append(result["operation_id"])
            return result

        with patch.object(registry_module.json, "loads", side_effect=record):
            result = self.registry.mutate(
                "owner.local",
                {
                    "operation_id": "op.retained.permission",
                    "action": "set_source_permissions",
                    "subject": self.connection,
                    "expected_revision": 0,
                    "data": {
                        "allowed": True,
                        "items": [{"serving_id": "model.kept", "expected_revision": 0}],
                    },
                },
            )
        self.assertEqual(returned, ["probe.retention.2", "probe.retention.1", "probe.retention.0"])
        self.assertTrue(result["record"]["items"][0]["allowed"])

    def test_probe_write_prunes_old_diagnostics_and_preserves_snapshot_anchors(self):
        self.seed()
        self.registry.provider_vault = SimpleNamespace(resolve=lambda *_: "synthetic-credential")
        with patch.object(
            registry_module,
            "provider_probe",
            return_value={"state": "failed", "reason": "synthetic_failure", "models": []},
        ):
            self.registry.probe_connection(
                "owner.local", self.connection, 1, "probe.new", "inventory"
            )
        self.registry.provider_vault = SimpleNamespace(resolve=lambda *_: "synthetic-credential")
        with patch.object(
            registry_module,
            "provider_probe",
            return_value={"state": "failed", "reason": "synthetic_failure", "models": []},
        ) as probe:
            self.registry.probe_connection(
                "owner.local", self.connection, 1, "probe.new", "inventory"
            )
            probe.assert_not_called()
            self.registry.probe_connection(
                "owner.local", self.connection, 1, "probe.retention.2", "inventory"
            )
            probe.assert_called_once()
        records = self.store.db.execute(
            "SELECT operation_id FROM registry_observations WHERE connection_id=?",
            (self.connection,),
        ).fetchall()
        self.assertLessEqual(len(records), 23)
        self.assertIn(("probe.retention.0",), records)
        self.assertIn(("probe.retention.1",), records)
        self.assertIn(("probe.new",), records)
        self.assertEqual(len(self.registry.observations(self.connection)), 20)
        self.assertIsNotNone(
            self.store.db.execute(
                "SELECT 1 FROM registry_observations WHERE connection_id='connection.foreign'"
            ).fetchone()
        )

    def test_provider_waits_release_the_probe_bookkeeping_lock(self):
        self.registry.provider_vault = SimpleNamespace(resolve=lambda *_: "synthetic-credential")

        def probe(*_args, **_kwargs):
            acquired = self.registry._probe_lock.acquire(blocking=False)
            if acquired:
                self.registry._probe_lock.release()
            self.assertTrue(acquired, "provider I/O retains the shared probe bookkeeping lock")
            return {"state": "observed", "reason": "synthetic_metadata", "models": []}

        with patch.object(registry_module, "provider_probe", side_effect=probe):
            self.registry.probe_connection(
                "owner.local", self.connection, 1, "probe.unlocked", "inventory"
            )

    def test_duplicate_probes_wait_without_shared_locks_and_reuse_the_saved_result(self):
        self.registry.provider_vault = SimpleNamespace(resolve=lambda *_: "synthetic-credential")
        entered, release, waiting = threading.Event(), threading.Event(), threading.Event()
        results, errors = [], []

        def probe(*_args, **_kwargs):
            entered.set()
            if not release.wait(3):
                raise RuntimeError("fixture probe was not released")
            return {"state": "observed", "reason": "synthetic_metadata", "models": []}

        def invoke():
            try:
                results.append(
                    self.registry.probe_connection(
                        "owner.local", self.connection, 1, "probe.duplicate", "inventory"
                    )
                )
            except Exception as error:
                errors.append(error)

        leader, follower = threading.Thread(target=invoke), threading.Thread(target=invoke)
        with patch.object(registry_module, "provider_probe", side_effect=probe) as external:
            leader.start()
            try:
                self.assertTrue(entered.wait(3))
                active = self.registry._probe_active
                self.assertIsNotNone(active)
                original_wait = active.wait

                def wait(*args, **kwargs):
                    waiting.set()
                    return original_wait(*args, **kwargs)

                with patch.object(active, "wait", side_effect=wait):
                    follower.start()
                    self.assertTrue(waiting.wait(3))
            finally:
                release.set()
                leader.join(3)
                if follower.ident is not None:
                    follower.join(3)
            self.assertFalse(leader.is_alive())
            self.assertFalse(follower.is_alive())
            self.assertEqual(errors, [])
            external.assert_called_once()
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0], results[1])
        self.assertIsNone(self.registry._probe_active)

    def test_failed_probe_releases_the_slot_for_a_retry(self):
        self.registry.provider_vault = SimpleNamespace(resolve=lambda *_: "synthetic-credential")
        with patch.object(registry_module, "provider_probe", side_effect=RuntimeError("synthetic")):
            with self.assertRaisesRegex(RuntimeError, "synthetic"):
                self.registry.probe_connection(
                    "owner.local", self.connection, 1, "probe.retry", "inventory"
                )
        self.assertIsNone(self.registry._probe_active)
        with patch.object(
            registry_module,
            "provider_probe",
            return_value={"state": "observed", "reason": "synthetic_metadata", "models": []},
        ):
            self.assertEqual(
                self.registry.probe_connection(
                    "owner.local", self.connection, 1, "probe.retry", "inventory"
                )["state"],
                "observed",
            )

    def test_anchor_queries_use_their_connection_indexes(self):
        self.seed()
        plan = self.store.database.execute(
            Query(
                "EXPLAIN QUERY PLAN " + queries.SOURCE_INVENTORY_SELECT_REGISTRY_OBSERVATIONS.sql
            ),
            (self.connection,),
        ).fetchall()
        details = "\n".join(str(row[3]) for row in plan)
        for name in (
            "registry_inventory_latest",
            "registry_inventory_usable",
            "registry_inventory_complete",
        ):
            self.assertIn(name, details)
        self.assertNotIn("SCAN registry_observations", details)


class ObservationMigrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "version-one.sqlite"
        with closing(sqlite3.connect(self.path, isolation_level=None)) as connection:
            with (
                patch.object(schema, "MIGRATIONS", ("v001_initial.sql",)),
                patch.object(schema, "VERSION", 1),
            ):
                schema.initialize(connection)
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany(
                "INSERT INTO registry_observations VALUES (?,?,?)",
                [
                    (item["operation_id"], item["connection_id"], encode(item))
                    for item in historical_rows()
                ],
            )
            connection.execute(
                "INSERT INTO registry_prices VALUES (?,?,?)",
                ("cfg.preserved", "price.preserved", '{"amount_decimal":"0.000123456"}'),
            )
            connection.execute("COMMIT")

    def test_upgrade_retains_identical_snapshot_and_price_records_and_is_restartable(self):
        with closing(sqlite3.connect(self.path)) as connection:
            original_digest = connection.execute(
                "SELECT sha256 FROM schema_revisions WHERE version=1"
            ).fetchone()
            anchors = connection.execute(
                "SELECT * FROM registry_observations WHERE operation_id IN (?,?,?)",
                ("probe.retention.0", "probe.retention.1", "probe.retention.2"),
            ).fetchall()
            prices = connection.execute("SELECT * FROM registry_prices").fetchall()
        for _ in range(2):
            store = SQLiteStore(self.path)
            try:
                self.assertEqual(schema.validate(store.db), schema.VERSION)
                self.assertEqual(
                    store.db.execute(
                        "SELECT sha256 FROM schema_revisions WHERE version=1"
                    ).fetchone(),
                    original_digest,
                )
                self.assertEqual(
                    store.db.execute(
                        "SELECT * FROM registry_observations WHERE operation_id IN (?,?,?)",
                        ("probe.retention.0", "probe.retention.1", "probe.retention.2"),
                    ).fetchall(),
                    anchors,
                )
                self.assertEqual(
                    store.db.execute("SELECT * FROM registry_prices").fetchall(), prices
                )
                self.assertEqual(
                    store.db.execute("SELECT COUNT(*) FROM registry_observations").fetchone()[0], 23
                )
            finally:
                store.close()

    def test_failed_second_migration_rolls_back_indexes_deletes_and_revision(self):
        original = schema.migration

        def broken(number):
            source, digest = original(number)
            if number == 2:
                source += "\nTHIS IS NOT VALID SQL;\n"
                digest = hashlib.sha256(source.encode()).hexdigest()
            return source, digest

        with patch.object(schema, "migration", side_effect=broken):
            with self.assertRaises(sqlite3.Error):
                SQLiteStore(self.path)
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone(), (1,))
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM registry_observations").fetchone(), (2000,)
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM schema_revisions").fetchone(), (1,)
            )
            self.assertIsNone(
                connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='registry_inventory_latest'"
                ).fetchone()
            )
