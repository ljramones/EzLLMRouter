"""Build validation must resolve the files actually copied into each stage."""

import json
from pathlib import Path
import tempfile
import subprocess
import shutil
import sys
import unittest

from tools.container_tests import resolve, staged_sources, test_commands as commands


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
