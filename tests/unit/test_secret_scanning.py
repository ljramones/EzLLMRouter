"""Secret probes use synthetic values and never print matching contents."""

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.security_secrets import scan, policy_errors


class SecretScanningTests(unittest.TestCase):
    def repository(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        return root

    def commit(self, root):
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "-c",
                "user.name=Synthetic",
                "-c",
                "user.email=synthetic@example.invalid",
                "commit",
                "-qm",
                "synthetic fixture",
            ],
            check=True,
        )

    def test_deleted_history_secrets_and_untracked_worktree_secrets_are_both_detected(self):
        root = self.repository()
        token = "sk-" + "syntheticCanaryForScanner0123456789"
        path = root / "config.txt"
        path.write_text(token)
        self.commit(root)
        path.unlink()
        self.commit(root)
        (root / "new.txt").write_text("AKIA" + "SYNTHETICEXAMPLE")
        report = scan(root)
        self.assertTrue(any(row["source"].startswith("history:") for row in report["findings"]))
        self.assertTrue(any(row["source"] == "tree:new.txt" for row in report["findings"]))
        self.assertNotIn(token, json.dumps(report))
        self.assertTrue(policy_errors(report, {"exceptions": []}))

    def test_synthetic_exception_is_bound_to_exact_blob_and_finding_set(self):
        root = self.repository()
        path = root / "fixture.txt"
        path.write_text("-----BEGIN PRIVATE KEY-----\nsynthetic\n")
        self.commit(root)
        report = scan(root)
        policy = {
            "exceptions": [
                {
                    "blob_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "reason": "Synthetic nonfunctional private-key fixture.",
                    "findings": [
                        row["identity"]
                        for row in report["findings"]
                        if row["source"] == "tree:fixture.txt"
                    ],
                }
            ]
        }
        self.assertEqual(policy_errors(report, policy), [])
        path.write_text(path.read_text() + "\n" + "sk-" + "secondSyntheticCanary0123456789")
        self.assertTrue(policy_errors(scan(root), policy))

    def test_high_entropy_tokens_are_detected_without_echoing_the_value(self):
        root = self.repository()
        value = "aQ7mP9sT2vX4zB6dF8hJ0kL3nR5uW1yC+eG/iOoU6pV8rS"
        (root / "random.txt").write_text(value)
        self.commit(root)
        report = scan(root)
        self.assertTrue(any(row["identity"]["rule"] == "entropy" for row in report["findings"]))
        self.assertNotIn(value, json.dumps(report))

    def test_symlinks_cannot_read_private_files_outside_the_checkout(self):
        root = self.repository()
        (root / "normal").write_text("ordinary")
        self.commit(root)
        (root / "linked").symlink_to("/private/synthetic-nonexistent")
        with self.assertRaises(ValueError):
            scan(root)

    def test_shallow_history_cannot_report_a_complete_scan(self):
        root = self.repository()
        (root / "normal").write_text("ordinary")
        self.commit(root)
        head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"])
        (root / ".git/shallow").write_bytes(head)
        with self.assertRaisesRegex(ValueError, "nonshallow"):
            scan(root)

    def test_history_read_commands_are_narrowly_allowed_by_the_offline_runner(self):
        from tools.test_network import process_command

        for arguments in (
            ["rev-list", "--objects", "--all", "--no-object-names"],
            ["cat-file", "--batch-check"],
            ["cat-file", "--batch"],
        ):
            command = ["git", "-C", "/synthetic", "-c", "protocol.allow=never", *arguments]
            self.assertEqual(process_command(command), command)
        for arguments in (["fetch", "https://example.invalid"], ["cat-file", "--filters"]):
            with self.assertRaises(AssertionError):
                process_command(["git", *arguments])

    def test_windows_executable_names_keep_the_same_child_network_policy(self):
        from tools.test_network import process_command

        self.assertEqual(process_command(["node.exe", "fixture.cjs"]), ["node.exe", "fixture.cjs"])
        with self.assertRaisesRegex(AssertionError, "unapproved"):
            process_command(["npm.cmd", "install", "unreviewed"])
        command = ["npm.cmd", "pack", "--offline", "--ignore-scripts"]
        self.assertEqual(process_command(command), command)
        with self.assertRaisesRegex(AssertionError, "unapproved"):
            process_command(["curl.exe", "https://example.invalid"])

    def test_hex_credentials_are_detected_while_public_digests_are_distinguished(self):
        from tools.security_secrets import detect

        value = hashlib.sha256(b"synthetic entropy fixture").hexdigest()
        credential = ('api_key = "' + value + '"').encode()
        public_digest = ('sha256 = "' + value + '"').encode()
        self.assertTrue(detect(credential))
        self.assertEqual(detect(public_digest), [])
