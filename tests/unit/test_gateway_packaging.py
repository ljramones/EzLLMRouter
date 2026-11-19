"""Runtime import identity and staged isolation without Docker or a model call."""
import ast
from importlib import import_module
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
RUNTIME = ROOT / "server/src/duranki_server/gateway"
MODULES = ("guard", "adapter", "choice_b_sender", "choice_b_wire", "owned_sender_transport",
           "owned_tls_sender_transport", "proxy_recipe", "worker_ready", "dev12_guard")


class GatewayPackagingTests(unittest.TestCase):
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
        return subprocess.run([sys.executable, "-S", "-B", "-c", bootstrap + script],
            cwd=directory, env={**os.environ, "PYTHONPATH": ""}, capture_output=True,
            text=True, check=True, timeout=20)

    def test_legacy_imports_share_one_guard_context_and_exception_type(self):
        sys.path.insert(0, str(ROOT / "tests/gateway_integration"))
        self.addCleanup(sys.path.remove, str(ROOT / "tests/gateway_integration"))
        for name in MODULES:
            self.assertIs(import_module(name), import_module("duranki_server.gateway." + name), name)
        guard = import_module("duranki_server.gateway.guard")
        owned = import_module("duranki_server.gateway.owned_sender_transport")
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
import duranki_server
from duranki_server import registry, operator_web
from duranki_server.gateway import guard, choice_b_sender, adapter, synthetic_recipe
import guard as old_guard
import recipe as old_recipe
assert old_guard is guard
assert old_recipe.SyntheticDevelopmentRecipe is synthetic_recipe.SyntheticDevelopmentRecipe
assert 'service/server' in str(Path(duranki_server.__file__))
for name in ('guard', 'choice_b_sender', 'adapter', 'owned_sender_transport', 'owned_tls_sender_transport',
             'proxy_recipe', 'worker_ready', 'dev12_guard', 'choice_b_wire'):
    module = importlib.import_module('duranki_server.gateway.' + name)
    assert 'service/server' in module.__file__
assert 'litellm' not in sys.modules and 'openai' not in sys.modules
print(json.dumps({'runtime': 'staged package', 'optional_worker_imports': False}))
"""
            result = self.child(script, paths, build)
            self.assertEqual(json.loads(result.stdout)["runtime"], "staged package")

    def test_staged_worker_needs_only_its_two_modules(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for source, target in source_mapping(ROOT):
                if target.startswith("worker/") and target.endswith(".py"):
                    shutil.copy2(ROOT / source, directory / Path(target).name)
            self.assertEqual(sorted(path.name for path in directory.iterdir()),
                             ["choice_b_wire.py", "choice_b_worker.py"])
            script = """
import importlib.util, json
import choice_b_worker, choice_b_wire
assert importlib.util.find_spec('duranki_server') is None
assert 'litellm' not in sys.modules
assert choice_b_wire.LIMIT == 262144
print(json.dumps({'worker': 'isolated', 'service_importable': False}))
"""
            result = self.child(script, [directory, *self.dependencies()], directory)
            self.assertFalse(json.loads(result.stdout)["service_importable"])

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
