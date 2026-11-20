"""Exercise the blocking quality commands against disposable bad source files."""

from contextlib import redirect_stdout, redirect_stderr
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import check


class ChecksComplete(Exception):
    pass


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
