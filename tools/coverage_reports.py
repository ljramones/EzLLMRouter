"""Subsystem coverage, explicit critical gaps, HTML, and reviewed missing-code budgets."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import html
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def subsystem(path: str) -> str:
    name = Path(path).name
    if path.startswith("clients/python/"):
        return "python_client"
    if "/gateway/" in path:
        return "gateway"
    if "/operator_http/" in path or name == "operator_web.py":
        return "operator_http"
    if "/wire_http/" in path or name == "web.py":
        return "wire_http"
    if name.startswith("registry") or "/registry_mutations/" in path:
        return "registry"
    if name.startswith(("accounting", "integration_accounting", "reporting")):
        return "accounting_reports"
    if name.startswith(("secret", "provider_vault", "integration_credential", "user_management")):
        return "credentials_accounts"
    if name.startswith(("core", "store")):
        return "coordinator_persistence"
    return "shared_runtime_contracts"


def gaps(summary: Mapping[str, Any], policy: Mapping[str, Any]) -> list[dict[str, object]]:
    result = []
    for rule in policy.get("critical", []):
        path, function = rule["path"], rule["function"]
        row = summary["files"].get(path)
        if row is None:
            result.append(
                {"path": path, "function": function, "error": "missing source measurement"}
            )
            continue
        if function not in row.get("branch_functions", ()):
            result.append(
                {
                    "path": path,
                    "function": function,
                    "error": "missing critical conditional function",
                }
            )
            continue
        for branch in row["missing_branches"]:
            if branch["function"] == function:
                result.append({"path": path, **branch})
    return result


def regressions(summary: Mapping[str, Any], baseline: Mapping[str, Any]) -> list[str]:
    errors = []
    files = baseline.get("files", {})
    for path, row in summary["files"].items():
        permitted = files.get(path, {"missing_lines": 0, "missing_branches": 0})
        for key in ("missing_lines", "missing_branches"):
            if len(row[key]) > permitted[key]:
                errors.append(
                    f"{path}: {len(row[key])} {key} exceeds reviewed budget {permitted[key]}"
                )
    for path in files.keys() - summary["files"].keys():
        errors.append("missing measured library file: " + path)
    return errors


def render(
    summary: Mapping[str, Any], directory: Path, policy: Mapping[str, Any]
) -> dict[str, Any]:
    groups: dict[str, dict[str, int]] = {}
    for path, row in summary["files"].items():
        group = groups.setdefault(
            subsystem(path),
            {key: 0 for key in ("executable", "executed", "branches", "branches_executed")},
        )
        for key in group:
            group[key] += row[key]
    critical = gaps(summary, policy)
    followup = gaps(summary, {"critical": policy.get("followup_critical", [])})
    payload = {
        "scope": summary["scope"],
        "subsystems": groups,
        "critical_uncovered_branches": critical,
        "followup_critical_uncovered_branches": followup,
    }
    (directory / "subsystems.json").write_text(json.dumps(payload, indent=2) + "\n")
    lines = [
        "<!doctype html><meta charset=utf-8><title>EzLLMRouter coverage</title><h1>EzLLMRouter coverage</h1>",
        "<p>" + html.escape(summary["scope"]) + "</p>",
        "<table><tr><th>Subsystem<th>Lines<th>Conditional exits",
    ]
    for name, row in sorted(groups.items()):
        lines.append(
            f"<tr><td>{html.escape(name)}<td>{row['executed']}/{row['executable']}<td>{row['branches_executed']}/{row['branches']}"
        )
    lines.append(
        "</table><h2>Critical uncovered branches</h2><pre>"
        + html.escape(json.dumps(critical, indent=2))
        + "</pre><h2>Follow-up critical gaps (ratcheted)</h2><pre>"
        + html.escape(json.dumps(followup, indent=2))
        + "</pre><h2>Missing source</h2>"
    )
    for path, row in sorted(summary["files"].items()):
        lines.append(
            "<details><summary>"
            + html.escape(path)
            + "</summary><pre>"
            + html.escape(
                json.dumps(
                    {key: row[key] for key in ("sha256", "missing_lines", "missing_branches")},
                    indent=2,
                )
            )
            + "</pre></details>"
        )
    (directory / "index.html").write_text("\n".join(lines) + "\n")
    return payload


def baseline_for(summary: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "measurement": summary["scope"],
        "python": summary["python"],
        "files": {
            path: {
                "source_sha256": row["sha256"],
                "missing_lines": len(row["missing_lines"]),
                "missing_branches": len(row["missing_branches"]),
            }
            for path, row in sorted(summary["files"].items())
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--policy", type=Path, default=ROOT / "tools/coverage_policy.json")
    parser.add_argument("--baseline", type=Path, default=ROOT / "tools/coverage_budget.json")
    parser.add_argument(
        "--write-baseline", action="store_true", help="explicit reviewed baseline creation/update"
    )
    parser.add_argument("--enforce-critical", action="store_true")
    args = parser.parse_args()
    summary = json.loads((args.directory / "summary.json").read_text())
    policy = json.loads(args.policy.read_text())
    rendered = render(summary, args.directory, policy)
    if args.write_baseline:
        args.baseline.write_text(json.dumps(baseline_for(summary), indent=2) + "\n")
    baseline = json.loads(args.baseline.read_text())
    errors = regressions(summary, baseline)
    if args.enforce_critical and rendered["critical_uncovered_branches"]:
        errors.append("critical conditional branches remain uncovered; see subsystems.json")
    if errors:
        print("\n".join(errors))
        return 1
    print(
        f"Coverage budgets pass; {len(rendered['critical_uncovered_branches'])} critical exits need tests; {args.directory}/index.html"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
