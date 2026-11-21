"""Extracted domain modules must import before their public facade."""

from pathlib import Path
import ast
import importlib
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
                "*.py",
                "operator_http/*.py",
                "wire_http/*.py",
                "registry_*.py",
                "accounting_*.py",
                "core_*.py",
                "store_*.py",
                "integration_credential_*.py",
                "registry_mutations/*.py",
                "gateway/*.py",
                "successor_contract.py",
                "successor_plan.py",
                "retrieval_descriptor.py",
                "local_connector_*.py",
                "campaign_reporting.py",
            )
            for path in PACKAGE.glob(pattern)
        }
        script = (
            "import importlib, sys; sys.path.insert(0, sys.argv[1]); "
            "importlib.import_module(sys.argv[2])"
        )
        self.assertTrue(paths)
        for path in sorted(paths):
            if path.name == "__main__.py":
                continue
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
        modules.extend(
            "tools.gateway.docker." + name
            for name in ("fetching", "resolution", "input_collection")
        )
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

    def test_moved_domains_keep_facade_dependencies_and_collector_default(self):
        domains = {
            "ezllmrouter_server.local_connector_http": "ezllmrouter_server.local_connectors",
            "ezllmrouter_server.local_connector_inventory": "ezllmrouter_server.local_connectors",
            "ezllmrouter_server.campaign_reporting": "ezllmrouter_server.personal_campaign",
            "tools.gateway.docker.fetching": "tools.gateway.docker.prepare",
            "tools.gateway.docker.resolution": "tools.gateway.docker.prepare",
            "tools.gateway.docker.input_collection": "tools.gateway.docker.prepare",
        }
        for domain_name, facade_name in domains.items():
            domain, facade = (
                importlib.import_module(domain_name),
                importlib.import_module(facade_name),
            )
            tree = ast.parse(Path(domain.__file__).read_text())
            names = {
                node.attr
                for node in ast.walk(tree)
                if isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "_api"
            }
            for name in names:
                with self.subTest(domain=domain_name, dependency=name):
                    self.assertTrue(hasattr(facade, name))
        from tools.gateway.docker import prepare

        self.assertIs(prepare.inputs02_collect_core.__defaults__[0], prepare.inputs02_fetch)
