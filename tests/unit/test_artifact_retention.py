"""Only completed, owned and unpinned default runs may be automatically pruned."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch

from tools import check


class ArtifactRetentionTests(unittest.TestCase):
    def test_symlinks_and_unmarked_directories_are_never_pruned(self):
        from tools.artifact_runs import finish_run, new_run, prune

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent, external = root / "runs", root / "external"
            parent.mkdir()
            external.mkdir()
            secret = external / "retained.txt"
            secret.write_text("synthetic retained evidence")
            (parent / "run-linked").symlink_to(external, target_is_directory=True)
            pinned = new_run(parent, "run-", "health")
            (pinned / ".keep").symlink_to(root / "missing-pin-target")
            finish_run(pinned, passed=True)
            for _ in range(8):
                path = new_run(parent, "run-", "health")
                finish_run(path, passed=True)
            prune(parent, "health", keep_success=1, keep_failure=1)
            self.assertTrue(pinned.is_dir())
            self.assertTrue((parent / "run-linked").is_symlink())
            self.assertEqual(secret.read_text(), "synthetic retained evidence")

    def test_crashed_runs_become_failed_evidence_after_their_lease_is_released(self):
        from tools.artifact_runs import MARKER, prune

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = (
                "import os,sys; from pathlib import Path; "
                f"sys.path.insert(0,{str(Path(__file__).resolve().parents[2])!r}); "
                "from tools.artifact_runs import new_run; "
                "new_run(Path(sys.argv[1]),'run-','health'); os._exit(7)"
            )
            result = subprocess.run(
                [sys.executable, "-I", "-S", "-c", source, str(root)],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 7, result.stderr)
            prune(root, "health")
            run = next(root.glob("run-*"))
            self.assertEqual(json.loads((run / MARKER).read_text())["state"], "abandoned")

    def test_default_health_output_is_bounded_across_repeated_invocations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".nvmrc").write_text("24.22.1")
            with (
                patch.object(check, "ROOT", root),
                patch.object(check, "test_inventory_errors", return_value=[]),
                patch.object(check, "javascript_inventory_errors", return_value=[]),
                patch.object(check, "MODULES", ()),
                patch.object(check, "SCRIPT_TESTS", ()),
                patch.object(check, "FRONTEND_TESTS", ()),
                patch.object(check, "JAVASCRIPT_SCRIPTS", ()),
                patch.object(check.subprocess, "check_output", return_value="v24.22.1"),
                patch.object(check, "run"),
                patch("sys.argv", ["tools.check", "--tests-only"]),
                patch.dict("os.environ"),
                redirect_stdout(io.StringIO()),
            ):
                for _ in range(13):
                    self.assertEqual(check.main(), 0)
            runs = list((root / ".artifacts/test-health").glob("run-*"))
            self.assertLessEqual(len(runs), 5)

    def test_retention_preserves_active_pinned_legacy_and_failed_evidence(self):
        from tools.artifact_runs import finish_run, new_run, prune

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            legacy = root / "run-legacy"
            legacy.mkdir()
            (legacy / "evidence.txt").write_text("retained historical evidence")
            failed = new_run(root, "run-", "health")
            (failed / ".keep").touch()
            finish_run(failed, passed=False)
            active = new_run(root, "run-", "health")
            try:
                for _ in range(7):
                    complete = new_run(root, "run-", "health")
                    finish_run(complete, passed=True)
                prune(root, "health", keep_success=2, keep_failure=2)
                self.assertTrue(legacy.is_dir())
                self.assertTrue(failed.is_dir())
                self.assertTrue(active.is_dir())
                from tools.artifact_runs import MARKER

                self.assertEqual(json.loads((active / MARKER).read_text())["state"], "active")
                self.assertEqual(len(list(root.glob("run-*"))), 5)
            finally:
                finish_run(active, passed=False)
