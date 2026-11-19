"""Runtime import identity and staged isolation without Docker or a model call."""
import ast
from importlib import import_module
from importlib.util import find_spec
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import unittest

from tools.gateway.stage import source_mapping

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "server/src/ezllmrouter_server/gateway"
MODULES = ("guard", "adapter", "choice_b_sender", "choice_b_wire", "owned_sender_transport",
           "owned_tls_sender_transport", "proxy_recipe", "worker_ready", "dev12_guard")


class GatewayPackagingTests(unittest.TestCase):
    def test_python_distributions_have_one_implementation_namespace(self):
        import tomllib
        from ezllmrouter_client import EzLLMRouterClient
        from ezllmrouter_server.core import Coordinator

        for directory, namespace in (("server", "ezllmrouter_server"),
                                     ("clients/python", "ezllmrouter_client")):
            package = ROOT / directory
            config = tomllib.loads((package / "pyproject.toml").read_text())
            self.assertEqual(config["tool"]["uv"]["build-backend"]["module-name"], namespace)
            implementations = {path.name for path in (package / "src").iterdir()
                               if path.is_dir() and (path / "__init__.py").is_file()}
            self.assertEqual(implementations, {namespace})
        self.assertEqual(EzLLMRouterClient.__module__, "ezllmrouter_client")
        self.assertEqual(Coordinator.__module__, "ezllmrouter_server.core")

    def dependencies(self, *, native=False):
        # Reuse the active declared dependency environment, with no checkout or
        # test directories in the child interpreter's import search path.
        paths = [str(Path(path).resolve()) for path in sys.path
                 if path and not Path(path).resolve().is_relative_to(ROOT)]
        if native:
            paths.append(sysconfig.get_paths()["platlib"])
        return paths

    def child(self, script, paths, directory):
        bootstrap = "import sys; sys.path[:0] = " + repr([str(path) for path in paths]) + "\n"
        result = subprocess.run([sys.executable, "-S", "-B", "-c", bootstrap + script],
            cwd=directory, env={**os.environ, "PYTHONPATH": ""}, capture_output=True,
            text=True, check=False, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def worker_dependencies(self, directory):
        # Copy only the declared HTTP dependency modules. The development venv
        # lives inside ROOT, and adding its entire site-packages could expose
        # service code from a non-editable installation to the isolated worker.
        destination = directory / ".dependencies"
        destination.mkdir()
        for name in ("httpx", "httpcore", "anyio", "h11", "certifi", "idna",
                     "typing_extensions", "sniffio"):
            spec = find_spec(name)
            if spec is None:
                self.assertEqual(name, "sniffio", "missing HTTP dependency: " + name)
                continue  # Older AnyIO versions use sniffio; current versions do not.
            source = Path(spec.origin)
            if spec.submodule_search_locations:
                shutil.copytree(source.parent, destination / name,
                                ignore=shutil.ignore_patterns("__pycache__"))
            else:
                shutil.copy2(source, destination / source.name)
        return destination

    def test_legacy_imports_share_one_guard_context_and_exception_type(self):
        sys.path.insert(0, str(ROOT / "tests/gateway_integration"))
        self.addCleanup(sys.path.remove, str(ROOT / "tests/gateway_integration"))
        for name in MODULES:
            self.assertIs(import_module(name), import_module("ezllmrouter_server.gateway." + name), name)
        guard = import_module("ezllmrouter_server.gateway.guard")
        owned = import_module("ezllmrouter_server.gateway.owned_sender_transport")
        self.assertIs(guard.ACTIVE, owned.ACTIVE)
        self.assertIs(guard.GuardRejected, owned.GuardRejected)

    def test_runtime_package_has_no_imports_from_tests_or_tooling(self):
        for source in RUNTIME.glob("*.py"):
            with self.subTest(source=source.name):
                tree = ast.parse(source.read_text())
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom):
                        self.assertFalse((node.module or "").startswith(("tests", "tools", "worker")))
                        self.assertNotEqual(node.module, "recipe")
                    elif isinstance(node, ast.Import):
                        self.assertFalse(any(item.name.startswith(("tests", "tools", "worker")) for item in node.names))

    def test_staged_service_imports_without_the_checkout_or_test_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            build = Path(temporary)
            sources = source_mapping(ROOT, dev05=True)
            self.assertEqual(len({target for _, target in sources}), len(sources))
            for source, target in sources:
                if not target.startswith(("service/server/", "service/gateway/", "service/dev_slice/")):
                    continue
                destination = build / target
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / source, destination)
            paths = [build / "service/server", build / "service/gateway", build / "service/dev_slice",
                     *self.dependencies(native=True)]
            script = """
import importlib, json
from pathlib import Path
import ezllmrouter_server
from ezllmrouter_server import registry, operator_web
from ezllmrouter_server import secret_rotation
from ezllmrouter_server.store import SQLiteStore
from ezllmrouter_server.gateway import guard, choice_b_sender, adapter, synthetic_recipe
import guard as old_guard
import recipe as old_recipe
assert old_guard is guard
assert old_recipe.SyntheticDevelopmentRecipe is synthetic_recipe.SyntheticDevelopmentRecipe
assert 'service/server' in str(Path(ezllmrouter_server.__file__))
assert 'service/server' in secret_rotation.__file__
store = SQLiteStore('staged.sqlite')
assert store.db.execute('PRAGMA user_version').fetchone() == (1,)
store.close()
for name in ('guard', 'choice_b_sender', 'adapter', 'owned_sender_transport', 'owned_tls_sender_transport',
             'proxy_recipe', 'worker_ready', 'dev12_guard', 'choice_b_wire'):
    module = importlib.import_module('ezllmrouter_server.gateway.' + name)
    assert 'service/server' in module.__file__
assert 'litellm' not in sys.modules and 'openai' not in sys.modules
print(json.dumps({'runtime': 'staged package', 'optional_worker_imports': False}))
"""
            result = self.child(script, paths, build)
            self.assertEqual(json.loads(result.stdout)["runtime"], "staged package")

    def test_staged_worker_needs_only_runtime_wire_and_safe_logger(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for source, target in source_mapping(ROOT):
                if target.startswith("worker/") and target.endswith(".py"):
                    shutil.copy2(ROOT / source, directory / Path(target).name)
            self.assertEqual(sorted(path.name for path in directory.iterdir()),
                             ["choice_b_wire.py", "choice_b_worker.py", "worker_logging.py"])
            script = """
import importlib.util, json
import choice_b_worker, choice_b_wire, worker_logging
assert importlib.util.find_spec('ezllmrouter_server') is None
assert 'litellm' not in sys.modules
assert choice_b_wire.LIMIT == 262144
print(json.dumps({'worker': 'isolated', 'service_importable': False}))
"""
            dependencies = self.worker_dependencies(directory)
            result = self.child(script, [directory, dependencies], directory)
            self.assertFalse(json.loads(result.stdout)["service_importable"])

    def test_fault_fixtures_require_explicit_staging_and_are_absent_from_runtime(self):
        for dev05 in (False, True):
            normal = {target for _, target in source_mapping(ROOT, dev05)}
            fixture = {target for _, target in source_mapping(ROOT, dev05, fixtures=True)}
            extras = {"service/gateway/fixture_adapters.py", "service/gateway/service_fixture.py",
                      "worker/fixture/worker_fixture.py"}
            self.assertTrue(extras.isdisjoint(normal))
            self.assertEqual(fixture - normal, extras)
        self.assertEqual((ROOT / "server/src/ezllmrouter_server/observability.py").read_bytes(),
                         next((ROOT / source).read_bytes() for source, target in source_mapping(ROOT)
                              if target == "worker/worker_logging.py"))

    def test_staged_runtime_implementation_inputs_are_not_test_sources(self):
        mappings = dict((target, source) for source, target in source_mapping(ROOT, True))
        for target, source in mappings.items():
            if target.startswith(("service/server/", "worker/")) and target.endswith(".py"):
                self.assertFalse(source.startswith("tests/"), (source, target))
        for target in ("service/gateway/guard.py", "service/gateway/choice_b_sender.py",
                       "service/gateway/adapter.py", "service/gateway/owned_sender_transport.py",
                       "service/gateway/owned_tls_sender_transport.py", "service/gateway/service_main.py",
                       "service/gateway/choice_b_service.py", "receiver/receiver.py"):
            self.assertTrue(mappings[target].startswith("tools/gateway/"), target)

    def test_old_and_new_evidence_imports_share_the_same_functions(self):
        legacy = import_module("tests.gateway_integration.capture_runtime")
        current = import_module("tools.gateway.evidence.capture_runtime")
        self.assertIs(legacy.capture, current.capture)
        self.assertIs(legacy.CaptureLimit, current.CaptureLimit)

    def test_local_launch_modules_are_safe_to_import_without_credentials(self):
        for name in ("service_main", "choice_b_service", "receiver"):
            module = import_module("tools.gateway." + name)
            self.assertTrue(callable(module.main))
