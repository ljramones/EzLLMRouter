"""Independent arrival correlation for one recorded, completed synthetic exercise."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]

from deploy.local import local_profile as profile


class Client:
    def call(self, method, path):
        if not (method == "GET"):
            raise AssertionError("fixture invariant failed")
        number = int(path.rsplit(".", 1)[1])
        return {
            "submission_id": f"submission.{number}",
            "attempt_id": f"attempt.{number}",
            "submission_state": "completed",
            "dispatch_state": "response_observed",
            "intent": {"present": True},
            "dispatch_receipt": {
                "present": True,
                "body_sha256": f"{number:064x}",
                "body_bytes": 100 + number,
            },
            "candidate_access": "not_retained" if number == 4 else "present",
            "content_store_allowed": number != 4,
        }


class LiveAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name)
        (self.state / "last-explicit-exercise.json").write_text(
            json.dumps(
                {
                    "kind": "DEV-06 explicit synthetic operator exercise",
                    "before_submissions": 3,
                    "after_submissions": 7,
                    "caller_lookups": 1,
                    "provider_requests_expected_delta": 4,
                    "submission_ids": [f"submission.{n}" for n in range(1, 5)],
                    "no_store_submission_id": "submission.4",
                }
            )
        )
        self.arrivals = [
            {"attempt_id": f"attempt.{n}", "body_sha256": f"{n:064x}", "body_bytes": 100 + n}
            for n in range(1, 8)
        ]
        self.patched = patch.object(profile, "STATE", self.state)
        self.patched.start()
        self.addCleanup(self.patched.stop)

    def audit(self, rows):
        with (
            patch.object(profile, "secrets_on_disk", return_value=({}, "p" * 40)),
            patch.object(
                profile,
                "wait_health",
                return_value=(
                    Client(),
                    {
                        "build": {"fingerprint": "f" * 64},
                        "service": {"state": "live"},
                        "worker": {"state": "live"},
                        "sender": {"state": "live"},
                    },
                ),
            ),
            patch.object(profile, "topology", return_value=len(rows)),
            patch.object(profile, "command", return_value=(json.dumps(rows), 0)),
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                profile.audit_live({"fingerprint": "f" * 64}, {})

    def test_four_attempts_match_once_with_no_store_metadata(self):
        self.audit(self.arrivals)
        result = json.loads((self.state / "last-live-audit.json").read_text())
        self.assertEqual(result["receiver_arrivals_total"], 7)
        self.assertEqual(result["matched_exercise_attempts"], 4)
        self.assertEqual(result["no_store_candidate_access"], "not_retained")

    def test_duplicate_receiver_attempt_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "duplicate attempt"):
            self.audit(self.arrivals + [self.arrivals[0]])
        self.assertFalse((self.state / "last-live-audit.json").exists())

    def test_hash_mismatch_fails_closed(self):
        rows = [dict(row) for row in self.arrivals]
        rows[0]["body_sha256"] = "0" * 64
        with self.assertRaisesRegex(RuntimeError, "receipt mismatch"):
            self.audit(rows)
        self.assertFalse((self.state / "last-live-audit.json").exists())


if __name__ == "__main__":
    unittest.main()
