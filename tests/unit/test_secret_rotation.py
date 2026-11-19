"""Day-zero key separation and interrupted rotation, using temporary stores only."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
import base64
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from duranki_server.integration_credentials import DatabaseCredentialStore
from duranki_server.local_connectors import ConnectorError, LocalConnectors
from duranki_server.private_files import write_private
from duranki_server.provider_vault import ProviderVault
from duranki_server.secret_box import SecretBox, SecretBoxError
from duranki_server.secret_rotation import main as maintenance
from tests.operator_console import test_integration_credentials as credential_fixtures
from tests.operator_console import test_local_connectors as connector_fixtures


SECRET = "synthetic-encryption-test-credential"


class SecretBoxTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "keys.json"
        self.box = SecretBox(self.path, "test-purpose")

    def test_purposes_and_mac_use_independent_keys(self):
        boxes = [self.box, SecretBox(self.root / "other.keys.json", "other-purpose")]
        keys = []
        for box in boxes:
            state = json.loads(box.path.read_text())
            keys.extend([state["mac_key"], *state["keys"].values()])
            self.assertEqual(box.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(len(set(keys)), 4)
        self.assertNotEqual(boxes[0].request_digest(b"request"), boxes[1].request_digest(b"request"))

    def test_ciphertext_is_bound_to_purpose_record_and_key_id(self):
        envelope = self.box.seal(SECRET, b"record.one")
        for mutation, context in (({}, b"record.two"), ({"purpose": "other"}, b"record.one"),
                ({"key_id": "unknown"}, b"record.one"), ({"version": True}, b"record.one"),
                ({"ciphertext": base64.b64encode(b"tampered").decode()}, b"record.one")):
            with self.subTest(mutation=tuple(mutation), context=context):
                with self.assertRaises(SecretBoxError):
                    self.box.open({**envelope, **mutation}, context)
        self.assertEqual(self.box.open(envelope, b"record.one"), SECRET)
        with self.assertRaises(SecretBoxError):
            SecretBox(self.path, "other-purpose")

    def test_rotation_preserves_reads_and_mac_and_refreshes_other_instances(self):
        other = SecretBox(self.path, "test-purpose")
        original = self.box.seal(SECRET, b"record")
        digest = self.box.request_digest(b"request")
        identity = self.box.identity
        active = self.box.rotate()
        self.assertNotEqual(active, original["key_id"])
        self.assertEqual(other.open(original, b"record"), SECRET)
        self.assertEqual(other.seal(SECRET, b"record")["key_id"], active)
        self.assertEqual(other.request_digest(b"request"), digest)
        self.assertEqual(other.identity, identity)

    def test_failed_key_publication_keeps_previous_keyring(self):
        saved = self.path.read_bytes()
        with patch("duranki_server.private_files.os.replace", side_effect=OSError("injected")):
            with self.assertRaises(OSError):
                self.box.rotate()
        self.assertEqual(self.path.read_bytes(), saved)
        self.assertFalse(list(self.root.glob("*.new")))
        self.assertEqual(self.box.open(self.box.seal(SECRET, b"record"), b"record"), SECRET)

    def test_concurrent_key_publication_retains_all_versions(self):
        def rotate(_):
            return SecretBox(self.path, "test-purpose").rotate()
        with ThreadPoolExecutor(max_workers=4) as executor:
            identifiers = list(executor.map(rotate, range(8)))
        state = json.loads(self.path.read_text())
        self.assertEqual(len(state["keys"]), 9)
        self.assertTrue(set(identifiers) <= state["keys"].keys())

    def test_missing_public_or_symlinked_keys_are_never_replaced(self):
        saved = self.path.read_bytes()
        self.path.chmod(0o644)
        with self.assertRaises(SecretBoxError):
            self.box.rotate()
        self.path.chmod(0o600)
        self.path.unlink()
        with self.assertRaises(SecretBoxError):
            SecretBox(self.path, "test-purpose", required=True)
        self.assertFalse(self.path.exists())
        target = self.root / "private.json"
        write_private(target, saved)
        self.path.symlink_to(target)
        with self.assertRaises(SecretBoxError):
            SecretBox(self.path, "test-purpose")
        self.assertEqual(target.read_bytes(), saved)

    def test_maintenance_does_not_initialize_an_unrelated_database(self):
        path = self.root / "uninitialized.sqlite"
        connection = sqlite3.connect(path)
        connection.close()
        saved = self.path.read_bytes()
        with redirect_stderr(io.StringIO()):
            self.assertEqual(maintenance(["rotate", "--scope", "integration", "--db", str(path),
                                         "--keyring", str(self.path)]), 1)
        with sqlite3.connect(path) as connection:
            self.assertEqual(connection.execute("SELECT name FROM sqlite_master").fetchall(), [])
        self.assertEqual(self.path.read_bytes(), saved)


class ProviderRotationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.vault = ProviderVault(self.root / "vault")
        for version in (1, 2):
            self.vault.seal("conn.test", version, SECRET + str(version))

    def test_rotation_preserves_all_credential_versions_and_idempotency(self):
        digest = self.vault.request_digest(b"request")
        result = self.vault.rotate_encryption_key(["conn.test"])
        self.assertEqual(result["rewritten"], 2)
        reopened = ProviderVault(self.vault.root, require_existing=True)
        for version in (1, 2):
            self.assertEqual(reopened.resolve("conn.test", version), SECRET + str(version))
            envelope = json.loads(reopened._path("conn.test", version).read_text())
            self.assertEqual(envelope["key_id"], result["key_id"])
        self.assertEqual(reopened.request_digest(b"request"), digest)
        self.assertEqual(reopened.reencrypt_secrets(["conn.test"]), 0)

    def test_interrupted_file_rotation_reopens_and_resumes(self):
        original_write = write_private
        writes = []
        def fail_second(path, value, **kwargs):
            writes.append(path)
            if len(writes) == 2:
                raise OSError("injected interruption")
            return original_write(path, value, **kwargs)
        with patch("duranki_server.provider_vault.write_private", side_effect=fail_second):
            with self.assertRaises(OSError):
                self.vault.rotate_encryption_key(["conn.test"])
        reopened = ProviderVault(self.vault.root, require_existing=True)
        for version in (1, 2):
            self.assertEqual(reopened.resolve("conn.test", version), SECRET + str(version))
        self.assertEqual(reopened.reencrypt_secrets(["conn.test"]), 1)

    def test_swapped_ciphertext_and_unknown_file_identity_fail_closed(self):
        self.vault.seal("conn.other", 1, SECRET)
        write_private(self.vault._path("conn.other", 1), self.vault._path("conn.test", 1).read_bytes(), replace=True)
        with self.assertRaises(SecretBoxError):
            self.vault.resolve("conn.other", 1)
        with self.assertRaises(SecretBoxError):
            self.vault.reencrypt_secrets(["conn.test"])

    def test_missing_keyring_never_creates_a_replacement(self):
        self.vault.key_path.unlink()
        with self.assertRaises(SecretBoxError):
            ProviderVault(self.vault.root)
        self.assertFalse(self.vault.key_path.exists())

    def test_keyring_remains_required_after_provider_credentials_are_removed(self):
        for version in (1, 2):
            self.vault.remove("conn.test", version)
        self.vault.key_path.unlink()
        with self.assertRaises(SecretBoxError):
            ProviderVault(self.vault.root, require_existing=True)
        self.assertFalse(self.vault.key_path.exists())


class IntegrationRotationTests(unittest.TestCase):
    setUp = credential_fixtures.CredentialTests.setUp
    connect = credential_fixtures.CredentialTests.connect

    def test_rotation_preserves_binding_versions_history_and_request_retries(self):
        item = self.connect()
        account = item["account_id"]
        item = self.credentials.save(self.owner, account, {"dataset_id": self.dataset,
            "expected_revision": item["revision"], "selected_models": ["claude-opus-4-8"],
            "allowed_operations": []})
        item = self.credentials.replace(self.owner, account, {"dataset_id": self.dataset,
            "expected_revision": item["revision"], "api_key": SECRET})
        binding = self.credentials._binding(account)
        history = self.store.db.execute("SELECT * FROM integration_credential_operations").fetchall()
        result = self.credentials.rotate_encryption_key()
        self.assertEqual(result["rewritten"], 2)
        reopened = DatabaseCredentialStore(self.registry, self.key_path, discover=self.credentials.discover)
        self.assertEqual(reopened._binding(account), binding)
        self.assertEqual(reopened._resolve(binding, binding["pending_version"]), SECRET)
        self.assertEqual(reopened._resolve(binding, 1), "known-fixture-api-key-0001")
        self.assertEqual(self.store.db.execute("SELECT * FROM integration_credential_operations").fetchall(), history)
        calls = len(self.calls)
        self.assertEqual(self.connect()["account_id"], account)
        self.assertEqual(len(self.calls), calls)

    def test_failed_database_rotation_rolls_back_ciphertext_then_resumes(self):
        first = self.connect()
        second = self.connect(key=SECRET, operation="op.connect.2")
        rows = self.store.db.execute("SELECT * FROM integration_credential_versions ORDER BY account_id").fetchall()
        seal = self.credentials.box.seal_parts
        count = 0
        def fail_second(*args):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError("injected interruption")
            return seal(*args)
        with patch.object(self.credentials.box, "seal_parts", side_effect=fail_second):
            with self.assertRaises(OSError):
                self.credentials.rotate_encryption_key()
        self.assertEqual(self.store.db.execute(
            "SELECT * FROM integration_credential_versions ORDER BY account_id").fetchall(), rows)
        reopened = DatabaseCredentialStore(self.registry, self.key_path, discover=self.credentials.discover)
        self.assertEqual(reopened._resolve(first, 1), "known-fixture-api-key-0001")
        self.assertEqual(reopened._resolve(second, 1), SECRET)
        self.assertEqual(reopened.reencrypt_secrets(), 2)

    def test_cli_rotate_and_resume_work_without_network_or_registry_mutations(self):
        self.connect()
        operations = self.store.db.execute("SELECT * FROM registry_operations").fetchall()
        output = io.StringIO()
        args = ["--scope", "integration", "--db", str(self.root / "service.sqlite"),
                "--keyring", str(self.key_path)]
        with redirect_stdout(output):
            self.assertEqual(maintenance(["rotate", *args]), 0)
            self.assertEqual(maintenance(["resume", *args]), 0)
        first, second = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(first["key_id"], second["key_id"])
        self.assertEqual((first["rewritten"], second["rewritten"]), (1, 0))
        self.assertEqual(self.store.db.execute("SELECT * FROM registry_operations").fetchall(), operations)
        self.assertNotIn("known-fixture-api-key-0001", output.getvalue())

    def test_provider_registry_operation_replays_after_encryption_rotation(self):
        vault = ProviderVault(self.root / "provider-vault")
        self.registry.provider_vault = vault
        self.registry.mutate("owner.local", {"operation_id": "op.connection", "action": "create_connection",
            "subject": "conn.encryption", "expected_revision": 0, "data": {
                "display_name": "Synthetic encryption test", "adapter_id": "openai.responses.v1",
                "settings": {"origin": "https://api.openai.com", "location": "commercial", "site": "owner.local"},
                "owner": "owner.local"}})
        def replace():
            return self.registry.set_provider_credential("owner.local", "conn.encryption", 1,
                "op.provider.credential", "replace", SECRET)
        result = replace()
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(maintenance(["rotate", "--scope", "provider", "--db", self.store.path,
                                         "--vault", str(vault.root)]), 0)
        self.assertEqual(json.loads(output.getvalue())["rewritten"], 1)
        self.assertEqual(replace(), result)
        self.assertEqual(vault.resolve("conn.encryption", 1), SECRET)


class ConnectorRotationTests(connector_fixtures.LocalFixture):

    def test_rotation_and_reads_do_not_depend_on_other_attached_subsystems(self):
        item = self.connector(api_key=SECRET)
        before = self.connectors.get("owner.local", item["connector_id"])
        self.registry.integration_credentials = object()
        self.registry.provider_vault = object()
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(maintenance(["rotate", "--scope", "connectors", "--db", self.store.path]), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["rewritten"], 1)
        reopened = LocalConnectors(self.registry)
        self.addCleanup(reopened.close)
        raw = self.store.db.execute("SELECT secret FROM local_connectors WHERE id=?",
                                   (item["connector_id"],)).fetchone()[0]
        self.assertEqual(reopened._resolve(item["connector_id"], raw), SECRET)
        self.assertEqual(reopened.get("owner.local", item["connector_id"]), before)

    def test_failed_connector_rotation_rolls_back_and_resumes(self):
        for _ in range(2):
            self.connector(api_key=SECRET)
        rows = self.store.db.execute("SELECT id,secret FROM local_connectors ORDER BY id").fetchall()
        seal = self.connectors.box.seal
        count = 0
        def fail_second(*args):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError("injected interruption")
            return seal(*args)
        with patch.object(self.connectors.box, "seal", side_effect=fail_second):
            with self.assertRaises(OSError):
                self.connectors.rotate_encryption_key()
        self.assertEqual(self.store.db.execute("SELECT id,secret FROM local_connectors ORDER BY id").fetchall(), rows)
        for identifier, raw in rows:
            self.assertEqual(self.connectors._resolve(identifier, raw), SECRET)
        self.assertEqual(self.connectors.reencrypt_secrets(), 2)

    def test_invalid_short_keys_are_rejected_consistently(self):
        with self.assertRaises(ConnectorError):
            self.connector(api_key="too-short")


if __name__ == "__main__":
    unittest.main()
