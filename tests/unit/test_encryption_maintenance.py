"""Offline leases, reference-checked retirement, cache invalidation and publication faults."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
import errno
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from ezllmrouter_server.instance_lock import InstanceBusy, InstanceLease
from ezllmrouter_server.private_files import AtomicPublicationError, read_private, write_private
from ezllmrouter_server.provider_vault import ProviderVault
from ezllmrouter_server.secret_box import SecretBox, SecretBoxError
from ezllmrouter_server.secret_rotation import main as maintenance
from ezllmrouter_server.store import SQLiteStore
from tests.operator_console import test_integration_credentials as credential_fixtures
from tests.operator_console import test_local_connectors as connector_fixtures
from tests.unit.test_secret_rotation import stopped_store

SECRET = "synthetic-encryption-maintenance-credential"
ROOT = Path(__file__).resolve().parents[2]


class KeyringCacheTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / "keys.json"
        self.box = SecretBox(self.path, "test-cache")

    def test_unchanged_keyrings_are_not_reread_or_reparsed_for_each_operation(self):
        nonces = set()
        with patch("ezllmrouter_server.secret_box.read_private", wraps=read_private) as reads:
            for _ in range(32):
                envelope = self.box.seal(SECRET, b"context")
                nonces.add(envelope["nonce"])
                self.assertEqual(self.box.open(envelope, b"context"), SECRET)
                self.box.request_digest(b"request")
                self.assertTrue(self.box.identity.startswith("ring."))
                self.assertEqual(self.box.active_id, envelope["key_id"])
        reads.assert_not_called()
        self.assertEqual(len(nonces), 32)

    def test_other_instance_rotation_refreshes_the_cache_and_preserves_old_reads(self):
        envelope = self.box.seal(SECRET, b"context")
        before = self.box.request_digest(b"request")
        other = SecretBox(self.path, "test-cache")
        active = other.rotate()
        self.assertEqual(self.box.seal(SECRET, b"context")["key_id"], active)
        self.assertEqual(self.box.open(envelope, b"context"), SECRET)
        self.assertEqual(self.box.request_digest(b"request"), before)

    def test_cached_keyring_permissions_symlinks_and_deletion_fail_closed(self):
        self.path.chmod(0o644)
        with self.assertRaises(SecretBoxError):
            self.box.request_digest(b"request")
        self.path.chmod(0o600)
        saved = self.path.read_bytes()
        replacement = self.root / "replacement"
        write_private(replacement, saved)
        self.path.unlink()
        self.path.symlink_to(replacement)
        with self.assertRaises(SecretBoxError):
            self.box.request_digest(b"request")
        self.path.unlink()
        with self.assertRaises(SecretBoxError):
            self.box.request_digest(b"request")

    def test_corruption_is_not_hidden_by_a_previously_valid_cache(self):
        self.box.request_digest(b"request")
        self.path.write_bytes(b"invalid-keyring")
        with self.assertRaises(SecretBoxError):
            self.box.seal(SECRET, b"context")

    def test_failed_rotation_does_not_mutate_the_cached_or_published_state(self):
        before = self.path.read_bytes()
        active = self.box.active_id
        with patch(
            "ezllmrouter_server.secret_box.write_private", side_effect=OSError("controlled failure")
        ):
            with self.assertRaises(OSError):
                self.box.rotate()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.box.active_id, active)

    def test_retirement_refreshes_other_caches_without_changing_mac_identity(self):
        old = self.box.active_id
        old_envelope = self.box.seal(SECRET, b"context")
        identity = self.box.identity
        digest = self.box.request_digest(b"request")
        active = self.box.rotate()
        other = SecretBox(self.path, "test-cache")
        self.assertEqual(other.open(old_envelope, b"context"), SECRET)
        self.box.retire_key(old, referenced_ids=set(), backup_acknowledged=True)
        self.assertEqual(other.active_id, active)
        self.assertEqual(other.identity, identity)
        self.assertEqual(other.request_digest(b"request"), digest)
        with self.assertRaises(SecretBoxError):
            other.open(old_envelope, b"context")
        self.assertEqual(other.open(other.seal(SECRET, b"context"), b"context"), SECRET)

    def test_retirement_rejects_active_referenced_and_unreviewed_keys(self):
        old = self.box.active_id
        with self.assertRaises(SecretBoxError):
            self.box.retire_key(old, referenced_ids=set(), backup_acknowledged=True)
        self.box.rotate()
        with self.assertRaises(SecretBoxError):
            self.box.retire_key(old, referenced_ids={old}, backup_acknowledged=True)
        with self.assertRaises(SecretBoxError):
            self.box.retire_key(old, referenced_ids=set())
        self.assertIn(old, json.loads(self.path.read_bytes())["keys"])

    def test_cached_cipher_operations_remain_independent_across_threads(self):
        def roundtrip(i):
            context = str(i).encode()
            return self.box.open(self.box.seal(SECRET, context), context)

        with ThreadPoolExecutor(max_workers=8) as executor:
            self.assertEqual(list(executor.map(roundtrip, range(48))), [SECRET] * 48)


class LeaseTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.path = self.root / "service.sqlite"
        self.store = SQLiteStore(self.path)
        self.addCleanup(self.store.close)

    def test_service_is_exclusive_and_offline_readers_share_the_lease(self):
        with self.assertRaises(InstanceBusy):
            SQLiteStore(self.path)
        with self.assertRaises(InstanceBusy):
            SQLiteStore.open_existing(self.path)
        self.store.close()
        second = SQLiteStore.open_existing(self.path, read_only=True)
        self.addCleanup(second.close)
        third = SQLiteStore.open_existing(self.path, read_only=True)
        self.addCleanup(third.close)
        with self.assertRaises(InstanceBusy):
            SQLiteStore.open_existing(self.path, maintenance=True)
        with self.assertRaises(InstanceBusy):
            SQLiteStore(self.path)
        second.close()
        with self.assertRaises(InstanceBusy):
            SQLiteStore.open_existing(self.path, maintenance=True)
        third.close()
        maintenance_store = SQLiteStore.open_existing(self.path, maintenance=True)
        self.addCleanup(maintenance_store.close)
        with self.assertRaises(InstanceBusy):
            SQLiteStore(self.path)

    def test_shared_and_exclusive_leases_are_enforced_across_processes(self):
        script = (
            "import sys; sys.path.insert(0, "
            + repr(str(ROOT / "server/src"))
            + ")\nfrom ezllmrouter_server.instance_lock import InstanceLease, InstanceBusy\ntry:\n lease=InstanceLease(sys.argv[1], exclusive=True)\nexcept InstanceBusy:\n sys.exit(7)\nelse:\n lease.close()\n"
        )
        command = [sys.executable, "-I", "-S", "-c", script, str(self.path)]
        self.assertEqual(subprocess.run(command, capture_output=True, timeout=10).returncode, 7)
        self.store.close()
        result = subprocess.run(command, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_second_service_process_cannot_open_the_live_database(self):
        before = list(self.store.db.iterdump())
        script = (
            "import sys; sys.path.insert(0, " + repr(str(ROOT / "server/src")) + ")\n"
            "from ezllmrouter_server.store import SQLiteStore\n"
            "from ezllmrouter_server.instance_lock import InstanceBusy\n"
            "try:\n store=SQLiteStore(sys.argv[1])\n"
            "except InstanceBusy:\n sys.exit(7)\n"
            "else:\n store.close()\n"
        )
        command = [sys.executable, "-I", "-c", script, str(self.path)]
        result = subprocess.run(command, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(list(self.store.db.iterdump()), before)
        self.store.close()
        result = subprocess.run(command, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_sqlite_open_failure_releases_the_service_lease(self):
        self.store.close()
        with patch(
            "ezllmrouter_server.store.sqlite3.connect",
            side_effect=sqlite3.OperationalError("controlled open"),
        ):
            with self.assertRaises(sqlite3.OperationalError):
                SQLiteStore(self.path)
        lease = InstanceLease(self.path, exclusive=True)
        lease.close()

    def test_symlinked_lease_files_and_hard_linked_databases_are_rejected(self):
        self.store.close()
        alias = self.root / "alias.sqlite"
        os.link(self.path, alias)
        with self.assertRaises(ValueError):
            InstanceLease(alias)
        alias.unlink()
        lease_path = self.path.with_name(self.path.name + ".instance.lock")
        lease_path.unlink()
        target = self.root / "private"
        write_private(target, b"unchanged")
        lease_path.symlink_to(target)
        with self.assertRaises(OSError):
            InstanceLease(self.path)
        self.assertEqual(target.read_bytes(), b"unchanged")

    def test_cli_rejects_a_live_service_without_touching_key_material_or_error_logging(self):
        path = self.root / "integration.keys.json"
        SecretBox(path, "integration-credentials")
        before = path.read_bytes()
        with (
            patch("ezllmrouter_server.secret_rotation.configure_logging"),
            redirect_stderr(io.StringIO()),
            self.assertNoLogs("ezllmrouter", level="ERROR"),
        ):
            result = maintenance(
                ["rotate", "--scope", "integration", "--db", str(self.path), "--keyring", str(path)]
            )
        self.assertEqual(result, 1)
        self.assertEqual(path.read_bytes(), before)

    def test_backup_requires_the_same_offline_lease_before_creating_a_target(self):
        from ezllmrouter_server.integration_local import main

        backup = self.root / "backup.sqlite"
        args = ["--db", str(self.path), "--backup", str(backup)]
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(args)
        self.assertFalse(backup.exists())
        self.store.close()
        with redirect_stdout(io.StringIO()):
            main(args)
        with sqlite3.connect(backup) as restored:
            self.assertGreater(restored.execute("PRAGMA user_version").fetchone()[0], 0)


class RetirementCLITests(unittest.TestCase):
    setUp = credential_fixtures.CredentialTests.setUp
    connect = credential_fixtures.CredentialTests.connect

    def command(self, action, *extra):
        output, errors = io.StringIO(), io.StringIO()
        with (
            patch("ezllmrouter_server.secret_rotation.configure_logging"),
            stopped_store(self),
            redirect_stdout(output),
            redirect_stderr(errors),
        ):
            result = maintenance(
                [
                    action,
                    "--scope",
                    "integration",
                    "--db",
                    self.store.path,
                    "--keyring",
                    str(self.key_path),
                    *extra,
                ]
            )
        return result, output.getvalue(), errors.getvalue()

    def test_referenced_keys_cannot_retire_then_resume_allows_safe_retirement(self):
        self.connect()
        old = self.credentials.box.active_id
        mac = self.credentials.box.request_digest(b"request")
        self.credentials.box.rotate()
        before = self.key_path.read_bytes()
        with self.assertNoLogs("ezllmrouter", level="ERROR"):
            result, _, _ = self.command("retire", "--key-id", old, "--confirm-no-dependent-backups")
        self.assertEqual(result, 1)
        self.assertEqual(self.key_path.read_bytes(), before)
        self.assertEqual(self.command("resume")[0], 0)
        result, output, _ = self.command(
            "retire", "--key-id", old, "--confirm-no-dependent-backups"
        )
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output)["retired_key_id"], old)
        self.assertNotIn(old, json.loads(self.key_path.read_bytes())["keys"])
        self.assertEqual(self.credentials.box.request_digest(b"request"), mac)

    def test_retirement_requires_an_explicit_backup_dependency_confirmation(self):
        old = self.credentials.box.active_id
        before = self.key_path.read_bytes()
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            maintenance(
                [
                    "retire",
                    "--scope",
                    "integration",
                    "--db",
                    self.store.path,
                    "--keyring",
                    str(self.key_path),
                    "--key-id",
                    old,
                ]
            )
        self.assertEqual(self.key_path.read_bytes(), before)

    def test_missing_referenced_keys_remain_visible_as_rotation_errors(self):
        self.connect()
        old = self.credentials.box.active_id
        self.credentials.box.rotate()
        state = json.loads(self.key_path.read_bytes())
        del state["keys"][old]
        write_private(self.key_path, json.dumps(state).encode(), replace=True)
        before = self.key_path.read_bytes()
        with self.assertLogs("ezllmrouter", level="ERROR"):
            result, _, errors = self.command("rotate")
        self.assertEqual(result, 1)
        self.assertIn("Encryption maintenance failed", errors)
        self.assertEqual(self.key_path.read_bytes(), before)

    def test_provider_retirement_includes_sealed_files_with_unknown_registry_identity(self):
        vault = ProviderVault(self.root / "vault")
        old = vault.box.active_id
        vault.seal("conn.orphan", 1, SECRET)
        vault.box.rotate()
        with (
            patch("ezllmrouter_server.secret_rotation.configure_logging"),
            stopped_store(self),
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
            self.assertLogs("ezllmrouter", level="ERROR"),
        ):
            result = maintenance(
                [
                    "retire",
                    "--scope",
                    "provider",
                    "--db",
                    self.store.path,
                    "--vault",
                    str(vault.root),
                    "--key-id",
                    old,
                    "--confirm-no-dependent-backups",
                ]
            )
        self.assertEqual(result, 1)
        self.assertIn(old, json.loads(vault.key_path.read_bytes())["keys"])
        self.assertEqual(vault.resolve("conn.orphan", 1), SECRET)


class ConnectorRetirementTests(connector_fixtures.LocalFixture):
    def test_connector_keys_retire_only_after_stored_envelopes_are_rewritten(self):
        self.connector(api_key=SECRET)
        old = self.connectors.box.active_id
        self.connectors.box.rotate()
        args = ["--scope", "connectors", "--db", self.store.path]
        with stopped_store(self), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(
                maintenance(["retire", *args, "--key-id", old, "--confirm-no-dependent-backups"]), 1
            )
            self.assertEqual(maintenance(["resume", *args]), 0)
            self.assertEqual(
                maintenance(["retire", *args, "--key-id", old, "--confirm-no-dependent-backups"]), 0
            )
        self.assertNotIn(old, json.loads(self.connectors.key_path.read_bytes())["keys"])


class PublicationTests(unittest.TestCase):
    def test_unsupported_hard_links_fail_without_a_partial_target(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "secret"
            with patch(
                "ezllmrouter_server.private_files.os.link",
                side_effect=OSError(errno.EOPNOTSUPP, "unsupported"),
            ):
                with self.assertRaises(AtomicPublicationError) as failure:
                    write_private(path, b"complete-secret")
            self.assertFalse(failure.exception.published)
            self.assertFalse(path.exists())
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_directory_fsync_failure_reports_publication_uncertainty_and_keeps_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "secret"
            with patch(
                "ezllmrouter_server.private_files.os.fsync",
                side_effect=[None, OSError(errno.EINVAL, "unsupported")],
            ):
                with self.assertRaises(AtomicPublicationError) as failure:
                    write_private(path, b"complete-secret")
            self.assertTrue(failure.exception.published)
            self.assertEqual(read_private(path), b"complete-secret")
            self.assertEqual([p.name for p in Path(directory).iterdir()], ["secret"])

    def test_publication_never_implicitly_replaces_a_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "secret"
            write_private(path, b"first")
            with self.assertRaises(FileExistsError):
                write_private(path, b"second")
            self.assertEqual(read_private(path), b"first")
            write_private(path, b"second", replace=True)
            self.assertEqual(read_private(path), b"second")

    def test_private_reads_require_the_current_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "secret"
            write_private(path, b"private")
            with patch(
                "ezllmrouter_server.private_files.os.geteuid", return_value=os.geteuid() + 1
            ):
                with self.assertRaises(ValueError):
                    read_private(path)
