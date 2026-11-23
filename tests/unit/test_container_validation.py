"""Build validation must resolve the files actually copied into each stage."""

import json
from pathlib import Path
import tempfile
import subprocess
import shutil
import sys
import hashlib
import tarfile
import zipfile
from copy import deepcopy
import unittest
from unittest.mock import patch

from tools.container_tests import resolve, staged_sources, test_commands as commands


class QualificationSafetyTests(unittest.TestCase):
    def test_component_inventory_finds_copied_tools_modules_and_symlinks(self):
        from tools.deployment_qualification import runtime_components

        control = (
            "f\t755\t/usr/bin/find\0f\t755\t/usr/bin/dpkg-query\0f\t755\t/usr/local/bin/python\0"
        )
        for location in (
            "/opt/alternate-bin/nsenter",
            "/usr/local/bin/mount",
            "/vendor/bin/getfacl",
            "/vendor/bin/setfacl",
            "/vendor/bin/chacl",
            "/vendor/bin/getfattr",
            "/vendor/bin/setfattr",
            "/vendor/bin/infocmp",
            "/vendor/perl/Pod/Text.pm",
            "/vendor/perl/Pod/Text.pmc",
            "/vendor/perl/Archive/Tar.pm",
            "/vendor/perl/Archive/Tar.pmc",
        ):
            for kind in ("f\t755\t", "l\t777\t"):
                with (
                    self.subTest(location=location, kind=kind),
                    self.assertRaisesRegex(ValueError, "forbidden runtime component"),
                ):
                    runtime_components(control + kind + location + "\0")
        result = runtime_components(control)
        self.assertEqual(result["entries"], 3)
        self.assertEqual(result["forbidden_components"], [])
        self.assertIn("Pod/Text.pm", result["checked_perl_paths"])
        self.assertEqual(
            result, runtime_components("\0".join(reversed(control[:-1].split("\0"))) + "\0")
        )

    def test_component_inventory_rejects_incomplete_or_ambiguous_censuses(self):
        from tools.deployment_qualification import runtime_components

        control = "f\t755\t/usr/bin/find\0f\t755\t/usr/bin/dpkg-query\0"
        for raw in (
            "",
            control[:-1],
            "f\t755\t/usr/bin/find\0",
            control + "f\t755\t/usr/bin/find\0",
            control + "f\t755\trelative/path\0",
            control + "f\t755\t/opt/../bin/tool\0",
            control + "f\t755\t/opt//bin/tool\0",
            control + "f\t755\t/opt/unreadable\nname\0",
            control + "d\t755\t/opt/tool\0",
            control + "f\txyz\t/opt/tool\0",
            control + "f\t755\t/opt/tab\tname\0",
            control + "f\t755\t/opt/" + "x" * (10 * 1024 * 1024) + "\0",
            control + "f\t644\t/opt/control\0" * 100_001,
        ):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                runtime_components(raw)

    def test_component_inventory_preserves_data_files_and_unrelated_perl_modules(self):
        from tools.deployment_qualification import runtime_components

        control = "f\t755\t/usr/bin/find\0f\t755\t/usr/bin/dpkg-query\0"
        data = "f\t644\t/etc/passwd\0f\t644\t/usr/share/perl5/Debconf/FrontEnd/Text.pm\0"
        self.assertEqual(runtime_components(control + data)["entries"], 4)
        for link in ("/vendor/perl/Pod", "/vendor/perl/Archive"):
            with self.subTest(link=link), self.assertRaisesRegex(ValueError, "forbidden"):
                runtime_components(control + "l\t777\t" + link + "\0")
        for module in ("/vendor/Pod/Text.pm", "/vendor/Archive/Tar.pmc"):
            with self.subTest(module=module), self.assertRaisesRegex(ValueError, "forbidden"):
                runtime_components(control + "f\t644\t" + module + "\0")

    def test_runtime_policy_rejects_installed_tools_setid_files_and_unsafe_locales(self):
        from tools.deployment_qualification import runtime_footprint

        image = {
            "Id": "sha256:" + "a" * 64,
            "Config": {"Env": ["LANG=C.UTF-8", "LC_ALL=C.UTF-8", "LANGUAGE=C"]},
        }
        for changed in (
            {"Env": ["LANG=C.UTF-8", "LANGUAGE=C"]},
            {"Env": ["LANG=C.UTF-8", "LC_ALL=C.UTF-8", "LANGUAGE=../../untrusted"]},
            {"Env": image["Config"]["Env"] + ["LANGUAGE=C"]},
        ):
            with self.subTest(config=changed), self.assertRaises(ValueError):
                runtime_footprint(dict(image, Config=changed), set(), ["login"], {})
        with self.assertRaises(ValueError):
            runtime_footprint(image, {"login"}, ["login"], {})
        for outputs in ((("/usr/bin/suid-canary", 0),), (("", 0), ("/usr/bin/nsenter", 0))):
            with (
                self.subTest(outputs=outputs),
                patch("tools.deployment_qualification.profile.command", side_effect=outputs),
                self.assertRaises(ValueError),
            ):
                runtime_footprint(image, set(), ["login"], {})
        with patch(
            "tools.deployment_qualification.profile.command",
            side_effect=[("", 0), ("f\t755\t/usr/bin/find\0f\t755\t/usr/bin/dpkg-query\0", 0)],
        ) as command:
            result = runtime_footprint(image, set(), ["login"], {})
        self.assertEqual(result["removed_packages"], ["login"])
        self.assertEqual(result["setid_files"], [])
        self.assertEqual(result["component_inventory"]["entries"], 2)
        self.assertEqual(
            command.call_args.args[1][-12:],
            [
                "find",
                "/",
                "-xdev",
                "(",
                "-type",
                "f",
                "-o",
                "-type",
                "l",
                ")",
                "-printf",
                "%y\\t%m\\t%p\\0",
            ],
        )

    def test_service_sqlite_probe_rejects_weakened_or_missing_capabilities(self):
        from tools.deployment_qualification import database_capabilities

        for observed in (
            {"defensive": False, "extension_loading": False},
            {"defensive": True, "extension_loading": True},
            {},
        ):
            with (
                self.subTest(observed=observed),
                patch(
                    "tools.deployment_qualification.profile.command",
                    return_value=(json.dumps(observed), 0),
                ),
                self.assertRaises(ValueError),
            ):
                database_capabilities("sha256:" + "a" * 64, {})
        expected = {"defensive": True, "extension_loading": False}
        with patch(
            "tools.deployment_qualification.profile.command", return_value=(json.dumps(expected), 0)
        ):
            self.assertEqual(database_capabilities("sha256:" + "a" * 64, {}), expected)

    def test_cold_archives_reject_links_traversal_foreign_owners_and_writable_files(self):
        from tools.qualification_storage import archive_members

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "backup.tar"
            for name, kind, uid, mode in (
                ("data", tarfile.REGTYPE, 10001, 0o600),
                ("../escape", tarfile.REGTYPE, 10001, 0o600),
                ("/absolute", tarfile.REGTYPE, 10001, 0o600),
                ("link", tarfile.SYMTYPE, 10001, 0o600),
                ("data", tarfile.REGTYPE, 10002, 0o600),
                ("data", tarfile.REGTYPE, 10001, 0o666),
            ):
                member = tarfile.TarInfo(name)
                member.type, member.uid, member.gid, member.mode = kind, uid, 10001, mode
                with tarfile.open(path, "w") as archive:
                    archive.addfile(member)
                with self.subTest(name=name, kind=kind, uid=uid, mode=mode):
                    if name == "data" and uid == 10001 and mode == 0o600:
                        self.assertEqual(archive_members(path), 1)
                    else:
                        with self.assertRaises(ValueError):
                            archive_members(path)

    def test_staged_source_changes_cannot_inherit_the_clean_manifest(self):
        from tools.deployment_qualification import validate_staging

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "runtime.py"
            source.write_text("reviewed runtime")
            packet = root / "source.zip"
            with zipfile.ZipFile(packet, "w") as archive:
                archive.writestr(
                    "SOURCE-MANIFEST.json",
                    json.dumps(
                        {
                            "source_files": [
                                {
                                    "target": "runtime.py",
                                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                                }
                            ]
                        }
                    ),
                )
            build = {"source_packet": str(packet), "build_dir": str(root), "overlays": []}
            # OS custody has independent positive/negative coverage in test_os_inputs;
            # this sparse fixture isolates the runtime-source identity boundary.
            with patch("tools.deployment_qualification.verify_os_staging"):
                self.assertEqual(
                    validate_staging(build), hashlib.sha256(packet.read_bytes()).hexdigest()
                )
                source.write_text("unreviewed runtime")
                with self.assertRaisesRegex(ValueError, "source identity"):
                    validate_staging(build)

    def test_rust_graph_requires_the_declared_versions_checksums_and_complete_metadata(self):
        from tools.security_rust import REGISTRY, rust_graph

        manifest = {
            "package": {"name": "sdk", "version": "1.0.0"},
            "dependencies": {"dep": "=2.0.0"},
        }
        lock = {
            "version": 4,
            "package": [
                {"name": "sdk", "version": "1.0.0", "dependencies": ["dep"]},
                {"name": "dep", "version": "2.0.0", "source": REGISTRY, "checksum": "a" * 64},
            ],
        }
        metadata = {
            "packages": [
                {"id": "sdk", "name": "sdk", "version": "1.0.0", "source": None},
                {"id": "dep", "name": "dep", "version": "2.0.0", "source": REGISTRY},
            ],
            "resolve": {
                "nodes": [{"id": "sdk", "deps": [{"pkg": "dep"}]}, {"id": "dep", "deps": []}]
            },
        }
        self.assertEqual(len(rust_graph(lock, manifest, metadata)), 1)
        for key, value in (
            ("source", "git+https://example.invalid/repo"),
            ("checksum", "bad"),
            ("version", "3.0.0"),
        ):
            changed = deepcopy(lock)
            changed["package"][1][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                rust_graph(changed, manifest, metadata)
        changed = deepcopy(metadata)
        changed["resolve"]["nodes"].pop()
        with self.assertRaisesRegex(ValueError, "incomplete"):
            rust_graph(lock, manifest, changed)
        changed = deepcopy(metadata)
        changed["resolve"]["nodes"][0]["deps"] = []
        with self.assertRaisesRegex(ValueError, "edge mismatch"):
            rust_graph(lock, manifest, changed)


class ContainerValidationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "test_sample.py"
        self.source.write_text(
            "import unittest\nclass Sample(unittest.TestCase):\n def test_ok(self): pass\n"
        )
        self.staged = {"service/tests/test_sample.py": self.source}

    def test_omitting_the_copy_cannot_pass_using_the_build_context_as_the_image(self):
        recipe = "FROM scratch\nCOPY tests/ /app/tests/\nWORKDIR /app\nRUN python -m unittest tests.test_sample\n"
        self.assertEqual(resolve(recipe, "service", self.staged), [])
        self.assertTrue(
            resolve(recipe.replace("COPY tests/ /app/tests/\n", ""), "service", self.staged)
        )

    def test_workdir_and_pythonpath_control_where_modules_are_found(self):
        recipe = "FROM scratch\nCOPY tests/ /suite/\nWORKDIR /suite\nRUN python -m unittest test_sample\n"
        self.assertEqual(resolve(recipe, "service", self.staged), [])
        self.assertTrue(
            resolve(recipe.replace("WORKDIR /suite", "WORKDIR /wrong"), "service", self.staged)
        )
        recipe = "FROM scratch\nCOPY tests/ /suite/\nENV PYTHONPATH=/suite\nRUN python -m unittest test_sample\n"
        self.assertEqual(resolve(recipe, "service", self.staged), [])

    def test_stages_reset_files_and_copy_from_an_earlier_stage_is_explicit(self):
        initial = "FROM scratch AS source\nCOPY tests/ /staged/tests/\n"
        recipe = (
            initial
            + "FROM scratch\nCOPY --from=source /staged/tests/ /app/tests/\nWORKDIR /app\nRUN python -m unittest tests.test_sample\n"
        )
        self.assertEqual(resolve(recipe, "service", self.staged), [])
        self.assertTrue(
            resolve(
                recipe.replace("COPY --from=source /staged/tests/ /app/tests/\n", ""),
                "service",
                self.staged,
            )
        )

    def test_exec_form_shell_wrappers_and_pytest_never_disappear_from_the_inventory(self):
        for statement in (
            "RUN " + json.dumps(["python", "-m", "unittest", "tests.test_sample"]),
            "RUN sh -ec 'python -m unittest tests.test_sample'",
            "RUN python -m pytest /app/tests/test_sample.py",
            "RUN pytest /app/tests/test_sample.py -q",
        ):
            with self.subTest(statement=statement):
                self.assertTrue(commands(statement), "validation command parsed to zero checks")
                recipe = "FROM scratch\nCOPY tests/ /app/tests/\nWORKDIR /app\n" + statement
                self.assertEqual(resolve(recipe, "service", self.staged), [])

    def test_unknown_validation_forms_fail_instead_of_parsing_to_zero_checks(self):
        for statement in (
            'RUN python -c "import unittest; unittest.main()"',
            "RUN some-wrapper python -m pytest tests/",
            "RUN python -m unittest $TEST_SELECTOR",
            "RUN python -m another_wrapper unittest tests.test_sample",
            'FROM scratch\nSHELL ["powershell", "-Command"]\nRUN python -m unittest tests.test_sample',
        ):
            with self.subTest(statement=statement), self.assertRaises(ValueError):
                commands(statement)

    def test_non_test_named_python_validation_scripts_are_required(self):
        recipe = "FROM scratch\nCOPY target_preflight.py /checks/target_preflight.py\nRUN python /checks/target_preflight.py\n"
        staged = {"service/target_preflight.py": self.source}
        self.assertTrue(commands(recipe))
        self.assertEqual(resolve(recipe, "service", staged), [])
        self.assertTrue(resolve(recipe, "service", {}))

    def test_bind_mounts_shadow_copied_files_and_do_not_leak_to_later_instructions(self):
        initial = "FROM scratch\nCOPY tests/ /app/tests/\nWORKDIR /app\n"
        hidden = "RUN --mount=type=bind,source=empty,target=/app/tests python -m unittest tests.test_sample\n"
        self.assertTrue(resolve(initial + hidden, "service", self.staged))
        mounted = "RUN --mount=type=bind,source=tests,target=/suite python /suite/test_sample.py\n"
        self.assertEqual(resolve("FROM scratch\n" + mounted, "service", self.staged), [])
        self.assertTrue(
            resolve(
                "FROM scratch\n" + mounted + "RUN python /suite/test_sample.py",
                "service",
                self.staged,
            )
        )

    def test_current_profile_detects_missing_copy_and_missing_preflight_sources(self):
        root = Path(__file__).resolve().parents[2]
        recipe = (root / "deploy/local/Dockerfile.service").read_text()
        staged = staged_sources()
        self.assertEqual(resolve(recipe, "service", staged), [])
        self.assertTrue(
            resolve(recipe.replace("COPY --chmod=0555 tests/ /app/tests/\n", ""), "service", staged)
        )
        staged = {
            key: value
            for key, value in staged.items()
            if not key.endswith("dev07_target_preflight.py")
        }
        self.assertTrue(resolve(recipe, "service", staged))

    def test_staged_preflight_can_import_its_shared_source_layout_helper(self):
        gateway = self.root / "gateway"
        for target, source in staged_sources().items():
            if target.startswith("service/gateway/tools/"):
                destination = gateway / target.removeprefix("service/gateway/")
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
        script = (
            "import sys,pathlib; sys.path.insert(0,sys.argv[1]); "
            "import tools.gateway.paths as helper; "
            "assert pathlib.Path(helper.__file__).resolve()==pathlib.Path(sys.argv[1],'tools/gateway/paths.py').resolve()"
        )
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", script, str(gateway)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        (gateway / "tools/gateway/paths.py").unlink()
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", script, str(gateway)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0, "missing staged helper inherited a host package")

    def test_removing_the_image_files_invalidates_a_later_validation(self):
        recipe = "FROM scratch\nCOPY tests/ /app/tests/\nWORKDIR /app\nRUN rm -rf /app\nRUN python -m unittest tests.test_sample\n"
        self.assertTrue(resolve(recipe, "service", self.staged))

    def test_new_dockerfiles_with_validation_require_a_qualified_staging_context(self):
        from tools.container_tests import repository_errors

        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / "Dockerfile.extra").write_text(
            "FROM scratch\nRUN python -m unittest tests.test_sample\n"
        )
        errors = repository_errors(self.root, self.staged)
        self.assertTrue(any("Dockerfile.extra" in error for error in errors), errors)

    def test_numeric_stage_copies_and_json_copy_paths_work(self):
        recipe = (
            "FROM scratch AS initial\nCOPY tests/ /staged/\nFROM scratch AS middle\n"
            'COPY --from=0 ["/staged/test_sample.py", "/checks/test_sample.py"]\n'
            "FROM middle\nWORKDIR /checks\nRUN python -m unittest test_sample\n"
        )
        self.assertEqual(resolve(recipe, "service", self.staged), [])

    def test_inventory_uses_the_same_static_environment_as_resolution(self):
        recipe = (
            "FROM scratch\nENV TEST_SELECTOR=tests.test_sample\nCOPY tests/ /app/tests/\n"
            "WORKDIR /app\nRUN python -m unittest $TEST_SELECTOR\n"
        )
        self.assertEqual(len(commands(recipe)), 1)
        self.assertEqual(resolve(recipe, "service", self.staged), [])
