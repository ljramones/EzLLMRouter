"""Local Unix-socket startup and strict identity-output controls; no model calls."""

import json
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]

from ezllmrouter_server.gateway.choice_b_wire import receive, send
from tools.gateway.evidence.verify_dev05 import one
from ezllmrouter_server.gateway import worker_ready as worker_ready


def identity():
    return {
        "boundary": "network-disabled LiteLLM ASGI worker",
        "selected_transport": "RelayTransport",
        "relay_attempt_counts": {},
        **{
            name: {"path": "/synthetic/" + name, "sha256": "a" * 64}
            for name in ("litellm", "proxy", "openai_sdk", "httpx")
        },
    }


class WorkerReadyFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dev05-worker-ready-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "worker.sock"
        self.commands = []
        self.threads = []

    def start_server(self, response=None, delay=0.0, malformed=False):
        def serve():
            time.sleep(delay)
            if self.path.exists():
                self.path.unlink()
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
                listener.bind(str(self.path))
                listener.listen(1)
                listener.settimeout(2)
                with listener.accept()[0] as stream:
                    self.commands.append(receive(stream))
                    if malformed:
                        stream.sendall(struct.pack("!I", 1) + b"{")
                    else:
                        send(stream, identity() if response is None else response)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        self.threads.append(thread)

    def run_probe(self, deadline="0.4", allow_activity=False):
        entry = ["-m", "ezllmrouter_server.gateway.worker_ready"]
        if isinstance(self, WorkerReadyOfflineTests):
            # Exercise the child's real retry/deadline path without opening a
            # named IPC endpoint outside the offline socket-pair fixtures.
            entry = [
                "-c",
                "from unittest.mock import patch; from ezllmrouter_server.gateway import worker_ready; "
                "guard=patch.object(worker_ready.socket.socket,'connect',side_effect=FileNotFoundError('synthetic absent endpoint')); "
                "guard.start(); worker_ready.main()",
            ]
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                *entry,
                "--socket",
                str(self.path),
                "--deadline",
                deadline,
                *(["--allow-activity"] if allow_activity else []),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
        for thread in self.threads:
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())
        self.assertTrue(all(command == {"kind": "module_identity"} for command in self.commands))
        return result


class WorkerReadyTests(WorkerReadyFixture, unittest.TestCase):
    def test_delayed_socket_handshake_and_strict_json_consumer(self):
        self.start_server(delay=0.12)
        result = self.run_probe()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.commands), 1)
        self.assertEqual(json.loads(result.stdout), identity())
        run = self.root / "run"
        run.mkdir()
        (run / "d05-worker-identities.stdout").write_text(result.stdout)
        self.assertEqual(one(run, "d05-worker-identities"), identity())

    def test_stale_refused_socket_then_live_handshake(self):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stale:
            stale.bind(str(self.path))
        self.start_server(delay=0.12)
        result = self.run_probe()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.commands), 1)

    def test_failed_worker_stale_endpoint_is_bounded(self):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stale:
            stale.bind(str(self.path))
        result = self.run_probe("0.2")
        self.assertEqual(result.returncode, 1)
        self.assertIn("worker identity socket not ready by deadline", result.stderr)
        self.assertEqual(self.commands, [])

    def test_malformed_response_stops_without_retry(self):
        self.start_server(malformed=True)
        result = self.run_probe()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("worker readiness failed", result.stderr)
        self.assertEqual(len(self.commands), 1)

    def test_wrong_identity_stops_without_retry(self):
        wrong = identity()
        wrong["selected_transport"] = "wrong"
        self.start_server(response=wrong)
        result = self.run_probe()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("worker identity mismatch", result.stderr)
        self.assertEqual(len(self.commands), 1)

    def test_live_profile_allows_recorded_attempts_but_default_remains_strict(self):
        active = identity()
        active["relay_attempt_counts"] = {"attempt." + "a" * 32: 1}
        with self.assertRaisesRegex(ValueError, "worker identity mismatch"):
            worker_ready.validate_identity(active)
        self.assertEqual(worker_ready.validate_identity(active, require_empty=False), active)
        self.start_server(response=active)
        result = self.run_probe(allow_activity=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), active)


class WorkerReadyOfflineTests(WorkerReadyFixture, unittest.TestCase):
    def test_never_ready_is_bounded(self):
        start = time.monotonic()
        result = self.run_probe("0.2")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("worker identity socket not ready by deadline", result.stderr)
        self.assertLess(time.monotonic() - start, 1.0)
        self.assertEqual(self.commands, [])

    def test_live_profile_rejects_malformed_attempt_counter(self):
        for counts in ({"attempt." + "b" * 32: 0}, {"wrong": 1}, {"attempt." + "b" * 32: True}, []):
            with self.subTest(counts=counts):
                value = identity()
                value["relay_attempt_counts"] = counts
                with self.assertRaisesRegex(ValueError, "worker identity mismatch"):
                    worker_ready.validate_identity(value, require_empty=False)

    def test_permission_error_stops_without_retry(self):
        class DeniedSocket:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def settimeout(self, _timeout):
                pass

            def connect(self, _path):
                raise PermissionError("synthetic Unix socket denial")

        with patch.object(worker_ready.socket, "socket", return_value=DeniedSocket()) as opened:
            with self.assertRaisesRegex(PermissionError, "synthetic Unix socket denial"):
                worker_ready.probe(self.path, 0.4)
        self.assertEqual(opened.call_count, 1)

    def test_failed_probe_capture_preserves_failure_and_no_secret(self):
        result = self.run_probe("0.2")
        self.assertEqual(result.returncode, 1)
        run = self.root / "run-20261020-95"
        run.mkdir()
        for name, value in (
            ("d05-worker-identities.argv", "worker_ready.py --socket worker.sock\n"),
            ("d05-worker-identities.stdout", result.stdout),
            ("d05-worker-identities.stderr", result.stderr),
            ("d05-worker-identities.exit", str(result.returncode) + "\n"),
            ("work.exit", "1\n"),
            ("run.exit", "1\n"),
        ):
            (run / name).write_text(value)
        script = (
            'source "$1"; run_dir=$2; result_dir=$3; capture_tool=$4; '
            "capture_script=$5; python_tool=/usr/bin/true; started=1; built_images=(); "
            'compose() { if [[ "$1" == logs && "$*" == *worker_choice_b* ]]; '
            'then printf "synthetic worker startup failure\\n"; fi; }; '
            'capture() { "$capture_tool" -I -B "$capture_script" '
            '"$run_dir" "$result_dir" DEV-05; }; '
            "finish_dev05 1"
        )
        finished = subprocess.run(
            [
                "bash",
                "-c",
                script,
                "bash",
                str(ROOT / "tools/gateway/evidence/dev05_steps.sh"),
                str(run),
                str(self.root),
                sys.executable,
                str(ROOT / "tools/gateway/evidence/capture_runtime.py"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(finished.returncode, 1, finished.stderr)
        self.assertEqual((run / "capture.exit").read_text(), "0\n")
        self.assertEqual((run / "worker-startup-logs.exit").read_text(), "0\n")
        packet = self.root / "DEV-05-RUNTIME-run-20261020-95.zip"
        with zipfile.ZipFile(packet) as archive:
            self.assertEqual(archive.read("work.exit"), b"1\n")
            self.assertEqual(archive.read("run.exit"), b"1\n")
            self.assertEqual(archive.read("d05-worker-identities.exit"), b"1\n")
            self.assertIn(
                b"worker identity socket not ready by deadline",
                archive.read("d05-worker-identities.stderr"),
            )
            self.assertIn(
                b"synthetic worker startup failure", archive.read("worker-startup-logs.stdout")
            )
            self.assertNotIn("token", archive.namelist())
            self.assertNotIn("provider-key", archive.namelist())
        self.assertEqual(self.commands, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
