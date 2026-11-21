"""Offline Ruff security rules for every server/Python-client source file."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCOPES = ("server/src", "clients/python/src")


def scan(root: Path = ROOT) -> list[dict[str, Any]]:
    version = subprocess.check_output(
        [sys.executable, "-m", "ruff", "--version"], text=True
    ).strip()
    if version != "ruff 0.14.0":
        raise RuntimeError("security scan requires the locked Ruff 0.14.0")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--isolated",
            "--target-version",
            "py312",
            "--select",
            "S",
            "--ignore-noqa",
            "--output-format",
            "json",
            *(str(root / path) for path in SCOPES),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError("security scanner could not complete")
    rows = json.loads(result.stdout)
    if not isinstance(rows, list):
        raise ValueError("invalid scanner output")
    return [
        dict(row, path=Path(row["filename"]).resolve().relative_to(root.resolve()).as_posix())
        for row in rows
    ]


def errors(root: Path, findings: list[dict[str, Any]], policy: dict[str, Any]) -> list[str]:
    remaining = Counter((row["path"], row["code"]) for row in findings)
    failures = []
    seen = set()
    for exception in policy["exceptions"]:
        key = exception["path"], exception["code"]
        if key in seen or not exception["reason"].strip():
            failures.append("invalid/duplicate security exception: " + str(key))
            continue
        seen.add(key)
        source = root / exception["path"]
        if (
            not source.is_file()
            or hashlib.sha256(source.read_bytes()).hexdigest() != exception["source_sha256"]
        ):
            failures.append("review changed security exception source: " + exception["path"])
            continue
        if remaining[key] != exception["count"]:
            failures.append("update changed/resolved security exception count: " + str(key))
            continue
        del remaining[key]
    failures.extend(
        f"unreviewed security finding: {path} {code} ({count})"
        for (path, code), count in sorted(remaining.items())
        if count
    )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".artifacts/security/sast.json")
    args = parser.parse_args()
    findings = scan()
    policy = json.loads((ROOT / "tools/security_sast_exceptions.json").read_text())
    failures = errors(ROOT, findings, policy)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "tool": "Ruff 0.14.0 S rules",
                "scope": SCOPES,
                "findings": findings,
                "errors": failures,
            },
            indent=2,
        )
        + "\n"
    )
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(
        f"Runtime security rules pass with {len(findings)} source-pinned, reviewed SQL findings; {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
