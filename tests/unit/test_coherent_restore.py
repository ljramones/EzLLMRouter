"""Restore the documented database/keyring set using only disposable synthetic data."""

from contextlib import redirect_stdout
import io
from pathlib import Path
import shutil
import unittest

from ezllmrouter_server.integration_credentials import DatabaseCredentialStore
from ezllmrouter_server.integration_local import main as local_main
from ezllmrouter_server.local_connectors import LocalConnectors
from ezllmrouter_server.private_files import write_private
from ezllmrouter_server.provider_vault import ProviderVault
from ezllmrouter_server.registry import Registry
from ezllmrouter_server.secret_box import SecretBoxError
from ezllmrouter_server.store import SQLiteStore
from tests.operator_console import test_integration_credentials as fixtures
from tests.operator_console.accounting_support import EXAMPLES


class CoherentRestoreTests(unittest.TestCase):
    def test_complete_snapshot_restores_all_three_credential_scopes_and_accounting(self):
        fixture = fixtures.CredentialTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        pending = fixture.connect()
        fixture.credentials.save(
            fixture.owner,
            pending["account_id"],
            {
                "dataset_id": fixture.dataset,
                "expected_revision": pending["revision"],
                "selected_models": ["claude-opus-4-8"],
                "allowed_operations": [],
            },
        )
        local_key = "synthetic-restored-local-key-000001"
        provider_key = "synthetic-restored-provider-key-000001"
        connectors = LocalConnectors(fixture.registry)
        self.addCleanup(connectors.close)
        connector = connectors.create(
            "owner.local",
            {
                "display_name": "Restored synthetic connector",
                "kind": "ollama",
                "base_url": "http://localhost:11434",
                "api_key": local_key,
            },
        )
        vault = ProviderVault(fixture.root / "provider")
        vault.seal("conn.restore", 1, provider_key)
        ledger = fixture.registry.integration
        dataset = {**EXAMPLES["dataset"], "ingest_principal_id": "svc.integration"}
        ledger.create_dataset(fixture.owner, dataset)
        ledger.create_account(fixture.owner, EXAMPLES["account"])
        for event in EXAMPLES["events"]:
            ledger.append_event(fixture.registry.principal("svc.integration"), event)
        before = ledger.report(fixture.owner, dataset["dataset_id"])
        self.assertEqual(before["known_total_by_currency"], {"USD": "0.050000000"})
        for secret in (local_key, provider_key, "known-fixture-api-key-0001"):
            self.assertNotIn(secret, "\n".join(fixture.store.db.iterdump()))

        connectors.close()
        fixture.store.close()
        snapshot = fixture.root / "snapshot"
        snapshot.mkdir(mode=0o700)
        database = snapshot / "service.sqlite"
        with redirect_stdout(io.StringIO()):
            local_main(["--db", str(fixture.root / "service.sqlite"), "--backup", str(database)])
        shutil.copytree(fixture.root / "secrets", snapshot / "secrets")
        shutil.copytree(
            Path(str(fixture.root / "service.sqlite") + ".secrets"),
            Path(str(database) + ".secrets"),
        )
        shutil.copytree(fixture.root / "provider", snapshot / "provider")

        restored = SQLiteStore(database)
        self.addCleanup(restored.close)
        registry = Registry(restored, fixtures.Authority())
        credentials = DatabaseCredentialStore(
            registry,
            snapshot / "secrets/integration.keys.json",
            discover=lambda *_args, **_kwargs: self.fail("restore must not discover providers"),
            controlled=True,
        )
        consumer = registry.credential_principal(fixture.consumer_token)
        released = credentials.resolve_for(
            consumer,
            fixture.dataset,
            pending["account_id"],
            "claude-opus-4-8",
            "generation",
            "ezllmrouter-provider-dispatch",
        )
        self.assertEqual(released["api_key"], "known-fixture-api-key-0001")
        local = LocalConnectors(registry)
        self.addCleanup(local.close)
        _, sealed = local._load(restored.database, connector["connector_id"])
        self.assertEqual(local._resolve(connector["connector_id"], sealed), local_key)
        provider = ProviderVault(snapshot / "provider", require_existing=True)
        self.assertEqual(provider.resolve("conn.restore", 1), provider_key)
        after = registry.integration.report(
            registry.principal("owner.local"), dataset["dataset_id"]
        )
        self.assertEqual(after["known_total_by_currency"], before["known_total_by_currency"])
        self.assertEqual(after["attempts"], before["attempts"])
        self.assertEqual(restored.db.execute("PRAGMA quick_check").fetchone()[0], "ok")

        for path, reopen in (
            (credentials.key_path, lambda: DatabaseCredentialStore(registry, credentials.key_path)),
            (local.key_path, lambda: LocalConnectors(registry)),
            (
                provider.key_path,
                lambda: ProviderVault(snapshot / "provider", require_existing=True),
            ),
        ):
            with self.subTest(missing_keyring=path.name):
                original = path.read_bytes()
                path.unlink()
                try:
                    with self.assertRaises(SecretBoxError):
                        reopen()
                    self.assertFalse(path.exists(), "missing key material must not be regenerated")
                finally:
                    write_private(path, original)
