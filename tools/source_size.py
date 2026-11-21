"""Measure source spans and reject growth beyond reviewed per-symbol ceilings."""

from __future__ import annotations

import ast
from collections.abc import Mapping
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SCOPES = ("server/src", "clients/python/src", "tools", "tests")
EXTENSIONS = {".py", ".js", ".cjs", ".mjs", ".ts", ".go", ".java", ".cs", ".rs"}
RUNTIME_LIMITS = {"file": 800, "function": 100, "class": 600}
TOOL_LIMITS = {"file": 1500, "function": 200, "class": 1500}


def limits(path: str) -> Mapping[str, int]:
    return TOOL_LIMITS if path.startswith(("tools/", "tests/")) else RUNTIME_LIMITS


def measure(path: str, source: str) -> dict[str, int]:
    sizes = {f"{path}:file": len(source.splitlines())}
    if not path.endswith(".py"):
        return sizes

    def visit(node: ast.AST, parents: tuple[str, ...]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                kind = "class" if isinstance(child, ast.ClassDef) else "function"
                qualified = (*parents, child.name)
                assert child.end_lineno is not None
                key = f"{path}:{kind}:{'.'.join(qualified)}"
                if key in sizes:
                    raise ValueError(f"duplicate source symbol: {key}")
                sizes[key] = child.end_lineno - child.lineno + 1
                visit(child, qualified)
            else:
                visit(child, parents)

    visit(ast.parse(source, filename=path), ())
    return sizes


def oversized(sizes: Mapping[str, int]) -> dict[str, int]:
    return {
        key: size
        for key, size in sorted(sizes.items())
        if size > limits(key.split(":", 1)[0])[key.split(":")[1]]
    }


def regressions(ceilings: Mapping[str, int], sizes: Mapping[str, int]) -> list[str]:
    offenders = oversized(sizes)
    errors = []
    for key, size in offenders.items():
        path, kind, *_ = key.split(":")
        ceiling = ceilings.get(key, limits(path)[kind])
        if size > ceiling:
            errors.append(f"{key}: {size} lines exceeds ceiling {ceiling}")
    for key, ceiling in ceilings.items():
        if key not in offenders:
            errors.append(f"{key}: remove resolved or missing size allowance")
        elif offenders[key] < ceiling:
            errors.append(f"{key}: lower ceiling from {ceiling} to {offenders[key]}")
    return errors


def repository_sizes(root: Path = ROOT) -> dict[str, int]:
    files = subprocess.check_output(
        [
            "git",
            "-C",
            str(root),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
            "--",
            *SCOPES,
        ],
        text=True,
    ).split("\0")
    sizes = {}
    for name in sorted(set(files) - {""}):
        path = root / name
        if path.is_file() and path.suffix in EXTENSIONS:
            sizes.update(measure(name, path.read_text()))
    return sizes
