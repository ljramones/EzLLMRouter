"""Independent branch, outcome and telemetry checks for the test instruments."""

from contextlib import redirect_stderr
import io
import asyncio
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from tools.test_coverage import LineCoverage, report
from tools.test_health import TimedResult, summarize, write_result


class BranchMeasurementTests(unittest.TestCase):
    def test_while_predicates_have_one_pair_of_logical_exits(self):
        from tools.branch_coverage import branches

        for source, expected in (
            ("def run(n):\n while n:\n  n-=1\n return n\n", 2),
            ("def run(n,m):\n while n and m:\n  n-=1\n  m-=1\n", 4),
            ("def run(n,m):\n while n:\n  while m:\n   m-=1\n  n-=1\n", 4),
            ("def run(n,m):\n while n or m:\n  if n: n-=1\n  else: m-=1\n", 6),
            ("def run(n):\n while n:\n  if n>1:\n   n-=1\n   continue\n  break\n", 4),
            ("def run(values):\n for value in values:\n  pass\n", 2),
        ):
            with self.subTest(source=source):
                self.assertEqual(len(branches(compile(source, "synthetic.py", "exec"))), expected)

    def test_short_circuit_and_await_loop_copies_keep_every_real_exit(self):
        sources = (
            (
                "def run(n):\n value=0\n while n:\n"
                + "  value += 1\n" * 140
                + "  n-=1\n return value\n",
                ((0,), (2,)),
                2,
            ),
            (
                "def run(n,m):\n while n and m:\n  n-=1\n  m-=1\n",
                ((0, 2), (2, 0), (1, 2), (2, 1)),
                4,
            ),
            (
                "async def flag(n):\n return bool(n)\nasync def run(n):\n while await flag(n):\n  n-=1\n",
                ((0,), (3,)),
                2,
            ),
            (
                "def run(n,m):\n while n or m:\n  if n: n-=1\n  else: m-=1\n",
                ((0, 0), (1, 0), (0, 1), (2, 1)),
                6,
            ),
        )
        for source, arguments, expected in sources:
            with self.subTest(source=source), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                path = root / "sample.py"
                path.write_text(source)
                with LineCoverage(root / "output", (root,)):
                    namespace = runpy.run_path(str(path))
                    for args in arguments:
                        result = namespace["run"](*args)
                        if source.startswith("async"):
                            asyncio.run(result)
                row = report(root / "output", (root,), root)["files"]["sample.py"]
                self.assertEqual((row["branches"], row["branches_executed"]), (expected, expected))

    def test_old_physical_branch_artifacts_cannot_be_mixed_with_logical_coverage(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "branches-old.json").write_text(json.dumps({"old.py": []}))
            with self.assertRaisesRegex(ValueError, "fresh logical-branch"):
                report(root, (root,), root)

    def test_large_loop_jump_operands_merge_but_finally_handler_copies_stay_distinct(self):
        import dis
        from tools.branch_coverage import branches, codes

        padding = "  value += 1\n" * 140
        source = "def run(n):\n value=0\n while n:\n" + padding + "  n-=1\n return value\n"
        code = compile(source, "synthetic.py", "exec")
        self.assertTrue(
            any(i.opname == "EXTENDED_ARG" for c in codes(code) for i in dis.get_instructions(c))
        )
        self.assertEqual(len(branches(code)), 2)
        # The compiler duplicates a finally handler, including its own for/if
        # decisions. Those are separate physical paths, not a while predicate.
        for tail in ("", "  action()\n", "   action()\n"):
            code = compile(
                "def run(flag):\n try:\n  action()\n finally:\n  for value in values:\n   if flag: action()\n"
                + tail,
                "synthetic.py",
                "exec",
            )
            with self.subTest(tail=tail):
                self.assertEqual(len(branches(code)), 8)
        code = compile(
            "def run(flag,n):\n try:\n  action()\n finally:\n  while n:\n   if flag: action()\n   action()\n   n-=1\n",
            "synthetic.py",
            "exec",
        )
        self.assertEqual(len(branches(code)), 8)

    def test_loop_exhaustion_covers_false_without_requiring_a_zero_iteration_call(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "loop.py"
            path.write_text("def run(n):\n while n:\n  n-=1\n return n\n")
            with LineCoverage(root / "output", (root,)):
                namespace = runpy.run_path(str(path))
                self.assertEqual(namespace["run"](3), 0)
            row = report(root / "output", (root,), root)["files"]["loop.py"]
            self.assertEqual((row["branches"], row["branches_executed"]), (2, 2))
            self.assertEqual(row["missing_branches"], [])

    def test_trace_preservation_probe_rejects_a_collector_that_clears_the_hook(self):
        original = LineCoverage.__enter__

        def drops_trace(collector):
            result = original(collector)
            sys.settrace(None)
            return result

        nested = BranchMeasurementTests(
            "test_failure_restores_trace_and_monitoring_and_still_writes_evidence"
        )
        with patch.object(LineCoverage, "__enter__", drops_trace):
            with self.assertRaises(AssertionError):
                nested.test_failure_restores_trace_and_monitoring_and_still_writes_evidence()

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

    def test_concurrent_first_calls_initialize_once_and_retain_both_exits(self):
        from tools.test_coverage import branch_api

        api = branch_api()
        original = api.identity
        arrivals = []
        second = threading.Event()

        def identity(code):
            if code.co_name == "choose":
                arrivals.append(threading.get_ident())
                if len(arrivals) == 1:
                    # Hashing a large code object releases the GIL. Hold that
                    # window open so a second first-call callback can contend.
                    second.wait(0.1)
                else:
                    second.set()
            return original(code)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "sample.py"
            path.write_text("def choose(value):\n return 1 if value else 0\n")
            namespace = runpy.run_path(str(path))
            barrier = threading.Barrier(2)

            def invoke(value):
                barrier.wait(2)
                namespace["choose"](value)

            with patch.object(api, "identity", identity), LineCoverage(root / "output", (root,)):
                threads = [
                    threading.Thread(target=invoke, args=(value,)) for value in (True, False)
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(2)
                    self.assertFalse(thread.is_alive())
            self.assertEqual(
                len(arrivals), 1, "concurrent entry reset a code object's observations"
            )
            row = report(root / "output", (root,), root)["files"]["sample.py"]
            self.assertEqual((row["branches"], row["branches_executed"]), (2, 2))

    def test_failure_restores_trace_and_monitoring_and_still_writes_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "trace_sample.py"
            path.write_text("def execute(marker):\n return marker\n")
            previous = sys.gettrace()
            observed = []

            def tracer(frame, event, value):
                if (
                    frame.f_code.co_filename == str(path)
                    and event == "return"
                    and frame.f_code.co_name == "execute"
                ):
                    observed.append(value)
                return tracer

            sys.settrace(tracer)
            try:
                tools = [sys.monitoring.get_tool(i) for i in range(6)]
                original = ValueError("original consumer failure")
                with self.assertRaises(ValueError) as caught, LineCoverage(root, (root,)):
                    namespace = runpy.run_path(str(path))
                    namespace["execute"]("inside")
                    raise original
                self.assertIs(caught.exception, original)
                self.assertIs(sys.gettrace(), tracer)
                namespace["execute"]("after")
                self.assertEqual(observed, ["inside", "after"])
                self.assertEqual([sys.monitoring.get_tool(i) for i in range(6)], tools)
                self.assertEqual(len(list(root.glob("branches-*.json"))), 1)
            finally:
                sys.settrace(previous)


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
    def test_console_counter_swaps_and_changed_sources_require_review(self):
        from tools.javascript_coverage import budget_errors

        row = {
            "sha256": "same",
            "measured": True,
            "functions": 2,
            "counters": 5,
            "missing_functions": 1,
            "missing_statements_or_observed_blocks": 1,
            "missing_counter_ids": ["function:10:20", "statement:30:40"],
        }
        baseline = {"web/component.js": row}
        changed = {**row, "missing_counter_ids": ["function:11:21", "statement:30:40"]}
        self.assertTrue(budget_errors({"web/component.js": changed}, baseline))
        self.assertTrue(budget_errors({"web/component.js": {**row, "sha256": "changed"}}, baseline))
        improved = {**row, "missing_functions": 0, "missing_counter_ids": ["statement:30:40"]}
        self.assertTrue(
            any(
                "tighten" in error
                for error in budget_errors({"web/component.js": improved}, baseline)
            )
        )

    def test_console_cannot_keep_an_unmeasured_zero_budget(self):
        from tools.javascript_coverage import budget_errors

        row = {
            "sha256": "synthetic",
            "measured": False,
            "missing_functions": 0,
            "missing_statements_or_observed_blocks": 0,
        }
        self.assertTrue(budget_errors({"web/unused.js": row}, {"web/unused.js": row}))

    def test_unexecuted_console_source_has_static_counter_denominators(self):
        from tools.javascript_coverage import report

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "web").mkdir()
            output = root / "coverage"
            output.mkdir()
            (root / "web/unused.js").write_text(
                'throw Error("inventory must not execute"); function unused(){ return 42; }\n'
            )
            with patch.dict(
                os.environ, {"EZLLMROUTER_JS_COVERAGE": str(output), "NODE_V8_COVERAGE": ""}
            ):
                row = report(output, root)["files"]["web/unused.js"]
            self.assertEqual(list(output.glob("vm-coverage-*.json")), [])
            self.assertFalse(row["measured"])
            self.assertEqual(row["functions"], 1)
            self.assertGreater(row["statements"], 0)

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
