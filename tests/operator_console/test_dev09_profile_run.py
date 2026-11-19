"""One-use namespace and credential-safe actor evidence without Docker."""
from pathlib import Path
import importlib.util
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


LOCAL = Path(__file__).resolve().parents[2] / "deploy/local"
sys.path.insert(0, str(LOCAL))
spec = importlib.util.spec_from_file_location("dev09_profile_run", LOCAL / "dev09_profile_run.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
prepare_spec = importlib.util.spec_from_file_location("dev09_prepare", LOCAL / "prepare.py")
prepare = importlib.util.module_from_spec(prepare_spec)
prepare_spec.loader.exec_module(prepare)


class ProfileRunnerTests(unittest.TestCase):
    def test_offline_wheel_reuse_requires_clean_matching_client_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            client = root / "clients/python/pyproject.toml"
            client.parent.mkdir(parents=True)
            client.write_text("[project]\nname='client'\n")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "add", "clients/python/pyproject.toml"], cwd=root,
                           check=True, capture_output=True)
            subprocess.run(["git", "-c", "user.name=EzLLMRouter test",
                            "-c", "user.email=test@example.invalid", "commit", "-qm", "baseline"],
                           cwd=root, check=True, capture_output=True)
            commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root).decode().strip()
            stage = root / "state/staging/source-prior"
            wheel = stage / "sdk" / prepare.DEV09_CLIENT
            wheel.parent.mkdir(parents=True)
            wheel.write_bytes(b"synthetic wheel bytes")
            digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
            manifest = stage / "LOCAL-BUILD-MANIFEST.json"
            manifest.write_text(json.dumps({"commit": commit, "dirty": False,
                                            "dev09_client_wheel_sha256": digest}))
            output = root / "sdk"
            output.mkdir()
            with patch.object(prepare, "ROOT", root), patch.object(prepare, "STATE", root / "state"):
                self.assertEqual(prepare.reuse_client_wheel(output)["source_commit"], commit)
                self.assertEqual((output / prepare.DEV09_CLIENT).read_bytes(), wheel.read_bytes())
                (output / prepare.DEV09_CLIENT).unlink()
                wheel.write_bytes(b"tampered")
                self.assertIsNone(prepare.reuse_client_wheel(output))
                wheel.write_bytes(b"synthetic wheel bytes")
                client.write_text("[project]\nname='changed'\n")
                self.assertIsNone(prepare.reuse_client_wheel(output))

    def test_staging_scope_preserves_unrelated_untracked_documents(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            staged = root / "deploy/local/prepare.py"
            staged.parent.mkdir(parents=True)
            staged.write_text("initial\n")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "add", "deploy/local/prepare.py"], cwd=root,
                           check=True, capture_output=True)
            subprocess.run(["git", "-c", "user.name=EzLLMRouter test",
                            "-c", "user.email=test@example.invalid", "commit", "-qm", "baseline"],
                           cwd=root, check=True, capture_output=True)
            other = root / "docs/architecture/new-notes.md"
            other.parent.mkdir(parents=True)
            other.write_text("unrelated\n")
            with patch.object(prepare, "ROOT", root):
                self.assertFalse(prepare.source_dirty())
                staged.write_text("changed\n")
                self.assertTrue(prepare.source_dirty())
                staged.write_text("initial\n")
                (root / "deploy/local/new-staged-file.py").write_text("new\n")
                self.assertTrue(prepare.source_dirty())

    def test_offline_package_inventory_ignores_uv_gitignore_only(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for name in (".gitignore", "client.whl"):
                (directory / name).write_text("synthetic")
            self.assertEqual(prepare.package_artifacts(directory), {"client.whl"})
            (directory / "unexpected.tgz").write_text("synthetic")
            self.assertEqual(prepare.package_artifacts(directory), {"client.whl", "unexpected.tgz"})

    def test_failed_prepare_discards_only_its_temporary_stage(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / "deploy/local/.state"
            artifact = root / "artifacts"
            artifact.mkdir()
            (artifact / "ARTIFACT-CUSTODY.json").write_text(
                json.dumps({"items": [{} for _ in range(177)]}))
            old = state / "staging/source-historical"
            old.mkdir(parents=True)
            (old / "failure.txt").write_text("preserve")
            with patch.object(prepare, "ROOT", root), patch.object(prepare, "STATE", state), \
                 patch.object(prepare, "fingerprint", return_value="a" * 64), \
                 patch.object(prepare, "prepare_work", side_effect=RuntimeError("offline build failed")), \
                 patch.dict(prepare.os.environ, {"EZLLMROUTER_ARTIFACT_ROOT": str(artifact)}):
                with self.assertRaisesRegex(RuntimeError, "offline build failed"):
                    prepare.main()
            self.assertEqual(sorted(path.name for path in (state / "staging").iterdir()),
                             ["source-historical"])
            self.assertEqual((old / "failure.txt").read_text(), "preserve")

    def test_claim_does_not_reuse_completed_or_partial_run(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(runner, "RUNS", Path(temp)):
            path = runner.claim("dev09-profile-20261022-01")
            (path / "failure.json").write_text("historical failure")
            with self.assertRaises(SystemExit) as refused:
                runner.claim("dev09-profile-20261022-01")
            self.assertIn("run ID already exists", str(refused.exception))
            self.assertEqual((path / "failure.json").read_text(), "historical failure")

    def test_actor_outcome_expectation_matches_grant_stage(self):
        with patch.object(runner, "command", return_value="{}") as command:
            runner.actor(Path("unused"), "denied", ["actor"], {}, token="synthetic", rows=[],
                         outcome={"event_id": "denied"}, denied=True)
            self.assertIs(command.call_args.kwargs["payload"]["expect_outcome_authority"], False)
            runner.actor(Path("unused"), "authorized", ["actor"], {}, token="synthetic", rows=[],
                         outcome={"event_id": "authorized"})
            self.assertIs(command.call_args.kwargs["payload"]["expect_outcome_authority"], True)

    def test_actor_output_redacts_even_early_failure(self):
        secret = "synthetic-test-token-do-not-save"
        with tempfile.TemporaryDirectory() as temp:
            payload = {"token": secret, "rows": []}
            completed = subprocess.CompletedProcess(["actor"], 1, secret, "failed: " + secret)
            with patch.object(runner.subprocess, "run", return_value=completed), \
                 patch.object(runner.profile, "redact", side_effect=lambda value: value):
                with self.assertRaises(RuntimeError) as failed:
                    runner.command(Path(temp), "early", ["actor"], {}, payload=payload)
            self.assertNotIn(secret, str(failed.exception))
            self.assertNotIn(secret, (Path(temp) / "early.stdout.txt").read_text())
            self.assertNotIn(secret, (Path(temp) / "early.stderr.txt").read_text())
            self.assertEqual((Path(temp) / "early.exit.txt").read_text(), "1\n")


if __name__ == "__main__":
    unittest.main()
