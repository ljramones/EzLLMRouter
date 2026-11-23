"""Offline OS custody and source-bound staging fail before Docker can execute."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from tools.gateway import os_inputs

ROOT = Path(__file__).resolve().parents[2]


class OSInputTests(unittest.TestCase):
    def test_runtime_removals_reject_protected_duplicate_or_option_like_packages(self):
        original = os_inputs.load_lock(ROOT)
        for names in (
            sorted(original["runtime_removals"] + ["libc6"]),
            sorted(original["runtime_removals"] + ["libstdc++6"]),
            sorted(original["runtime_removals"] + ["apt"]),
            sorted(original["runtime_removals"] + ["--allow-unauthenticated"]),
            sorted(original["runtime_removals"] + ["apt\nlibc6"]),
            list(reversed(original["runtime_removals"])),
        ):
            changed = deepcopy(original)
            changed["runtime_removals"] = names
            with self.subTest(names=names), self.assertRaises(ValueError):
                os_inputs.validate_lock(changed)

    def staged_build(self, root, store):
        directory = root / "build"
        record = os_inputs.stage_archives(root, store, directory)
        packet = root / "source.zip"
        with zipfile.ZipFile(packet, "w") as archive:
            archive.writestr("SOURCE-MANIFEST.json", json.dumps({"os_inputs": record}))
        return {"build_dir": str(directory), "source_packet": str(packet), "os_inputs": record}

    def fixture(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        lock = deepcopy(os_inputs.load_lock(ROOT))
        lock.pop("native_build", None)
        lock["format"] = "ezllmrouter-debian-inputs-v3"
        source = root / os_inputs.LOCK
        source.parent.mkdir(parents=True)
        installer = root / os_inputs.INSTALLER
        installer.write_bytes((ROOT / os_inputs.INSTALLER).read_bytes())
        store = root / "store"
        directory = store / os_inputs.STORE
        directory.mkdir(parents=True)
        lock["packages"] = []
        for name, roles in (("common", ["python", "node"]), ("python-only", ["python"])):
            payload = ("reviewed fixture archive " + name).encode()
            filename = name + "_1_arm64.deb"
            (directory / filename).write_bytes(payload)
            lock["packages"].append(
                {
                    "package": name,
                    "version": "1",
                    "source": name,
                    "source_version": "1",
                    "architecture": "arm64",
                    "roles": roles,
                    "origin_suite": "trixie",
                    "origin_version_id": "13",
                    "filename": filename,
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "url": "https://deb.debian.org/debian/pool/main/f/fixture/" + filename,
                }
            )
        source.write_text(json.dumps(lock))
        return root, store, lock

    def test_advisory_origins_require_reviewed_suite_version_and_authentication(self):
        original = os_inputs.load_lock(ROOT)
        for change in ("suite", "version", "signature", "url"):
            lock = deepcopy(original)
            with self.subTest(change=change):
                if change == "suite":
                    lock["packages"][0]["origin_suite"] = "unreviewed"
                elif change == "version":
                    lock["packages"][0]["origin_version_id"] = "14"
                elif change == "signature":
                    lock["additional_origins"]["forky"]["inrelease_sha256"] = ""
                else:
                    lock["additional_origins"]["forky"]["url"] = "https://example.invalid/index"
                with self.assertRaises(ValueError):
                    os_inputs.validate_lock(lock)

    def test_installed_origins_bind_exact_binary_and_source_versions(self):
        from tools.release_inventory import debian_packages

        lock = os_inputs.load_lock(ROOT)
        selected = next(row for row in lock["packages"] if row["package"] == "libsqlite3-0")
        raw = (
            "\t".join(
                (
                    selected["package"],
                    selected["version"],
                    selected["source"],
                    selected["source_version"],
                    "installed",
                )
            )
            + "\n"
        )
        old = "libsqlite3-0\t3.46.1-7+deb13u2\tsqlite3\t3.46.1-7+deb13u2\tinstalled\n"
        rows = debian_packages(raw + old, "Debian:13", lock)
        self.assertEqual([row["ecosystem"] for row in rows], ["Debian:14", "Debian:13"])
        self.assertEqual(rows[0]["origin_suite"], "forky")
        with self.assertRaises(ValueError):
            debian_packages(raw.replace("\tsqlite3\t", "\tforeign-source\t"), "Debian:13", lock)

    def test_historical_v2_staging_has_no_origin_override(self):
        _, _, lock = self.fixture()
        lock["format"] = "ezllmrouter-debian-inputs-v2"
        lock.pop("native_build", None)
        lock.pop("additional_origins")
        for row in lock["packages"]:
            row.pop("origin_suite")
            row.pop("origin_version_id")
        os_inputs.validate_lock(lock)
        self.assertEqual(os_inputs.advisory_ecosystem(lock, lock["packages"][0]), "Debian:13")
        lock["packages"][0]["origin_version_id"] = "14"
        with self.assertRaises(ValueError):
            os_inputs.validate_lock(lock)

    def test_declared_archive_proof_binds_the_audited_inventory_lock(self):
        from tools.security_resolutions import capture_archives

        root, store, lock = self.fixture()
        digest = os_inputs.digest(root / os_inputs.LOCK)
        inventory = {"source_sha256": {os_inputs.LOCK: digest}, "sha256": "a" * 64}
        proof = capture_archives(root, store, inventory)
        self.assertEqual(proof["lock_sha256"], digest)
        self.assertEqual(proof["inventory_sha256"], inventory["sha256"])
        self.assertEqual(len(proof["packages"]), 2)
        inventory["source_sha256"][os_inputs.LOCK] = "b" * 64
        with self.assertRaisesRegex(ValueError, "differs from audited inventory"):
            capture_archives(root, store, inventory)

    def test_unrecorded_staged_archives_and_native_files_fail_before_build(self):
        for name in ("unreviewed.deb", "NODE_RUNTIME"):
            with self.subTest(name=name):
                root, store, lock = self.fixture()
                manifest = self.staged_build(root, store)
                (Path(manifest["build_dir"]) / "js/os-inputs" / name).write_text("unsealed")
                with self.assertRaisesRegex(ValueError, "unexpected staged OS input"):
                    os_inputs.verify_staging(manifest)

    def test_archive_set_bytes_and_links_are_checked_before_staging(self):
        for change in ("missing", "extra", "changed", "linked"):
            with self.subTest(change=change):
                root, store, lock = self.fixture()
                os_inputs.verify_archives(root, store)
                directory = store / os_inputs.STORE
                archive = directory / lock["packages"][0]["filename"]
                if change == "missing":
                    archive.unlink()
                elif change == "extra":
                    (directory / "unreviewed.deb").write_bytes(b"unreviewed")
                elif change == "changed":
                    archive.write_bytes(b"changed")
                else:
                    target = directory / "original"
                    archive.rename(target)
                    archive.symlink_to(target)
                with self.assertRaises(ValueError):
                    os_inputs.stage_archives(root, store, root / "build")
                self.assertFalse((root / "build").exists())

    def test_wrong_target_mutable_base_and_changed_installer_fail(self):
        for change in ("suite", "base", "role", "filename", "installer"):
            with self.subTest(change=change):
                root, store, lock = self.fixture()
                if change == "suite":
                    lock["suite"] = "bookworm"
                elif change == "base":
                    lock["bases"]["python"]["reference"] = "python:latest"
                elif change == "role":
                    lock["packages"][0]["roles"] = ["unreviewed"]
                elif change == "filename":
                    lock["packages"][0]["filename"] = "../outside.deb"
                else:
                    (root / os_inputs.INSTALLER).write_text("exit 0\n")
                (root / os_inputs.LOCK).write_text(json.dumps(lock))
                with self.assertRaises(ValueError):
                    os_inputs.verify_archives(root, store)

    def test_role_closures_and_rehashed_tampering_remain_bound_to_review(self):
        root, store, lock = self.fixture()
        build = root / "build"
        manifest = self.staged_build(root, store)
        record = manifest["os_inputs"]
        self.assertEqual(os_inputs.verify_staging(manifest), lock)
        self.assertTrue((build / "worker/os-inputs/python-only_1_arm64.deb").exists())
        self.assertFalse((build / "js/os-inputs/python-only_1_arm64.deb").exists())
        for filename in ("common_1_arm64.deb", "install.sh", "SHA256SUMS", "REMOVE-PACKAGES"):
            with self.subTest(filename=filename):
                changed = deepcopy(record)
                path = build / "worker/os-inputs" / filename
                original = path.read_bytes()
                path.write_bytes(b"rehashing must not approve changed input")
                row = next(
                    item
                    for item in changed["files"]
                    if item["path"] == path.relative_to(build).as_posix()
                )
                row.update(bytes=path.stat().st_size, sha256=os_inputs.digest(path))
                with self.assertRaises(ValueError):
                    os_inputs.verify_staging(dict(manifest, os_inputs=changed))
                path.write_bytes(original)
        record["lock"]["bases"]["python"]["reference"] = (
            "docker.io/library/python@sha256:" + "b" * 64
        )
        with self.assertRaisesRegex(ValueError, "source packet"):
            os_inputs.verify_staging(manifest)

    def test_profile_and_qualification_reject_tampered_inputs_before_docker(self):
        from deploy.local import local_profile
        from tools import deployment_qualification

        root, store, _ = self.fixture()
        directory = root / "build"
        build = self.staged_build(root, store)
        (directory / "worker/os-inputs/common_1_arm64.deb").write_bytes(b"changed")
        for caller, args in (
            (local_profile.build_images, (build, {})),
            (local_profile.build_dev07_actors, (build, {})),
            (deployment_qualification.build_images, (build, {}, "synthetic")),
        ):
            with self.subTest(caller=caller), patch.object(local_profile, "command") as command:
                with self.assertRaisesRegex(ValueError, "identity"):
                    caller(*args)
                command.assert_not_called()

    def test_legacy_cached_images_can_restart_but_missing_images_require_new_inputs(self):
        from deploy.local import local_profile

        env = {
            "EZLLMROUTER_" + name + "_IMAGE": "synthetic-old:" + name.lower()
            for name in (
                "PYTHON",
                "RECEIVER",
                "WORKER",
                "SERVICE",
                "DEV07_PYACTOR",
                "DEV07_JSACTOR",
            )
        }
        for builder, count in (
            (local_profile.build_images, 4),
            (local_profile.build_dev07_actors, 2),
        ):
            with self.subTest(builder=builder):
                with patch.object(local_profile, "command", return_value=("", 0)) as command:
                    builder({"build_dir": "unused-old-staging"}, env)
                self.assertEqual(len(command.call_args_list), count)
                self.assertTrue(all("inspect" in call.args[1] for call in command.call_args_list))
                with patch.object(local_profile, "command", return_value=("", 1)) as command:
                    with self.assertRaisesRegex(ValueError, "prepare reviewed OS inputs"):
                        builder({"build_dir": "unused-old-staging"}, env)
                self.assertEqual(len(command.call_args_list), 1)
