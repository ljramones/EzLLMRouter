"""Report projection, cursor ownership and concurrent-writer regressions."""

from contextlib import contextmanager
import sqlite3
import copy
import gc
import tracemalloc
import json
import threading
import unittest
from unittest.mock import patch

from ezllmrouter_server.database import Database, Query
from ezllmrouter_server import reporting
from ezllmrouter_server.repositories import reporting as queries
from ezllmrouter_server.store import encode
from tests.operator_console import test_reporting as support


class StreamingReportTests(unittest.TestCase):
    def setUp(self):
        self.fixture = support.ReportingTests("test_scope_before_counts_and_exports")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store = self.fixture.store

    def test_only_small_single_attempt_projections_reach_python(self):
        payload = "unrelated-private-marker" * 8192
        for sid, raw in self.store.db.execute("SELECT submission_id,record FROM submissions"):
            record = json.loads(raw)
            record["unrelated_private_content"] = payload
            self.store.db.execute(
                "UPDATE submissions SET record=? WHERE submission_id=?", (encode(record), sid)
            )
        for aid, revision, raw in self.store.db.execute(
            "SELECT attempt_id,revision,usage FROM usage_revisions"
        ):
            usage = json.loads(raw)
            usage["unrelated_provider_response"] = payload
            self.store.db.execute(
                "UPDATE usage_revisions SET usage=? WHERE attempt_id=? AND revision=?",
                (encode(usage), aid, revision),
            )
        decode = reporting._visible_attempts
        execute = Database.execute
        observed = []

        def decode_projection(connections, cutoff, latest, raw, scope):
            self.assertEqual(len(raw), 1)
            for record, intent in raw:
                self.assertNotIn("unrelated_private_content", record)
                self.assertLess(len(record), 8192)
                self.assertLess(len(intent or ""), 8192)
            for usage in latest.values():
                self.assertNotIn("unrelated_provider_response", usage)
            observed.append(1)
            return decode(connections, cutoff, latest, raw, scope)

        def bounded_execute(database, query, parameters=()):
            self.assertNotIn(
                query,
                (
                    queries.USAGE_COSTS_SELECT_SUBMISSIONS,
                    queries.USAGE_COSTS_SELECT_USAGE_REVISIONS,
                ),
            )
            return execute(database, query, parameters)

        with (
            patch.object(reporting, "_visible_attempts", decode_projection),
            patch.object(Database, "execute", bounded_execute),
        ):
            result = reporting.usage_costs(
                self.fixture.registry,
                {"role": "registry_admin", "principal_id": "owner.local"},
                {"cutoff": "2030-01-01T00:00:20Z"},
                attempt_page=2,
                attempt_limit=3,
            )
        self.assertEqual(len(observed), len(support.FIXTURE["attempts"]))
        self.assertEqual(
            [row["attempt_id"] for row in result["attempts"]],
            [row["id"] for row in support.FIXTURE["attempts"]][3:6],
        )
        self.assertEqual(result["total"]["known_subtotals"], {"EUR": "4", "USD": "32"})
        self.assertEqual(result["attempt_pagination"]["total"], 10)

    def test_input_memory_stays_bounded_as_same_group_attempts_grow(self):
        self.fixture.report()  # Import/warm both projection and timestamp parsing.
        base = json.loads(
            self.store.db.execute("SELECT record FROM submissions LIMIT 1").fetchone()[0]
        )
        peaks = []
        previous = 0
        for count in (100, 1000):

            def create(previous=previous, count=count):
                for index in range(previous, count):
                    record = copy.deepcopy(base)
                    identifier = "memory." + str(index)
                    record.update(
                        attempt_id=identifier,
                        submission_id="submission." + identifier,
                        unrelated_private_content="x" * 2048,
                    )
                    record["work_key"]["step_id"] = "step." + identifier
                    record["work_digest"] = "sha256:" + str(index).zfill(64)
                    self.store.create(record)

            self.store.database.transaction(create)
            previous = count
            gc.collect()
            tracemalloc.start()
            try:
                result = reporting.usage_costs(
                    self.fixture.registry,
                    {"role": "registry_admin", "principal_id": "owner.local"},
                    {"cutoff": "2030-01-01T00:00:20Z"},
                    attempt_limit=3,
                )
                peaks.append(tracemalloc.get_traced_memory()[1])
            finally:
                tracemalloc.stop()
            self.assertEqual(result["total"]["attempts"], count + 10)
            self.assertEqual(len(result["attempts"]), 3)
        self.assertLess(peaks[1], peaks[0] * 3 + 100000)

    def test_zero_token_coverage_and_twenty_sample_latency_survive_aggregation(self):
        root = json.loads(
            self.store.db.execute(
                "SELECT record FROM attribution_runs WHERE id='run.root'"
            ).fetchone()[0]
        )
        for index in range(20):
            run = {
                **root,
                "run_id": "run.metrics." + str(index),
                "root_run_id": "run.metrics." + str(index),
                "terminal_at": "2030-01-01T00:00:" + str(index + 10) + "Z",
            }
            self.store.db.execute(
                "INSERT INTO attribution_runs VALUES (?,?)", (run["run_id"], encode(run))
            )
            event = {
                "kind": "task_outcome",
                "run_id": run["run_id"],
                "verdict": "accepted",
                "evaluator_version": run["evaluation_ref"],
                "subject_revision": 1,
            }
            self.store.db.execute(
                "INSERT INTO attribution_outcomes VALUES (?,?,?,?,?,?,?,?)",
                (
                    "evaluator.fixture",
                    "event." + run["run_id"],
                    encode([run["run_id"], "task_outcome"]),
                    1,
                    "digest.fixture",
                    encode(event),
                    "2030-01-01T00:00:35Z",
                    "{}",
                ),
            )
        for aid, revision, raw in self.store.db.execute(
            "SELECT attempt_id,revision,usage FROM usage_revisions"
        ):
            usage = json.loads(raw)
            usage["normalized_usage"] = {
                "input_uncached": {"count": 0},
                "output_text": {"count": 0},
            }
            self.store.db.execute(
                "UPDATE usage_revisions SET usage=? WHERE attempt_id=? AND revision=?",
                (encode(usage), aid, revision),
            )
        result = self.fixture.report({"cutoff": "2030-01-01T00:01:00Z"})
        cohort = next(row for row in result["cohorts"] if row["task_class"] == "fixture.workflow")
        metrics = cohort["performance"]
        self.assertEqual(metrics["latency_accepted_samples"], 20)
        self.assertEqual(metrics["median_seconds_to_accepted"], 19.5)
        self.assertEqual(metrics["p95_seconds_to_accepted"], 28)
        self.assertEqual(metrics["tokens_per_accepted_task"], {"input": "0", "output": "0"})
        self.assertEqual(metrics["token_coverage_attempts"], 6)
        aid = self.store.db.execute(
            "SELECT attempt_id FROM usage_revisions ORDER BY attempt_id LIMIT 1"
        ).fetchone()[0]
        self.store.db.execute(
            "UPDATE usage_revisions SET usage=json_set(usage,'$.normalized_usage.input_uncached.count',json('true')) WHERE attempt_id=?",
            (aid,),
        )
        changed = self.fixture.report({"cutoff": "2030-01-01T00:01:00Z"})
        metrics = next(
            row for row in changed["cohorts"] if row["task_class"] == "fixture.workflow"
        )["performance"]
        self.assertIsNone(metrics["tokens_per_accepted_task"])
        self.assertEqual(metrics["token_coverage_attempts"], 5)

    def test_consumer_failure_closes_the_cursor_before_releasing_the_snapshot(self):
        from ezllmrouter_server.reporting_stream import Accumulator

        stream = Database.stream
        closed = []
        original = ValueError("injected aggregation failure")

        @contextmanager
        def observed_stream(database, query, parameters=()):
            try:
                with stream(database, query, parameters) as rows:
                    yield rows
            finally:
                with self.assertRaises(sqlite3.ProgrammingError):
                    next(rows)
                closed.append(True)

        with (
            patch.object(Database, "stream", observed_stream),
            patch.object(Accumulator, "add", side_effect=original),
            self.assertRaises(ValueError) as caught,
        ):
            self.fixture.report()
        self.assertIs(caught.exception, original)
        self.assertEqual(closed, [True])
        self.assertEqual(self.fixture.report()["total"]["attempts"], 10)

    def test_writer_commits_while_projection_runs_and_snapshot_stays_consistent(self):
        before = self.fixture.report()
        decode = reporting._visible_attempts
        written = threading.Event()
        failures = []
        started = False

        def write_revision():
            try:
                self.store.database.transaction(
                    lambda: self.store.database.execute(
                        Query("INSERT INTO usage_revisions VALUES (?,?,?,?)"),
                        (
                            "a01",
                            99,
                            "submission.a01",
                            encode(
                                {
                                    "attempt_id": "a01",
                                    "revision": 99,
                                    "recorded_at": "2030-01-01T00:00:19Z",
                                    "cost": {
                                        "status": "calculated",
                                        "currency": "USD",
                                        "amount_decimal": "999",
                                    },
                                    "normalized_usage": {},
                                }
                            ),
                        ),
                    )
                )
            except Exception as exc:
                failures.append(exc)
            finally:
                written.set()

        def decode_with_writer(*args):
            nonlocal started
            if not started:
                started = True
                writer = threading.Thread(target=write_revision)
                writer.start()
                try:
                    self.assertTrue(written.wait(2), "report stream blocked a metadata writer")
                finally:
                    writer.join(2)
                self.assertFalse(writer.is_alive())
                self.assertEqual(failures, [])
            return decode(*args)

        with patch.object(reporting, "_visible_attempts", decode_with_writer):
            during = self.fixture.report()
        self.assertEqual(during, before)
        after = self.fixture.report()
        self.assertNotEqual(after["total"], before["total"])


if __name__ == "__main__":
    unittest.main()
