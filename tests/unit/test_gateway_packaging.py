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
import zipfile

from tools.gateway.stage import inspect_wheel, source_mapping
from deploy.local import prepare

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "server/src/ezllmrouter_server/gateway"


class TrustedImageTests(unittest.TestCase):
    def test_startup_hooks_are_rejected_by_archive_inspection(self):
        with tempfile.TemporaryDirectory() as temporary:
            wheel = Path(temporary) / "review.whl"
            for name in (
                "boot.pth",
                "data/purelib/boot.PTH",
                "sitecustomize.py",
                "usercustomize.pyc",
                "sitecustomize/__init__.py",
                "../../outside.py",
            ):
                with self.subTest(name=name):
                    with zipfile.ZipFile(wheel, "w") as archive:
                        archive.writestr(name, "raise RuntimeError('must never execute')")
                    with self.assertRaisesRegex(ValueError, "unsafe wheel startup entry"):
                        inspect_wheel(wheel)
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr(
                    "package/__init__.py", "raise RuntimeError('inspection is not import')"
                )
            inspect_wheel(wheel)

    def test_trusted_lock_is_a_minimal_subset_of_the_reviewed_worker_lock(self):
        gateway = set(
            (ROOT / "deploy/local/inputs/gateway/requirements.gateway.lock")
            .read_text()
            .splitlines()
        )
        runtime = set(
            (ROOT / "deploy/local/inputs/requirements.runtime.lock").read_text().splitlines()
        )
        self.assertLessEqual(runtime, gateway)
        names = {line.split("==")[0].lower().replace("_", "-") for line in runtime}
        self.assertEqual(
            names,
            {
                "anyio",
                "certifi",
                "cffi",
                "cryptography",
                "h11",
                "httpcore",
                "httpx",
                "idna",
                "pycparser",
                "sniffio",
                "typing-extensions",
            },
        )
        dockerfile = (ROOT / "deploy/local/Dockerfile.service").read_text()
        self.assertIn("--require-hashes -r /opt/ezllmrouter/requirements.runtime.lock", dockerfile)
        self.assertNotIn("requirements.gateway.lock", dockerfile)
        self.assertIn("importlib.util.find_spec('litellm') is None", dockerfile)
        self.assertNotIn("test_alt_handler.py", dockerfile)

    def test_frozen_checks_are_staged_for_their_actual_docker_runners(self):
        with tempfile.TemporaryDirectory() as temporary:
            build = Path(temporary)
            package = build / "service/server/ezllmrouter_server"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("")
            prepare.stage_worker_validation(build)
            worker = (ROOT / "deploy/local/Dockerfile.worker").read_text()
            for name in prepare.WORKER_VALIDATION_FILES:
                self.assertTrue((build / "worker/validation" / name).is_file())
                self.assertIn("/tmp/validation/" + name, worker)
            self.assertIn("source=validation,target=/tmp/validation,readonly", worker)
            service = (ROOT / "deploy/local/Dockerfile.service").read_text()
            self.assertIn("tests.gateway_integration.test_freshness_interface", service)
            self.assertIn("target=/app/gateway-inputs/dev04/wheels,readonly", service)


MODULES = (
    "guard",
    "choice_b_sender",
    "choice_b_wire",
    "owned_sender_transport",
    "owned_tls_sender_transport",
    "proxy_recipe",
    "worker_ready",
    "retrieval_guard",
)


class GatewayPackagingTests(unittest.TestCase):
    def test_python_distributions_have_one_implementation_namespace(self):
        import tomllib
        from ezllmrouter_client import EzLLMRouterClient
        from ezllmrouter_server.core import Coordinator

        for directory, namespace in (
            ("server", "ezllmrouter_server"),
            ("clients/python", "ezllmrouter_client"),
        ):
            package = ROOT / directory
            config = tomllib.loads((package / "pyproject.toml").read_text())
            self.assertEqual(config["tool"]["uv"]["build-backend"]["module-name"], namespace)
            implementations = {
                path.name
                for path in (package / "src").iterdir()
                if path.is_dir() and (path / "__init__.py").is_file()
            }
            self.assertEqual(implementations, {namespace})
        self.assertEqual(EzLLMRouterClient.__module__, "ezllmrouter_client")
        self.assertEqual(Coordinator.__module__, "ezllmrouter_server.core")

    def dependencies(self, *, native=False):
        # Reuse the active declared dependency environment, with no checkout or
        # test directories in the child interpreter's import search path.
        paths = [
            str(Path(path).resolve())
            for path in sys.path
            if path and not Path(path).resolve().is_relative_to(ROOT)
        ]
        if native:
            paths.append(sysconfig.get_paths()["platlib"])
        return paths

    def child(self, script, paths, directory):
        bootstrap = "import sys; sys.path[:0] = " + repr([str(path) for path in paths]) + "\n"
        result = subprocess.run(
            [sys.executable, "-S", "-B", "-c", bootstrap + script],
            cwd=directory,
            env={**os.environ, "PYTHONPATH": ""},
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def worker_dependencies(self, directory):
        # Copy only the declared HTTP dependency modules. The development venv
        # lives inside ROOT, and adding its entire site-packages could expose
        # service code from a non-editable installation to the isolated worker.
        destination = directory / ".dependencies"
        destination.mkdir()
        for name in (
            "httpx",
            "httpcore",
            "anyio",
            "h11",
            "certifi",
            "idna",
            "typing_extensions",
            "sniffio",
        ):
            spec = find_spec(name)
            if spec is None:
                self.assertEqual(name, "sniffio", "missing HTTP dependency: " + name)
                continue  # Older AnyIO versions use sniffio; current versions do not.
            source = Path(spec.origin)
            if spec.submodule_search_locations:
                shutil.copytree(
                    source.parent, destination / name, ignore=shutil.ignore_patterns("__pycache__")
                )
            else:
                shutil.copy2(source, destination / source.name)
        return destination

    def test_canonical_imports_share_one_guard_context_and_exception_type(self):
        package_root = Path(import_module("ezllmrouter_server.gateway").__file__).parent
        for name in MODULES:
            module = import_module("ezllmrouter_server.gateway." + name)
            self.assertTrue(Path(module.__file__).is_relative_to(package_root))
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
                        self.assertFalse(
                            (node.module or "").startswith(("tests", "tools", "worker"))
                        )
                        self.assertNotEqual(node.module, "recipe")
                    elif isinstance(node, ast.Import):
                        self.assertFalse(
                            any(
                                item.name.startswith(("tests", "tools", "worker"))
                                for item in node.names
                            )
                        )

    def test_staged_service_imports_without_the_checkout_or_test_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            build = Path(temporary)
            sources = source_mapping(ROOT, dev05=True)
            self.assertEqual(len({target for _, target in sources}), len(sources))
            for source, target in sources:
                if not target.startswith(
                    ("service/server/", "service/gateway/", "service/dev_slice/")
                ):
                    continue
                destination = build / target
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / source, destination)
            paths = [
                build / "service/server",
                build / "service/gateway",
                build / "service/dev_slice",
                *self.dependencies(native=True),
            ]
            script = """
import importlib, json
from pathlib import Path
import ezllmrouter_server
from ezllmrouter_server import registry, operator_web
from ezllmrouter_server import secret_rotation
from ezllmrouter_server.store import SQLiteStore
from ezllmrouter_server.gateway import guard, choice_b_sender, synthetic_recipe
from tools.gateway import asgi_adapter
import service_main, choice_b_service
assert 'service/server' in str(Path(ezllmrouter_server.__file__))
assert 'service/server' in secret_rotation.__file__
store = SQLiteStore('staged.sqlite')
from ezllmrouter_server.schema import VERSION
assert store.db.execute('PRAGMA user_version').fetchone() == (VERSION,)
store.close()
for name in ('guard', 'choice_b_sender', 'owned_sender_transport', 'owned_tls_sender_transport',
             'proxy_recipe', 'worker_ready', 'retrieval_guard', 'choice_b_wire'):
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
            from tools.gateway.worker_package import stage_worker

            stage_worker(ROOT, directory / "ezllmrouter_worker")
            self.assertEqual(
                sorted(path.name for path in (directory / "ezllmrouter_worker").iterdir()),
                [
                    "__init__.py",
                    "__main__.py",
                    "connection_resources.py",
                    "execution_policy.py",
                    "execution_resources.py",
                    "ipc.py",
                    "observability.py",
                    "resources.py",
                    "socket_lease.py",
                    "worker.py",
                ],
            )
            script = """
import importlib.util, json
from ezllmrouter_worker import worker, ipc, observability
assert importlib.util.find_spec('ezllmrouter_server') is None
assert 'litellm' not in sys.modules
assert ipc.LIMIT == 262144
print(json.dumps({'worker': 'isolated', 'service_importable': False}))
"""
            dependencies = self.worker_dependencies(directory)
            result = self.child(script, [directory, dependencies], directory)
            self.assertFalse(json.loads(result.stdout)["service_importable"])

    def test_fault_fixtures_require_explicit_staging_and_are_absent_from_runtime(self):
        for dev05 in (False, True):
            normal = {source for source, _ in source_mapping(ROOT, dev05)}
            explicit = {source for source, _ in source_mapping(ROOT, dev05, fixtures=True)}
            required = {
                "tools/gateway/fixture_adapters.py",
                "tools/gateway/service_fixture.py",
                "tools/gateway/worker_fixture.py",
                "tools/synthetic/successor_service.py",
            }
            self.assertTrue(required.isdisjoint(normal))
            self.assertTrue(required <= explicit)
        self.assertEqual(
            (ROOT / "server/src/ezllmrouter_server/observability.py").read_bytes(),
            next(
                (ROOT / source).read_bytes()
                for source, target in source_mapping(ROOT)
                if target == "worker/ezllmrouter_worker/observability.py"
            ),
        )

    def test_staged_runtime_implementation_inputs_are_not_test_sources(self):
        mappings = dict((target, source) for source, target in source_mapping(ROOT, True))
        for name in MODULES:
            target = "service/server/ezllmrouter_server/gateway/" + name + ".py"
            self.assertTrue(mappings[target].startswith("server/src/ezllmrouter_server/"))
        self.assertFalse(any("/compat/" in source for source in mappings.values()))

    def test_evidence_has_one_implementation_outside_the_test_tree(self):
        module = import_module("tools.gateway.evidence.capture_runtime")
        self.assertTrue(Path(module.__file__).is_relative_to(ROOT / "tools/gateway/evidence"))
        self.assertFalse((ROOT / "tests/gateway_integration/capture_runtime.py").exists())
