"""Offline Ruff security rules with source- and finding-bound review identities."""

from __future__ import annotations

import argparse
import ast
from functools import lru_cache
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCOPES = ("server/src", "clients/python/src", "worker", "deploy", "tools")


def scan(root: Path = ROOT) -> list[dict[str, Any]]:
    version = subprocess.check_output(
        [sys.executable, "-m", "ruff", "--version"], text=True
    ).strip()
    if version != "ruff 0.14.0":
        raise RuntimeError("security scan requires the locked Ruff 0.14.0")
    if (root / ".git").exists():
        names = subprocess.check_output(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
            ],
            text=True,
        ).split("\0")
        paths = sorted(
            root / name
            for name in set(names)
            if name.endswith(".py") and any(name.startswith(scope + "/") for scope in SCOPES)
        )
    else:
        paths = sorted({path for scope in SCOPES for path in (root / scope).rglob("*.py")})
    if not paths:
        raise ValueError("empty security scan scope")
    if any(path.is_symlink() or not path.is_file() for path in paths):
        raise ValueError("security source must be a regular file")
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
            *(str(path) for path in paths),
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


@lru_cache(maxsize=512)
def _syntax(source: bytes) -> ast.Module:
    return ast.parse(source)


def finding_identity(root: Path, row: dict[str, Any]) -> dict[str, Any]:
    tree = _syntax((root / row["path"]).read_bytes())
    line, column = row["location"]["row"], row["location"]["column"]

    def contains(node: ast.AST) -> bool:
        return hasattr(node, "lineno") and (node.lineno, getattr(node, "col_offset", 0)) <= (
            line,
            column - 1,
        ) <= (
            getattr(node, "end_lineno", 0),
            getattr(node, "end_col_offset", 0),
        )

    nodes = [node for node in ast.walk(tree) if contains(node)]
    statements = [node for node in nodes if isinstance(node, ast.stmt)]
    if not statements:
        raise ValueError("security finding has no source statement")
    statement = min(
        statements,
        key=lambda node: (
            getattr(node, "end_lineno", 0) - node.lineno,
            getattr(node, "end_col_offset", 0) - getattr(node, "col_offset", 0),
        ),
    )
    scopes = sorted(
        (
            node
            for node in nodes
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        ),
        key=lambda node: (node.lineno, getattr(node, "col_offset", 0)),
    )
    return {
        "line": line,
        "column": column,
        "symbol": ".".join(node.name for node in scopes) or "<module>",
        "statement_sha256": hashlib.sha256(
            ast.dump(statement, include_attributes=False).encode()
        ).hexdigest(),
        "context_sha256": hashlib.sha256(
            ast.dump(scopes[-1] if scopes else tree, include_attributes=False).encode()
        ).hexdigest(),
    }


def errors(root: Path, findings: list[dict[str, Any]], policy: dict[str, Any]) -> list[str]:
    def key(row: dict[str, Any], identity: dict[str, Any]) -> tuple[str, str, str]:
        return row["path"], row["code"], json.dumps(identity, sort_keys=True)

    remaining = Counter(key(row, finding_identity(root, row)) for row in findings)
    failures = []
    seen = set()
    for exception in policy["exceptions"]:
        group = exception["path"], exception["code"]
        if group in seen or not exception["reason"].strip():
            failures.append("invalid/duplicate security exception: " + str(group))
            continue
        seen.add(group)
        source = root / exception["path"]
        if (
            not source.is_file()
            or source.is_symlink()
            or hashlib.sha256(source.read_bytes()).hexdigest() != exception["source_sha256"]
        ):
            failures.append("review changed security exception source: " + exception["path"])
            continue
        identities = exception.get("findings", [])
        keys = [key(exception, identity) for identity in identities]
        if not keys or len(set(keys)) != len(keys):
            failures.append("missing/duplicate security finding identities: " + str(group))
            continue
        for identity in keys:
            if remaining[identity] != 1:
                failures.append("changed/resolved security finding identity: " + str(group))
            else:
                del remaining[identity]
    failures.extend(
        f"unreviewed security finding: {path} {code} {identity} ({count})"
        for (path, code, identity), count in sorted(remaining.items())
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
        f"Security rules pass with {len(findings)} source- and finding-pinned, reviewed findings; {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
