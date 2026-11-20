"""Measure disposable synthetic SQLite data; never opens a service database or calls a provider."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import platform
import sqlite3
import statistics
import tempfile
import threading
import time
from types import SimpleNamespace

from ezllmrouter_server.database_audit import audit
from ezllmrouter_server.operator_projection import OperatorProjection
from ezllmrouter_server.registry import Registry
from ezllmrouter_server.repositories import registry as registry_queries
from ezllmrouter_server.repositories.store import LATEST_USAGE
from ezllmrouter_server.store import SQLiteStore, encode

ROOT = Path(__file__).resolve().parents[1]


def measured(connection, action):
    operations = 0
    statements = 0

    def progress():
        nonlocal operations
        operations += 100
        return 0

    def trace(sql):
        nonlocal statements
        if sql.lstrip().upper().startswith(("SELECT", "WITH")):
            statements += 1

    connection.set_progress_handler(progress, 100)
    connection.set_trace_callback(trace)
    started = time.perf_counter()
    try:
        result = action()
    finally:
        elapsed = time.perf_counter() - started
        connection.set_progress_handler(None, 0)
        connection.set_trace_callback(None)
    return {
        "seconds": round(elapsed, 6),
        "vm_steps_approx": operations,
        "read_statements": statements,
    }, result


def contention(stores, workers, operations, label):
    barrier = threading.Barrier(workers)

    def worker(worker_id):
        samples = []
        errors = 0
        store = stores[worker_id % len(stores)]
        barrier.wait(timeout=10)
        for i in range(operations):
            started = time.perf_counter()
            try:
                if i % 5 == 0:
                    key = f"benchmark.{label}.{worker_id}.{i}"
                    store.database.transaction(
                        lambda key=key: store.database.execute(
                            registry_queries.ACTION_INSERT_REGISTRY_META, (key, "synthetic")
                        )
                    )
                else:
                    with store.database.read():
                        store.database.execute(
                            LATEST_USAGE,
                            ("attempt.benchmark.0",),
                        ).fetchone()
            except sqlite3.OperationalError:
                errors += 1
            samples.append(time.perf_counter() - started)
        return samples, errors

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(worker, range(workers)))
    elapsed = time.perf_counter() - started
    samples = sorted(value for values, _ in results for value in values)
    return {
        "connections": len(stores),
        "workers": workers,
        "operations": len(samples),
        "write_fraction": "0.2",
        "sqlite_errors": sum(errors for _, errors in results),
        "seconds": round(elapsed, 6),
        "operations_per_second": round(len(samples) / elapsed, 1),
        "latency_ms_median": round(statistics.median(samples) * 1000, 3),
        "latency_ms_p95": round(samples[min(len(samples) - 1, int(len(samples) * 0.95))] * 1000, 3),
        "latency_ms_max": round(max(samples) * 1000, 3),
    }


def run(size, workers, operations):
    with tempfile.TemporaryDirectory(prefix="ezllmrouter-database-") as temporary:
        with closing(SQLiteStore(Path(temporary) / "synthetic.sqlite")) as store:
            authority = SimpleNamespace(gate=threading.RLock(), epoch=0)
            registry = Registry(
                store,
                authority,
                legacy_destination={
                    "configuration_ref": "cfg.synthetic",
                    "service": "synthetic",
                    "endpoint": "127.0.0.1",
                    "model": "model.synthetic",
                    "model_version": "v1",
                    "processing_region": "local",
                },
                legacy_token="synthetic-benchmark-token-never-used-for-network",
                legacy_trusted={
                    "principal_id": "svc.synthetic",
                    "charging_owner_id": "owner.local",
                },
            )
            principal = {
                "principal_id": "svc.benchmark",
                "owner": "owner.local",
                "role": "ordinary",
                "kind": "service",
                "status": "active",
            }
            store.database.transaction(
                lambda: store.database.execute(
                    registry_queries.APPLY_INSERT_REGISTRY_PRINCIPALS,
                    (principal["principal_id"], encode(principal)),
                )
            )
            dataset = "dataset.synthetic.benchmark"
            registry.integration.create_dataset(
                registry.principal("owner.local"),
                {
                    "dataset_id": dataset,
                    "platform_id": "platform.synthetic",
                    "environment_id": "environment.synthetic",
                    "owner_id": "owner.local",
                    "ingest_principal_id": principal["principal_id"],
                    "activated_at": "2026-10-01T00:00:00Z",
                },
            )
            example = json.loads(
                (
                    ROOT / "tests/fixtures/contracts/integration-readiness-v2/examples.json"
                ).read_text()
            )["events"][0]
            submissions, usages, attempts = [], [], []
            for i in range(size):
                sid, aid = f"submission.benchmark.{i}", f"attempt.benchmark.{i}"
                key = {
                    "principal_id": principal["principal_id"],
                    "task_id": "task.synthetic",
                    "step_id": f"step.{i}",
                    "step_revision": 1,
                    "execution_generation": "generation.synthetic",
                }
                record = {
                    "submission_id": sid,
                    "attempt_id": aid,
                    "principal_id": principal["principal_id"],
                    "work_key": key,
                    "submission_state": "completed",
                    "dispatch_state": "response_observed",
                    "candidate_access": "not_retained",
                    "status_revision": 1,
                }
                submissions.append(
                    (
                        sid,
                        principal["principal_id"],
                        "task.synthetic",
                        encode(key),
                        "synthetic",
                        encode(record),
                    )
                )
                for revision in (1, 2):
                    usage = {
                        "revision": revision,
                        "cost": {
                            "status": "calculated",
                            "currency": "USD",
                            "amount_decimal": "0.000000001",
                        },
                    }
                    usages.append((aid, revision, sid, encode(usage)))
                event = deepcopy(example)
                event.update(
                    dataset_id=dataset,
                    attempt_id=aid,
                    event_id=f"event.{i}",
                    context_ref=f"feature.{i}",
                )
                attempts.append((dataset, aid, event["event_id"], encode(event), 1))

            def seed():
                store.db.executemany("INSERT INTO submissions VALUES (?,?,?,?,?,?)", submissions)
                store.db.executemany("INSERT INTO usage_revisions VALUES (?,?,?,?)", usages)
                store.db.executemany(
                    "INSERT INTO integration_attempts VALUES (?,?,?,?,?)", attempts
                )

            store.database.transaction(seed)
            projection = OperatorProjection(store, principal["principal_id"])
            usage_metrics, usage = measured(store.db, projection.usage)
            incoming = deepcopy(example)
            incoming.update(
                dataset_id=dataset,
                event_id="event.incoming",
                attempt_id="attempt.incoming",
                context_ref="feature.incoming",
            )
            ingest_metrics, _ = measured(
                store.db, lambda: registry.integration.append_event(principal, incoming)
            )
            maintenance_metrics, _ = measured(store.db, registry.integration.maintain)
            result = {
                "seeded_attempts_per_domain": size,
                "usage_revisions_per_attempt": 2,
                "usage_report": {
                    **usage_metrics,
                    "returned_attempts": usage["attempts"],
                    "truncated": usage["truncated"],
                },
                "independent_attempt_ingest": ingest_metrics,
                "idle_maintenance": maintenance_metrics,
                "single_connection_contention": contention([store], workers, operations, "single"),
            }
            with closing(SQLiteStore.open_existing(Path(store.path))) as second:
                result["two_connection_contention"] = contention(
                    [store, second], workers, operations, "dual"
                )
            result["integrity_ok"] = audit(store)["ok"]
            result["database_bytes"] = sum(
                path.stat().st_size for path in Path(temporary).iterdir()
            )
            return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+", default=[1000, 10000])
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--operations-per-worker", type=int, default=200)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if any(n < 1 for n in [*args.sizes, args.workers, args.operations_per_worker]):
        parser.error("sizes, workers and operation counts must be positive")
    result = {
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "sqlite": sqlite3.sqlite_version,
        },
        "scope": "Disposable synthetic metadata, no provider or HTTP calls. Results describe this machine; they are not production capacity guarantees.",
        "runs": [run(size, args.workers, args.operations_per_worker) for size in args.sizes],
    }
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    print(rendered, end="")
    return (
        0
        if all(
            run["integrity_ok"]
            and run["single_connection_contention"]["sqlite_errors"] == 0
            and run["two_connection_contention"]["sqlite_errors"] == 0
            for run in result["runs"]
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
