"""One-time provisioning preserves private custody after possible issuance."""

from contextlib import ExitStack, contextmanager, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "tested_local_provision", ROOT / "deploy/local/provision.py"
)
provision = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(provision)
SECRET = "synthetic-one-time-credential-not-a-real-secret-000000"


class ProvisionRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.state = directory / "state"
        self.state.mkdir()
        (self.state / "operator-password").write_text("synthetic-owner-login-password")
        self.target = self.state / "provisioned/svc.synthetic.credential"
        self.receipt = self.target.with_name("svc.synthetic.provision.json")
        self.stack.enter_context(patch.object(provision, "STATE", self.state))
        self.stack.enter_context(
            patch.object(provision.sys, "argv", ["provision.py", "svc.synthetic", "7"])
        )
        self.connection = Mock()
        self.stack.enter_context(
            patch.object(provision.http.client, "HTTPConnection", return_value=self.connection)
        )
        self.calls = []
        self.exchange = self.stack.enter_context(
            patch.object(provision, "exchange", side_effect=self.reply)
        )

    def reply(self, connection, path, body, **kwargs):
        self.calls.append((path, body))
        if path.endswith("/login"):
            return {
                "role": "registry_admin",
                "csrf": "synthetic-csrf",
            }, "session=synthetic; HttpOnly"
        self.assertEqual(json.loads(self.receipt.read_text()), body)
        self.assertEqual(self.target.read_bytes(), b"")
        return {"one_time_credential": SECRET}, None

    def assert_custody(self, expected=SECRET + "\n"):
        self.assertEqual(self.target.read_text(), expected)
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.receipt.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.target.parent.stat().st_mode & 0o777, 0o700)
        record = json.loads(self.receipt.read_text())
        self.assertEqual(record["principal_id"], "svc.synthetic")
        self.assertEqual(record["expected_revision"], 7)
        self.assertNotIn(SECRET, self.receipt.read_text())

    def test_success_saves_exact_secret_and_durable_operation_identity(self):
        output = io.StringIO()
        with redirect_stdout(output):
            provision.main()
        self.assert_custody()
        self.assertNotIn(SECRET, output.getvalue())
        self.assertEqual(
            [path for path, _ in self.calls], ["/operator/v1/login", "/operator/v1/provision"]
        )
        self.connection.close.assert_called_once()

    def test_output_failure_or_interrupt_never_deletes_saved_credential(self):
        for error in (BrokenPipeError("synthetic output failure"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                with patch("builtins.print", side_effect=error):
                    with self.assertRaises(type(error)) as failed:
                        provision.main()
                self.assert_custody()
                self.assertIn("Retained", failed.exception.__notes__[0])
                with self.assertRaises(FileExistsError):
                    provision.main()
                self.assertEqual(sum(path.endswith("/provision") for path, _ in self.calls), 1)
                self.target.unlink()
                self.receipt.unlink()
                self.calls.clear()

    def test_connection_close_failure_keeps_saved_credential(self):
        self.connection.close.side_effect = OSError("synthetic close failure")
        with redirect_stdout(io.StringIO()), self.assertRaises(OSError):
            provision.main()
        self.assert_custody()

    def test_uncertain_reply_keeps_reservation_and_receipt_and_blocks_retry(self):
        reply = self.reply

        def lost(connection, path, body, **kwargs):
            value = reply(connection, path, body, **kwargs)
            if path.endswith("/provision"):
                raise KeyboardInterrupt()
            return value

        self.exchange.side_effect = lost
        with self.assertRaises(KeyboardInterrupt):
            provision.main()
        self.assert_custody("")
        with self.assertRaises(FileExistsError):
            provision.main()
        self.assertEqual(sum(path.endswith("/provision") for path, _ in self.calls), 1)

    def test_malformed_issuance_reply_keeps_operation_identity(self):
        reply = self.reply

        def missing(connection, path, body, **kwargs):
            result = reply(connection, path, body, **kwargs)
            return ({}, None) if path.endswith("/provision") else result

        self.exchange.side_effect = missing
        with self.assertRaises(RuntimeError):
            provision.main()
        self.assert_custody("")

    def test_credential_fsync_failure_preserves_readable_file(self):
        sync = os.fsync

        def fail(descriptor):
            info = os.fstat(descriptor)
            if (
                self.target.exists()
                and info.st_ino == self.target.stat().st_ino
                and info.st_size > 0
            ):
                raise OSError("synthetic credential sync failure")
            sync(descriptor)

        with patch.object(provision.os, "fsync", side_effect=fail), self.assertRaises(OSError):
            provision.main()
        self.assert_custody()

    def test_interrupted_partial_credential_write_is_not_unlinked(self):
        fdopen = os.fdopen
        prefix = SECRET[: len(SECRET) // 2]

        @contextmanager
        def open_handle(descriptor, mode):
            is_credential = os.fstat(descriptor).st_ino == self.target.stat().st_ino
            with fdopen(descriptor, mode) as handle:
                if not is_credential:
                    yield handle
                else:

                    class InterruptedWriter:
                        def write(self, value):
                            handle.write(value[: len(prefix)])
                            handle.flush()
                            raise KeyboardInterrupt()

                    yield InterruptedWriter()

        with patch.object(provision.os, "fdopen", side_effect=open_handle):
            with self.assertRaises(KeyboardInterrupt):
                provision.main()
        self.assert_custody(prefix)

    def test_login_failure_removes_only_unused_reservation(self):
        self.exchange.side_effect = RuntimeError("synthetic login failure")
        with self.assertRaises(RuntimeError):
            provision.main()
        self.assertFalse(self.target.exists())
        self.assertFalse(self.receipt.exists())

    def test_receipt_sync_failure_prevents_issuance_and_removes_unused_files(self):
        with patch.object(
            provision, "sync_directory", side_effect=OSError("synthetic receipt sync failure")
        ):
            with self.assertRaises(OSError):
                provision.main()
        self.assertEqual([path for path, _ in self.calls], ["/operator/v1/login"])
        self.assertFalse(self.target.exists())
        self.assertFalse(self.receipt.exists())

    def test_existing_receipt_is_never_overwritten_or_used_for_another_issuance(self):
        self.receipt.parent.mkdir()
        self.receipt.write_text("previous operation")
        with self.assertRaises(FileExistsError):
            provision.main()
        self.assertEqual(self.receipt.read_text(), "previous operation")
        self.assertFalse(self.target.exists())
        self.assertEqual([path for path, _ in self.calls], ["/operator/v1/login"])
