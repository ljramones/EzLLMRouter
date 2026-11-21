"""Record test identities, outcomes and durations without exception payloads."""

from __future__ import annotations

from collections.abc import Sequence
import json
import os
from pathlib import Path
import sys
import time
from typing import Any
import unittest
import uuid


def _write_json(path: Path, payload: object) -> None:
    temporary = path.with_name(".pending-" + uuid.uuid4().hex)
    temporary.write_text(json.dumps(payload, indent=2) + "\n")
    temporary.replace(path)


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
        self._outcome(test, "failed")
        super().addFailure(test, err)

    def addError(self, test: unittest.TestCase, err: Any) -> None:
        self._outcome(test, "error")
        super().addError(test, err)

    def addSkip(self, test: unittest.TestCase, reason: str) -> None:
        self._outcome(test, "skipped")
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

    def _outcome(self, test: unittest.TestCase, outcome: str) -> None:
        identity = test.id()
        if identity in self.started:
            self.outcomes[identity] = outcome
        else:
            # unittest uses _ErrorHolder for module/class fixtures and never
            # calls startTest/stopTest. Its duration is in the module total.
            self.observations.append(
                {"test": identity, "seconds": None, "outcome": outcome, "phase": "fixture"}
            )


def instrumentation() -> list[str]:
    return [
        name
        for name, enabled in (
            ("coverage", os.environ.get("EZLLMROUTER_TEST_COVERAGE")),
            ("lock_audit", os.environ.get("EZLLMROUTER_LOCK_AUDIT")),
            ("javascript_coverage", os.environ.get("EZLLMROUTER_JS_COVERAGE")),
            ("v8_coverage", os.environ.get("NODE_V8_COVERAGE")),
        )
        if enabled
    ]


def write_result(
    name: str,
    result: TimedResult,
    seconds: float,
    directory: str | None,
    *,
    loopback: bool = False,
    audit_violations: Sequence[dict[str, object]] = (),
    instruments: Sequence[str] | None = None,
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
        "instrumentation": list(instruments) if instruments is not None else instrumentation(),
        "invocation": os.environ.get("EZLLMROUTER_TEST_INVOCATION"),
    }
    payload["outcome"] = "passed" if payload["passed"] else "failed"
    _write_json(output / f"module-{uuid.uuid4().hex}.json", payload)


def write_module_failure(
    name: str,
    seconds: float,
    outcome: str,
    directory: str | None,
    *,
    loopback: bool = False,
    invocation: str | None = None,
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
        "tests_run": 0,
        "skipped": 0,
        "passed": False,
        "outcome": outcome,
        "instrumentation": instrumentation(),
        "invocation": invocation or os.environ.get("EZLLMROUTER_TEST_INVOCATION"),
        "audit_violations": [],
        "tests": [{"test": name, "seconds": None, "outcome": outcome, "phase": "module"}],
    }
    _write_json(output / f"module-{uuid.uuid4().hex}.json", payload)


def has_failed_invocation(directory: str | None, invocation: str) -> bool:
    if not directory:
        return False
    for path in Path(directory).glob("module-*.json"):
        try:
            row = json.loads(path.read_text())
            if row.get("invocation") == invocation and row.get("passed") is False:
                return True
        except (OSError, ValueError):
            continue
    return False


def write_script_result(
    name: str, seconds: float, passed: bool, directory: str | None, instruments: Sequence[str]
) -> None:
    if not directory:
        return
    output = Path(directory)
    output.mkdir(parents=True, exist_ok=True)
    row = {
        "module": "script:" + name,
        "tier": "offline",
        "kind": "script",
        "seconds": seconds,
        "passed": passed,
        "outcome": "passed" if passed else "failed",
        "tests_run": 0,
        "skipped": 0,
        "tests": [],
        "audit_violations": [],
        "instrumentation": list(instruments),
        "invocation": os.environ.get("EZLLMROUTER_TEST_INVOCATION"),
    }
    _write_json(output / f"module-{uuid.uuid4().hex}.json", row)


def write_command(argv: Sequence[str], seconds: float, outcome: str, directory: str | None) -> None:
    if directory:
        output = Path(directory)
        output.mkdir(parents=True, exist_ok=True)
        _write_json(
            output / f"command-{uuid.uuid4().hex}.json",
            {"argv": list(argv), "seconds": round(seconds, 6), "outcome": outcome},
        )


def summarize(directory: Path, commands: Sequence[dict[str, object]] = ()) -> dict[str, object]:
    modules = [json.loads(path.read_text()) for path in sorted(directory.glob("module-*.json"))]
    tests: dict[str, list[dict[str, object]]] = {}
    module_outcomes: dict[str, set[str]] = {}
    for module in modules:
        if "module" in module:
            identity = module.get("tier", "offline") + ":" + module["module"]
            module_outcomes.setdefault(identity, set()).add(
                module.get("outcome", "passed" if module.get("passed") else "failed")
            )
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
        "unstable_modules": sorted(
            name for name, outcomes in module_outcomes.items() if len(outcomes) > 1
        ),
        "slowest_tests": sorted(
            (row for rows in tests.values() for row in rows),
            key=lambda row: float(str(row.get("seconds") or 0)),
            reverse=True,
        )[:30],
    }
    _write_json(directory / "summary.json", result)
    return result


def budget_errors(directory: Path, seconds: float) -> list[str]:
    """Keep slow-module moves explicit; retries never hide a failed module."""
    errors = []
    for path in sorted(directory.glob("module-*.json")):
        row = json.loads(path.read_text())
        if row.get("instrumentation"):
            continue
        if row["seconds"] > seconds:
            errors.append(f"{row['module']}: {row['seconds']}s exceeds module budget {seconds}s")
    return errors


def instability_errors(summary: dict[str, Any]) -> list[str]:
    return [
        f"{key}: {identity}"
        for key in ("unstable_tests", "unstable_modules")
        for identity in summary.get(key, [])
    ]
