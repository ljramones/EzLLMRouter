"""Measure synthetic operator scale and soak in disposable, bounded subprocesses."""

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

from .performance_metrics import instrumentation

ROOT = Path(__file__).resolve().parents[1]


def validate(sizes, samples, seconds, concurrency, seed):
    if (
        not sizes
        or len(sizes) > 8
        or len(set(sizes)) != len(sizes)
        or any(type(n) is not int or not 1 <= n <= 100_000 for n in sizes)
    ):
        raise ValueError("performance sizes must be 1 to 100000, unique, at most eight")
    for name, value, minimum, maximum in (
        ("samples", samples, 1, 100),
        ("seconds", seconds, 0, 1800),
        ("concurrency", concurrency, 1, 4),
        ("seed", seed, 0, 2**63 - 1),
    ):
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError("invalid performance " + name)


def provenance():
    git = shutil.which("git")
    if git is None:
        raise ValueError("Git is required for performance source identity")
    paths = {
        path
        for directory in (ROOT / "server/src", ROOT / "clients/python/src")
        for path in directory.rglob("*")
        if path.suffix in {".py", ".json"}
    }
    paths.update((ROOT / "tools").glob("performance_*.py"))
    paths.update(
        ROOT / name
        for name in (
            "uv.lock",
            "pyproject.toml",
            ".python-version",
            ".github/requirements-bootstrap.lock",
            "tools/test_network.py",
            "tools/test_child.py",
            "tools/artifact_runs.py",
            "tests/operator_console/test_reporting.py",
            "tests/operator_console/dev09_accounting_fixture.json",
            ".github/workflows/performance.yml",
        )
    )
    if any(path.is_symlink() or not path.is_file() for path in paths):
        raise ValueError("performance source must be regular files")
    return {
        "source_commit": subprocess.check_output(
            [git, "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=15
        ).strip(),
        "source_dirty": bool(
            subprocess.check_output(
                [git, "status", "--porcelain"], cwd=ROOT, text=True, timeout=15
            ).strip()
        ),
        "source_sha256": {
            path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(paths)
        },
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "sqlite": sqlite3.sqlite_version,
        "instrumentation": instrumentation(),
    }


def worker(config, directory):
    from .performance_scenarios import scale, soak
    from .test_network import block_network

    validate(
        [config["rows"]],
        config["samples"],
        config["seconds"],
        config["concurrency"],
        config["seed"],
    )
    if config["kind"] not in {"scale", "soak"} or instrumentation():
        raise ValueError("invalid or instrumented performance worker")
    result = {"format": "ezllmrouter-performance-phase-v1", "config": config, "passed": False}
    started = time.monotonic()
    try:
        with ExitStack() as network:
            block_network(network, loopback=True)
            result["measurements"] = (
                scale(config) if config["kind"] == "scale" else soak(config, directory)
            )
        result["passed"] = True
    except BaseException as error:
        result["error_type"] = type(error).__name__
        raise
    finally:
        result["wall_seconds"] = time.monotonic() - started
        (directory / "summary.json").write_text(json.dumps(result, indent=2) + "\n")


def run(sizes, samples, seconds, concurrency, seed, directory, *, invoke=subprocess.run):
    validate(sizes, samples, seconds, concurrency, seed)
    if instrumentation():
        raise ValueError("performance baselines require an uninstrumented interpreter")
    source = provenance()
    phases = [{"kind": "scale", "rows": size} for size in sizes] + [
        {"kind": "soak", "rows": max(sizes)}
    ]
    summary = {
        "format": "ezllmrouter-performance-v1",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "provenance": source,
        "seed": seed,
        "phases": [],
        "passed": False,
        "timing_budgets_enforced": False,
        "limits": [
            "Synthetic loopback operator HTTP and metadata probes; no browser render or model inference measurements",
            "Initial timing, CPU, RSS and heap observations do not approve production SLOs or long-term growth budgets",
            "Percentiles use nearest rank over at most the last 2048 observations per operation",
            "RSS is a process high-water mark; periodic heap observations and cleanup checks have separate meanings",
        ],
    }
    try:
        for index, phase in enumerate(phases):
            target = directory / f"{index:02d}-{phase['kind']}-{phase['rows']}"
            target.mkdir()
            config = {
                **phase,
                "samples": samples,
                "seconds": seconds,
                "concurrency": concurrency,
                "seed": seed,
            }
            (target / "config.json").write_text(json.dumps(config, indent=2) + "\n")
            record = {"path": target.name, "config": config, "passed": False}
            summary["phases"].append(record)
            try:
                if provenance() != source:
                    raise ValueError("performance source changed during the run")
                # The parent owns all temporary databases, credentials and keys,
                # including cleanup after a worker timeout or abrupt exit.
                with (
                    tempfile.TemporaryDirectory(prefix="ezllmrouter-performance-") as private,
                    (target / "worker.log").open("x") as log,
                ):
                    result = invoke(
                        [
                            sys.executable,
                            "-B",
                            "-m",
                            "tools.performance_suite",
                            "--worker-config",
                            str(target / "config.json"),
                        ],
                        cwd=ROOT,
                        env={**os.environ, "TMPDIR": private},
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        timeout=max(120, seconds + 90) if phase["kind"] == "soak" else 120,
                        check=False,
                    )
                record["returncode"] = result.returncode
                if result.returncode:
                    return False
                measured = json.loads((target / "summary.json").read_text())
                if (
                    measured.get("config") != config
                    or measured.get("passed") is not True
                    or measured["measurements"].get("cleanup_complete") is not True
                ):
                    raise ValueError("missing or mismatched performance phase evidence")
                record.update(
                    passed=True,
                    summary_sha256=hashlib.sha256(
                        (target / "summary.json").read_bytes()
                    ).hexdigest(),
                )
                if provenance() != source:
                    raise ValueError("performance source changed during the run")
            except subprocess.TimeoutExpired:
                record["outcome"] = "timeout"
                return False
        summary["passed"] = True
        return True
    finally:
        (directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+", default=[1000, 10000])
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--soak-seconds", type=int, default=300)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20261123)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker-config", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker_config:
        config = json.loads(args.worker_config.read_text())
        worker(config, args.worker_config.parent)
        return 0
    from .artifact_runs import new_run, session

    with session() as artifacts:
        validate(args.sizes, args.samples, args.soak_seconds, args.concurrency, args.seed)
        if args.output:
            args.output.mkdir(parents=True, exist_ok=False)
        else:
            args.output = new_run(ROOT / ".artifacts/performance", "run-", "performance")
        passed = run(
            args.sizes,
            args.samples,
            args.soak_seconds,
            args.concurrency,
            args.seed,
            args.output.resolve(),
        )
        artifacts.passed = passed
        print(
            "Performance workload "
            + ("passed" if passed else "failed")
            + "; "
            + str(args.output / "summary.json")
        )
        return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
