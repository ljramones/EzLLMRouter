"""The service-only update cannot reuse its one-use evidence namespace."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "deploy/local"))
import usage_update


class UpdateNamespaceTests(unittest.TestCase):
    def test_existing_run_is_reported_without_overwrite(self):
        with tempfile.TemporaryDirectory() as scratch, patch.object(usage_update, "RUNS", Path(scratch)):
            run = usage_update.claim_run_id("usage-20261021-01")
            result = run / "result.json"
            result.write_text('{"status":"PASS"}\n')
            with self.assertRaises(SystemExit) as raised:
                usage_update.claim_run_id("usage-20261021-01")
            self.assertIn("run ID already exists", str(raised.exception))
            self.assertIn(str(result), str(raised.exception))
            self.assertEqual(result.read_text(), '{"status":"PASS"}\n')
            self.assertFalse((run / "failure.json").exists())


if __name__ == "__main__":
    unittest.main()
