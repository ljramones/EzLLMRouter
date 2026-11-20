"""Credential staging and coherent authority reads, with disposable owned stores."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from ezllmrouter_server.provider_vault import ProviderVault
from ezllmrouter_server.registry import Registry
from ezllmrouter_server.repositories import registry as queries
from ezllmrouter_server.store import SQLiteStore, encode
from tests.operator_console.test_registry import Authority, DEST, TOKEN, TRUSTED


class PersistenceRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = SQLiteStore(self.root / "store.sqlite")
        self.addCleanup(self.store.close)
        self.vault = ProviderVault(self.root / "vault")
        self.registry = Registry(
            self.store,
            Authority(),
            legacy_destination=DEST,
            legacy_token=TOKEN,
            legacy_trusted=TRUSTED,
            provider_vault=self.vault,
        )
        self.connection = "conn.recovery"
        record = {
            "connection_id": self.connection,
            "revision": 1,
            "credential_version": 0,
            "credential_state": "absent",
            "credential_ref": None,
            "status": "draft",
        }
        self.store.database.transaction(
            lambda: self.store.database.execute(
                queries.APPLY_INSERT_REGISTRY_CONNECTIONS, (self.connection, encode(record))
            )
        )

    def replace(self, revision=1, operation="op.replace", secret="synthetic-provider-secret"):
        return self.registry.set_provider_credential(
            "owner.local", self.connection, revision, operation, "replace", secret
        )

    def test_orphaned_successor_is_replaced_without_overwriting_selected_credential(self):
        self.vault.seal(self.connection, 1, "synthetic-orphaned-secret")
        self.store.close()
        self.store = SQLiteStore(self.root / "store.sqlite")
        self.addCleanup(self.store.close)
        self.vault = ProviderVault(self.root / "vault")
        self.registry = Registry(
            self.store,
            Authority(),
            legacy_destination=DEST,
            legacy_token=TOKEN,
            legacy_trusted=TRUSTED,
            provider_vault=self.vault,
        )
        reply = self.replace()
        self.assertEqual(reply["record"]["credential_version"], 1)
        self.assertEqual(self.vault.resolve(self.connection, 1), "synthetic-provider-secret")
        with self.assertRaises(ValueError):
            self.vault.seal(self.connection, 1, "must-not-replace", committed_version=1)
        self.assertEqual(self.vault.resolve(self.connection, 1), "synthetic-provider-secret")

    def test_lost_commit_acknowledgement_keeps_selected_secret_and_retry_is_idempotent(self):
        self.replace()
        transaction = self.store.database.transaction

        def lost_ack(action):
            transaction(action)
            raise RuntimeError("synthetic lost commit acknowledgement")

        with patch.object(self.store.database, "transaction", side_effect=lost_ack):
            with self.assertRaises(RuntimeError):
                self.replace(2, "op.rotate", "synthetic-rotated-secret")
        self.assertEqual(self.registry.connection(self.connection)["credential_version"], 2)
        self.assertEqual(self.vault.resolve(self.connection, 2), "synthetic-rotated-secret")
        reply = self.replace(2, "op.rotate", "synthetic-rotated-secret")
        self.assertEqual(reply["record"]["credential_version"], 2)
        self.assertEqual(self.registry.send_authority.epoch, self.registry.version())
        self.assertFalse(self.vault._path(self.connection, 1).exists())
        self.assertEqual(self.vault.resolve(self.connection, 2), "synthetic-rotated-secret")

    def test_admission_reads_one_revision_while_a_writer_waits(self):
        entered, release, writer_entered = threading.Event(), threading.Event(), threading.Event()
        principal = self.registry.principal
        before = self.registry.version()

        def held(identifier):
            value = principal(identifier)
            if identifier == TRUSTED["principal_id"] and not entered.is_set():
                entered.set()
                if not release.wait(3):
                    raise AssertionError("admission not released")
            return value

        def mutate():
            writer_entered.set()
            return self.registry.mutate(
                "owner.local",
                {
                    "operation_id": "op.disable",
                    "action": "model_state",
                    "subject": DEST["configuration_ref"],
                    "expected_revision": 1,
                    "data": {"status": "disabled", "reason": "synthetic test"},
                },
            )

        with (
            ThreadPoolExecutor(max_workers=2) as executor,
            patch.object(self.registry, "principal", side_effect=held),
        ):
            reader = executor.submit(
                self.registry.admit,
                TRUSTED["principal_id"],
                DEST["configuration_ref"],
                "execution",
                "class.demo",
            )
            try:
                self.assertTrue(entered.wait(1))
                writer = executor.submit(mutate)
                self.assertTrue(writer_entered.wait(1))
                self.assertFalse(writer.done())
            finally:
                release.set()
            destination, decision = reader.result(timeout=2)
            self.assertEqual(destination, DEST)
            self.assertEqual(decision["authority_revision"], before)
            writer.result(timeout=2)
        self.assertFalse(
            self.registry.explain(
                TRUSTED["principal_id"], DEST["configuration_ref"], "execution", "class.demo"
            )["allowed"]
        )
