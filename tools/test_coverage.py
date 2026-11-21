"""Optional Python line coverage using only the standard library, including child runs."""

from __future__ import annotations

from collections import defaultdict
from typing import Any
import dis
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import types
import uuid

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (ROOT / "server/src/ezllmrouter_server", ROOT / "clients/python/src/ezllmrouter_client")


def branch_api():
    # Isolated child interpreters intentionally cannot import the checkout.
    name = "_ezllmrouter_branch_coverage"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, ROOT / "tools/branch_coverage.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sys.modules[name] = module
    return sys.modules[name]


class LineCoverage:
    def __init__(self, output: str | Path, roots: tuple[Path, ...] = SOURCES) -> None:
        self.output = Path(output)
        self.roots = tuple(Path(root).resolve() for root in roots)
        self.prefixes = tuple(
            str(path) + os.sep
            for root in roots
            for path in (Path(root).absolute(), Path(root).resolve())
        )
        self.lines: dict[str, set[int]] = defaultdict(set)
        self.active = False

    def __enter__(self) -> LineCoverage:
        self.branches = branch_api().BranchCoverage(self.output, self.prefixes)
        self.branches.__enter__()
        self.active = True
        self.lines = self.branches.lines
        return self

    def __exit__(self, *_error: object) -> None:
        self.active = False
        self.branches.__exit__(*_error)
        self.output.mkdir(parents=True, exist_ok=True)
        # Copy before serialization: a finishing worker can still report a line.
        rows = {name: sorted(values.copy()) for name, values in list(self.lines.items())}
        (self.output / f"lines-{os.getpid()}-{uuid.uuid4().hex}.json").write_text(json.dumps(rows))


def executable_lines(path: Path) -> set[int]:
    pending = [compile(path.read_bytes(), str(path), "exec", dont_inherit=True)]
    lines = set()
    while pending:
        code = pending.pop()
        lines.update(line for _, line in dis.findlinestarts(code) if line > 0)
        pending.extend(value for value in code.co_consts if isinstance(value, types.CodeType))
    return lines


def report(
    directory: str | Path, roots: tuple[Path, ...] = SOURCES, base: Path = ROOT
) -> dict[str, Any]:
    directory = Path(directory)
    base = base.resolve()
    observed = defaultdict(set)
    for path in directory.glob("lines-*.json"):
        for name, lines in json.loads(path.read_text()).items():
            observed[str(Path(name).resolve())].update(lines)
    branch_hits = defaultdict(set)
    for path in directory.glob("branches-*.json"):
        for name, values in json.loads(path.read_text()).items():
            branch_hits[str(Path(name).resolve())].update(values)
    files = {}
    for root in roots:
        for path in sorted(Path(root).resolve().rglob("*.py")):
            possible = executable_lines(path)
            hit = possible & observed[str(path)]
            possible_branches = branch_api().branches(
                compile(path.read_bytes(), str(path), "exec", dont_inherit=True)
            )
            hit_branches = possible_branches.keys() & branch_hits[str(path)]
            files[path.relative_to(base).as_posix()] = {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "executed": len(hit),
                "executable": len(possible),
                "missing_lines": sorted(possible - hit),
                "branches": len(possible_branches),
                "branches_executed": len(hit_branches),
                "branch_functions": sorted({row["function"] for row in possible_branches.values()}),
                "missing_branches": [
                    {"id": key, **row}
                    for key, row in sorted(possible_branches.items())
                    if key not in hit_branches
                ],
            }
    total = sum(row["executable"] for row in files.values())
    hit = sum(row["executed"] for row in files.values())
    result = {
        "scope": "Python lines and conditional-bytecode branch exits; exception edges/native/JavaScript excluded",
        "python": sys.version.split()[0],
        "branches": sum(row["branches"] for row in files.values()),
        "branches_executed": sum(row["branches_executed"] for row in files.values()),
        "executed": hit,
        "executable": total,
        "percent": round(100 * hit / total, 2) if total else 0,
        "files": files,
    }
    (directory / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
