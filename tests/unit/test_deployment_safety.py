"""Offline profile secret custody and complete operator asset staging."""

from html.parser import HTMLParser
from contextlib import redirect_stdout
import io
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import sys
from copy import deepcopy
import unittest
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
