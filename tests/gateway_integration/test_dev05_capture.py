"""Controlled pre-Docker failure exports for absent and partial credentials."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capture_runtime import CaptureLimit, capture


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / "run-20261020-99"
        self.run.mkdir()
        (self.run / "work.exit").write_text("1\n")
        (self.run / "choice-b-component.exit").write_text("1\n")
        (self.run / "choice-b-component.stderr").write_text("original component failure\n")

    def generated(self, expected, present):
        (self.run / "generate-credentials.argv").write_text("synthetic generator\n")
        (self.run / "credential-generation-state.json").write_text(
            json.dumps({"expected": expected})
        )
        for name, value in present.items():
            (self.run / name).write_text(value)

    def assert_safe(self, secrets):
        packet = Path(capture(self.run, self.root, "DEV-05")["runtime_packet"])
        with zipfile.ZipFile(packet) as archive:
            names = archive.namelist()
            self.assertNotIn("token", names)
            self.assertNotIn("provider-key", names)
            self.assertEqual(archive.read("work.exit"), b"1\n")
            self.assertEqual(archive.read("choice-b-component.exit"), b"1\n")
            self.assertIn(b"original component failure", archive.read("choice-b-component.stderr"))
            for name in names:
                raw = archive.read(name)
                for secret in secrets:
                    self.assertNotIn(secret.encode(), raw, name)
        self.assertEqual((self.run / "work.exit").read_text(), "1\n")

    def test_absent_credentials_preserve_early_failure(self):
        self.assert_safe(())

    def test_encryption_keyrings_and_sealed_credentials_are_not_exported(self):
        private = self.run / "private"
        private.mkdir()
        for name in (
            "integration.keys.json",
            "provider.keys.json",
            "local-connectors.keys.json",
            "provider.keys.json.lock",
            "credential.1.sealed",
        ):
            (private / name).write_text("synthetic-key-material-canary")
        self.assert_safe(("synthetic-key-material-canary",))
        with zipfile.ZipFile(self.root / "DEV-05-RUNTIME-run-20261020-99.zip") as archive:
            self.assertFalse(any(name.startswith("private/") for name in archive.namelist()))

    def test_partial_credentials_redact_available_secret(self):
        token = "synthetic-token-value-123456"
        self.generated(["token"], {"token": token})
        (self.run / "choice-b-component.stderr").write_text(
            "original component failure " + token + "\n"
        )
        self.assert_safe((token,))
        packet = self.root / "DEV-05-RUNTIME-run-20261020-99.zip"
        with zipfile.ZipFile(packet) as archive:
            self.assertIn(
                b"[REDACTED-SYNTHETIC-CREDENTIAL]", archive.read("choice-b-component.stderr")
            )

    def test_full_credentials_redact_both(self):
        token, key = "synthetic-token-value-123456", "sk-synthetic-key-value-123456"
        self.generated(["token", "provider-key"], {"token": token, "provider-key": key})
        (self.run / "generate-credentials.exit").write_text("0\n")
        (self.run / "choice-b-component.stderr").write_text(
            "original component failure " + token + " " + key + "\n"
        )
        self.assert_safe((token, key))

    def test_expected_lost_credential_withholds_packet(self):
        self.generated(["token", "provider-key"], {"token": "synthetic-token-value-123456"})
        with self.assertRaisesRegex(CaptureLimit, "expected credential is missing"):
            capture(self.run, self.root, "DEV-05")
        self.assertFalse((self.root / "DEV-05-RUNTIME-run-20261020-99.zip").exists())

    def test_attempt_without_lifecycle_withholds_packet(self):
        (self.run / "generate-credentials.argv").write_text("synthetic generator\n")
        with self.assertRaisesRegex(CaptureLimit, "lifecycle record"):
            capture(self.run, self.root, "DEV-05")
        self.assertFalse((self.root / "DEV-05-RUNTIME-run-20261020-99.zip").exists())

    def test_finalizer_preserves_primary_exit_when_capture_fails(self):
        steps = Path(__file__).with_name("dev05_steps.sh")
        script = (
            'source "$1"; run_dir=$2; started=0; built_images=(); '
            'capture() { printf "synthetic capture failure\\n" >&2; return 2; }; '
            "finish_dev05 7"
        )
        result = subprocess.run(
            ["bash", "-c", script, "bash", str(steps), str(self.run)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 7)
        self.assertEqual((self.run / "run.exit").read_text(), "7\n")
        self.assertEqual((self.run / "capture.exit").read_text(), "2\n")
        self.assertIn("synthetic capture failure", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
