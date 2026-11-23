"""Disposable synthetic ledger with an independent decimal conservation oracle."""

import copy
from decimal import Decimal
import hashlib
import json
import random
import threading
import time

from ezllmrouter_server.database import Query
from ezllmrouter_server.reporting import usage_costs
from ezllmrouter_server.store import encode
from tests.operator_console.test_reporting import ReportingTests
from .performance_metrics import Timings

COUNTS = {
    "submissions": Query("SELECT COUNT(*) FROM submissions"),
    "intents": Query("SELECT COUNT(*) FROM intents"),
    "guard_dispatches": Query("SELECT COUNT(*) FROM guard_dispatches"),
    "usage_revisions": Query("SELECT COUNT(*) FROM usage_revisions"),
}
INSERT_INTENT = Query("INSERT INTO intents VALUES (?,?,?)")
INSERT_USAGE = Query("INSERT INTO usage_revisions VALUES (?,?,?,?)")
FILTERS = {"cutoff": "2030-01-01T00:00:20Z"}
SCOPE = {"role": "registry_admin", "principal_id": "owner.local"}


class Workload:
    def __init__(self, rows, seed):
        self.fixture = ReportingTests("test_scope_before_counts_and_exports")
        self.writer_stop = threading.Event()
        self.writer = None
        self.writer_errors = []
        self.commits = 0
        self.writer_timer = Timings()
        self.rows = rows
        try:
            self.fixture.setUp()
            self.store, self.registry = self.fixture.store, self.fixture.registry
            self._seed(rows, seed)
            self.original_counts = self.counts()
        except BaseException:
            self.close()
            raise

    def _seed(self, rows, seed):
        rng = random.Random(seed)
        base = json.loads(
            self.store.database.execute(
                Query("SELECT record FROM submissions ORDER BY submission_id LIMIT 1")
            ).fetchone()[0]
        )
        self.cents = 0
        checksum = hashlib.sha256()

        def seed_rows():
            for index in range(rows):
                record = copy.deepcopy(base)
                identifier = "attempt.performance." + str(index)
                record.update(
                    attempt_id=identifier,
                    submission_id="submission." + identifier,
                    synthetic_padding="x" * 2048,
                )
                record["work_key"]["step_id"] = "step.performance." + str(index)
                record["work_digest"] = "sha256:" + hashlib.sha256(identifier.encode()).hexdigest()
                self.store.create(record)
                destination = {
                    "service": "synthetic",
                    "model": "model.performance." + str(rng.randrange(16)),
                    "connection_id": "connection.performance",
                    "configuration_ref": "configuration.performance",
                }
                self.store.database.execute(
                    INSERT_INTENT,
                    (identifier, record["submission_id"], encode({"destination": destination})),
                )
                cents = rng.randrange(1, 10)
                self.cents += cents
                usage = {
                    "attempt_id": identifier,
                    "revision": 1,
                    "recorded_at": "2030-01-01T00:00:19Z",
                    "normalized_usage": {},
                    "cost": {
                        "status": "calculated",
                        "currency": "USD",
                        "amount_decimal": str(Decimal(cents) / 100),
                        "source_ref": "synthetic.performance",
                    },
                }
                raw = encode(usage)
                self.store.database.execute(
                    INSERT_USAGE, (identifier, 1, record["submission_id"], raw)
                )
                checksum.update((encode(record) + raw + encode(destination)).encode())
                if index == 0:
                    self.writer_usage = usage
                    self.writer_submission = record["submission_id"]

        self.store.database.transaction(seed_rows)
        self.input_sha256 = checksum.hexdigest()

    def counts(self):
        with self.store.database.read():
            return {
                name: self.store.database.execute(query).fetchone()[0]
                for name, query in COUNTS.items()
            }

    def report(self):
        report = usage_costs(self.registry, SCOPE, FILTERS, attempt_limit=10)
        self.validate(report)
        return report

    def validate(self, report):
        expected = {"EUR": Decimal(4), "USD": Decimal(32) + Decimal(self.cents) / 100}
        actual = {
            currency: Decimal(value)
            for currency, value in report["total"]["known_subtotals"].items()
        }
        if actual != expected or report["total"]["attempts"] != self.rows + 10:
            raise RuntimeError("performance report lost accounting conservation")
        if (
            len(report["attempts"]) != min(10, self.rows + 10)
            or report["attempt_pagination"]["total"] != self.rows + 10
        ):
            raise RuntimeError("performance report pagination mismatch")

    def start_writer(self):
        def write():
            while not self.writer_stop.is_set():
                started = time.perf_counter()
                try:
                    revision = self.commits + 2
                    usage = {**self.writer_usage, "revision": revision}
                    self.store.database.transaction(
                        lambda usage=usage, revision=revision: self.store.database.execute(
                            INSERT_USAGE,
                            (usage["attempt_id"], revision, self.writer_submission, encode(usage)),
                        )
                    )
                    self.commits += 1
                    self.writer_timer.add(time.perf_counter() - started)
                except Exception as error:
                    self.writer_errors.append(type(error).__name__)
                    return
                self.writer_stop.wait(0.1)

        self.writer = threading.Thread(
            target=write, name="ezllmrouter-performance-writer", daemon=True
        )
        self.writer.start()

    def stop_writer(self):
        self.writer_stop.set()
        if self.writer:
            self.writer.join(10)
            if self.writer.is_alive():
                raise RuntimeError("performance writer failed to stop")

    def verify(self):
        self.stop_writer()
        after = self.counts()
        expected = dict(self.original_counts)
        expected["usage_revisions"] += self.commits
        if self.writer_errors or after != expected:
            raise RuntimeError("performance workload changed execution counts or lost writes")
        self.report()
        return {
            "before": self.original_counts,
            "after": after,
            "writer_commits": self.commits,
            "writer_errors": self.writer_errors,
            "writer_transaction_latency": self.writer_timer.report() if self.commits else None,
        }

    def close(self):
        try:
            self.stop_writer()
        finally:
            if not self.fixture.doCleanups():
                raise RuntimeError("performance fixture cleanup failed")
