"""DEV-08 profile upgrade must use the running identity after local staging."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deploy/local"))
import dev08_profile_upgrade as upgrade


class ProfileUpgradeTests(unittest.TestCase):
    def test_running_build_uses_observed_identity_not_current_pointer(self):
        with tempfile.TemporaryDirectory() as scratch:
            state = Path(scratch)
            fingerprint = "a" * 64
            staged = state / "staging" / ("source-" + fingerprint[:16])
            staged.mkdir(parents=True)
            build = staged / "build"
            build.mkdir()
            manifest = {"fingerprint": fingerprint, "commit": "old-running-commit",
                        "build_dir": str(build)}
            (staged / "LOCAL-BUILD-MANIFEST.json").write_text(json.dumps(manifest))
            observed = {"build": {"fingerprint": fingerprint,
                                  "commit": "old-running-commit"}}
            with patch.object(upgrade.profile, "STATE", state), patch.object(
                    upgrade, "wait_health", return_value=(None, observed)):
                self.assertEqual(upgrade.running_build("private-password"), manifest)
                observed["build"]["commit"] = "different-commit"
                with self.assertRaisesRegex(RuntimeError, "identity mismatch"):
                    upgrade.running_build("private-password")


if __name__ == "__main__":
    unittest.main()
