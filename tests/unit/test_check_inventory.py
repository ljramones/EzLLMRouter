"""New regression files must run or carry a maintained exclusion reason."""

import shutil

from pathlib import Path
from contextlib import ExitStack
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools.check import block_network, test_inventory_errors as audit


@unittest.skipUnless(shutil.which("git"), "git is required for this fixture")
class InventoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.path = self.root / "tests/unit/test_example.py"
        self.path.parent.mkdir(parents=True)
        self.path.write_text("")

    def check_inventory(self, *, modules=(), scripts=(), excluded=None):
        return audit(self.root, modules, scripts, excluded or {})

    def test_unregistered_test_is_an_error(self):
        self.assertEqual(
            self.check_inventory(), ["Unclassified test file: tests/unit/test_example.py"]
        )

    def test_module_or_class_registration_covers_its_file(self):
        for module in ("tests.unit.test_example", "tests.unit.test_example.Cases"):
            self.assertEqual(self.check_inventory(modules=(module,)), [])

    def test_script_registration_covers_its_file(self):
        self.assertEqual(self.check_inventory(scripts=("tests/unit/test_example.py",)), [])

    def test_ignored_runtime_and_dependencies_are_not_source_tests(self):
        (self.root / ".gitignore").write_text(".state/\nnode_modules/\n")
        for folder in ("deploy/local/.state/staging", "tests/playwright/node_modules"):
            path = self.root / folder / "test_dependency.py"
            path.parent.mkdir(parents=True)
            path.write_text("")
        self.assertEqual(self.check_inventory(modules=("tests.unit.test_example",)), [])

    def test_exclusion_requires_a_reason_and_cannot_hide_a_registered_test(self):
        path = "tests/unit/test_example.py"
        self.assertEqual(
            self.check_inventory(excluded={path: "Needs a reviewed isolated worker"}), []
        )
        self.assertIn(
            "Missing exclusion reason: " + path, self.check_inventory(excluded={path: ""})
        )
        self.assertIn(
            "Test is both registered and excluded: " + path,
            self.check_inventory(scripts=(path,), excluded={path: "Duplicated"}),
        )

    def test_missing_catalogue_entries_are_errors(self):
        errors = self.check_inventory(
            modules=("tests.unit.test_missing",),
            scripts=("tests/unit/test_missing.py",),
            excluded={"tests/unit/test_removed.py": "Removed"},
        )
        self.assertIn("Missing registered test module: tests.unit.test_missing", errors)
        self.assertIn("Missing registered test script: tests/unit/test_missing.py", errors)
        self.assertIn("Missing excluded test file: tests/unit/test_removed.py", errors)


class NetworkGuardTests(unittest.TestCase):
    def test_loopback_mode_allows_only_local_socket_destinations(self):
        original = Mock(return_value=None)
        with patch.object(socket.socket, "connect", original), ExitStack() as stack:
            block_network(stack, loopback=True)
            with socket.socket() as connection:
                connection.connect(("127.0.0.1", 8765))
                original.assert_called_once_with(connection, ("127.0.0.1", 8765))
                for host in ("192.0.2.1", "0.0.0.0", "provider.invalid"):
                    with self.assertRaises(AssertionError):
                        connection.connect((host, 8765))
            self.assertEqual(original.call_count, 1)

    def test_external_dns_is_rejected_before_resolution(self):
        resolve = Mock(
            return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))]
        )
        with patch.object(socket, "getaddrinfo", resolve), ExitStack() as stack:
            block_network(stack, loopback=True)
            self.assertEqual(socket.getaddrinfo("localhost", 80)[0][4][0], "127.0.0.1")
            with self.assertRaises(AssertionError):
                socket.getaddrinfo("provider.invalid", 80)
            self.assertEqual(resolve.call_count, 1)

    def test_localhost_cannot_resolve_to_an_external_address(self):
        with (
            patch.object(
                socket,
                "getaddrinfo",
                return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", 80))],
            ),
            ExitStack() as stack,
        ):
            block_network(stack, loopback=True)
            with self.assertRaises(AssertionError):
                socket.getaddrinfo("localhost", 80)

    def test_offline_mode_still_rejects_loopback(self):
        with ExitStack() as stack:
            block_network(stack)
            with socket.socket() as connection, self.assertRaises(AssertionError):
                connection.connect(("127.0.0.1", 80))
