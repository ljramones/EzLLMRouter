"""Own fresh tier measurements, reviewed budgets and combined Python reports."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .coverage_reports import gaps, merge_baselines, merge_summaries, regressions, render

ROOT = Path(__file__).resolve().parents[1]


def prepare(directory: Path | None, tier: str) -> Path:
    if directory is None:
        parent = ROOT / ".artifacts/coverage"
        parent.mkdir(parents=True, exist_ok=True)
        directory = Path(tempfile.mkdtemp(prefix=f"python-{tier}-", dir=parent))
    else:
        directory = directory.resolve()
        directory.mkdir(parents=True, exist_ok=True)
        if any(directory.iterdir()):
            raise ValueError("coverage output must be fresh and empty: " + str(directory))
    os.environ["EZLLMROUTER_TEST_COVERAGE"] = str(directory)
    javascript = directory / "javascript"
    javascript.mkdir()
    os.environ["EZLLMROUTER_JS_COVERAGE"] = str(javascript)
    return directory


def baseline_for_tier(tier: str) -> dict[str, Any]:
    filename = "coverage_budget_http.json" if tier == "http" else "coverage_budget.json"
    baseline: dict[str, Any] = json.loads((ROOT / "tools" / filename).read_text())
    if tier == "combined":
        baseline = merge_baselines(baseline, baseline_for_tier("http"))
    return baseline


def finish(directory: Path, tier: str, *, enforce: bool, merge: Path | None) -> list[str]:
    from .test_coverage import report

    summary = report(directory)
    summary["tier"] = tier
    (directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    policy = json.loads((ROOT / "tools/coverage_policy.json").read_text())
    render(summary, directory, policy)
    errors = regressions(summary, baseline_for_tier(tier)) if enforce else []
    critical_summary = summary
    if merge is not None:
        previous = json.loads((merge / "summary.json").read_text())
        if previous.get("tier") != "offline" or tier != "http":
            raise ValueError("coverage merging requires an offline report and a fresh HTTP run")
        critical_summary = merge_summaries(previous, summary)
        combined = directory / "combined"
        combined.mkdir()
        (combined / "summary.json").write_text(json.dumps(critical_summary, indent=2) + "\n")
        render(critical_summary, combined, policy)
        print(
            f"Combined Python line coverage: {critical_summary['percent']}%; {combined}/summary.json",
            flush=True,
        )
    critical_policy = policy
    if tier == "http" and merge is None:
        critical_policy = {"critical": policy.get("critical_http", [])}
    if enforce and gaps(critical_summary, critical_policy):
        errors.append("critical conditional exits remain uncovered")
    if tier != "http":
        errors.extend(javascript_errors(directory / "javascript", enforce=enforce))
    print(
        f"Python {tier} line coverage: {summary['percent']}% ({summary['executed']}/{summary['executable']}); {directory}/summary.json",
        flush=True,
    )
    return errors


def javascript_errors(directory: Path, *, enforce: bool) -> list[str]:
    from .javascript_coverage import budgets, budget_errors, report

    summary = report(directory)
    if not enforce:
        return []
    baseline = json.loads((ROOT / "tools/javascript_coverage_budget.json").read_text())
    return budget_errors(budgets(summary, "console"), baseline["console"])
