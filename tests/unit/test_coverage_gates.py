"""Counterexamples for HTTP measurement and coverage budgets with fixed identities."""

from copy import deepcopy
from contextlib import redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import subprocess
import shlex
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools.coverage_reports import baseline_for, regressions
from tools.javascript_coverage import budget_errors, budgets, report as javascript_report

ROOT = Path(__file__).resolve().parents[2]


def measurement(lines=(3, 4), branches=("left", "right"), sha="synthetic-source"):
    return {
        "scope": "synthetic conditional exits",
        "python": "3.12.15",
        "files": {
            "source.py": {
                "sha256": sha,
                "executable": 10,
                "executed": 10 - len(lines),
                "missing_lines": list(lines),
                "branches": 4,
                "branches_executed": 4 - len(branches),
                "branch_functions": ["choose"],
                "missing_branches": [
                    {"id": name, "function": "choose", "from": 2, "to": 3} for name in branches
                ],
            }
        },
    }


class PythonCoverageGateTests(unittest.TestCase):
    def test_previously_covered_lines_cannot_spend_other_lines_allowance(self):
        baseline = baseline_for(measurement())
        self.assertTrue(regressions(measurement(lines=(4, 5)), baseline))

    def test_previously_covered_exits_cannot_spend_other_exits_allowance(self):
        baseline = baseline_for(measurement())
        self.assertTrue(regressions(measurement(branches=("right", "new")), baseline))

    def test_improvements_require_tightening_the_unchanged_source_baseline(self):
        baseline = baseline_for(measurement())
        errors = regressions(measurement(lines=(3,), branches=("left",)), baseline)
        self.assertTrue(any("tighten" in error.lower() for error in errors), errors)

    def test_changed_source_cannot_inherit_an_unreviewed_budget(self):
        baseline = baseline_for(measurement())
        self.assertTrue(regressions(measurement(sha="changed-source"), baseline))

    def test_exact_baseline_passes_and_new_fully_covered_sources_need_no_allowance(self):
        summary = measurement()
        self.assertEqual(regressions(summary, baseline_for(summary)), [])
        self.assertEqual(regressions(measurement(lines=(), branches=()), {"files": {}}), [])


class HTTPCoverageGateTests(unittest.TestCase):
    def test_both_tiers_exercise_scheduler_outcomes_deterministically(self):
        from tools import check

        self.assertIn("tests.unit.test_operator_scheduler", check.MODULES)
        self.assertIn("tests.unit.test_operator_scheduler", check.LOOPBACK_MODULES)

    def test_measurements_reject_reusing_nonempty_output_directories(self):
        from tools.coverage_run import prepare

        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ):
            output = Path(temporary) / "http"
            self.assertEqual(prepare(output, "http"), output.resolve())
            with self.assertRaisesRegex(ValueError, "fresh and empty"):
                prepare(output, "http")

    def test_pr_http_step_measures_audits_merges_and_retains_results(self):
        workflow = (ROOT / ".github/workflows/check.yml").read_text()
        command = next(line for line in workflow.splitlines() if "tools.check --http-only" in line)
        arguments = shlex.split(command.split("run:", 1)[1])
        for flag in ("--coverage", "--coverage-gate", "--lock-audit", "--coverage-merge"):
            self.assertIn(flag, arguments)
        self.assertGreater(
            workflow.index("name: Retain coverage and test health"),
            workflow.index("name: Local HTTP regression fixtures"),
        )

    def test_http_runner_propagates_audit_and_coverage_and_reports_after_a_failed_module(self):
        from tools import check

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output, merge = root / "http", root / "offline"
            seen = []

            def run(arguments):
                seen.append(arguments)
                self.assertIn("--loopback", arguments)
                self.assertEqual(os.environ["EZLLMROUTER_LOCK_AUDIT"], "1")
                self.assertEqual(os.environ["EZLLMROUTER_TEST_COVERAGE"], str(output))
                if "bad.module" in arguments:
                    raise subprocess.CalledProcessError(1, arguments)

            with (
                patch.dict(os.environ),
                patch.object(check, "test_inventory_errors", return_value=[]),
                patch.object(check, "javascript_inventory_errors", return_value=[]),
                patch.object(check, "LOOPBACK_MODULES", ("bad.module", "good.module")),
                patch.object(check.subprocess, "check_output", return_value="v24.22.1"),
                patch.object(check, "run", side_effect=run),
                patch("tools.coverage_run.finish", return_value=[]) as finish,
                patch.object(
                    sys,
                    "argv",
                    [
                        "tools.check",
                        "--http-only",
                        "--coverage",
                        "--coverage-gate",
                        "--lock-audit",
                        "--coverage-dir",
                        str(output),
                        "--coverage-merge",
                        str(merge),
                        "--health-dir",
                        str(root / "health"),
                    ],
                ),
                redirect_stdout(io.StringIO()),
                redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(check.main(), 1)
                finish.assert_called_once_with(output, "http", enforce=True, merge=merge)
            self.assertEqual(len(seen), 2)

    def test_separate_http_and_combined_budgets_preserve_reviewed_source_identities(self):
        from tools.coverage_reports import merge_baselines
        from tools.coverage_run import baseline_for_tier

        offline = baseline_for(measurement())
        http = baseline_for(measurement(lines=(4, 5), branches=("right", "new")))
        combined = merge_baselines(offline, http)
        self.assertEqual(
            regressions(
                measurement(lines=(4,), branches=("right",)),
                combined,
            ),
            [],
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "tools").mkdir()
            import json

            (root / "tools/coverage_budget.json").write_text(json.dumps(offline))
            (root / "tools/coverage_budget_http.json").write_text(json.dumps(http))
            with patch("tools.coverage_run.ROOT", root):
                self.assertEqual(baseline_for_tier("offline"), offline)
                self.assertEqual(baseline_for_tier("http"), http)
                self.assertEqual(baseline_for_tier("combined"), combined)

    def test_merged_report_unions_hits_and_rejects_incompatible_sources(self):
        from tools.coverage_reports import merge_summaries

        offline = measurement(lines=(3, 4), branches=("left", "right"))
        http = measurement(lines=(4, 5), branches=("right", "new"))
        merged = merge_summaries(offline, http)
        self.assertEqual(merged["files"]["source.py"]["missing_lines"], [4])
        self.assertEqual(
            [row["id"] for row in merged["files"]["source.py"]["missing_branches"]],
            ["right"],
        )
        self.assertEqual(merged["files"]["source.py"]["executed"], 9)
        for change in ("source", "runtime", "inventory", "denominator"):
            changed = deepcopy(http)
            if change == "source":
                changed["files"]["source.py"]["sha256"] = "different"
            elif change == "runtime":
                changed["python"] = "3.12.0"
            elif change == "inventory":
                changed["files"] = {}
            else:
                changed["files"]["source.py"]["branches"] += 1
            with self.subTest(change=change), self.assertRaises(ValueError):
                merge_summaries(offline, changed)


class JavaScriptFunctionGateTests(unittest.TestCase):
    def test_static_sdk_budget_rejects_lost_functions_and_tightens_improvements(self):
        row = {
            "sha256": "synthetic",
            "measured": True,
            "functions": 3,
            "missing_functions": 1,
            "missing_function_ids": ["10:20"],
        }
        baseline = {"clients/js/index.cjs": row}
        self.assertEqual(budget_errors(baseline, baseline), [])
        swapped = {**row, "missing_function_ids": ["30:40"]}
        self.assertTrue(budget_errors({"clients/js/index.cjs": swapped}, baseline))
        covered = {**row, "missing_functions": 0, "missing_function_ids": []}
        self.assertTrue(budget_errors({"clients/js/index.cjs": covered}, baseline))
        changed = {**row, "sha256": "changed"}
        self.assertTrue(budget_errors({"clients/js/index.cjs": changed}, baseline))

    def test_utf16_methods_accessors_arrows_generators_and_constructors_match_real_v8_hits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "clients/js/index.cjs"
            source.parent.mkdir(parents=True)
            source.write_text(
                'const text="😀"; function plain(){return ()=>1;} '
                "async function* stream(){yield 1;} "
                "const obj={method(){return 1;},get value(){return 1;},set value(v){}}; "
                "class Shape{constructor(){this.x=1;} method(){return ()=>this.x;} "
                "static async ready(){return 1;}} "
                "plain()();stream().next();obj.method();obj.value;obj.value=2;"
                "new Shape().method()();Shape.ready();\n"
            )
            output = root / "coverage"
            output.mkdir()
            subprocess.run(
                ["node", str(source)],
                env={**os.environ, "NODE_V8_COVERAGE": str(output)},
                check=True,
                capture_output=True,
                timeout=10,
            )
            row = javascript_report(output, root)["files"]["clients/js/index.cjs"]
            self.assertEqual(row["functions"], 10)
            self.assertEqual(row["functions_hit"], 10, row["missing_function_offsets_utf16"])

    def test_executed_script_wrapper_does_not_cover_an_identically_sized_uncalled_function(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "clients/js/index.cjs"
            source.parent.mkdir(parents=True)
            source.write_text("function unused(){}")
            output = root / "coverage"
            output.mkdir()
            subprocess.run(
                ["node", str(source)],
                env={**os.environ, "NODE_V8_COVERAGE": str(output)},
                check=True,
                capture_output=True,
                timeout=10,
            )
            row = javascript_report(output, root)["files"]["clients/js/index.cjs"]
            self.assertEqual(row["functions"], 1)
            self.assertEqual(row["functions_hit"], 0)

    def test_removing_outer_calls_cannot_reduce_the_static_function_denominator(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "clients/js/index.cjs"
            source.parent.mkdir(parents=True)
            source.write_text(
                "function outer(){function left(){return 1;} function right(){return 2;}"
                "return 3;} module.exports={outer};\n"
            )
            rows = []
            for mode in ("called", "uncalled"):
                output = root / mode
                output.mkdir()
                subprocess.run(
                    [
                        "node",
                        "-e",
                        "const m=require(process.argv[1]);if(process.argv[2]==='called')m.outer();",
                        str(source),
                        mode,
                    ],
                    env={**os.environ, "NODE_V8_COVERAGE": str(output)},
                    check=True,
                    capture_output=True,
                    timeout=10,
                )
                summary = javascript_report(output, root)
                row = summary["files"]["clients/js/index.cjs"]
                rows.append((row, budgets(summary, "sdk")["clients/js/index.cjs"]))
            self.assertEqual([row["functions"] for row, _ in rows], [3, 3])
            self.assertEqual([row["functions_hit"] for row, _ in rows], [1, 0])
            self.assertEqual([budget["missing_functions"] for _, budget in rows], [2, 3])

    def test_never_loaded_sdk_functions_are_present_and_uncovered(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "clients/js/index.cjs"
            source.parent.mkdir(parents=True)
            source.write_text("function unused(){return ()=>1;} module.exports={unused};\n")
            output = root / "coverage"
            output.mkdir()
            payload = javascript_report(output, root)
            row = payload["files"]["clients/js/index.cjs"]
            self.assertFalse(row["measured"])
            self.assertEqual(row["functions"], 2)
            self.assertEqual(row["functions_hit"], 0)
            self.assertEqual(len(row["missing_function_offsets_utf16"]), 2)


if __name__ == "__main__":
    unittest.main()
