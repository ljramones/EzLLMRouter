"""Optional Python line coverage using only the standard library, including child runs."""

from __future__ import annotations

from collections import defaultdict
from typing import Any
import dis
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import types
import uuid

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (ROOT / "server/src/ezllmrouter_server", ROOT / "clients/python/src/ezllmrouter_client")


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

    def _local(self, frame, event, _argument):
        if self.active and event == "line":
            self.lines[frame.f_code.co_filename].add(frame.f_lineno)
        return self._local

    def _global(self, frame, event, _argument):
        if self.active and event == "call" and frame.f_code.co_filename.startswith(self.prefixes):
            return self._local
        return None

    def __enter__(self) -> LineCoverage:
        self.active = True
        self.previous = sys.gettrace(), threading.gettrace()
        threading.settrace(self._global)
        sys.settrace(self._global)
        return self

    def __exit__(self, *_error: object) -> None:
        self.active = False
        sys.settrace(self.previous[0])
        threading.settrace(self.previous[1])
        self.output.mkdir(parents=True, exist_ok=True)
        # Copy before serialization: a finishing worker can still report a line.
        rows = {name: sorted(values.copy()) for name, values in list(self.lines.items())}
        (self.output / f"lines-{os.getpid()}-{uuid.uuid4().hex}.json").write_text(json.dumps(rows))


def executable_lines(path: Path) -> set[int]:
    pending = [compile(path.read_bytes(), str(path), "exec")]
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
    files = {}
    for root in roots:
        for path in sorted(Path(root).resolve().rglob("*.py")):
            possible = executable_lines(path)
            hit = possible & observed[str(path)]
            files[path.relative_to(base).as_posix()] = {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "executed": len(hit),
                "executable": len(possible),
                "missing_lines": sorted(possible - hit),
            }
    total = sum(row["executable"] for row in files.values())
    hit = sum(row["executed"] for row in files.values())
    result = {
        "scope": "Python executable-line coverage; no branch/native/JavaScript claim",
        "executed": hit,
        "executable": total,
        "percent": round(100 * hit / total, 2) if total else 0,
        "files": files,
    }
    (directory / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
