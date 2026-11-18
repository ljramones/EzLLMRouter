"""Credential failure capture and persistent-profile preparation boundaries."""
import json
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "deploy/local"))
import profile


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / ".state"
        self.state.mkdir(mode=0o700)
        self.patched = patch.object(profile, "STATE", self.state)
        self.patched.start()
        self.addCleanup(self.patched.stop)

    def test_first_generation_and_stable_readback(self):
        data, password = profile.secrets_on_disk()
        self.assertGreaterEqual(len(password), 32)
        self.assertTrue(data["synthetic_provider_key"].startswith("sk-"))
        self.assertEqual(profile.secrets_on_disk(), (data, password))
        self.assertNotIn(password, profile.redact("prefix " + password + " suffix"))
        self.assertNotIn(data["service_token"], profile.redact(data["service_token"]))

    def test_partial_credentials_fail_without_default_or_overwrite(self):
        path = self.state / "credentials.json"
        path.write_text(json.dumps({"service_token": "synthetic"}))
        original = path.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "partial local credentials"):
            profile.secrets_on_disk()
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse((self.state / "operator-password").exists())
        stderr = io.StringIO()
        with patch.object(sys, "argv", ["profile.py", "up"]), \
                contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
            profile.run_cli()
        self.assertIn("partial local credentials", stderr.getvalue())
        diagnostic = json.loads((self.state / "last-error.json").read_text())
        self.assertEqual(diagnostic["error_type"], "RuntimeError")
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse((self.state / "commands").exists())

    def test_invalid_fully_generated_shape_fails_closed(self):
        (self.state / "credentials.json").write_text("{}")
        (self.state / "operator-password").write_text("p" * 40)
        with self.assertRaises((KeyError, RuntimeError)):
            profile.secrets_on_disk()

    def test_readiness_failure_captures_logs_before_owned_cleanup(self):
        names = []

        def fake_command(name, _argv, env=None, allowed=(0,)):
            names.append(name)
            return ("127.0.0.1:8780" if name == "console-port" else ""), 0

        with patch.object(profile, "secrets_on_disk", return_value=({}, "p" * 40)), \
                patch.object(profile, "current", return_value={"fingerprint": "f" * 64}), \
                patch.object(profile, "environment", return_value={}), \
                patch.object(profile, "ensure_owner"), \
                patch.object(profile, "build_images"), \
                patch.object(profile, "wait_health", side_effect=RuntimeError("readiness deadline")), \
                patch.object(profile, "command", side_effect=fake_command):
            with self.assertRaisesRegex(RuntimeError, "readiness deadline"):
                profile.profile_up()
        self.assertLess(names.index("failure-ps"), names.index("failure-down"))
        self.assertLess(names.index("failure-logs"), names.index("failure-down"))
        self.assertEqual(names.count("failure-down"), 1)

    def test_missing_console_binding_fails_before_readiness_wait(self):
        names = []

        def fake_command(name, _argv, env=None, allowed=(0,)):
            names.append(name)
            return "", 0

        with patch.object(profile, "secrets_on_disk", return_value=({}, "p" * 40)), \
                patch.object(profile, "current", return_value={"fingerprint": "f" * 64}), \
                patch.object(profile, "environment", return_value={}), \
                patch.object(profile, "ensure_owner"), \
                patch.object(profile, "build_images"), \
                patch.object(profile, "wait_health") as health, \
                patch.object(profile, "command", side_effect=fake_command):
            with self.assertRaisesRegex(RuntimeError, "console loopback port binding missing"):
                profile.profile_up()
        health.assert_not_called()
        self.assertLess(names.index("failure-console-port"), names.index("failure-down"))
        self.assertLess(names.index("failure-console-socket"), names.index("failure-down"))

    def test_diagnose_reads_existing_profile_without_restarting(self):
        (self.state / "PROFILE-OWNER.json").write_text("{}")
        names = []

        def fake_command(name, _argv, env=None, allowed=(0,)):
            names.append(name)
            return ("service Exited (1)" if name == "diagnose-ps" else "service traceback"), 0

        output = io.StringIO()
        with patch.object(sys, "argv", ["profile.py", "diagnose"]), \
                patch.object(profile, "current", return_value={"fingerprint": "f" * 64}), \
                patch.object(profile, "environment", return_value={}), \
                patch.object(profile, "command", side_effect=fake_command), \
                contextlib.redirect_stdout(output):
            profile.main()
        self.assertEqual(names, ["diagnose-ps", "diagnose-logs"])
        self.assertIn("service traceback", output.getvalue())

    def test_restart_stops_only_owned_profile_without_removing_volumes(self):
        (self.state / "PROFILE-OWNER.json").write_text("{}")
        names = []

        def fake_command(name, argv, env=None, allowed=(0,)):
            names.append((name, argv))
            return "", 0

        with patch.object(sys, "argv", ["profile.py", "restart"]), \
                patch.object(profile, "current", return_value={"fingerprint": "f" * 64}), \
                patch.object(profile, "environment", return_value={}), \
                patch.object(profile, "ensure_owner") as owner, \
                patch.object(profile, "command", side_effect=fake_command), \
                patch.object(profile, "profile_up") as up:
            profile.main()
        owner.assert_called_once_with({})
        up.assert_called_once_with()
        self.assertEqual([name for name, _ in names], ["restart-stop"])
        self.assertEqual(names[0][1][-2:], ["down", "--remove-orphans"])
        self.assertNotIn("-v", names[0][1])

    def test_audit_uses_existing_owned_build_without_prepare_or_restart(self):
        (self.state / "PROFILE-OWNER.json").write_text("{}")
        build = {"fingerprint": "f" * 64}
        with patch.object(sys, "argv", ["profile.py", "audit"]), \
                patch.object(profile, "current", return_value=build), \
                patch.object(profile, "environment", return_value={}), \
                patch.object(profile, "ensure_owner") as owner, \
                patch.object(profile, "audit_live") as audit, \
                patch.object(profile, "command") as command:
            profile.main()
        owner.assert_called_once_with({})
        audit.assert_called_once_with(build, {})
        command.assert_not_called()

    def test_persistence_reuses_images_and_volumes_without_send(self):
        receipt = {"submission_ids": ["s1", "s2", "s3", "s4"],
                   "no_store_submission_id": "s4", "after_submissions": 7}
        (self.state / "last-explicit-exercise.json").write_text(json.dumps(receipt))
        (self.state / "last-live-audit.json").write_text(json.dumps({
            "kind": "DEV-06 read-only live correlation",
            "build": {"fingerprint": "f" * 64}, "matched_exercise_attempts": 4,
            "single_arrival_per_receiver_attempt": True,
            "topology_negative_added_arrivals": False, "receiver_arrivals_total": 7}))
        overview = {"build": {"fingerprint": "f" * 64},
                    "counts": {"submissions": 7, "completed": 7,
                               "known_failures": 0, "unknown_outcomes": 0}}
        names = []

        def fake_command(name, argv, env=None, allowed=(0,)):
            names.append((name, argv))
            return "127.0.0.1:8780" if name == "console-port" else "", 0

        with patch.object(profile, "secrets_on_disk", return_value=({}, "p" * 40)), \
                patch.object(profile, "wait_health", return_value=(object(), overview)), \
                patch.object(profile, "readback", return_value={"retained_submission_ids": 4,
                    "no_store_candidate_access": "not_retained"}) as readback, \
                patch.object(profile, "receiver_count", return_value=7) as count, \
                patch.object(profile, "topology", return_value=7) as topology, \
                patch.object(profile, "command", side_effect=fake_command):
            with contextlib.redirect_stdout(io.StringIO()):
                profile.verify_persistence({"fingerprint": "f" * 64}, {})
        self.assertEqual([name for name, _ in names],
                         ["persistence-stop", "persistence-up", "console-port"])
        self.assertEqual(names[0][1][-2:], ["down", "--remove-orphans"])
        self.assertEqual(names[1][1][-3:], ["up", "-d", "--no-build"])
        self.assertNotIn("-v", names[0][1])
        self.assertEqual(readback.call_count, 2)
        self.assertEqual(count.call_count, 2)
        topology.assert_called_once()
        self.assertEqual(json.loads((self.state / "last-persistence-check.json").read_text())
                         ["new_provider_requests"], 0)

    def test_persistence_refuses_nonquiescent_profile_before_stop(self):
        (self.state / "last-explicit-exercise.json").write_text(json.dumps({
            "submission_ids": ["s1", "s2", "s3", "s4"],
            "no_store_submission_id": "s4", "after_submissions": 7}))
        (self.state / "last-live-audit.json").write_text(json.dumps({
            "kind": "DEV-06 read-only live correlation",
            "build": {"fingerprint": "f" * 64}, "matched_exercise_attempts": 4,
            "single_arrival_per_receiver_attempt": True,
            "topology_negative_added_arrivals": False, "receiver_arrivals_total": 7}))
        overview = {"build": {"fingerprint": "f" * 64},
                    "counts": {"submissions": 7, "completed": 6,
                               "known_failures": 0, "unknown_outcomes": 0}}
        with patch.object(profile, "secrets_on_disk", return_value=({}, "p" * 40)), \
                patch.object(profile, "wait_health", return_value=(object(), overview)), \
                patch.object(profile, "command") as command:
            with self.assertRaisesRegex(RuntimeError, "not quiescent"):
                profile.verify_persistence({"fingerprint": "f" * 64}, {})
        command.assert_not_called()
        self.assertFalse((self.state / "last-persistence-check.json").exists())

    def test_service_image_imports_copied_recipe(self):
        dockerfile = (ROOT / "deploy/local/Dockerfile.service").read_text()
        self.assertIn("COPY dev_slice/ /app/dev_slice/", dockerfile)
        self.assertIn("/app/dev_slice", dockerfile.split("PYTHONPATH=", 1)[1].splitlines()[0].split(":"))
        self.assertTrue((ROOT / "tests/development_slice/recipe.py").is_file())


if __name__ == "__main__":
    unittest.main()
