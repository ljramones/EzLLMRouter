"""Regression probes for failures that happen before a test starts or after a timeout."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from tools import check
from tools.test_health import TimedResult, budget_errors, summarize, write_result


class FixtureOutcomeTests(unittest.TestCase):
    def test_loader_exceptions_are_recorded_before_they_propagate(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.dict(os.environ, {"EZLLMROUTER_TEST_HEALTH": temporary}),
        ):
            with patch.object(
                unittest.defaultTestLoader,
                "loadTestsFromName",
                side_effect=RuntimeError("synthetic import failure"),
            ):
                with self.assertRaisesRegex(RuntimeError, "synthetic import failure"):
                    check.run_module("synthetic.loader", loopback=False)
            summary = summarize(Path(temporary))
            self.assertEqual(summary["modules"][0]["outcome"], "load_error")

    def test_setup_class_errors_have_sanitized_outcomes_without_start_test(self):
        canary = "synthetic-private-setup-error"

        class Case(unittest.TestCase):
            @classmethod
            def setUpClass(cls):
                raise RuntimeError(canary)

            def test_unreached(self):
                self.fail("fixture should not reach the test")

        result = unittest.TextTestRunner(stream=io.StringIO(), resultclass=TimedResult).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(Case)
        )
        self.assertFalse(result.wasSuccessful())
        self.assertEqual(len(result.observations), 1)
        self.assertEqual(result.observations[0]["outcome"], "error")
        with tempfile.TemporaryDirectory() as temporary:
            write_result("synthetic", result, 0.1, temporary)
            self.assertNotIn(canary, next(Path(temporary).glob("module-*.json")).read_text())

    def test_setup_module_failure_then_success_is_visible_as_an_unstable_module(self):
        module = ModuleType("ezllmrouter_synthetic_setup_fixture")

        def fail():
            raise RuntimeError("synthetic setup module failure")

        module.setUpModule = fail
        case = type(
            "Case",
            (unittest.TestCase,),
            {"__module__": module.__name__, "test_ok": lambda self: None},
        )
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.dict(sys.modules, {module.__name__: module}),
        ):
            for failed in (True, False):
                module.setUpModule = fail if failed else lambda: None
                result = unittest.TextTestRunner(stream=io.StringIO(), resultclass=TimedResult).run(
                    unittest.defaultTestLoader.loadTestsFromTestCase(case)
                )
                write_result("synthetic.module", result, 0.1, temporary)
            summary = summarize(Path(temporary))
            self.assertIn("offline:synthetic.module", summary.get("unstable_modules", []))

    def test_timeout_is_retained_as_a_module_outcome(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.dict(os.environ, {"EZLLMROUTER_TEST_HEALTH": temporary}),
        ):
            with patch.object(
                check.subprocess, "run", side_effect=subprocess.TimeoutExpired("synthetic", 180)
            ):
                with self.assertRaises(subprocess.TimeoutExpired):
                    check.run(
                        [sys.executable, "-m", "tools.check", "--test-module", "synthetic.timeout"]
                    )
            summary = summarize(Path(temporary))
            self.assertEqual(len(summary["modules"]), 1)
            self.assertEqual(summary["modules"][0]["outcome"], "timeout")
            self.assertFalse(summary["modules"][0]["passed"])

    def test_instrumented_timings_do_not_enforce_the_uninstrumented_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "module-synthetic.json").write_text(
                json.dumps(
                    {
                        "module": "synthetic",
                        "seconds": 1000,
                        "passed": True,
                        "instrumentation": ["coverage"],
                    }
                )
            )
            self.assertEqual(budget_errors(root, 30), [])

    def test_timeout_after_child_result_still_records_the_failed_process_exit(self):
        from tools.test_health import write_script_result

        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.dict(os.environ, {"EZLLMROUTER_TEST_HEALTH": temporary}),
        ):

            def timeout(command, **options):
                with patch.dict(os.environ, options["env"]):
                    write_script_result("synthetic", 0.1, True, temporary, [])
                raise subprocess.TimeoutExpired(command, 180)

            with patch.object(check.subprocess, "run", side_effect=timeout):
                with self.assertRaises(subprocess.TimeoutExpired):
                    check.run(
                        [sys.executable, "-m", "tools.check", "--test-module", "synthetic.timeout"]
                    )
            outcomes = [row["outcome"] for row in summarize(Path(temporary))["modules"]]
            self.assertIn("timeout", outcomes)


class RunnerOutcomeTests(unittest.TestCase):
    def run_empty(self, arguments, summary=None):
        with (
            patch.object(check, "test_inventory_errors", return_value=[]),
            patch.object(check, "javascript_inventory_errors", return_value=[]),
            patch.object(check, "MODULES", ()),
            patch.object(check, "SCRIPT_TESTS", ()),
            patch.object(check, "FRONTEND_TESTS", ()),
            patch.object(check, "JAVASCRIPT_SCRIPTS", ()),
            patch.object(check, "run"),
            patch.object(check.subprocess, "check_output", return_value="v24.22.1"),
            patch("tools.coverage_run.prepare", return_value=Path("/unused")),
            patch("tools.coverage_run.finish", return_value=[]),
            patch(
                "tools.test_health.summarize",
                return_value=summary or {"unstable_tests": [], "unstable_modules": []},
            ),
            patch.object(sys, "argv", ["tools.check", "--tests-only", *arguments]),
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            return check.main()

    def test_duration_budget_rejects_instrumented_runs(self):
        with tempfile.TemporaryDirectory() as temporary:
            for flag in ("--coverage", "--lock-audit"):
                with self.subTest(flag=flag):
                    with self.assertRaises(SystemExit) as result:
                        self.run_empty([flag, "--health-budget", "30", "--health-dir", temporary])
                    self.assertEqual(result.exception.code, 2)

    def test_ci_duration_gate_is_separate_from_both_instrumented_tiers(self):
        workflow = (Path(__file__).resolve().parents[2] / ".github/workflows/check.yml").read_text()
        commands = [line.strip()[5:] for line in workflow.splitlines() if "run: " in line]
        checks = [command for command in commands if "-m tools.check " in command]
        measured = [command for command in checks if "--coverage" in command]
        self.assertEqual(len(measured), 2)
        self.assertTrue(all("--health-budget" not in command for command in measured))
        timed = [command for command in checks if "--health-budget" in command]
        self.assertEqual(len(timed), 1)
        self.assertIn("--loopback", timed[0])
        self.assertNotIn("--lock-audit", timed[0])

    def test_unstable_tests_or_modules_make_the_runner_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            for key in ("unstable_tests", "unstable_modules"):
                with self.subTest(key=key):
                    summary = {
                        "unstable_tests": [],
                        "unstable_modules": [],
                        key: ["offline:synthetic"],
                    }
                    self.assertEqual(self.run_empty(["--health-dir", temporary], summary), 1)

    def test_stress_seed_controls_actual_generated_inputs_and_is_replayable(self):
        from tools.concurrency_stress import run

        observations = []

        def invoke(command, **options):
            observations.append(
                (
                    command[command.index("--test-module") + 1],
                    options.get("env", {}).get("EZLLMROUTER_TEST_SEED"),
                )
            )
            return SimpleNamespace(returncode=0)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertTrue(run(2, 17, root / "first", offline_only=True, invoke=invoke))
            original = list(observations)
            self.assertTrue(all(seed is not None for _, seed in original))
            self.assertTrue(
                any("Generated" in module or "StateModel" in module for module, _ in original)
            )
            observations.clear()
            self.assertTrue(run(2, 17, root / "second", offline_only=True, invoke=invoke))
            self.assertEqual(observations, original)


class MonitoringDisableTests(unittest.TestCase):
    def test_reusing_a_code_object_in_sequential_collectors_restores_all_events(self):
        from tools.test_coverage import LineCoverage, report

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "sample.py"
            source.write_text("def choose(value):\n return 1 if value else 0\n")
            namespace = {}
            exec(compile(source.read_bytes(), str(source), "exec"), namespace)
            rows = []
            for index, value in enumerate((True, False, True)):
                output = root / str(index)
                with LineCoverage(output, (root,)):
                    namespace["choose"](value)
                rows.append(report(output, (root,), root)["files"]["sample.py"])
            self.assertEqual([row["branches_executed"] for row in rows], [1, 1, 1])
            self.assertNotEqual(rows[0]["missing_branches"], rows[1]["missing_branches"])

    def test_warmed_lines_and_both_branch_exits_stop_delivering_callbacks(self):
        from tools.branch_coverage import BranchCoverage

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            code = compile(
                "def choose(value):\n return 1 if value else 0\n", str(root / "sample.py"), "exec"
            )
            namespace = {}
            exec(code, namespace)
            collector = BranchCoverage(root / "output", (str(root) + os.sep,))
            counts = {"line": 0, "branch": 0}
            original_line, original_branch = collector._line, collector._branch

            def line(*arguments):
                counts["line"] += 1
                return original_line(*arguments)

            def branch(*arguments):
                counts["branch"] += 1
                return original_branch(*arguments)

            collector._line, collector._branch = line, branch
            with collector:
                namespace["choose"](True)
                namespace["choose"](False)
                warmed = dict(counts)
                for value in range(1000):
                    namespace["choose"](bool(value % 2))
            self.assertEqual(counts, warmed, "coverage kept invoking already-complete locations")
