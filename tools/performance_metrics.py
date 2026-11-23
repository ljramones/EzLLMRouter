"""Bounded measurement buffers; timing observations do not approve budgets."""

from collections import deque
import math
import os
from pathlib import Path
import resource
import sys
import threading
import time
import tracemalloc


class Timings:
    def __init__(self):
        self.values = deque(maxlen=2048)
        self.count = 0
        self.total = 0.0

    def add(self, seconds):
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("invalid performance observation")
        self.values.append(seconds)
        self.count += 1
        self.total += seconds

    def report(self):
        ordered = sorted(self.values)
        if not ordered:
            raise ValueError("empty performance sample")
        return {
            "count": self.count,
            "total_seconds": self.total,
            "percentile_window": "last 2048 observations",
            "window_samples": len(ordered),
            **{
                f"p{p}_seconds": ordered[max(0, math.ceil(len(ordered) * p / 100) - 1)]
                for p in (50, 95, 99)
            },
            "window_max_seconds": ordered[-1],
        }


def resources():
    usage = resource.getrusage(resource.RUSAGE_SELF)
    descriptor_root = next(
        (path for path in (Path("/proc/self/fd"), Path("/dev/fd")) if path.is_dir()), None
    )
    return {
        "monotonic_seconds": time.monotonic(),
        "cpu_seconds": usage.ru_utime + usage.ru_stime,
        "rss_high_water_bytes": usage.ru_maxrss * (1 if sys.platform == "darwin" else 1024),
        "python_traced_current_bytes": tracemalloc.get_traced_memory()[0]
        if tracemalloc.is_tracing()
        else None,
        "threads": threading.active_count(),
        "file_descriptors": len(list(descriptor_root.iterdir())) if descriptor_root else None,
    }


def instrumentation():
    values = [
        name
        for name in ("EZLLMROUTER_TEST_COVERAGE", "EZLLMROUTER_LOCK_AUDIT")
        if os.environ.get(name)
    ]
    if sys.gettrace() is not None:
        values.append("sys.gettrace")
    if sys.getprofile() is not None:
        values.append("sys.getprofile")
    if tracemalloc.is_tracing():
        values.append("tracemalloc")
    values.extend(
        str(sys.monitoring.get_tool(index))
        for index in range(6)
        if sys.monitoring.get_tool(index) is not None
    )
    return values


def check_cleanup(before_threads, before_descriptors, after):
    leaked = [thread.name for thread in threading.enumerate() if thread not in before_threads]
    if leaked:
        raise RuntimeError("performance workload leaked threads: " + ", ".join(leaked))
    if before_descriptors is not None and (
        after["file_descriptors"] is None or after["file_descriptors"] > before_descriptors
    ):
        raise RuntimeError("performance workload leaked file descriptors")
