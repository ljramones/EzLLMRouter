"""A reused catalogue run ID fails before any upgrade stage or evidence write."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "deploy/local"))
import catalogue_run


class RunIdTests(unittest.TestCase):
    def test_collision_reports_result_location_without_overwriting(self):
        with (
            tempfile.TemporaryDirectory() as scratch,
            patch.object(catalogue_run, "RUNS", Path(scratch)),
        ):
            namespace = catalogue_run.claim_run_id("catalogue-20261021-02")
            result = namespace / "result.json"
            result.write_text('{"status":"PASS"}\n')
            with self.assertRaises(SystemExit) as raised:
                catalogue_run.claim_run_id("catalogue-20261021-02")
            self.assertIn("run ID already exists", str(raised.exception))
            self.assertIn(str(result), str(raised.exception))
            self.assertEqual(result.read_text(), '{"status":"PASS"}\n')
            self.assertFalse((namespace / "failure.json").exists())

    def test_unexpected_run_id_cannot_escape_run_root(self):
        with (
            tempfile.TemporaryDirectory() as scratch,
            patch.object(catalogue_run, "RUNS", Path(scratch)),
        ):
            with self.assertRaises(SystemExit):
                catalogue_run.claim_run_id("catalogue-20261021-../../elsewhere")
            self.assertEqual(list(Path(scratch).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
