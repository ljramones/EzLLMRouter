"""One-use DEV-08 owner runner checks without invoking Docker."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "deploy/local"))
import dev08_target


class TargetRunnerTests(unittest.TestCase):
    def test_existing_run_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "dev08-20261021-01"
            run.mkdir()
            marker = run / "result.json"
            marker.write_text("historical\n")
            with patch.object(dev08_target, "RUNS", Path(tmp)), patch.object(sys, "argv",
                ["dev08_target.py", "dev08-20261021-01"]), patch.dict("os.environ",
                {"DURANKI_ARTIFACT_ROOT": tmp}), patch.object(dev08_target, "command") as command:
                with self.assertRaisesRegex(SystemExit, "run ID already exists"):
                    dev08_target.main()
                command.assert_not_called()
            self.assertEqual(marker.read_text(), "historical\n")

    def test_dirty_source_fails_before_docker(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(dev08_target, "RUNS", Path(tmp)), patch.object(sys, "argv",
                ["dev08_target.py", "dev08-20261021-02"]), patch.dict("os.environ",
                {"DURANKI_ARTIFACT_ROOT": tmp}), patch.object(dev08_target.subprocess,
                "check_output", side_effect=["a" * 40, " M web/app.js"]), patch.object(
                dev08_target, "command") as command:
                with self.assertRaisesRegex(SystemExit, "source checkout is dirty"):
                    dev08_target.main()
                command.assert_not_called()
            self.assertTrue((Path(tmp) / "dev08-20261021-02/failure.json").is_file())


if __name__ == "__main__":
    unittest.main()
