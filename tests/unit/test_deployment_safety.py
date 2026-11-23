"""Offline profile secret custody and complete operator asset staging."""

from html.parser import HTMLParser
from contextlib import redirect_stdout
import io
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import tempfile
import sys
from copy import deepcopy
import unittest
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]

# Avoid the standard-library module with the same name, used by profilers.
spec = importlib.util.spec_from_file_location(
    "local_profile", ROOT / "deploy/local/local_profile.py"
)
profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)
from deploy.local import initialize_credentials as initialize_credentials
from deploy.local import prepare as prepare


class FrozenInputTests(unittest.TestCase):
    def fixture(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        source = root / "source"
        wheels = source / "inputs/gateway-inputs/dev04/wheels"
        wheels.mkdir(parents=True)
        wheel = wheels / "example-1.0-py3-none-any.whl"
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr(
                "example/__init__.py", "raise AssertionError('review must not import')"
            )
            archive.writestr("example-1.0.dist-info/METADATA", "Name: example\nVersion: 1.0\n")
        row = {
            "name": "example",
            "version": "1.0",
            "filename": wheel.name,
            "bytes": wheel.stat().st_size,
            "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        }
        inputs = root / "deploy/local/inputs/gateway"
        inputs.mkdir(parents=True)
        (inputs / "WHEEL-INVENTORY.json").write_text(json.dumps({"wheels": [row]}))
        (inputs / "requirements.gateway.lock").write_text(
            "example==1.0 --hash=sha256:" + row["sha256"] + "\n"
        )
        (source / "ARTIFACT-CUSTODY.json").write_text("{}")
        replacements = root / "replacements"
        replacements.mkdir()
        return root, source, replacements

    def test_frozen_custody_binds_bytes_complete_inventory_and_selected_sources(self):
        from tools.gateway.frozen_inputs import assemble, verify_custody

        root, source, replacements = self.fixture()
        output = root / "candidate"
        assemble(root, source, replacements, output)
        verify_custody(root, output)
        marker = output / "ARTIFACT-CUSTODY.json"
        original = json.loads(marker.read_text())
        for change in ("missing_item", "wrong_hash", "wrong_source"):
            changed = deepcopy(original)
            if change == "missing_item":
                changed["items"] = []
            elif change == "wrong_hash":
                changed["items"][0]["sha256"] = "0" * 64
            else:
                changed["inventory_sha256"] = "0" * 64
            marker.write_text(json.dumps(changed))
            with self.subTest(change=change), self.assertRaises(ValueError):
                verify_custody(root, output)
        marker.write_text(json.dumps(original))
        wheel = output / "inputs" / original["items"][0]["path"]
        wheel.write_bytes(b"tampered wheel")
        with self.assertRaisesRegex(ValueError, "identity"):
            verify_custody(root, output)

    def test_unselected_replacements_cannot_enter_a_frozen_bundle(self):
        from tools.gateway.frozen_inputs import assemble

        root, source, replacements = self.fixture()
        (replacements / "unreviewed-1.0-py3-none-any.whl").write_bytes(b"not selected")
        with self.assertRaisesRegex(ValueError, "unselected"):
            assemble(root, source, replacements, root / "candidate")
        self.assertFalse((root / "candidate").exists())

    def test_hash_valid_bundle_still_rejects_incompatible_dependency_constraints(self):
        from tools.gateway.frozen_inputs import assemble

        root, source, replacements = self.fixture()
        path = next((source / "inputs/gateway-inputs/dev04/wheels").glob("*.whl"))
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(
                "example-1.0.dist-info/METADATA",
                "Name: example\nVersion: 1.0\nRequires-Dist: example<1.0\n",
            )
        inputs = root / "deploy/local/inputs/gateway"
        row = {
            "name": "example",
            "version": "1.0",
            "filename": path.name,
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        (inputs / "WHEEL-INVENTORY.json").write_text(json.dumps({"wheels": [row]}))
        (inputs / "requirements.gateway.lock").write_text(
            "example==1.0 --hash=sha256:" + row["sha256"] + "\n"
        )
        with self.assertRaisesRegex(ValueError, "dependency constraint"):
            assemble(root, source, replacements, root / "candidate")

    def test_client_fixture_cannot_reintroduce_the_retired_certifi_wheel(self):
        from tools.gateway import client_inputs

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in (
                "deploy/local/inputs/gateway/WHEEL-INVENTORY.json",
                "tests/client_parity/wheelhouse.lock.json",
            ):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((ROOT / name).read_bytes())
            path = root / "tests/client_parity/wheelhouse.lock.json"
            lock = json.loads(path.read_text())
            index = next(
                i for i, row in enumerate(lock["wheels"]) if row["filename"].startswith("certifi-")
            )
            lock["wheels"][index] = lock["derived_from"]["replaced_certifi"]
            path.write_text(json.dumps(lock))
            with (
                patch.object(client_inputs, "verify_custody"),
                patch.object(client_inputs, "build_clients") as build,
                patch.dict(os.environ, {"EZLLMROUTER_ARTIFACT_ROOT": str(root)}),
            ):
                with self.assertRaisesRegex(ValueError, "closure differs"):
                    client_inputs.stage_fixture_inputs(
                        root, root / "run", lambda *args: self.fail("unreviewed wheel copied")
                    )
            build.assert_not_called()

    def test_os_packages_and_advisories_keep_actual_target_attribution(self):
        from tools.release_inventory import attribution, debian_packages, package_key

        self.assertEqual(
            package_key({"ecosystem": "PyPI", "name": "Typing_Extensions", "version": "1"}),
            ("PyPI", "typing-extensions", "1"),
        )

        rows = debian_packages(
            "bin\t1\tsrc\t1\tinstalled\nold\t1\told\t1\tconfig-files\n", "Debian:12"
        )
        self.assertEqual([row["name"] for row in rows], ["src"])
        with self.assertRaisesRegex(ValueError, "incomplete"):
            debian_packages("bin\t1\tsrc\t1\tunpacked\n", "Debian:12")
        issues = [
            {
                "id": "fixture-only",
                "blocking": True,
                "package": {"name": "certifi", "version": "old", "sources": ["tests/fixture.lock"]},
            },
            {
                "id": "runtime",
                "blocking": True,
                "package": {
                    "name": "lib",
                    "version": "1",
                    "sources": ["image:worker:sha256:example"],
                },
            },
        ]
        report = attribution(issues, {"worker": {"image": {"id": "sha256:example"}}})
        self.assertEqual(report["images"]["worker"]["blocking"], 1)
        self.assertEqual(report["images"]["worker"]["findings"][0]["id"], "runtime")
        self.assertEqual(report["declared_only"]["findings"][0]["id"], "fixture-only")


class SecretCustodyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.state = self.directory / "state"
        replacement = patch.object(profile, "STATE", self.state)
        replacement.start()
        self.addCleanup(replacement.stop)

    def test_world_readable_legacy_files_are_secured_without_rotation(self):
        self.state.mkdir()
        expected = {"service_token": "t" * 40, "synthetic_provider_key": "sk-" + "k" * 40}
        (self.state / "credentials.json").write_text(json.dumps(expected, indent=2))
        (self.state / "operator-password").write_text("p" * 40)
        for path in self.state.iterdir():
            path.chmod(0o644)
        self.assertEqual(profile.secrets_on_disk(), (expected, "p" * 40))
        for path in self.state.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o700)

    def test_interrupted_initialization_resumes_without_losing_credentials(self):
        write = profile.write_private

        def fail_projection(path, content, **kwargs):
            if path.name == "credentials.json":
                raise OSError("simulated publication failure")
            return write(path, content, **kwargs)

        with patch.object(profile, "write_private", side_effect=fail_projection):
            with self.assertRaises(OSError):
                profile.secrets_on_disk()
        bundle = json.loads((self.state / "profile-secrets.json").read_bytes())
        self.assertEqual(
            profile.secrets_on_disk(), (bundle["credentials"], bundle["operator_password"])
        )

    def test_symlink_is_rejected_without_changing_its_target(self):
        self.state.mkdir()
        outside = self.directory / "unrelated"
        outside.write_text("unrelated")
        outside.chmod(0o644)
        (self.state / "credentials.json").symlink_to(outside)
        with self.assertRaisesRegex(RuntimeError, "symlinks"):
            profile.secrets_on_disk()
        self.assertEqual(outside.stat().st_mode & 0o777, 0o644)
        self.assertEqual(outside.read_text(), "unrelated")

    def test_container_copy_is_readable_only_by_service_uid(self):
        credentials, password = profile.secrets_on_disk()
        payload = json.dumps({"credentials": credentials, "operator_password": password}).encode()
        destination = self.directory / "volume"
        with (
            patch.object(initialize_credentials.os, "chown") as directory_owner,
            patch.object(initialize_credentials.os, "fchown") as file_owner,
        ):
            initialize_credentials.initialize(payload, destination)
            initialize_credentials.initialize(payload, destination)
        directory_owner.assert_called_with(destination, 0, 0)
        self.assertEqual(file_owner.call_count, 4)
        for call in file_owner.call_args_list:
            self.assertEqual(call.args[1:], (10001, 10001))
        self.assertEqual(
            sorted(path.name for path in destination.iterdir()),
            ["credentials.json", "operator-password"],
        )
        for path in destination.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o400)
        self.assertEqual(json.loads((destination / "credentials.json").read_text()), credentials)
        self.assertEqual((destination / "operator-password").read_text().strip(), password)
        compose = (ROOT / "deploy/local/compose.yaml").read_text()
        self.assertNotIn("./.state/credentials.json:", compose)
        self.assertIn("credential_data:/run/ezllmrouter:ro", compose)

    def test_file_mode_is_set_before_ownership_is_transferred(self):
        credentials, password = profile.secrets_on_disk()
        payload = json.dumps({"credentials": credentials, "operator_password": password}).encode()
        transferred = set()
        fchmod = os.fchmod

        def identity(descriptor):
            info = os.fstat(descriptor)
            return info.st_dev, info.st_ino

        def transfer(descriptor, uid, gid):
            self.assertEqual((uid, gid), (10001, 10001))
            transferred.add(identity(descriptor))

        def chmod(descriptor, mode):
            if identity(descriptor) in transferred:
                raise PermissionError("CHOWN alone cannot chmod a file owned by the service UID")
            fchmod(descriptor, mode)

        with (
            patch.object(initialize_credentials.os, "chown"),
            patch.object(initialize_credentials.os, "fchown", side_effect=transfer),
            patch.object(initialize_credentials.os, "fchmod", side_effect=chmod),
        ):
            initialize_credentials.initialize(payload, self.directory / "volume")
        self.assertEqual(len(transferred), 2)

    def test_invalid_container_input_creates_no_files(self):
        destination = self.directory / "volume"
        with self.assertRaises((KeyError, ValueError, TypeError)):
            initialize_credentials.initialize(b'{"credentials":{}}', destination)
        self.assertFalse(destination.exists())


class ReferencedAssets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.references = set()

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if (
                name in {"src", "href"}
                and value
                and not value.startswith(("http", "#", "data:", "mailto:"))
            ):
                self.references.add(value.split("?")[0].lstrip("/"))


class ConsoleStagingTests(unittest.TestCase):
    def test_all_console_documents_and_their_assets_are_staged(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "web"
            prepare.copy_web_assets(ROOT / "web", destination)
            documents = list((ROOT / "web").glob("*.html"))
            self.assertGreaterEqual(len(documents), 1)
            for document in documents:
                self.assertEqual((destination / document.name).read_bytes(), document.read_bytes())
                parser = ReferencedAssets()
                parser.feed(document.read_text())
                for relative in parser.references:
                    self.assertTrue((destination / relative).is_file(), (document.name, relative))


class CredentialQualificationTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            "credential_check", ROOT / "tests/security/check_credential_init.py"
        )
        self.fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.fixture)

    def configuration(self, project):
        volume = {"type": "volume", "source": "credential_data", "target": "/run/ezllmrouter"}
        return {
            "services": {
                "credential-init": {
                    "network_mode": "none",
                    "read_only": True,
                    "user": "0:0",
                    "cap_drop": ["ALL"],
                    "cap_add": ["CHOWN"],
                    "security_opt": ["no-new-privileges:true"],
                    "volumes": [volume],
                },
                "service": {
                    "read_only": True,
                    "user": "10001:10001",
                    "cap_drop": ["ALL"],
                    "security_opt": ["no-new-privileges:true"],
                    "volumes": [{**volume, "read_only": True}],
                },
            },
            "volumes": {"credential_data": {"name": project + "_credential_data"}},
        }

    def test_named_volume_check_rejects_tmpfs_external_and_live_profile_mounts(self):
        config = self.configuration("fixture")
        self.fixture.validate_configuration(config, "fixture")
        for change in ("tmpfs", "external", "live", "capability"):
            altered = deepcopy(config)
            if change == "tmpfs":
                altered["services"]["credential-init"]["volumes"][0]["type"] = "tmpfs"
            elif change == "external":
                altered["volumes"]["credential_data"]["external"] = True
            elif change == "live":
                altered["volumes"]["credential_data"]["name"] = (
                    "ezllmrouter-dev06-local_credential_data"
                )
            else:
                altered["services"]["credential-init"]["cap_add"].append("DAC_OVERRIDE")
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.fixture.validate_configuration(altered, "fixture")

    def test_compose_qualification_reuses_one_isolated_volume_across_three_containers(self):
        overrides = []

        def configuration(argv, **kwargs):
            project = argv[argv.index("--project-name") + 1]
            self.assertTrue(project.startswith("ezllmrouter-credential-check-"))
            if argv.count("-f") == 2:
                overrides.append(
                    json.loads(Path(argv[argv.index("-f", argv.index("-f") + 1) + 1]).read_text())
                )
            return json.dumps(self.configuration(project))

        with (
            patch.object(sys, "argv", ["check_credential_init.py"]),
            patch.object(self.fixture.subprocess, "check_output", side_effect=configuration),
            patch.object(self.fixture.subprocess, "run") as run,
            redirect_stdout(io.StringIO()),
        ):
            self.fixture.main()
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(len(commands), 4)
        self.assertEqual(
            [argv[argv.index("--phase") + 1] for argv in commands[:3]], ["1", "2", "2"]
        )
        self.assertTrue(all("credential-init" in argv for argv in commands[:2]))
        self.assertIn("credential-reader", commands[2])
        self.assertEqual(commands[-1][-3:], ["down", "--volumes", "--remove-orphans"])
        self.assertEqual(len({argv[argv.index("--project-name") + 1] for argv in commands}), 1)
        reader = overrides[0]["services"]["credential-reader"]
        self.assertEqual(reader["user"], "10001:10001")
        self.assertTrue(reader["volumes"][0]["read_only"])
        self.assertEqual(reader["volumes"][0]["source"], "credential_data")
        self.assertNotIn("cap_add", reader)
