"""Socket-free bootstrap, credential-release and connection-budget regressions."""
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from tests.operator_console import test_user_management as user_fixtures
from tests.operator_console import test_integration_credentials as credential_fixtures
from duranki_server.http_server import BoundedThreadingMixIn, SafeHTTPRequestHandler, REQUEST_TIMEOUT_SECONDS
from duranki_server.private_files import read_private, secret_text, write_private
from duranki_server.user_management import UserManager, UserError, password_hash


class PrivateFileTests(unittest.TestCase):
    def test_random_private_secret_is_reused_and_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "secrets/admin.password"
            first = secret_text(path)
            self.assertGreaterEqual(len(first), 48)
            self.assertEqual(secret_text(path), first)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                write_private(path, b"replacement")
            self.assertEqual(read_private(path).decode().strip(), first)

    def test_failure_before_publication_leaves_no_partial_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "admin.password"
            with patch("duranki_server.private_files.os.link", side_effect=OSError("publication failed")):
                with self.assertRaises(OSError):
                    write_private(path, b"complete-secret")
            self.assertFalse(path.exists())
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_symlinks_and_public_files_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "private"
            write_private(private, b"private-secret")
            link = Path(directory) / "link"
            link.symlink_to(private)
            with self.assertRaises(OSError):
                read_private(link)
            private.chmod(0o644)
            with self.assertRaises(ValueError):
                read_private(private)


class BootstrapTests(unittest.TestCase):
    setUp = user_fixtures.UserFixture.setUp

    def test_fresh_database_has_a_random_bootstrap_password_and_no_shared_login(self):
        self.store.db.execute("DELETE FROM console_users")
        path = Path(self.tmp.name) / "bootstrap/admin.password"
        with patch.dict(os.environ, {}, clear=True):
            users = UserManager(self.registry, bootstrap_password_file=path)
        password = read_private(path).decode().strip()
        self.assertTrue(users.authenticate("admin", password)["must_change_password"])
        with self.assertRaises(UserError):
            users.authenticate("admin", "ChangeMeNow!")
        with patch.dict(os.environ, {}, clear=True):
            UserManager(self.registry, bootstrap_password_file=path)
        self.assertEqual(read_private(path).decode().strip(), password)
        self.assertNotIn(password, "\n".join(self.store.db.iterdump()))

    def test_bootstrap_resumes_using_the_private_file_after_a_transaction_failure(self):
        self.store.db.execute("DELETE FROM console_users")
        path = Path(self.tmp.name) / "bootstrap/admin.password"
        calls = 0
        def failing_hash(value):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("database bootstrap interrupted")
            return password_hash(value)
        with patch.dict(os.environ, {}, clear=True), patch("duranki_server.user_management.password_hash", side_effect=failing_hash):
            with self.assertRaises(RuntimeError):
                UserManager(self.registry, bootstrap_password_file=path)
        password = read_private(path).decode().strip()
        with patch.dict(os.environ, {}, clear=True):
            users = UserManager(self.registry, bootstrap_password_file=path)
        self.assertTrue(users.authenticate("admin", password)["must_change_password"])

    def test_invalid_explicit_bootstrap_password_has_a_clear_error(self):
        self.store.db.execute("DELETE FROM console_users")
        with patch.dict(os.environ, {"EZLLMROUTER_ADMIN_PASSWORD": "short"}, clear=True):
            with self.assertRaises(UserError) as raised:
                UserManager(self.registry)
        self.assertEqual(raised.exception.code, "BOOTSTRAP_PASSWORD_REQUIRES_12_TO_256_CHARACTERS")
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM console_users").fetchone()[0], 0)

    def test_inactive_admin_can_be_demoted_without_removing_the_active_admin(self):
        other = self.users.create("owner.local", {"username": "second-admin", "display_name": "Second admin",
            "role": "registry_admin", "status": "active", "password": user_fixtures.PASSWORD})
        other = self.users.update("owner.local", other["principal_id"], {"expected_revision": other["revision"],
            "username": other["username"], "display_name": other["display_name"], "role": other["role"], "status": "suspended"})
        self.registry.mutate("owner.local", {"operation_id": "op.demote.inactive", "action": "set_role",
            "subject": other["principal_id"], "expected_revision": other["revision"], "data": {"role": "ordinary"}})
        self.assertEqual(self.registry.principal(other["principal_id"])["role"], "ordinary")
        self.assertEqual(self.registry.principal("owner.local")["role"], "registry_admin")


class CredentialAuditTests(unittest.TestCase):
    setUp = credential_fixtures.CredentialTests.setUp
    connect = credential_fixtures.CredentialTests.connect

    def saved(self):
        pending = self.connect()
        return self.credentials.save(self.owner, pending["account_id"], {"dataset_id": self.dataset,
            "expected_revision": pending["revision"], "selected_models": ["claude-opus-4-8"], "allowed_operations": []})

    def test_each_credential_release_commits_metadata_only_audit(self):
        item = self.saved()
        for _ in range(2):
            resolved = self.credentials.resolve_for(self.consumer, self.dataset, item["account_id"],
                "claude-opus-4-8", "generation", "vega-provider-dispatch")
            self.assertEqual(resolved["api_key"], "known-fixture-api-key-0001")
        rows = self.store.db.execute("SELECT a.actor,a.subject,v.after_json FROM registry_audit a "
            "JOIN registry_audit_values v ON a.seq=v.seq WHERE a.action='credential_resolved'").fetchall()
        self.assertEqual(len(rows), 2)
        for actor, account, raw in rows:
            self.assertEqual(actor, self.consumer["principal_id"])
            self.assertEqual(account, item["account_id"])
            facts = json.loads(raw)
            self.assertEqual(facts["credential_version"], 1)
            self.assertEqual(facts["purpose"], "vega-provider-dispatch")
            self.assertNotIn("known-fixture-api-key", raw)

    def test_audit_transaction_failure_prevents_plaintext_release(self):
        item = self.saved()
        self.store.db.execute("CREATE TEMP TRIGGER reject_key_audit BEFORE INSERT ON registry_audit "
            "WHEN NEW.action='credential_resolved' BEGIN SELECT RAISE(ABORT, 'audit unavailable'); END")
        with patch.object(self.credentials, "_resolve") as decrypt:
            with self.assertRaises(sqlite3.IntegrityError):
                self.credentials.resolve_for(self.consumer, self.dataset, item["account_id"],
                    "claude-opus-4-8", "generation", "vega-provider-dispatch")
        decrypt.assert_not_called()


class HTTPBudgetTests(unittest.TestCase):
    def test_connections_are_bounded_and_slots_are_released(self):
        entered = threading.Barrier(3)
        completed = threading.Barrier(3)
        release = threading.Event()
        closed = []
        class Base:
            def __init__(self):
                pass
            def finish_request(self, request, address):
                entered.wait(timeout=3)
                release.wait(timeout=3)
            def shutdown_request(self, request):
                closed.append(request)
        class Server(BoundedThreadingMixIn, Base):
            def process_request_thread(self, request, address):
                super().process_request_thread(request, address)
                completed.wait(timeout=3)
        server = Server(max_connections=2)
        try:
            server.process_request("first", None)
            server.process_request("second", None)
            entered.wait(timeout=3)
            server.process_request("excess", None)
            self.assertIn("excess", closed)
            self.assertFalse(server._connection_slots.acquire(blocking=False))
        finally:
            release.set()
            completed.wait(timeout=3)
        self.assertTrue(server._connection_slots.acquire(blocking=False))
        self.assertTrue(server._connection_slots.acquire(blocking=False))
        self.assertFalse(server._connection_slots.acquire(blocking=False))
        server._connection_slots.release()
        server._connection_slots.release()

    def test_absolute_input_deadline_interrupts_a_dribbling_connection(self):
        handler = SafeHTTPRequestHandler.__new__(SafeHTTPRequestHandler)
        handler.connection = Mock()
        timer = Mock()
        callbacks = []
        def make_timer(seconds, callback):
            self.assertEqual(seconds, REQUEST_TIMEOUT_SECONDS)
            callbacks.append(callback)
            return timer
        def slow_input():
            callbacks[0]()
        with patch("duranki_server.http_server.threading.Timer", side_effect=make_timer), \
                patch("http.server.BaseHTTPRequestHandler.handle_one_request", side_effect=slow_input):
            handler.handle_one_request()
        handler.connection.shutdown.assert_called_once()
        timer.start.assert_called_once()
        timer.cancel.assert_called_once()

    def test_body_completion_cancels_input_deadline_before_long_processing(self):
        handler = SafeHTTPRequestHandler.__new__(SafeHTTPRequestHandler)
        handler.rfile = io.BytesIO(b"request")
        with patch.object(handler, "_finish_input") as finish:
            self.assertEqual(handler.read_body(7), b"request")
        finish.assert_called_once()
        self.assertEqual(handler.timeout, REQUEST_TIMEOUT_SECONDS)

    def test_password_hash_work_is_bounded_separately_from_http_threads(self):
        lock, release = threading.Lock(), threading.Event()
        two_entered = threading.Event()
        active = peak = 0
        def hash_work(*args, **kwargs):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
                if active == 2:
                    two_entered.set()
            release.wait(timeout=3)
            with lock:
                active -= 1
            return b"x" * 32
        with patch("duranki_server.user_management.hashlib.scrypt", side_effect=hash_work), ThreadPoolExecutor(max_workers=6) as pool:
            jobs = [pool.submit(password_hash, "synthetic test password") for _ in range(6)]
            try:
                self.assertTrue(two_entered.wait(timeout=3))
                self.assertEqual(peak, 2)
            finally:
                release.set()
            for job in jobs:
                job.result(timeout=3)
        self.assertEqual(peak, 2)
