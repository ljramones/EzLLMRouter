"""Untrusted archives cannot become executable CI inputs before verification."""

from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import ci_toolchains as ci


class CiToolchainTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def tar(self, name="jdk/bin/java", link=None):
        archive = self.root / "java.tar.gz"
        with tarfile.open(archive, "w:gz") as output:
            member = tarfile.TarInfo(name)
            if link is None:
                member.size = 4
                member.mode = 0o755
                output.addfile(member, io.BytesIO(b"test"))
            else:
                member.type = tarfile.SYMTYPE
                member.linkname = link
                output.addfile(member)
        return archive

    def test_hash_mismatch_prevents_extraction_and_environment_export(self):
        archive = self.tar()
        policy = {
            "java": {
                "artifacts": {
                    "Linux-X64": {
                        "filename": archive.name,
                        "sha256": "0" * 64,
                        "home": "jdk",
                    }
                }
            }
        }
        with patch.object(ci, "extract_archive") as extract:
            with self.assertRaisesRegex(ValueError, "hash differs"):
                ci.install("java", policy, "Linux-X64", self.root, archive)
            extract.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [archive])

    def test_verified_archive_installs_without_running_downloaded_code(self):
        archive = self.tar()
        policy = {
            "java": {
                "artifacts": {
                    "Linux-X64": {
                        "filename": archive.name,
                        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                        "home": "jdk",
                    }
                }
            }
        }
        home = ci.install("java", policy, "Linux-X64", self.root, archive)
        self.assertEqual((home / "bin/java").read_bytes(), b"test")
        environment, paths = self.root / "environment", self.root / "paths"
        with patch.dict(os.environ, {"GITHUB_ENV": str(environment), "GITHUB_PATH": str(paths)}):
            ci.export_environment("java", home)
        self.assertEqual(environment.read_text(), "JAVA_HOME=" + str(home) + "\n")
        self.assertEqual(paths.read_text(), str(home / "bin") + "\n")

    def test_tar_paths_and_links_cannot_escape_installation(self):
        for name, link in (
            ("../escaped", None),
            ("/absolute", None),
            ("jdk/link", "../../escaped"),
            ("jdk/link", "/etc/passwd"),
        ):
            with self.subTest(name=name, link=link):
                archive = self.tar(name, link)
                with tempfile.TemporaryDirectory(dir=self.root) as target:
                    with self.assertRaises((ValueError, tarfile.FilterError)):
                        ci.extract_archive(archive, Path(target) / "payload")
        self.assertFalse((self.root / "escaped").exists())

    def test_zip_paths_and_links_cannot_escape_installation(self):
        for name, mode in (
            ("../escaped", 0),
            ("C:/escaped", 0),
            ("jdk\\escaped", 0),
            ("jdk/link", 0o120777),
        ):
            with self.subTest(name=name):
                archive = self.root / "java.zip"
                with zipfile.ZipFile(archive, "w") as output:
                    member = zipfile.ZipInfo(name)
                    member.external_attr = mode << 16
                    output.writestr(member, b"../../escaped")
                with tempfile.TemporaryDirectory(dir=self.root) as target:
                    with self.assertRaises(ValueError):
                        ci.extract_archive(archive, Path(target) / "payload")

    def test_publisher_redirects_reject_downgrade_and_foreign_hosts(self):
        redirect = ci.PublisherRedirect()
        for url in (
            "http://github.com/archive",
            "https://attacker.example/archive",
            "https://github.com@attacker.example/archive",
            "file:///tmp/archive",
        ):
            with self.assertRaises(ValueError):
                redirect.redirect_request(None, None, 302, "Found", {}, url)

    def test_unreviewed_platform_digest_home_and_publisher_fail(self):
        original = ci.load_policy()
        directory = self.root / ".github"
        directory.mkdir()
        for field, value in (
            ("sha256", "xyz"),
            ("url", "https://attacker.example/tool.tar.gz"),
            ("home", "../outside"),
            ("filename", "../tool.tar.gz"),
        ):
            data = deepcopy(original)
            data["java"]["artifacts"]["Linux-X64"][field] = value
            (directory / "toolchain-inputs.json").write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                ci.load_policy(self.root)
        data = deepcopy(original)
        del data["dotnet"]["artifacts"]["Windows-X64"]
        (directory / "toolchain-inputs.json").write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            ci.load_policy(self.root)

    def test_version_label_cannot_relabel_an_older_archive(self):
        policy = ci.load_policy()
        policy["java"]["version"] = "17.0.22+1"
        directory = self.root / ".github"
        directory.mkdir()
        (directory / "toolchain-inputs.json").write_text(json.dumps(policy))
        with self.assertRaisesRegex(ValueError, "archive identity"):
            ci.load_policy(self.root)

    def test_sha512_is_enforced_for_dotnet(self):
        archive = self.tar()
        digest = hashlib.sha512(archive.read_bytes()).hexdigest()
        ci.verify_archive(archive, {"sha512": digest})
        with self.assertRaises(ValueError):
            ci.verify_archive(archive, {"sha512": "0" * 128})

    def test_all_reviewed_archives_reach_the_dependency_inventory(self):
        from tools.security_dependencies import inventory

        rows = [row for row in inventory()["artifacts"] if row["source"] == ci.POLICY]
        self.assertEqual(len(rows), 6)
        self.assertEqual({row["platform"] for row in rows}, ci.PLATFORMS)
        self.assertEqual({row["digest"].split(":")[0] for row in rows}, {"sha256", "sha512"})

    def test_extra_digest_cannot_bypass_the_required_sha512(self):
        archive = self.tar()
        with self.assertRaisesRegex(ValueError, "unambiguous"):
            ci.verify_archive(
                archive,
                {
                    "sha512": "0" * 128,
                    "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                },
            )
        policy = ci.load_policy()
        policy["dotnet"]["artifacts"]["Linux-X64"]["sha256"] = "0" * 64
        directory = self.root / ".github"
        directory.mkdir()
        (directory / "toolchain-inputs.json").write_text(json.dumps(policy))
        with self.assertRaises(ValueError):
            ci.load_policy(self.root)

    def test_environment_newlines_are_rejected_before_writing(self):
        with patch.dict(
            os.environ,
            {"GITHUB_ENV": str(self.root / "environment"), "GITHUB_PATH": str(self.root / "paths")},
        ):
            with self.assertRaises(ValueError):
                ci.export_environment("dotnet", Path("/tmp/injected\nVARIABLE=value"))
        self.assertFalse((self.root / "environment").exists())
