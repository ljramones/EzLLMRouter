"""Performance evidence must preserve failure, accounting and cleanup semantics."""

import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.performance_metrics import Timings, check_cleanup
from tools.performance_suite import run, validate
from tools.performance_workload import Workload


class PerformanceUnitTests(unittest.TestCase):
    def test_percentiles_use_nearest_rank_and_bounded_windows(self):
        timer = Timings()
        with self.assertRaises(ValueError):
            timer.report()
        for value in range(20):
            timer.add(value)
        observed = timer.report()
        self.assertEqual(
            [observed["p50_seconds"], observed["p95_seconds"], observed["p99_seconds"]], [9, 18, 19]
        )
        for value in range(3000):
            timer.add(value)
        self.assertEqual(timer.report()["window_samples"], 2048)
        self.assertEqual(timer.report()["count"], 3020)
        for invalid in (-1, float("nan"), float("inf")):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                timer.add(invalid)

    def test_invalid_workloads_are_rejected_before_creating_phases(self):
        for values in (
            ([], 1, 0, 1, 0),
            ([True], 1, 0, 1, 0),
            ([1, 1], 1, 0, 1, 0),
            ([100001], 1, 0, 1, 0),
            ([1], 0, 0, 1, 0),
            ([1], 1, -1, 1, 0),
            ([1], 1, 0, 5, 0),
            ([1], 1, 0, 1, -1),
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                validate(*values)

    def test_instrumented_runs_cannot_claim_an_uninstrumented_baseline(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch("tools.performance_suite.instrumentation", return_value=["coverage"]),
            patch("tools.performance_suite.provenance") as source,
        ):
            with self.assertRaises(ValueError):
                run([1], 1, 0, 1, 0, Path(temporary))
            source.assert_not_called()
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_cleanup_checks_reject_threads_and_descriptor_growth(self):
        with (
            patch(
                "tools.performance_metrics.threading.enumerate",
                return_value=[SimpleNamespace(name="leak")],
            ),
            self.assertRaises(RuntimeError),
        ):
            check_cleanup([], 2, {"file_descriptors": 2})
        with patch("tools.performance_metrics.threading.enumerate", return_value=[]):
            with self.assertRaises(RuntimeError):
                check_cleanup([], 2, {"file_descriptors": 3})
            check_cleanup([], 2, {"file_descriptors": 2})

    def test_failed_and_timed_out_workers_preserve_first_failure_and_private_cleanup(self):
        for timeout in (False, True):
            with self.subTest(timeout=timeout), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                private_paths = []

                def invoke(command, private_paths=private_paths, should_timeout=timeout, **options):
                    private_paths.append(Path(options["env"]["TMPDIR"]))
                    self.assertTrue(private_paths[-1].is_dir())
                    options["stdout"].write("original failure\n")
                    if should_timeout:
                        raise subprocess.TimeoutExpired(command, options["timeout"])
                    return SimpleNamespace(returncode=7)

                with (
                    patch("tools.performance_suite.instrumentation", return_value=[]),
                    patch("tools.performance_suite.provenance", return_value={}),
                ):
                    self.assertFalse(run([1, 2], 1, 0, 1, 0, directory, invoke=invoke))
                result = json.loads((directory / "summary.json").read_text())
                self.assertFalse(result["passed"])
                self.assertEqual(len(result["phases"]), 1)
                self.assertEqual(
                    (directory / result["phases"][0]["path"] / "worker.log").read_text(),
                    "original failure\n",
                )
                self.assertTrue(all(not path.exists() for path in private_paths))
                if timeout:
                    self.assertEqual(result["phases"][0]["outcome"], "timeout")

    def test_success_requires_matching_phase_evidence_and_cleanup(self):
        for corrupt in (False, True):
            with self.subTest(corrupt=corrupt), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)

                def invoke(command, corrupt=corrupt, **_options):
                    config_path = Path(command[-1])
                    config = json.loads(config_path.read_text())
                    result = {
                        "config": {**config, "rows": 900} if corrupt else config,
                        "passed": True,
                        "measurements": {"cleanup_complete": True},
                    }
                    (config_path.parent / "summary.json").write_text(json.dumps(result))
                    return SimpleNamespace(returncode=0)

                with (
                    patch("tools.performance_suite.instrumentation", return_value=[]),
                    patch("tools.performance_suite.provenance", return_value={}),
                ):
                    if corrupt:
                        with self.assertRaises(ValueError):
                            run([1], 1, 0, 1, 0, directory, invoke=invoke)
                    else:
                        self.assertTrue(run([1], 1, 0, 1, 0, directory, invoke=invoke))

    def test_source_changes_invalidate_a_long_running_measurement(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch("tools.performance_suite.instrumentation", return_value=[]),
            patch("tools.performance_suite.provenance", side_effect=[{}, {"changed": True}]),
        ):
            directory = Path(temporary)
            with self.assertRaisesRegex(ValueError, "source changed"):
                run([1], 1, 0, 1, 0, directory)
            self.assertFalse(json.loads((directory / "summary.json").read_text())["passed"])

    def test_ledger_seed_is_replayable_and_money_oracle_detects_corruption(self):
        first, second = Workload(8, 7), Workload(8, 7)
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        self.assertEqual(first.input_sha256, second.input_sha256)
        before = first.counts()
        observed = first.report()
        self.assertEqual(first.counts(), before)
        observed["total"]["known_subtotals"]["USD"] = "0"
        with self.assertRaises(RuntimeError):
            first.validate(observed)

    def test_worker_installs_the_network_guard_and_records_its_result(self):
        import socket
        from tools.performance_suite import worker

        def guarded(_config):
            with self.assertRaises(AssertionError):
                socket.create_connection(("203.0.113.1", 443), timeout=0.01)
            return {"cleanup_complete": True}

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            config = {
                "kind": "scale",
                "rows": 1,
                "seed": 1,
                "samples": 1,
                "seconds": 0,
                "concurrency": 1,
            }
            with (
                patch("tools.performance_suite.instrumentation", return_value=[]),
                patch("tools.performance_scenarios.scale", side_effect=guarded),
            ):
                worker(config, directory)
            self.assertTrue(json.loads((directory / "summary.json").read_text())["passed"])


class PerformanceHTTPTests(unittest.TestCase):
    def test_real_operator_exports_polling_writer_progress_and_cleanup(self):
        from tools.performance_scenarios import scale, soak

        config = {"rows": 12, "seed": 7, "samples": 1, "seconds": 0, "concurrency": 2}
        measured = scale(config)
        self.assertTrue(measured["cleanup_complete"])
        self.assertEqual(measured["probes"]["model_runner_calls"], 0)
        self.assertEqual(measured["timings"]["csv_export"]["count"], 1)
        with tempfile.TemporaryDirectory() as temporary:
            sustained = soak(config, Path(temporary))
            self.assertTrue(sustained["cleanup_complete"])
            self.assertEqual(sustained["cycles"], 2)
            self.assertEqual(sustained["completed_navigation_cycles"], 4)
            self.assertGreater(sustained["invariants"]["writer_commits"], 0)
            self.assertEqual(sustained["probes"]["unexpected_requests"], 0)
            self.assertEqual(len((Path(temporary) / "samples.jsonl").read_text().splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
