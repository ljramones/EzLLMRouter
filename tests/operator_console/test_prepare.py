"""Build identity follows source bytes and ignores local filesystem debris."""

import shutil
import re

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]

from deploy.local import prepare as prepare


@unittest.skipUnless(shutil.which("git"), "git is required for this fixture")
class PrepareTests(unittest.TestCase):
    def test_service_docker_validation_modules_are_staged_and_importable(self):
        dockerfile = (ROOT / "deploy/local/Dockerfile.service").read_text()
        modules = re.findall(r"\btests\.operator_console\.test_[a-z0-9_]+", dockerfile)
        self.assertTrue(modules)
        loader = unittest.TestLoader()
        for name in modules:
            with self.subTest(module=name):
                filename = name.rsplit(".", 1)[1] + ".py"
                self.assertIn(filename, prepare.SERVICE_VALIDATION_FILES)
                self.assertTrue((ROOT / "tests/operator_console" / filename).is_file())
                self.assertGreater(loader.loadTestsFromName(name).countTestCases(), 0)
        self.assertEqual(loader.errors, [])

    def test_fingerprint_uses_nonignored_git_source_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "deploy/local").mkdir(parents=True)
            (root / ".gitignore").write_text(".DS_Store\n")
            source = root / "deploy/local/product.py"
            source.write_text("version = 1\n")
            subprocess.run(("git", "init", "-q", str(root)), check=True, stdout=subprocess.DEVNULL)
            subprocess.run(
                ("git", "add", ".gitignore", "deploy/local/product.py"),
                cwd=root,
                check=True,
                stdout=subprocess.DEVNULL,
            )
            with (
                patch.object(prepare, "ROOT", root),
                patch.object(
                    prepare,
                    "git",
                    side_effect=lambda *args: "fixed-head" if args == ("rev-parse", "HEAD") else "",
                ),
            ):
                original = prepare.fingerprint()
                (root / "deploy/local/.DS_Store").write_bytes(b"local metadata")
                self.assertEqual(prepare.fingerprint(), original)
                source.write_text("version = 2\n")
                self.assertNotEqual(prepare.fingerprint(), original)


if __name__ == "__main__":
    unittest.main()
