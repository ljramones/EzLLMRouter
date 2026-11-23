"""Scale measurements and bounded concurrent operator navigation with a WAL writer."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import csv
import gc
import io
import json
import math
import threading
import time
import tracemalloc

from .performance_http import OperatorFixture, REPORT_PATH
from .performance_metrics import Timings, check_cleanup, resources
from .performance_workload import Workload


def navigation(workload, operator):
    timings = {}
    reports = []
    for name, suffix in (
        ("report_http", ""),
        ("json_export", "&export=json"),
        ("csv_export", "&export=csv"),
    ):
        started = time.perf_counter()
        raw, _ = operator.request("GET", REPORT_PATH + suffix)
        timings[name] = time.perf_counter() - started
        if name == "csv_export":
            rows = list(csv.DictReader(io.StringIO(raw.decode())))
            if [row["attempt_id"] for row in rows] != [
                row["attempt_id"] for row in reports[0]["attempts"]
            ]:
                raise RuntimeError("performance CSV export lost page parity")
        else:
            report = json.loads(raw)
            workload.validate(report)
            reports.append(report)
    if reports[0]["total"] != reports[1]["total"]:
        raise RuntimeError("performance JSON export lost total parity")
    started = time.perf_counter()
    for path in ("/", "/operator/v1/session", "/operator/v1/local-connectors"):
        operator.request("GET", path)
    timings["navigation_reads"] = time.perf_counter() - started
    started = time.perf_counter()
    operator.poll()
    timings["connector_poll"] = time.perf_counter() - started
    return timings


def cleanup_threads(before):
    deadline = time.monotonic() + 5
    for thread in threading.enumerate():
        if thread not in before:
            thread.join(max(0, deadline - time.monotonic()))


def scale(config):
    before_threads = set(threading.enumerate())
    before = resources()
    with ExitStack() as stack:
        workload = Workload(config["rows"], config["seed"])
        stack.callback(workload.close)
        operator = OperatorFixture(workload)
        stack.callback(operator.close)
        workload.report()
        navigation(workload, operator)
        metrics = {}
        cpu_start = resources()["cpu_seconds"]
        for _ in range(config["samples"]):
            started = time.perf_counter()
            workload.report()
            values = {
                "report_direct": time.perf_counter() - started,
                **navigation(workload, operator),
            }
            for name, seconds in values.items():
                metrics.setdefault(name, Timings()).add(seconds)
        cpu_seconds = resources()["cpu_seconds"] - cpu_start
        gc.collect()
        tracemalloc.start()
        try:
            workload.report()
            heap_peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        result = {
            "rows_added": config["rows"],
            "seeded_input_sha256": workload.input_sha256,
            "timings": {name: timer.report() for name, timer in metrics.items()},
            "timing_instrumentation": [],
            "cpu_seconds": cpu_seconds,
            "separate_report_python_peak_bytes": heap_peak,
            "memory_scope": "Process Python allocations during one additional report; background operator threads are present",
            "invariants": workload.verify(),
            "probes": operator.verify(),
        }
    cleanup_threads(before_threads)
    after = resources()
    check_cleanup(before_threads, before["file_descriptors"], after)
    return {**result, "after_cleanup": after, "cleanup_complete": True}


def soak(config, output):
    before_threads = set(threading.enumerate())
    before = resources()
    metrics = {}
    cycles = 0
    with ExitStack() as stack:
        workload = Workload(config["rows"], config["seed"])
        stack.callback(workload.close)
        operator = OperatorFixture(workload)
        stack.callback(operator.close)
        navigation(workload, operator)
        operator.drain()
        workload.start_writer()
        executor = stack.enter_context(
            ThreadPoolExecutor(
                max_workers=config["concurrency"],
                thread_name_prefix="ezllmrouter-performance-client",
            )
        )
        tracemalloc.start()
        stack.callback(tracemalloc.stop)
        gc.collect()
        started = time.monotonic()
        first, last = resources(), None
        peak_heap = first["python_traced_current_bytes"]
        peak_threads, peak_descriptors = first["threads"], first["file_descriptors"]
        with (output / "samples.jsonl").open("x") as log:
            while cycles < 2 or time.monotonic() - started < config["seconds"]:
                futures = [
                    executor.submit(navigation, workload, operator)
                    for _ in range(config["concurrency"])
                ]
                for future in futures:
                    for name, seconds in future.result(timeout=90).items():
                        metrics.setdefault(name, Timings()).add(seconds)
                cycles += 1
                last = resources()
                peak_heap = max(peak_heap, last["python_traced_current_bytes"])
                peak_threads = max(peak_threads, last["threads"])
                if last["file_descriptors"] is not None:
                    peak_descriptors = max(peak_descriptors or 0, last["file_descriptors"])
                log.write(
                    json.dumps(
                        {
                            "cycle": cycles,
                            "elapsed_seconds": time.monotonic() - started,
                            "writer_commits": workload.commits,
                            "resources": last,
                        }
                    )
                    + "\n"
                )
                log.flush()
                time.sleep(0.1)
        elapsed = time.monotonic() - started
        invariants = workload.verify()
        if not workload.commits or workload.writer_errors:
            raise RuntimeError("performance writer made no progress")
        probes = operator.verify()
        if probes["metadata_gets"] > math.ceil(elapsed / 2) + 2:
            raise RuntimeError("performance polling bypassed probe coalescing")
        result = {
            "rows_added": config["rows"],
            "seeded_input_sha256": workload.input_sha256,
            "requested_seconds": config["seconds"],
            "elapsed_seconds": elapsed,
            "cycles": cycles,
            "concurrency": config["concurrency"],
            "completed_navigation_cycles": cycles * config["concurrency"],
            "navigation_cycles_per_second": cycles * config["concurrency"] / elapsed,
            "timings": {name: timer.report() for name, timer in metrics.items()},
            "timing_instrumentation": ["tracemalloc"],
            "resource_first": first,
            "resource_last": last,
            "sampled_python_current_peak_bytes": peak_heap,
            "python_traced_current_growth_bytes": last["python_traced_current_bytes"]
            - first["python_traced_current_bytes"],
            "cpu_seconds": last["cpu_seconds"] - first["cpu_seconds"],
            "sampled_peak_threads": peak_threads,
            "sampled_peak_file_descriptors": peak_descriptors,
            "invariants": invariants,
            "probes": probes,
            "memory_limit": "Observational baseline; no long-term heap/RSS growth budget approved",
        }
    cleanup_threads(before_threads)
    after = resources()
    check_cleanup(before_threads, before["file_descriptors"], after)
    return {**result, "after_cleanup": after, "cleanup_complete": True}
