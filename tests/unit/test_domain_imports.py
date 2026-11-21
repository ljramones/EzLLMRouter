"""Extracted domain modules must import before their public facade."""

from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "server/src/ezllmrouter_server"


class DomainImportTests(unittest.TestCase):
    def test_each_domain_imports_first_in_a_fresh_interpreter(self):
        paths = {
            path
            for pattern in (
                "registry_*.py",
                "accounting_*.py",
                "core_*.py",
                "store_*.py",
                "integration_credential_*.py",
                "registry_mutations/*.py",
            )
            for path in PACKAGE.glob(pattern)
        }
        script = (
            "import importlib, sys; sys.path.insert(0, sys.argv[1]); "
            "importlib.import_module(sys.argv[2])"
        )
        self.assertTrue(paths)
        for path in sorted(paths):
            suffix = path.relative_to(PACKAGE).with_suffix("").parts
            if suffix[-1] == "__init__":
                suffix = suffix[:-1]
            module = ".".join(("ezllmrouter_server", *suffix))
            with self.subTest(module=module):
                result = subprocess.run(
                    [sys.executable, "-I", "-c", script, str(PACKAGE.parent), module],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    timeout=15,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
