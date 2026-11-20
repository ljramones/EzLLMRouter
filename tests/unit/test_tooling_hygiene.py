"""Import and ephemeral-port boundaries after the evidence tooling move."""

from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from ezllmrouter_server.operator_projection import OperatorProjection
from ezllmrouter_server.operator_web import serve
from ezllmrouter_server.store import SQLiteStore
from tests.operator_console.test_user_management_web import UserHTTPFixture
from tools.gateway.paths import source_root

ROOT = Path(__file__).resolve().parents[2]


class ToolingBoundaryTests(unittest.TestCase):
    def test_loopback_suites_load_without_fixture_paths(self):
        code = """
import sys
sys.path.insert(0, sys.argv[1])
from contextlib import ExitStack
import unittest
from tools.check import LOOPBACK_MODULES, block_network
before = sys.path[:]
loader = unittest.TestLoader()
with ExitStack() as stack:
    block_network(stack)
    for name in LOOPBACK_MODULES:
        suite = loader.loadTestsFromName(name)
        if not suite.countTestCases():
            raise RuntimeError('empty loopback suite: ' + name)
if loader.errors:
    raise RuntimeError('\\n'.join(loader.errors))
if sys.path != before:
    raise RuntimeError('loopback imports changed sys.path')
"""
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", code, str(ROOT)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_staged_actor_runs_from_private_stdin_without_an_image_source_file(self):
        source = (ROOT / "tools/operator/dev09_python_actor.py").read_text()
        code = (
            "from unittest.mock import patch\n"
            "with patch('socket.socket.connect', side_effect=AssertionError('network forbidden')):\n"
            "    exec(" + repr(source) + ")\n"
        )
        token = "private-synthetic-actor-token"
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", code],
            input=json.dumps({"base_url": "http://synthetic.invalid", "token": token, "rows": []}),
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(token, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["runs"], [])

    def test_package_imports_do_not_add_fixture_paths_or_flat_module_aliases(self):
        code = """
import sys
sys.path.insert(0, sys.argv[1])
before = sys.path[:]
from tests.gateway_integration import test_choice_b
from tools.gateway.evidence import dev12_integrated, dev12_ct02b_supp02
from deploy.local import local_profile
assert sys.path == before, (before, sys.path)
assert not {'guard', 'choice_b_sender', 'dev12_integrated', 'profile'} & sys.modules.keys()
"""
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", code, str(ROOT)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_source_root_supports_both_repository_and_extracted_service_layouts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, layout in (
                ("checkout", "server/src/ezllmrouter_server"),
                ("extracted", "server/ezllmrouter_server"),
            ):
                base = root / name
                (base / layout).mkdir(parents=True)
                script = base / "tools/gateway/evidence/proof.py"
                script.parent.mkdir(parents=True)
                script.write_text("")
                self.assertEqual(source_root(str(script)), base.resolve())
            with self.assertRaises(ValueError):
                source_root(str(root / "unrelated.py"))

    def test_operator_port_zero_uses_the_bound_port_for_host_and_origin_policy(self):
        class BoundServer:
            def __init__(self, address, handler):
                self.server_port = 49321
                self.server_address = (address[0], self.server_port)
                self.handler = handler

            def server_close(self):
                pass

        with tempfile.TemporaryDirectory() as temporary:
            store = SQLiteStore(Path(temporary) / "service.sqlite")
            self.addCleanup(store.close)
            with patch("ezllmrouter_server.operator_web.BoundedHTTPServer", BoundServer):
                server = serve(
                    "127.0.0.1",
                    0,
                    projection=OperatorProjection(store, "svc.synthetic"),
                    runner=None,
                    password="p" * 40,
                    fixture={},
                    build={},
                    web_root=ROOT / "web",
                    worker_probe=lambda: {},
                    sender_status=lambda: {},
                )
            try:
                origin = "http://127.0.0.1:49321"
                self.assertIn("127.0.0.1:49321", server.application.allowed_hosts)
                self.assertIn(origin, server.application.allowed_origins)
                self.assertNotIn("127.0.0.1:0", server.application.allowed_hosts)
                fixture = UserHTTPFixture()
                fixture.server, fixture.cookie, fixture.csrf = server, None, None
                status, headers, value = fixture.request(
                    "POST", "/operator/v1/login", {"password": "p" * 40}, origin=origin
                )
                self.assertEqual(status, 200)
                fixture.cookie = headers["Set-Cookie"].split(";", 1)[0]
                status, _, value = fixture.request("GET", "/operator/v1/session", origin=origin)
                self.assertEqual(status, 200)
                self.assertTrue(value["authenticated"])
            finally:
                server.server_close()
