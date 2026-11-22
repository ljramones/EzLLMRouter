"""Exercise the blocking quality commands against disposable bad source files."""

from contextlib import ExitStack, redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from tools import check
from tools import test_network


class ChecksComplete(Exception):
    pass


class PlatformReportingTests(unittest.TestCase):
    def test_one_failed_client_does_not_hide_later_results_or_make_the_job_pass(self):
        from tests.client_languages import platform_check

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(platform_check, "ROOT", Path(directory)),
            patch.object(platform_check, "run", return_value="synthetic-source\n"),
            patch.object(
                platform_check, "python_client", side_effect=RuntimeError("synthetic build failure")
            ),
            patch.object(
                platform_check, "javascript_client", return_value={"archive": "synthetic"}
            ) as later,
            patch.object(
                sys, "argv", ["platform_check.py", "--client", "python", "--client", "javascript"]
            ),
            patch.dict(os.environ),
            redirect_stderr(io.StringIO()),
        ):
            with self.assertRaisesRegex(SystemExit, "checks failed: python"):
                platform_check.main()
            later.assert_called_once()
            report = json.loads(
                (Path(directory) / ".artifacts/platform-clients/summary.json").read_text()
            )
            self.assertFalse(report["results"]["python"]["passed"])
            self.assertTrue(report["results"]["javascript"]["passed"])


class NetworkPlatformTests(unittest.TestCase):
    def test_absent_unix_family_keeps_loopback_allowed_and_external_network_denied(self):
        socket = test_network.socket
        operations = ["bind", "connect", "connect_ex", "sendto"]
        if hasattr(socket.socket, "sendmsg"):
            operations.append("sendmsg")
        with ExitStack() as patches:
            patches.enter_context(patch.object(socket, "AF_UNIX", create=True))
            del socket.AF_UNIX
            mocks = {
                name: patches.enter_context(patch.object(socket.socket, name, return_value=0))
                for name in operations
            }
            connection = SimpleNamespace(family=socket.AF_INET)

            def invoke(name, host):
                address = (host, 12345)
                args = (
                    ([b"x"], [], 0, address)
                    if name == "sendmsg"
                    else (b"x", address)
                    if name == "sendto"
                    else (address,)
                )
                return getattr(socket.socket, name)(connection, *args)

            with ExitStack() as guards:
                test_network.block_network(guards, loopback=True)
                for name in operations:
                    self.assertEqual(invoke(name, "127.0.0.1"), 0)
                    with self.assertRaisesRegex(AssertionError, "network/socket"):
                        invoke(name, "203.0.113.10")
                    self.assertEqual(mocks[name].call_count, 1)
            with ExitStack() as guards:
                test_network.block_network(guards, loopback=False)
                for name in operations:
                    with self.assertRaisesRegex(AssertionError, "network/socket"):
                        invoke(name, "127.0.0.1")


class QualityGateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in check.QUALITY_PATHS:
            (self.root / name).mkdir()
        (self.root / "pyproject.toml").write_bytes((check.ROOT / "pyproject.toml").read_bytes())
        self.node_version = (check.ROOT / ".nvmrc").read_text().strip().lstrip("v")
        (self.root / ".nvmrc").write_text(self.node_version)

    def run_checks(self, typed=("server/src/checked.py",)):
        commands, failures = [], []

        def execute(command):
            commands.append(command)
            try:
                subprocess.run(command, cwd=self.root, text=True, capture_output=True, check=True)
            except subprocess.CalledProcessError as exc:
                failures.append(exc)
                raise
            if command[1:3] == ["-m", "mypy"]:
                raise ChecksComplete()  # Never run the repository test suite recursively.

        with (
            patch.object(check, "ROOT", self.root),
            patch.object(check, "TYPED_PATHS", typed),
            patch.object(check, "test_inventory_errors", return_value=[]),
            patch.object(check, "run", side_effect=execute),
            patch.object(check.subprocess, "check_output", return_value="v" + self.node_version),
            patch.object(sys, "argv", ["check.py"]),
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            try:
                code = check.main()
            except ChecksComplete:
                code = 0
        return code, commands, failures

    def test_unused_import_and_blind_exception_in_tests_block_the_runner(self):
        (self.root / "tests/test_fixture.py").write_text(
            "import os\nimport unittest\nwith unittest.TestCase().assertRaises(Exception):\n    pass\n"
        )
        code, commands, failures = self.run_checks()
        self.assertNotEqual(code, 0)
        self.assertEqual(len(commands), 1)
        self.assertIn("F401", failures[0].stdout)
        self.assertIn("B017", failures[0].stdout)

    def test_unformatted_test_blocks_the_runner_after_lint(self):
        (self.root / "tests/test_fixture.py").write_text("value=1\n")
        code, commands, failures = self.run_checks()
        self.assertNotEqual(code, 0)
        self.assertEqual(len(commands), 2)
        self.assertIn("test_fixture.py", failures[0].stdout)

    def test_mypy_uses_imported_types_without_checking_the_imported_body(self):
        sources = self.root / "server/src"
        sources.mkdir()
        (sources / "helper.py").write_text("def label() -> str:\n    return 1\n")
        (sources / "checked.py").write_text(
            "from helper import label\n\n\ndef require_int(value: int) -> None:\n    pass\n"
            "\n\ndef check() -> None:\n    require_int(label())\n"
        )
        code, commands, failures = self.run_checks()
        self.assertNotEqual(code, 0)
        self.assertEqual(len(commands), 3)
        self.assertIn("[arg-type]", failures[0].stdout)
        self.assertNotIn("helper.py:", failures[0].stdout)

    def test_runtime_state_is_excluded_even_without_git_ignore_discovery(self):
        runtime = self.root / "deploy/local/.state"
        runtime.mkdir(parents=True)
        diagnostic = runtime / "diagnostic.py"
        original = "import os\nvalue=1\n"
        diagnostic.write_text(original)
        sources = self.root / "server/src"
        sources.mkdir()
        (sources / "checked.py").write_text("def value() -> int:\n    return 1\n")
        code, commands, failures = self.run_checks()
        self.assertEqual(code, 0)
        self.assertEqual(len(commands), 3)
        self.assertEqual(failures, [])
        self.assertEqual(diagnostic.read_text(), original)
