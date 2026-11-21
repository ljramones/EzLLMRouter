"""Report V8 SDK ranges and AST console counters with their distinct scopes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def sdk_inventory(root: Path) -> dict[str, Any]:
    sources = sorted([*root.glob("clients/js/*.cjs"), *root.glob("clients/js/*.mjs")])
    if not sources:
        return {}
    process = subprocess.run(
        ["node", str(ROOT / "tools/javascript_functions.cjs")],
        input=json.dumps([str(source) for source in sources]),
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    )
    return {
        Path(filename).relative_to(root).as_posix(): row
        for filename, row in json.loads(process.stdout).items()
    }


def source_for(url: str, root: Path = ROOT) -> Path | None:
    value = unquote(urlsplit(url).path) if url.startswith("file:") else url
    path = Path(value)
    candidates = [path, root / path, root / "web" / path.name]
    sources = [
        *root.glob("web/*.js"),
        *root.glob("clients/js/*.cjs"),
        *root.glob("clients/js/*.mjs"),
    ]
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in sources:
            return resolved
    # Installed npm consumers must match the canonical bytes, not just a basename.
    if path.is_file():
        for source in sources:
            if path.name == source.name and path.read_bytes() == source.read_bytes():
                return source
    return None


def report(directory: Path, root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    functions: dict[str, dict[tuple[int, int], int]] = {}
    blocks: dict[str, dict[tuple[int, int], int]] = {}
    vm: dict[str, dict[str, Any]] = {}
    aliases = {}
    for artifact in directory.glob("sources-*.json"):
        for url, entry in json.loads(artifact.read_text()).items():
            candidate = source_for(str(root / entry["canonical"]), root)
            if (
                candidate is None
                or hashlib.sha256(candidate.read_bytes()).hexdigest() != entry["sha256"]
            ):
                raise ValueError("installed SDK coverage identity changed")
            aliases[unquote(url)] = candidate
    inventory = sdk_inventory(root)
    for artifact in directory.glob("vm-coverage-*.json"):
        for filename, entry in json.loads(artifact.read_text())["files"].items():
            source = source_for(filename, root)
            if source is None:
                continue
            if entry["sha256"] != hashlib.sha256(source.read_bytes()).hexdigest():
                raise ValueError("VM coverage source changed: " + str(source))
            vm_entries = vm.setdefault(source.relative_to(root).as_posix(), {})
            for key, row in entry["counters"].items():
                previous = vm_entries.get(key)
                if previous is None or row["count"] > previous["count"]:
                    vm_entries[key] = row
    for artifact in directory.glob("coverage-*.json"):
        for script in json.loads(artifact.read_text()).get("result", []):
            source = source_for(script["url"], root) or aliases.get(unquote(script["url"]))
            if source is None:
                continue
            key = source.relative_to(root).as_posix()
            for index, function in enumerate(script["functions"]):
                ranges = function["ranges"]
                if not ranges:
                    continue
                span = (ranges[0]["startOffset"], ranges[0]["endOffset"])
                entries = functions.setdefault(key, {})
                static = inventory.get(key)
                # V8 includes a script wrapper, which may have the same span as
                # an uncalled function occupying the entire source file.
                wrapper = static and index == 0 and span == (0, static["utf16_length"])
                if static is None:
                    entries[span] = max(entries.get(span, 0), ranges[0]["count"])
                elif not wrapper:
                    for candidate in static["functions"]:
                        if (
                            candidate["end"] == span[1]
                            and candidate["start"] <= span[0] <= candidate["body_start"]
                        ):
                            identity = candidate["start"], candidate["end"]
                            entries[identity] = max(entries.get(identity, 0), ranges[0]["count"])
                for row in ranges:
                    target = blocks.setdefault(key, {})
                    span = row["startOffset"], row["endOffset"]
                    target[span] = max(target.get(span, 0), row["count"])
    files = {}
    for source in sorted(
        [*root.glob("web/*.js"), *root.glob("clients/js/*.cjs"), *root.glob("clients/js/*.mjs")]
    ):
        key = source.relative_to(root).as_posix()
        observed = functions.get(key, {})
        ranges = blocks.get(key, {})
        if key in inventory:
            observed = {
                (row["start"], row["end"]): observed.get((row["start"], row["end"]), 0)
                for row in inventory[key]["functions"]
            }
        files[key] = {
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "measured": key in functions,
            "functions": len(observed),
            "functions_hit": sum(count > 0 for count in observed.values()),
            "observed_blocks": len(ranges),
            "observed_blocks_hit": sum(count > 0 for count in ranges.values()),
            "missing_function_offsets_utf16": [
                list(span) for span, count in sorted(observed.items()) if count == 0
            ],
        }
        if key in inventory:
            files[key]["method"] = "TypeScript 5.9.3 static functions with V8 hit counts"
        if key in vm:
            rows = list(vm[key].values())
            files[key] = {
                "sha256": files[key]["sha256"],
                "measured": True,
                "method": "TypeScript 5.9.3 AST counters",
                "functions": sum(row["kind"] == "function" for row in rows),
                "functions_hit": sum(
                    row["kind"] == "function" and row["count"] > 0 for row in rows
                ),
                "statements": sum(row["kind"] == "statement" for row in rows),
                "statements_hit": sum(
                    row["kind"] == "statement" and row["count"] > 0 for row in rows
                ),
                "missing_counters": [row for row in rows if row["count"] == 0],
            }
    payload = {
        "scope": "Static TypeScript 5.9.3 SDK functions with V8 hits; diagnostic V8 block ranges; AST console counters; unmeasured files explicit; no exhaustive JS branch denominator claim",
        "files": files,
    }
    (directory / "summary.json").write_text(json.dumps(payload, indent=2) + "\n")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--scope", choices=("console", "sdk"))
    parser.add_argument(
        "--budget", type=Path, default=ROOT / "tools/javascript_coverage_budget.json"
    )
    parser.add_argument("--write-baseline", action="store_true")
    args = parser.parse_args()
    payload = report(args.directory)
    if args.scope:
        baseline = json.loads(args.budget.read_text()) if args.budget.exists() else {}
        measured = budgets(payload, args.scope)
        if args.write_baseline:
            baseline[args.scope] = measured
            args.budget.write_text(json.dumps(baseline, indent=2) + "\n")
        errors = budget_errors(measured, baseline.get(args.scope, {}))
        if errors:
            print("\n".join(errors))
            return 1
    print(
        f"V8 coverage: {sum(row['measured'] for row in payload['files'].values())}/{len(payload['files'])} source files measured; {args.directory}/summary.json"
    )
    return 0


def budgets(payload: dict[str, Any], scope: str) -> dict[str, dict[str, Any]]:
    prefix = "web/" if scope == "console" else "clients/js/"
    result = {}
    for name, row in payload["files"].items():
        if not name.startswith(prefix):
            continue
        statement_misses = (
            row["statements"] - row["statements_hit"]
            if "statements" in row
            else row["observed_blocks"] - row["observed_blocks_hit"]
        )
        result[name] = {
            "sha256": row["sha256"],
            "measured": row["measured"],
            "missing_functions": row["functions"] - row["functions_hit"],
            "missing_statements_or_observed_blocks": statement_misses,
        }
        if scope == "sdk":
            # V8's observed block ranges can change when an outer function runs.
            # Keep those diagnostic ranges out of a fixed-denominator ratchet.
            result[name].pop("missing_statements_or_observed_blocks")
            result[name]["functions"] = row["functions"]
            result[name]["missing_function_ids"] = [
                f"{start}:{end}" for start, end in row["missing_function_offsets_utf16"]
            ]
    return result


def budget_errors(current: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    errors = []
    for name, row in current.items():
        old = baseline.get(name)
        if old is None:
            if (
                not row["measured"]
                or row["missing_functions"]
                or row.get("missing_statements_or_observed_blocks", 0)
            ):
                errors.append("new JS source needs coverage: " + name)
        else:
            if old["measured"] and not row["measured"]:
                errors.append("lost JS source measurement: " + name)
            for metric in ("missing_functions", "missing_statements_or_observed_blocks"):
                if metric in row and row[metric] > old[metric]:
                    errors.append(f"{name}: {metric} exceeds reviewed budget")
            if "missing_function_ids" in row:
                if "missing_function_ids" not in old:
                    errors.append("review static SDK function baseline: " + name)
                elif row["sha256"] != old["sha256"]:
                    errors.append("SDK source changed; review function identities: " + name)
                else:
                    if row["functions"] != old["functions"]:
                        errors.append("static SDK function inventory changed: " + name)
                    current_ids = set(row["missing_function_ids"])
                    old_ids = set(old["missing_function_ids"])
                    if current_ids - old_ids:
                        errors.append("newly uncovered SDK functions: " + name)
                    if old_ids - current_ids:
                        errors.append("tighten covered SDK function budget: " + name)
    for name in baseline.keys() - current.keys():
        errors.append("missing JS source: " + name)
    return errors


if __name__ == "__main__":
    raise SystemExit(main())
