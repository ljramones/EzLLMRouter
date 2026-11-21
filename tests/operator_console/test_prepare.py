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

    def test_every_docker_test_command_resolves_against_actual_staging_helpers(self):
        from tools.container_tests import resolve, staged_sources

        sources = staged_sources()
        for context in ("service", "worker"):
            dockerfile = (ROOT / f"deploy/local/Dockerfile.{context}").read_text()
            self.assertEqual(resolve(dockerfile, context, sources), [])
        source = (ROOT / "deploy/local/Dockerfile.service").read_text()
        stale = source.replace(
            "tests.operator_console.test_reporting", "tests.operator_console.test_retired_reporting"
        )
        self.assertIn(
            "unstaged Docker test module: tests.operator_console.test_retired_reporting",
            resolve(stale, "service", sources),
        )
        missing = {
            key: value
            for key, value in sources.items()
            if key != "service/tests/operator_console/test_reporting.py"
        }
        self.assertIn(
            "unstaged Docker test module: tests.operator_console.test_reporting",
            resolve(source, "service", missing),
        )

    def test_docker_bind_mounts_are_instruction_scoped_and_discovery_is_not_empty(self):
        from tools.container_tests import resolve, test_commands

        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary) / "test_fixture.py"
            script.write_text("import unittest\n")
            staged = {"worker/validation/test_fixture.py": script}
            mounted = "RUN --network=none --mount=type=bind,source=validation,target=/tmp/validation,readonly python -B /tmp/validation/test_fixture.py"
            self.assertEqual(resolve(mounted, "worker", staged), [])
            self.assertIn(
                "unstaged Docker test script: /tmp/validation/test_fixture.py",
                resolve(
                    mounted + "\nRUN python -B /tmp/validation/test_fixture.py", "worker", staged
                ),
            )
            self.assertTrue(
                resolve(
                    "RUN python -m unittest discover -s /app/gateway -p test_missing.py",
                    "worker",
                    staged,
                )
            )
            with self.assertRaises(ValueError):
                test_commands("RUN python -m unittest")

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
