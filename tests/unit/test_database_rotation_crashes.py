"""SIGKILL preserves database credential versions, idempotency and resumable keys."""

from contextlib import closing, redirect_stdout
import io
import json
from pathlib import Path
import unittest

from ezllmrouter_server.integration_credentials import credential_context
from ezllmrouter_server.local_connectors import connector_context
from ezllmrouter_server.secret_box import SecretBox
from ezllmrouter_server.secret_rotation import main as maintenance
from ezllmrouter_server.store import SQLiteStore
from tests.unit import test_process_durability as processes
from tests.fixtures.schema_upgrades import table_manifest


class DatabaseRotationCrashTests(unittest.TestCase):
    setUp = processes.ProcessDurabilityTests.setUp
    stopped_at = processes.ProcessDurabilityTests.stopped_at
    kill = staticmethod(processes.ProcessDurabilityTests.kill)

    def test_killed_integration_and_connector_rotation_rolls_back_and_resumes_without_identity_changes(
        self,
    ):
        for scope in ("integration", "connectors"):
            for point in ("after_key_publish", "during_rewrite", "before_commit", "after_commit"):
                with self.subTest(scope=scope, point=point):
                    root = self.root / scope / point
                    self.kill(self.stopped_at(root, "db_rotation." + scope, point))
                    metadata = json.loads((root / "rotation.json").read_text())
                    purpose = (
                        "integration-credentials"
                        if scope == "integration"
                        else "local-connector-credentials"
                    )
                    box = SecretBox(Path(metadata["keyring"]), purpose, required=True)
                    self.assertNotEqual(box.active_id, metadata["old_key"])
                    self.assertEqual(
                        box.request_digest(b"synthetic-crash-operation"), metadata["digest"]
                    )
                    for resume in (False, True):
                        with closing(SQLiteStore(metadata["db"])) as store:
                            self.assertEqual(
                                store.db.execute("PRAGMA quick_check").fetchone()[0], "ok"
                            )
                            after = table_manifest(store.db)
                            affected = (
                                "integration_credential_versions"
                                if scope == "integration"
                                else "local_connectors"
                            )
                            for table, expected in metadata["before"].items():
                                if table != affected:
                                    self.assertEqual(after[table], expected, table)
                            self.assertEqual(
                                [
                                    list(row)
                                    for row in store.db.execute(
                                        "SELECT id,record FROM local_connectors ORDER BY id"
                                    )
                                ],
                                metadata["connector_records"],
                            )
                            if scope == "integration":
                                rows = list(
                                    store.db.execute(
                                        "SELECT account_id,version,key_id,nonce,ciphertext FROM integration_credential_versions"
                                    )
                                )
                                for account, version, key, nonce, ciphertext in rows:
                                    self.assertEqual(
                                        box.open_parts(
                                            key,
                                            nonce,
                                            ciphertext,
                                            credential_context(account, version, "anthropic"),
                                        ),
                                        "known-fixture-api-key-0001",
                                    )
                                keys = [row[2] for row in rows]
                            else:
                                rows = list(
                                    store.db.execute("SELECT id,secret FROM local_connectors")
                                )
                                keys = []
                                for identifier, raw in rows:
                                    envelope = json.loads(raw)
                                    self.assertIn(
                                        box.open(envelope, connector_context(identifier)),
                                        (
                                            "synthetic-rotation-secret-0",
                                            "synthetic-rotation-secret-1",
                                        ),
                                    )
                                    keys.append(envelope["key_id"])
                            self.assertEqual(len(keys), 2)
                            self.assertEqual(
                                set(keys),
                                {
                                    box.active_id
                                    if resume or point == "after_commit"
                                    else metadata["old_key"]
                                },
                            )
                        with redirect_stdout(io.StringIO()) as output:
                            self.assertEqual(
                                maintenance(
                                    [
                                        "resume",
                                        "--scope",
                                        scope,
                                        "--db",
                                        metadata["db"],
                                        "--keyring",
                                        metadata["keyring"],
                                    ]
                                ),
                                0,
                            )
                        self.assertEqual(
                            json.loads(output.getvalue())["rewritten"],
                            0 if resume or point == "after_commit" else 2,
                        )
                        self.assertEqual(
                            box.active_id,
                            SecretBox(Path(metadata["keyring"]), purpose, required=True).active_id,
                        )
