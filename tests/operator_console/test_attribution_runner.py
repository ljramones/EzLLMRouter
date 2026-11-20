"""Rehearse target-driver command construction without a Docker daemon."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / "deploy/local"

spec = importlib.util.spec_from_file_location("dev07_run", LOCAL / "dev07_run.py")
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


class RunnerTests(unittest.TestCase):
    def test_profile_stage_logs_precede_the_single_summary(self):
        output = (
            "Local profile: backup-service-id…\nLocal profile: backup-service-id exited 0\n"
            '{"submissions":7,"sha256":"a"}\n'
        )
        self.assertEqual(driver.profile_summary(output)["submissions"], 7)

    def test_private_actor_input_and_strict_single_result(self):
        with tempfile.TemporaryDirectory() as scratch, patch.object(driver, "STATE", Path(scratch)):
            run = driver.Run("dev07-unit-test-01")
            run.build = {"fingerprint": "a" * 64, "build_dir": scratch}
            run.netns = "b" * 64
            token = "synthetic-private-token-000000000000000000000000"
            run.tokens.append(token)
            captured = []

            def fake_command(label, argv, *, input_value, timeout):
                captured.append((label, argv, input_value, timeout))
                return json.dumps({"kind": "denied", "code": "POLICY_DENIED"})

            with patch.object(run, "command", side_effect=fake_command):
                result = run.actor("negative", "js", token, "deny", "cfg.test")
            self.assertEqual(result["code"], "POLICY_DENIED")
            self.assertNotIn(token, " ".join(captured[0][1]))
            self.assertEqual(captured[0][2]["token"], token)
            self.assertIn("--network", captured[0][1])
            self.assertIn("container:" + run.netns, captured[0][1])
            self.assertNotIn(token, (run.path / "actor-negative.json").read_text())

    def test_namespaces_are_single_use_and_invalid_names_fail(self):
        with tempfile.TemporaryDirectory() as scratch, patch.object(driver, "STATE", Path(scratch)):
            driver.Run("dev07-unit-test-02")
            with self.assertRaises(FileExistsError):
                driver.Run("dev07-unit-test-02")
            with self.assertRaises(RuntimeError):
                driver.Run("../bad")


if __name__ == "__main__":
    unittest.main()
