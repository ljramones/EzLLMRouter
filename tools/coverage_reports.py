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
    if baseline.get("python", summary.get("python")) != summary.get("python"):
        errors.append("coverage runtime differs from the reviewed baseline")
    for path, row in summary["files"].items():
        permitted = files.get(path)
        if permitted is not None:
            if permitted.get("source_sha256") != row.get("sha256"):
                errors.append(f"{path}: source changed; review and update coverage identities")
                continue
            if not {"missing_line_ids", "missing_branch_ids"} <= permitted.keys():
                errors.append(f"{path}: coverage budget requires exact missing-code identities")
                continue
        for key, identity_key in (
            ("missing_lines", "missing_line_ids"),
            ("missing_branches", "missing_branch_ids"),
        ):
            actual = (
                set(row[key]) if key == "missing_lines" else {entry["id"] for entry in row[key]}
            )
            expected = set(permitted[identity_key]) if permitted is not None else set()
            if permitted is not None and len(expected) != permitted[key]:
                errors.append(f"{path}: inconsistent {key} budget and identities")
            if actual - expected:
                errors.append(f"{path}: {len(actual - expected)} newly {key}")
            if expected - actual:
                errors.append(
                    f"{path}: tighten {key} budget; {len(expected - actual)} reviewed gaps are now covered"
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
        "format_version": 2,
        "measurement": summary["scope"],
        "python": summary["python"],
        "files": {
            path: {
                "source_sha256": row["sha256"],
                "missing_lines": len(row["missing_lines"]),
                "missing_branches": len(row["missing_branches"]),
                "missing_line_ids": sorted(row["missing_lines"]),
                "missing_branch_ids": sorted(branch["id"] for branch in row["missing_branches"]),
            }
            for path, row in sorted(summary["files"].items())
        },
    }


def merge_summaries(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    """Union measured hits only when both runs describe exactly the same sources."""
    if any(left[key] != right[key] for key in ("python", "scope")):
        raise ValueError("coverage runtime or measurement scope differs across tiers")
    if left["files"].keys() != right["files"].keys():
        raise ValueError("coverage source inventories differ across tiers")
    files = {}
    for path, first in left["files"].items():
        second = right["files"][path]
        for key in ("sha256", "executable", "branches", "branch_functions"):
            if first[key] != second[key]:
                raise ValueError(f"coverage identity/denominator differs across tiers: {path}")
        lines = sorted(set(first["missing_lines"]) & set(second["missing_lines"]))
        right_missing = {row["id"] for row in second["missing_branches"]}
        branches = [row for row in first["missing_branches"] if row["id"] in right_missing]
        files[path] = {
            **first,
            "missing_lines": lines,
            "executed": first["executable"] - len(lines),
            "missing_branches": branches,
            "branches_executed": first["branches"] - len(branches),
        }
    executable = sum(row["executable"] for row in files.values())
    executed = sum(row["executed"] for row in files.values())
    return {
        "scope": left["scope"],
        "python": left["python"],
        "tier": "combined",
        "branches": sum(row["branches"] for row in files.values()),
        "branches_executed": sum(row["branches_executed"] for row in files.values()),
        "executed": executed,
        "executable": executable,
        "percent": round(100 * executed / executable, 2) if executable else 0,
        "files": files,
    }


def merge_baselines(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    """Derive combined allowances from the independently reviewed tier budgets."""
    if left["python"] != right["python"] or left["files"].keys() != right["files"].keys():
        raise ValueError("coverage baseline runtimes or source inventories differ")
    files = {}
    for path, first in left["files"].items():
        second = right["files"][path]
        if first["source_sha256"] != second["source_sha256"]:
            raise ValueError("coverage baseline source identities differ: " + path)
        lines = sorted(set(first["missing_line_ids"]) & set(second["missing_line_ids"]))
        branches = sorted(set(first["missing_branch_ids"]) & set(second["missing_branch_ids"]))
        files[path] = {
            "source_sha256": first["source_sha256"],
            "missing_lines": len(lines),
            "missing_branches": len(branches),
            "missing_line_ids": lines,
            "missing_branch_ids": branches,
        }
    return {**left, "files": files}


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
