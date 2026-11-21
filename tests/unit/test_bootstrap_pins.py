"""Bootstrap pin regressions inspect source, without installing any package."""

from pathlib import Path
import shutil
import tempfile
import unittest

from tools.security_bootstrap import errors

ROOT = Path(__file__).resolve().parents[2]


class BootstrapPinTests(unittest.TestCase):
    def copy(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        shutil.copytree(ROOT / ".github", root / ".github")
        return root

    def test_previous_unhashed_bootstrap_and_mutable_dotnet_action_are_rejected(self):
        root = self.copy()
        for name in ("check.yml", "testing-scheduled.yml"):
            source = (ROOT / ".github/workflows" / name).read_text()
            source = source.replace(
                "python3 -m pip install --force-reinstall --only-binary=:all: --no-deps --require-hashes -r .github/requirements-bootstrap.lock",
                "python3 -m pip install uv==0.13.9",
            ).replace(
                "actions/setup-dotnet@26b0ec14cb23fa6904739307f278c14f94c95bf1",
                "actions/setup-dotnet@v5",
            )
            (root / ".github/workflows" / name).write_text(source)
        found = errors(root)
        self.assertTrue(any("unhashed" in row for row in found))
        self.assertTrue(any("mutable action" in row for row in found))

    def test_current_pins_pass_and_wheel_hash_change_requires_review(self):
        root = self.copy()
        self.assertEqual(errors(root), [])
        path = root / ".github/requirements-bootstrap.lock"
        path.write_text(path.read_text().replace("--hash=sha256:", "--hash=sha256:0", 1))
        self.assertTrue(errors(root))
        root = self.copy()
        path = root / ".github/workflows/check.yml"
        path.write_text(path.read_text().replace("--force-reinstall ", "", 1))
        self.assertTrue(errors(root), "an existing installation must not bypass wheel verification")
