"""Bounded deterministic reduction of synthetic traces, stopping at first divergence."""

import json
import os
from pathlib import Path
import uuid

from tools import artifact_runs
from tests.json_shrinking import minimize


class Divergence(AssertionError):
    def __init__(self, rule, expected, actual):
        self.rule, self.index = rule, 0
        super().__init__(f"{rule}: expected {expected!r}, observed {actual!r}")


def equal(rule, expected, actual):
    if expected != actual:
        raise Divergence(rule, expected, actual)


def reduce_trace(steps, fails, budget=48, stats=None):
    """Retain a nonempty trace with the same invariant, within one replay budget."""
    return minimize(steps, lambda trial: bool(trial) and fails(trial), budget, stats)


def run_trace(name, seed, steps, execute):
    try:
        execute(steps)
        return
    except Divergence as error:
        failure = error

    def reproduces(candidate):
        try:
            execute(candidate)
        except Divergence as error:
            return error.rule == failure.rule
        except Exception:
            # Simplified commands can violate their schema or setup dependencies.
            # Such candidates do not reproduce the original divergent invariant.
            return False
        return False

    prefix = steps[: failure.index + 1]
    reduction = {}
    minimized = reduce_trace(prefix, reproduces, stats=reduction)
    managed = None
    if os.environ.get("EZLLMROUTER_TEST_HEALTH"):
        root = Path(os.environ["EZLLMROUTER_TEST_HEALTH"]) / "generated-failures"
        root.mkdir(parents=True, exist_ok=True)
    else:
        managed = artifact_runs.new_run(
            Path(__file__).resolve().parents[1] / ".artifacts/test-health",
            "generated-",
            "generated",
        )
        root = managed
    path = root / (name + "-" + uuid.uuid4().hex + ".json")
    path.write_text(
        json.dumps(
            {
                "format_version": 2,
                "name": name,
                "seed": seed,
                "first_step": failure.index,
                "rule": failure.rule,
                "trace": prefix,
                "minimized": minimized,
                "reduction": reduction,
            },
            ensure_ascii=True,
            indent=2,
        )
        + "\n"
    )
    if managed:
        artifact_runs.finish_run(managed, passed=False)
    raise AssertionError(
        f"seed={seed} first_step={failure.index}: {failure}; minimized {len(prefix)} -> {len(minimized)} steps; trace={path}"
    ) from failure
