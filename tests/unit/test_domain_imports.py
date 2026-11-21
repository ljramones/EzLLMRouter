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

    def test_completion_domains_import_first_and_keep_registered_source_identity(self):
        domains = (
            "accounting",
            "checkpoint",
            "clients",
            "correlation",
            "handler_common",
            "identity_verification",
            "ingress",
            "plan",
            "recovery",
            "retrieval",
            "setup",
            "usage_verification",
            "write_verification",
            "supplement_state",
            "preflight_validation",
        )
        script = """
import importlib, inspect, sys
from hashlib import sha256
from pathlib import Path
sys.path[:0] = [sys.argv[1], sys.argv[2]]
importlib.import_module(sys.argv[3])
from tools.gateway.evidence.dev12_completion_handlers import DEV12_CASE_HANDLERS
from tools.gateway.evidence.dev12_completion_catalog import source_path_for_handler
for registration in DEV12_CASE_HANDLERS.values():
    path = Path(registration.source_path).resolve()
    assert inspect.isfunction(registration.run)
    assert Path(inspect.getsourcefile(registration.run)).resolve() == path
    assert path == source_path_for_handler(registration.name)
    assert sha256(path.read_bytes()).hexdigest() == registration.source_sha256
"""
        modules = ["tools.gateway.evidence.dev12_completion_" + name for name in domains]
        modules.append("tools.gateway.docker.staging")
        for name in modules:
            with self.subTest(module=name):
                self.assertTrue((ROOT / name.replace(".", "/")).with_suffix(".py").is_file())
                result = subprocess.run(
                    [
                        sys.executable,
                        "-I",
                        "-c",
                        script,
                        str(ROOT),
                        str(PACKAGE.parent),
                        name,
                    ],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    timeout=15,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
