"""Independent branch, outcome and telemetry checks for the test instruments."""

from contextlib import redirect_stderr
import io
import json
from pathlib import Path
import runpy
import sys
import tempfile
import threading
import unittest

from tools.test_coverage import LineCoverage, report
from tools.test_health import TimedResult, summarize, write_result


class BranchMeasurementTests(unittest.TestCase):
    def test_exception_dispatch_is_excluded_but_user_decisions_inside_handlers_count(self):
        from tools.branch_coverage import branches

        code = compile(
            "def run(x):\n    try:\n        return 1/x\n    except ZeroDivisionError:\n        return 1 if x else 2\n",
            "synthetic.py",
            "exec",
        )
        rows = list(branches(code).values())
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["from"] for row in rows}, {5})

    def test_branch_exits_include_threads_loop_exhaustion_and_unexecuted_functions(self):
        source = "def choose(value):\n    if value:\n        return 1\n    return 0\ndef loop(values):\n    for value in values:\n        choose(value)\ndef untouched(value):\n    return 1 if value else 0\n"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "sample.py"
            path.write_text(source)
            output = root / "observed"
            tools_before = [sys.monitoring.get_tool(i) for i in range(6)]
            with LineCoverage(output, (root,)):
                namespace = runpy.run_path(str(path))
                threads = [
                    threading.Thread(target=namespace["loop"], args=([value],))
                    for value in (False, True)
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(2)
                    self.assertFalse(thread.is_alive())
            self.assertEqual([sys.monitoring.get_tool(i) for i in range(6)], tools_before)
            result = report(output, (root,), root)
            detail = result["files"]["sample.py"]
            self.assertEqual(detail["branches"], 6)
            self.assertEqual(detail["branches_executed"], 4)
            self.assertEqual({row["function"] for row in detail["missing_branches"]}, {"untouched"})

    def test_one_taken_exit_does_not_cover_its_sibling_and_nested_collectors_restore(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "sample.py"
            path.write_text("def choose(value):\n    return 1 if value else 0\n")
            before = [sys.monitoring.get_tool(i) for i in range(6)]
            with LineCoverage(root / "outer", (root,)):
                with LineCoverage(root / "inner", (root,)):
                    namespace = runpy.run_path(str(path))
                    namespace["choose"](True)
                namespace["choose"](False)
            inner = report(root / "inner", (root,), root)["files"]["sample.py"]
            outer = report(root / "outer", (root,), root)["files"]["sample.py"]
            self.assertEqual((inner["branches_executed"], outer["branches_executed"]), (1, 2))
            self.assertEqual([sys.monitoring.get_tool(i) for i in range(6)], before)

    def test_failure_restores_trace_and_monitoring_and_still_writes_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            trace = sys.gettrace()
            tools = [sys.monitoring.get_tool(i) for i in range(6)]
            original = ValueError("original consumer failure")
            with self.assertRaises(ValueError) as caught, LineCoverage(root, (root,)):
                raise original
            self.assertIs(caught.exception, original)
            self.assertIs(sys.gettrace(), trace)
            self.assertEqual([sys.monitoring.get_tool(i) for i in range(6)], tools)
            self.assertEqual(len(list(root.glob("branches-*.json"))), 1)


class HealthMeasurementTests(unittest.TestCase):
    def test_duration_budget_includes_the_boundary_and_does_not_exempt_failed_runs(self):
        from tools.test_health import budget_errors

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "module-synthetic.json"
            path.write_text(json.dumps({"module": "synthetic", "seconds": 30, "passed": False}))
            self.assertEqual(budget_errors(root, 30), [])
            self.assertEqual(len(budget_errors(root, 29.99)), 1)

    def test_results_keep_failures_skips_subtests_and_no_exception_payloads(self):
        canary = "measurement-private-canary-value"

        class Cases(unittest.TestCase):
            def test_pass(self):
                pass

            def test_failure(self):
                self.fail(canary)

            def test_subtest(self):
                with self.subTest(private=canary):
                    self.assertEqual(1, 2)

            def test_skip(self):
                self.skipTest(canary)

        with tempfile.TemporaryDirectory() as temporary, redirect_stderr(io.StringIO()):
            result = unittest.TextTestRunner(stream=io.StringIO(), resultclass=TimedResult).run(
                unittest.defaultTestLoader.loadTestsFromTestCase(Cases)
            )
            write_result("synthetic", result, 0.5, temporary)
            root = Path(temporary)
            summary = summarize(root)
            self.assertFalse(summary["modules"][0]["passed"])
            observations = summary["modules"][0]["tests"]
            self.assertEqual(
                sorted(row["outcome"] for row in observations),
                ["failed", "failed", "passed", "skipped"],
            )
            self.assertTrue(all(row["seconds"] >= 0 for row in observations))
            for path in root.glob("*.json"):
                self.assertNotIn(canary, path.read_text())

    def test_repeat_failures_remain_visible_and_distinct_tiers_do_not_create_flakes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index, (tier, outcome) in enumerate(
                (("offline", "passed"), ("offline", "failed"), ("loopback", "skipped"))
            ):
                (root / f"module-{index}.json").write_text(
                    json.dumps(
                        {
                            "tier": tier,
                            "tests": [{"test": "suite.case", "outcome": outcome, "seconds": 0.1}],
                        }
                    )
                )
            summary = summarize(root)
            self.assertEqual(summary["unstable_tests"], ["offline:suite.case"])
            self.assertEqual(len(summary["modules"]), 3)


class CoveragePolicyTests(unittest.TestCase):
    def test_js_budget_fails_lost_measurements_new_unmeasured_sources_and_more_misses(self):
        from tools.javascript_coverage import budget_errors

        row = {"measured": True, "missing_functions": 1, "missing_statements_or_observed_blocks": 2}
        self.assertEqual(budget_errors({"a.js": row}, {"a.js": row}), [])
        self.assertTrue(budget_errors({"a.js": {**row, "measured": False}}, {"a.js": row}))
        self.assertTrue(budget_errors({"new.js": {**row, "measured": False}}, {}))
        self.assertTrue(budget_errors({"a.js": {**row, "missing_functions": 2}}, {"a.js": row}))
        self.assertTrue(budget_errors({}, {"a.js": row}))

    def test_missing_sources_selectors_new_uncovered_files_and_increased_gaps_fail(self):
        from tools.coverage_reports import baseline_for, gaps, regressions

        row = {
            "sha256": "synthetic",
            "missing_lines": [2],
            "missing_branches": [{"id": "secure:1->2", "function": "secure", "from": 1, "to": 2}],
            "branch_functions": ["secure"],
        }
        summary = {"scope": "synthetic", "python": "3.12.15", "files": {"source.py": row}}
        self.assertEqual(
            len(gaps(summary, {"critical": [{"path": "source.py", "function": "secure"}]})), 1
        )
        self.assertIn(
            "missing critical conditional function",
            gaps(summary, {"critical": [{"path": "source.py", "function": "renamed"}]})[0]["error"],
        )
        self.assertEqual(len(regressions(summary, {"files": {}})), 2)
        self.assertEqual(
            regressions(summary, baseline_for(summary)),
            [],
        )
        self.assertTrue(regressions({"files": {}}, {"files": {"source.py": {}}}))

    def test_html_escapes_source_names_and_keeps_subsystem_and_critical_gaps(self):
        from tools.coverage_reports import render

        summary = {
            "scope": "test",
            "files": {
                "clients/python/<script>.py": {
                    "sha256": "synthetic",
                    "executed": 1,
                    "executable": 2,
                    "missing_lines": [2],
                    "branches": 2,
                    "branches_executed": 1,
                    "branch_functions": ["secure"],
                    "missing_branches": [{"function": "secure", "from": 1, "to": 2}],
                }
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = render(
                summary,
                root,
                {"critical": [{"path": "clients/python/<script>.py", "function": "secure"}]},
            )
            self.assertEqual(result["subsystems"]["python_client"]["branches_executed"], 1)
            self.assertEqual(len(result["critical_uncovered_branches"]), 1)
            self.assertNotIn("<script>", (root / "index.html").read_text())

    def test_v8_folds_identical_installed_sources_and_keeps_unmeasured_files_explicit(self):
        from tools.javascript_coverage import report, source_for

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "clients/js"
            source.mkdir(parents=True)
            (source / "index.cjs").write_text("module.exports = () => 1;\n")
            (root / "web").mkdir()
            (root / "web/unmeasured.js").write_text("function untouched() {}\n")
            installed = root / "installed"
            installed.mkdir()
            path = installed / "index.cjs"
            path.write_bytes((source / "index.cjs").read_bytes())
            data = root / "coverage"
            data.mkdir()
            (data / "coverage-1.json").write_text(
                json.dumps(
                    {
                        "result": [
                            {
                                "url": path.as_uri(),
                                "functions": [
                                    {
                                        "ranges": [
                                            {"startOffset": 0, "endOffset": 25, "count": 1},
                                            {"startOffset": 17, "endOffset": 24, "count": 0},
                                        ]
                                    }
                                ],
                            }
                        ]
                    }
                )
            )
            summary = report(data, root)
            self.assertTrue(summary["files"]["clients/js/index.cjs"]["measured"])
            self.assertEqual(summary["files"]["clients/js/index.cjs"]["observed_blocks_hit"], 1)
            self.assertFalse(summary["files"]["web/unmeasured.js"]["measured"])
            path.write_text("unrelated bytes")
            self.assertIsNone(source_for(path.as_uri(), root))
            path.unlink()
            import hashlib

            (data / "sources-synthetic.json").write_text(
                json.dumps(
                    {
                        path.as_uri(): {
                            "canonical": "clients/js/index.cjs",
                            "sha256": hashlib.sha256(
                                (source / "index.cjs").read_bytes()
                            ).hexdigest(),
                        }
                    }
                )
            )
            self.assertTrue(report(data, root)["files"]["clients/js/index.cjs"]["measured"])
            (source / "index.cjs").write_text("changed after measurement")
            with self.assertRaisesRegex(ValueError, "identity changed"):
                report(data, root)


if __name__ == "__main__":
    unittest.main()
