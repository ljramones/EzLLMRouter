"""Startup interruption and cleanup controls, without sockets or external calls."""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
from pathlib import Path
import secrets
import signal
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from ezllmrouter_server import integration_local
from ezllmrouter_server.integration_bootstrap import BootstrapError, SERVICES, ensure_services
from ezllmrouter_server.private_files import read_private, write_private
from ezllmrouter_server.registry import Registry
from ezllmrouter_server.store import SQLiteStore

ROOT = Path(__file__).resolve().parents[2]


class StartupRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def open_instance(self, name="instance"):
        directory = self.root / name
        directory.mkdir(exist_ok=True)
        self.database = directory / "service.sqlite"
        self.directory = directory / "secrets"
        self.directory.mkdir(mode=0o700, exist_ok=True)
        self.reopen()

    def reopen(self):
        self.store = SQLiteStore(self.database)
        self.addCleanup(self.store.close)
        self.registry = Registry(
            self.store,
            integration_local.NoSendAuthority(),
            legacy_destination=integration_local.DEST,
            legacy_token=secrets.token_urlsafe(48),
            legacy_trusted={"principal_id": "svc.bootstrap", "charging_owner_id": "team.bootstrap"},
        )

    def assert_bootstrapped(self):
        for service in SERVICES:
            path = self.directory / service.token_file
            token = read_private(path).decode().strip()
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(
                self.registry.credential_principal(token, "service")["principal_id"],
                service.principal_id,
            )
            self.assertEqual(self.registry.principal(service.principal_id)["revision"], 3)
            self.assertNotIn(token, "\n".join(self.store.db.iterdump()))

    def test_restart_preserves_tokens_revisions_and_audit(self):
        self.open_instance()
        ensure_services(self.registry, self.directory)
        self.assert_bootstrapped()
        saved = {path.name: path.read_bytes() for path in self.directory.iterdir()}
        before = self.store.db.execute("SELECT * FROM registry_audit ORDER BY seq").fetchall()
        version = self.registry.version()
        self.store.close()
        self.reopen()
        ensure_services(self.registry, self.directory)
        self.assert_bootstrapped()
        self.assertEqual(saved, {path.name: path.read_bytes() for path in self.directory.iterdir()})
        self.assertEqual(
            before, self.store.db.execute("SELECT * FROM registry_audit ORDER BY seq").fetchall()
        )
        self.assertEqual(version, self.registry.version())

    def test_interruption_after_each_account_commit_resumes_once(self):
        for service in SERVICES:
            for phase in ("principal", "activate"):
                with self.subTest(service=service.principal_id, phase=phase):
                    self.open_instance(service.token_file + "-" + phase)
                    mutate = self.registry.mutate

                    def interrupted(actor, request):
                        result = mutate(actor, request)
                        if request["operation_id"] == service.operation_prefix + "." + phase:
                            raise RuntimeError("interrupted after commit")
                        return result

                    with patch.object(self.registry, "mutate", side_effect=interrupted):
                        with self.assertRaisesRegex(RuntimeError, "interrupted"):
                            ensure_services(self.registry, self.directory)
                    saved = {path.name: path.read_bytes() for path in self.directory.iterdir()}
                    self.store.close()
                    self.reopen()
                    ensure_services(self.registry, self.directory)
                    self.assert_bootstrapped()
                    for name, value in saved.items():
                        self.assertEqual((self.directory / name).read_bytes(), value)
                    for action in ("create_principal", "provision_credential", "principal_state"):
                        count = self.store.db.execute(
                            "SELECT COUNT(*) FROM registry_audit WHERE subject=? AND action=?",
                            (service.principal_id, action),
                        ).fetchone()[0]
                        self.assertEqual(count, 1)

    def test_credential_database_failure_keeps_the_saved_token_for_retry(self):
        for service in SERVICES:
            with self.subTest(service=service.principal_id):
                self.open_instance(service.token_file)
                self.store.db.execute(
                    "CREATE TEMP TRIGGER interrupt_binding BEFORE INSERT ON registry_credentials "
                    "WHEN NEW.principal_id='" + service.principal_id + "' "
                    "BEGIN SELECT RAISE(ABORT, 'simulated database failure'); END"
                )
                with self.assertRaises(sqlite3.IntegrityError):
                    ensure_services(self.registry, self.directory)
                path = self.directory / service.token_file
                saved = read_private(path)
                self.assertEqual(
                    self.registry.principal(service.principal_id)["credential_state"], "unbound"
                )
                self.store.close()
                self.reopen()
                ensure_services(self.registry, self.directory)
                self.assert_bootstrapped()
                self.assertEqual(read_private(path), saved)

    def test_file_publication_failure_leaves_no_bound_credential_or_partial_file(self):
        self.open_instance()
        with patch(
            "ezllmrouter_server.private_files.os.link",
            side_effect=OSError("disk write interrupted"),
        ):
            with self.assertRaisesRegex(OSError, "interrupted"):
                ensure_services(self.registry, self.directory)
        self.assertEqual(list(self.directory.iterdir()), [])
        self.assertEqual(self.registry.principal("svc.integration")["credential_state"], "unbound")
        self.assertEqual(
            self.store.db.execute(
                "SELECT COUNT(*) FROM registry_credentials WHERE principal_id='svc.integration'"
            ).fetchone()[0],
            0,
        )
        ensure_services(self.registry, self.directory)
        self.assert_bootstrapped()

    def test_interruption_after_binding_does_not_create_another_credential(self):
        self.open_instance()
        provision = self.registry.provision_credential

        def interrupted(*args, **kwargs):
            result = provision(*args, **kwargs)
            raise RuntimeError("interrupted after credential commit")

        with patch.object(self.registry, "provision_credential", side_effect=interrupted):
            with self.assertRaises(RuntimeError):
                ensure_services(self.registry, self.directory)
        token = read_private(self.directory / "ingest.token")
        self.store.close()
        self.reopen()
        ensure_services(self.registry, self.directory)
        self.assert_bootstrapped()
        self.assertEqual(read_private(self.directory / "ingest.token"), token)
        count = self.store.db.execute(
            "SELECT COUNT(*) FROM registry_audit WHERE subject='svc.integration' "
            "AND action='provision_credential'"
        ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_private_tokens_left_by_a_fresh_database_are_adopted(self):
        self.open_instance()
        saved = {}
        for service in SERVICES:
            saved[service.token_file] = (secrets.token_urlsafe(48) + "\n").encode()
            write_private(self.directory / service.token_file, saved[service.token_file])
        ensure_services(self.registry, self.directory)
        self.assert_bootstrapped()
        for name, value in saved.items():
            self.assertEqual(read_private(self.directory / name), value)

    def test_existing_bound_credential_is_never_replaced_to_repair_a_file(self):
        for mode in ("missing", "mismatch", "public", "symlink"):
            with self.subTest(mode=mode):
                self.open_instance(mode)
                ensure_services(self.registry, self.directory)
                original = self.store.db.execute(
                    "SELECT * FROM registry_credentials ORDER BY principal_id"
                ).fetchall()
                path = self.directory / "ingest.token"
                path.unlink()
                if mode == "mismatch":
                    write_private(path, (secrets.token_urlsafe(48) + "\n").encode())
                elif mode == "public":
                    path.write_text("synthetic-secret-" * 4)
                    path.chmod(0o644)
                elif mode == "symlink":
                    path.symlink_to(self.directory / "consumer.token")
                with self.assertRaises(BootstrapError):
                    ensure_services(self.registry, self.directory)
                self.assertEqual(
                    original,
                    self.store.db.execute(
                        "SELECT * FROM registry_credentials ORDER BY principal_id"
                    ).fetchall(),
                )
                if mode == "missing":
                    self.assertFalse(path.exists())

    def test_suspended_and_revoked_accounts_stay_disabled(self):
        self.open_instance()
        ensure_services(self.registry, self.directory)
        for service, status in zip(SERVICES, ("suspended", "revoked")):
            self.registry.mutate(
                "owner.local",
                {
                    "operation_id": "op.disable." + service.principal_id,
                    "action": "principal_state",
                    "subject": service.principal_id,
                    "expected_revision": 3,
                    "data": {"status": status, "reason": "owner choice"},
                },
            )
        version = self.registry.version()
        ensure_services(self.registry, self.directory)
        self.assertEqual(self.registry.version(), version)
        for service, status in zip(SERVICES, ("suspended", "revoked")):
            self.assertEqual(self.registry.principal(service.principal_id)["status"], status)

    def test_bootstrap_does_not_take_over_an_unrelated_reserved_identity(self):
        self.open_instance()
        self.registry.mutate(
            "owner.local",
            {
                "operation_id": "op.unrelated.create",
                "action": "create_principal",
                "subject": "svc.integration",
                "expected_revision": 0,
                "data": {
                    "display_name": "Unrelated identity",
                    "kind": "service",
                    "owner": "owner.local",
                },
            },
        )
        with self.assertRaisesRegex(BootstrapError, "conflicts"):
            ensure_services(self.registry, self.directory)
        self.assertEqual(self.registry.principal("svc.integration")["credential_state"], "unbound")
        self.assertFalse((self.directory / "ingest.token").exists())

    def test_secret_factory_runs_only_after_authorization_and_never_on_replay(self):
        self.open_instance()
        service = SERVICES[0]
        self.registry.mutate(
            "owner.local",
            {
                "operation_id": service.operation_prefix + ".principal",
                "action": "create_principal",
                "subject": service.principal_id,
                "expected_revision": 0,
                "data": {
                    "display_name": service.display_name,
                    "kind": "service",
                    "owner": "owner.local",
                    "role": "ordinary",
                },
            },
        )
        factory = Mock(return_value=secrets.token_urlsafe(48))
        with self.assertRaises(PermissionError):
            self.registry.provision_credential(
                "svc.bootstrap", service.principal_id, 1, "op.denied", secret_factory=factory
            )
        factory.assert_not_called()
        first = self.registry.provision_credential(
            "owner.local", service.principal_id, 1, "op.once", secret_factory=factory
        )
        second = self.registry.provision_credential(
            "owner.local", service.principal_id, 1, "op.once", secret_factory=factory
        )
        self.assertEqual(factory.call_count, 1)
        self.assertEqual(first[1], factory.return_value)
        self.assertIsNone(second[1])


class EntryPointTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.database = self.directory / "service.sqlite"
        self.secrets = self.directory / "secrets"
        self.arguments = [
            "--db",
            str(self.database),
            "--secrets-dir",
            str(self.secrets),
            "--web-root",
            str(ROOT / "web"),
        ]
        self.stores = []
        self.output, self.errors = io.StringIO(), io.StringIO()

    def store_factory(self, path):
        store = SQLiteStore(path)
        store.close = Mock(wraps=store.close)
        self.stores.append(store)
        return store

    def invoke(self, *, operator_error=None):
        stopped = threading.Event()
        api, operator = Mock(), Mock()
        self.api, self.operator = api, operator
        self.api_bind = Mock(return_value=api)
        self.operator_bind = Mock(return_value=operator, side_effect=operator_error)
        operator.serve_forever.side_effect = lambda: stopped.wait(timeout=5)
        operator.shutdown.side_effect = stopped.set
        installed_signals = []

        def install(number, handler):
            installed_signals.append((number, handler))
            return signal.SIG_DFL

        with ExitStack() as cleanup:
            cleanup.enter_context(redirect_stdout(self.output))
            cleanup.enter_context(redirect_stderr(self.errors))
            cleanup.enter_context(
                patch.object(integration_local, "SQLiteStore", side_effect=self.store_factory)
            )
            cleanup.enter_context(patch.object(integration_local, "api_serve", self.api_bind))
            cleanup.enter_context(
                patch.object(integration_local, "operator_serve", self.operator_bind)
            )
            cleanup.enter_context(
                patch.object(integration_local.signal, "signal", side_effect=install)
            )
            integration_local.main(self.arguments)
        return api, operator, installed_signals

    def test_existing_empty_database_initializes_and_exits_cleanly(self):
        SQLiteStore(self.database).close()
        api, operator, installed = self.invoke()
        api.server_close.assert_called_once()
        operator.server_close.assert_called_once()
        operator.operator_jobs.shutdown.assert_called_once_with(wait=True)
        self.stores[0].close.assert_called_once()
        with self.assertRaises(sqlite3.ProgrammingError):
            self.stores[0].db.execute("SELECT 1")
        self.assertEqual(
            [number for number, _ in installed],
            [signal.SIGINT, signal.SIGTERM, signal.SIGTERM, signal.SIGINT],
        )
        self.assertEqual(
            [handler for _, handler in installed[-2:]], [signal.SIG_DFL, signal.SIG_DFL]
        )
        for name in (
            "ingest.token",
            "consumer.token",
            "operator.password",
            "admin.password",
            "admin.token",
        ):
            token = read_private(self.secrets / name).decode().strip()
            self.assertNotIn(token, self.output.getvalue())

    def test_bind_failure_closes_database_and_preserves_tokens_for_retry(self):
        with self.assertRaisesRegex(OSError, "occupied"):
            self.invoke(operator_error=OSError("operator port occupied"))
        self.api.server_close.assert_called_once()
        self.stores[0].close.assert_called_once()
        tokens = {
            name: read_private(self.secrets / name) for name in ("ingest.token", "consumer.token")
        }
        self.invoke()
        for name, value in tokens.items():
            self.assertEqual(read_private(self.secrets / name), value)

    def test_registry_setup_failure_closes_the_database(self):
        with patch.object(
            integration_local, "Registry", side_effect=RuntimeError("setup interrupted")
        ):
            with self.assertRaisesRegex(RuntimeError, "setup interrupted"):
                self.invoke()
        self.stores[0].close.assert_called_once()

    def test_bootstrap_file_error_is_actionable_and_starts_no_listener(self):
        self.invoke()
        (self.secrets / "ingest.token").unlink()
        with self.assertRaises(SystemExit) as error:
            self.invoke()
        self.assertEqual(error.exception.code, 2)
        self.assertIn("restore the original private token file", self.errors.getvalue())
        self.api_bind.assert_not_called()
        self.operator_bind.assert_not_called()
        self.stores[-1].close.assert_called_once()
