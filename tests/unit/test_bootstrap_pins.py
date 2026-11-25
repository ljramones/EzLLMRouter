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

    def test_previous_unhashed_bootstrap_and_mutable_action_are_rejected(self):
        root = self.copy()
        for name in ("check.yml", "testing-scheduled.yml"):
            source = (ROOT / ".github/workflows" / name).read_text()
            source = source.replace(
                "python3 -m pip install --force-reinstall --only-binary=:all: --no-deps --require-hashes -r .github/requirements-bootstrap.lock",
                "python3 -m pip install uv==0.13.9",
            ).replace(
                "actions/checkout@08c6903cd8c0fde910a37f88322edcfb5dd907a8",
                "actions/checkout@v5",
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

    def test_every_platform_wheel_requires_matching_hash_and_clean_review(self):
        import json

        for change in (
            {"startup_hooks": ["unexpected.pth"]},
            {"yanked": True},
            {"filename": "uv-0.0.0-py3-none-win_amd64.whl"},
            {"sha256": "0" * 64},
        ):
            for index in range(2):
                root = self.copy()
                path = root / ".github/bootstrap-inputs.json"
                data = json.loads(path.read_text())
                data["uv"]["platform_artifacts"][index].update(change)
                path.write_text(json.dumps(data))
                self.assertTrue(errors(root), (index, change))

    def test_floating_versions_and_toolchain_install_bypasses_fail(self):
        import json

        for tool, version in (("java", "17"), ("dotnet", "10.0.x")):
            root = self.copy()
            path = root / ".github/toolchain-inputs.json"
            data = json.loads(path.read_text())
            data[tool]["version"] = version
            path.write_text(json.dumps(data))
            self.assertTrue(errors(root), tool)
        for old, new in (
            ("-I -S tools/ci_toolchains.py java", "-I -S unverified-java.py"),
            ("-I -S tools/ci_toolchains.py dotnet", "-I -S unverified-dotnet.py"),
            ("TSC_BINARY:", "IGNORED_COMPILER:"),
            ("npm --prefix tests/playwright ci", "npm install --global typescript@5.9.3"),
        ):
            root = self.copy()
            path = root / ".github/workflows/check.yml"
            path.write_text(path.read_text().replace(old, new))
            self.assertTrue(errors(root), (old, new))
