"""Record test identities, outcomes and durations without exception payloads."""

from __future__ import annotations

from collections.abc import Sequence
import json
from pathlib import Path
import sys
import time
from typing import Any
import unittest
import uuid


class TimedResult(unittest.TextTestResult):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.observations: list[dict[str, object]] = []
        self.started: dict[str, float] = {}
        self.outcomes: dict[str, str] = {}

    def startTest(self, test: unittest.TestCase) -> None:
        self.started[test.id()] = time.perf_counter()
        super().startTest(test)

    def stopTest(self, test: unittest.TestCase) -> None:
        self.observations.append(
            {
                "test": test.id(),
                "seconds": round(time.perf_counter() - self.started.pop(test.id()), 6),
                "outcome": self.outcomes.pop(test.id(), "passed"),
            }
        )
        super().stopTest(test)

    def addFailure(self, test: unittest.TestCase, err: Any) -> None:
        self.outcomes[test.id()] = "failed"
        super().addFailure(test, err)

    def addError(self, test: unittest.TestCase, err: Any) -> None:
        self.outcomes[test.id()] = "error"
        super().addError(test, err)

    def addSkip(self, test: unittest.TestCase, reason: str) -> None:
        self.outcomes[test.id()] = "skipped"
        super().addSkip(test, reason)

    def addSubTest(self, test: unittest.TestCase, subtest: unittest.TestCase, err: Any) -> None:
        if err is not None:
            self.outcomes[test.id()] = "failed"
        super().addSubTest(test, subtest, err)

    def addExpectedFailure(self, test: unittest.TestCase, err: Any) -> None:
        self.outcomes[test.id()] = "expected_failure"
        super().addExpectedFailure(test, err)

    def addUnexpectedSuccess(self, test: unittest.TestCase) -> None:
        self.outcomes[test.id()] = "unexpected_success"
        super().addUnexpectedSuccess(test)


def write_result(
    name: str,
    result: TimedResult,
    seconds: float,
    directory: str | None,
    *,
    loopback: bool = False,
    audit_violations: Sequence[dict[str, object]] = (),
) -> None:
    if not directory:
        return
    output = Path(directory)
    output.mkdir(parents=True, exist_ok=True)
    payload = {
        "module": name,
        "tier": "loopback" if loopback else "offline",
        "python": sys.version.split()[0],
        "seconds": round(seconds, 6),
        "tests_run": result.testsRun,
        "skipped": len(result.skipped),
        "passed": result.wasSuccessful()
        and result.testsRun > len(result.skipped)
        and not audit_violations,
        "audit_violations": list(audit_violations),
        "tests": result.observations,
    }
    (output / f"module-{uuid.uuid4().hex}.json").write_text(json.dumps(payload, indent=2) + "\n")


def write_command(argv: Sequence[str], seconds: float, outcome: str, directory: str | None) -> None:
    if directory:
        output = Path(directory)
        output.mkdir(parents=True, exist_ok=True)
        (output / f"command-{uuid.uuid4().hex}.json").write_text(
            json.dumps({"argv": list(argv), "seconds": round(seconds, 6), "outcome": outcome})
            + "\n"
        )


def summarize(directory: Path, commands: Sequence[dict[str, object]] = ()) -> dict[str, object]:
    modules = [json.loads(path.read_text()) for path in sorted(directory.glob("module-*.json"))]
    tests: dict[str, list[dict[str, object]]] = {}
    for module in modules:
        for observation in module["tests"]:
            tests.setdefault(module.get("tier", "offline") + ":" + observation["test"], []).append(
                observation
            )
    unstable = [name for name, rows in tests.items() if len({row["outcome"] for row in rows}) > 1]
    result: dict[str, object] = {
        "modules": modules,
        "commands": [
            *commands,
            *(json.loads(path.read_text()) for path in sorted(directory.glob("command-*.json"))),
        ],
        "unstable_tests": sorted(unstable),
        "slowest_tests": sorted(
            (row for rows in tests.values() for row in rows),
            key=lambda row: float(str(row["seconds"])),
            reverse=True,
        )[:30],
    }
    (directory / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def budget_errors(directory: Path, seconds: float) -> list[str]:
    """Keep slow-module moves explicit; retries never hide a failed module."""
    errors = []
    for path in sorted(directory.glob("module-*.json")):
        row = json.loads(path.read_text())
        if row["seconds"] > seconds:
            errors.append(f"{row['module']}: {row['seconds']}s exceeds module budget {seconds}s")
    return errors
