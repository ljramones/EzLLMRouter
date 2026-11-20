"""Local command ownership and filesystem boundaries without Docker."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from deploy.local import command_support, filesystem_support

ROOT = Path(__file__).resolve().parents[2]


class CommandCaptureTests(unittest.TestCase):
    def test_real_timeout_is_reaped_and_partial_output_is_saved_redacted_and_private(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = command_support.capture(
                [
                    sys.executable,
                    "-I",
                    "-c",
                    "import time; print('secret-canary',flush=True); time.sleep(30)",
                ],
                cwd=root,
                timeout=0.2,
            )
            self.assertEqual(result.returncode, 124)
            self.assertIn("secret-canary", result.stdout)
            saved = command_support.record(
                root, "timeout", result, lambda text: text.replace("secret-canary", "[REDACTED]")
            )
            self.assertNotIn("secret-canary", saved.stdout)
            self.assertEqual((root / "timeout.exit.txt").read_text(), "124\n")
            self.assertEqual((root / "timeout.stdout.txt").stat().st_mode & 0o777, 0o600)

    def test_record_names_and_symlinks_cannot_write_outside_the_evidence_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root / "original"
            outside.write_text("unchanged")
            result = subprocess.CompletedProcess(["synthetic"], 0, "new", "")
            with self.assertRaises(ValueError):
                command_support.record(root, "../escape", result, str)
            (root / "link.stdout.txt").symlink_to(outside)
            with self.assertRaises(ValueError):
                command_support.record(root, "link", result, str)
            self.assertEqual(outside.read_text(), "unchanged")

    def test_explicit_context_and_stdlib_profiler_coexist_with_local_profile(self):
        code = "import cProfile,local_profile,json; print(json.dumps(local_profile.DOCKER))"
        import os

        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT / "deploy/local",
            env={**os.environ, "EZLLMROUTER_DOCKER_CONTEXT": "controlled-test-context"},
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        self.assertIn('"--context", "controlled-test-context"', result.stdout)


class FilesystemHelperTests(unittest.TestCase):
    def test_current_dates_are_accepted_and_collisions_preserve_the_existing_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = filesystem_support.claim_run_id(root, "usage-20261120-01", "usage")
            (run / "result.json").write_text("original")
            with self.assertRaisesRegex(SystemExit, "run ID already exists"):
                filesystem_support.claim_run_id(root, run.name, "usage")
            self.assertEqual((run / "result.json").read_text(), "original")
            for name in ("usage-20260230-01", "usage-../../escape", "other-20261120-01"):
                with self.assertRaises(SystemExit):
                    filesystem_support.claim_run_id(root, name, "usage")

    def test_source_reuse_checks_bytes_and_rejects_missing_or_symlinked_trees(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            left, right = root / "left", root / "right"
            left.mkdir()
            right.mkdir()
            for path in (left, right):
                (path / "source.py").write_text("original")
            self.assertTrue(filesystem_support.same_tree(left, right))
            (right / "source.py").write_text("different")
            self.assertFalse(filesystem_support.same_tree(left, right))
            with self.assertRaises(ValueError):
                filesystem_support.same_tree(root / "absent", root / "also-absent")
            (right / "linked").symlink_to(left / "source.py")
            with self.assertRaises(ValueError):
                filesystem_support.same_tree(left, right)

    def test_fixture_mounts_are_explicit_readonly_and_fail_before_docker(self):
        from deploy.local import local_profile

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(ValueError):
                local_profile.fixture_mounts({"build_dir": str(root)})
            for name in ("gateway", "dev_slice", "tests"):
                (root / "service" / name).mkdir(parents=True)
            mounts = local_profile.fixture_mounts({"build_dir": str(root)})
            self.assertEqual(mounts.count("--mount"), 3)
            self.assertTrue(all(value.endswith(",readonly") for value in mounts[1::2]))


class OperatorSessionTests(unittest.TestCase):
    def test_oversized_reply_closes_connection_and_never_replays(self):
        from deploy.local.operator_client import OperatorSession

        connection = unittest.mock.Mock()
        connection.getresponse.return_value.read.return_value = b"x" * (16 * 1024 * 1024 + 1)
        with patch("http.client.HTTPConnection", return_value=connection):
            with self.assertRaises(ValueError):
                OperatorSession("private-test-password").call("GET", "/operator/v1/overview")
        connection.request.assert_called_once()
        connection.close.assert_called_once()
