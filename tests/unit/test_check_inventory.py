"""New regression files must run or carry a maintained exclusion reason."""

import shutil
import io
import json
import os
import sys

from pathlib import Path
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import check
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
        self.path.write_text(
            "import unittest\nclass Cases(unittest.TestCase):\n def test_example(self): pass\n"
        )
        for module in ("tests.unit.test_example", "tests.unit.test_example.Cases"):
            self.assertEqual(self.check_inventory(modules=(module,)), [])

    def test_class_registration_cannot_hide_an_added_class(self):
        self.path.write_text(
            "import unittest\nclass Cases(unittest.TestCase):\n def test_one(self): pass\nclass NewCases(unittest.TestCase):\n def test_two(self): pass\n"
        )
        errors = self.check_inventory(modules=("tests.unit.test_example.Cases",))
        self.assertIn("Unregistered test class: tests/unit/test_example.py:NewCases", errors)
        self.assertEqual(
            self.check_inventory(
                modules=("tests.unit.test_example.Cases", "tests.unit.test_example.NewCases")
            ),
            [],
        )

    def test_inherited_classes_and_testcase_aliases_require_whole_class_registration(self):
        self.path.write_text(
            "from unittest import TestCase as Case\nclass Base(Case):\n def test_one(self): pass\nclass Inherited(Base): pass\n"
        )
        errors = self.check_inventory(modules=("tests.unit.test_example.Base.test_one",))
        self.assertIn("Unregistered test class: tests/unit/test_example.py:Inherited", errors)
        self.assertIn(
            "Register the whole test class: tests/unit/test_example.py:Base.test_one", errors
        )
        self.assertEqual(
            self.check_inventory(
                modules=("tests.unit.test_example.Base", "tests.unit.test_example.Inherited")
            ),
            [],
        )

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
    def test_udp_is_blocked_and_python_isolated_children_and_grandchildren_inherit_guard(self):
        with ExitStack() as stack:
            block_network(stack)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
                with self.assertRaises(AssertionError):
                    connection.sendto(b"synthetic", ("127.0.0.1", 9))
            source = """import socket
blocked=0
for operation in ('connect','bind','sendto','dns'):
 try:
  with socket.socket(socket.AF_INET,socket.SOCK_DGRAM if operation=='sendto' else socket.SOCK_STREAM) as stream:
   if operation=='dns': socket.getaddrinfo('localhost',9)
   elif operation=='sendto': stream.sendto(b'test',('127.0.0.1',9))
   elif operation=='bind': stream.bind(('127.0.0.1',0))
   else: stream.connect(('127.0.0.1',9))
 except AssertionError: blocked+=1
assert blocked==4,blocked
print('guarded')
"""
            for flags in ([], ["-I"], ["-I", "-S"]):
                result = subprocess.run(
                    [sys.executable, *flags, "-c", source],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    env={},
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), "guarded")
            nested = (
                "import subprocess,sys; result=subprocess.run([sys.executable,'-I','-S','-c',"
                + repr(source)
                + "],capture_output=True,text=True); assert result.returncode==0,result.stderr"
            )
            subprocess.run([sys.executable, "-I", "-S", "-c", nested], check=True, timeout=10)

    def test_node_children_are_guarded_even_with_a_replaced_environment(self):
        source = "const net=require('node:net'),dns=require('node:dns'),dgram=require('node:dgram');let n=0;for(const action of [()=>net.connect(9,'127.0.0.1'),()=>dns.lookup('localhost'),()=>dgram.createSocket('udp4').send('test',9,'127.0.0.1'),()=>fetch('http://127.0.0.1:9')]){try{action();}catch(error){if(!error.message.includes('regression'))throw error;n++;}}if(n!==4)process.exit(1);console.log('guarded');"
        with ExitStack() as stack:
            block_network(stack)
            result = subprocess.run(
                [shutil.which("node"), "-e", source],
                capture_output=True,
                text=True,
                timeout=10,
                env={},
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "guarded")

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

    def test_http_server_bind_names_loopback_without_reverse_dns(self):
        from ezllmrouter_server.http_server import BoundedHTTPServer

        with (
            patch.object(socket.socket, "bind") as bind,
            patch.object(socket.socket, "getsockname", return_value=("127.0.0.1", 8765)),
            ExitStack() as stack,
        ):
            block_network(stack, loopback=True)
            for server_type in (HTTPServer, ThreadingHTTPServer, BoundedHTTPServer):
                with self.subTest(server=server_type.__name__):
                    with server_type(
                        ("127.0.0.1", 0), BaseHTTPRequestHandler, bind_and_activate=False
                    ) as server:
                        server.server_bind()
                        self.assertEqual(server.server_name, "127.0.0.1")
                        self.assertEqual(server.server_port, 8765)
            self.assertEqual(bind.call_count, 3)

    def test_loopback_names_do_not_enable_dns_or_offline_access(self):
        with ExitStack() as stack:
            block_network(stack, loopback=True)
            for host in ("127.0.0.1", "::1", "localhost", b"127.0.0.1"):
                with self.subTest(host=host):
                    expected = host.decode("ascii") if isinstance(host, bytes) else host
                    self.assertEqual(socket.getfqdn(host), expected)
            for host in ("192.0.2.1", "0.0.0.0", "provider.invalid", "", b"\xff"):
                with self.subTest(host=host), self.assertRaises(AssertionError):
                    socket.getfqdn(host)
            for name in ("gethostbyname", "gethostbyname_ex", "gethostbyaddr", "getnameinfo"):
                with self.subTest(operation=name), self.assertRaises(AssertionError):
                    getattr(socket, name)("127.0.0.1")
        with ExitStack() as stack:
            block_network(stack)
            with self.assertRaises(AssertionError):
                socket.getfqdn("127.0.0.1")

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


class RunnerResultsTests(unittest.TestCase):
    def test_all_skipped_and_empty_suites_are_not_passes(self):
        class Cases(unittest.TestCase):
            @unittest.skip("missing target")
            def test_target(self):
                pass

        for suite in (
            unittest.TestSuite(),
            unittest.defaultTestLoader.loadTestsFromTestCase(Cases),
        ):
            with (
                patch.object(unittest.defaultTestLoader, "loadTestsFromName", return_value=suite),
                redirect_stderr(io.StringIO()),
            ):
                self.assertFalse(check.run_module("synthetic", loopback=False))

    def test_javascript_inventory_rejects_new_or_unexplained_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "tests").mkdir()
            (root / "tests/new.cjs").write_text("console.log('test')")
            (root / "tests/javascript_inventory.json").write_text("{}")
            self.assertIn(
                "Unclassified JavaScript/TypeScript file: tests/new.cjs",
                check.javascript_inventory_errors(root),
            )
            (root / "tests/javascript_inventory.json").write_text(
                json.dumps({"tests/new.cjs": {"runner": "target", "reason": ""}})
            )
            self.assertIn(
                "Missing JavaScript classification reason: tests/new.cjs",
                check.javascript_inventory_errors(root),
            )

    def test_failures_from_modules_scripts_and_frontend_are_all_collected(self):
        seen = []

        def run(argv):
            seen.append(argv)
            if any(
                value in {"bad.module", "bad.script", "tests/operator_console/bad.cjs"}
                for value in argv
            ):
                raise subprocess.CalledProcessError(1, argv)

        error = io.StringIO()
        with (
            patch.object(check, "test_inventory_errors", return_value=[]),
            patch.object(check, "javascript_inventory_errors", return_value=[]),
            patch.object(
                check.subprocess,
                "check_output",
                return_value="v" + (check.ROOT / ".nvmrc").read_text().strip().lstrip("v"),
            ),
            patch.object(check, "MODULES", ("bad.module", "good.module")),
            patch.object(check, "SCRIPT_TESTS", ("bad.script", "good.script")),
            patch.object(check, "FRONTEND_TESTS", ("bad.cjs", "good.cjs")),
            patch.object(check, "JAVASCRIPT_SCRIPTS", ()),
            patch.object(check, "run", side_effect=run),
            patch.object(sys, "argv", ["check.py", "--tests-only"]),
            redirect_stdout(io.StringIO()),
            redirect_stderr(error),
        ):
            self.assertEqual(check.main(), 1)
        for name in ("bad.module", "bad.script", "bad.cjs"):
            self.assertIn(name, error.getvalue())
        self.assertTrue(any("good.module" in argv for argv in seen))
        self.assertTrue(any("good.script" in argv for argv in seen))
        self.assertTrue(any("tests/operator_console/good.cjs" in argv for argv in seen))


class CoverageTests(unittest.TestCase):
    def test_coverage_tracks_worker_lines_and_reports_unexecuted_source(self):
        import runpy
        import threading
        from tools.test_coverage import LineCoverage, report

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "package"
            source.mkdir()
            path = source / "example.py"
            path.write_text("def used():\n return 1\ndef missing():\n return 2\n")
            output = root / "coverage"
            with LineCoverage(output, (source,)):
                namespace = runpy.run_path(str(path))
                worker = threading.Thread(target=namespace["used"])
                worker.start()
                worker.join(1)
            summary = report(output, (source,), root)
            detail = summary["files"]["package/example.py"]
            self.assertNotIn(2, detail["missing_lines"])
            self.assertIn(4, detail["missing_lines"])
            self.assertLess(summary["percent"], 100)
            self.assertTrue((output / "summary.json").is_file())

    def test_isolated_child_writes_coverage_with_replaced_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            path = check.ROOT / "server/src/ezllmrouter_server/identifiers.py"
            source = (
                "import runpy; values=runpy.run_path("
                + repr(str(path))
                + "); assert values['require_identifier']('fixture')=='fixture'"
            )
            with (
                patch.dict(os.environ, {"EZLLMROUTER_TEST_COVERAGE": directory}),
                ExitStack() as stack,
            ):
                block_network(stack)
                subprocess.run(
                    [sys.executable, "-I", "-S", "-c", source], env={}, check=True, timeout=10
                )
            records = list(Path(directory).glob("lines-*.json"))
            self.assertTrue(records)
            names = {name for record in records for name in json.loads(record.read_text())}
            self.assertIn(str(path), names)
