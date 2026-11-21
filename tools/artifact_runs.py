"""Bound owned default outputs; leases and .keep protect retained evidence."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import fcntl
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any, Iterator
import uuid

MARKER = ".ezllmrouter-run.json"
_HELD: dict[Path, tuple[int, str]] = {}


@dataclass
class RunSession:
    paths: list[Path] = field(default_factory=list)
    passed: bool = False


_SESSION: ContextVar[RunSession | None] = ContextVar("ezllmrouter_artifact_session", default=None)


@contextmanager
def session() -> Iterator[RunSession]:
    current = RunSession()
    token = _SESSION.set(current)
    try:
        yield current
    finally:
        _SESSION.reset(token)
        errors = []
        for path in reversed(current.paths):
            try:
                finish_run(path, passed=current.passed)
            except (OSError, ValueError) as error:
                errors.append(error)
        if errors:
            raise ExceptionGroup("artifact finalization failed", errors)


def _write(path: Path, row: dict[str, Any]) -> None:
    temporary = path / (".run-" + uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(row, sort_keys=True) + "\n")
    temporary.replace(path / MARKER)


def _read(path: Path, parent: Path, kind: str) -> dict[str, Any] | None:
    if path.is_symlink() or not path.is_dir() or (path / MARKER).is_symlink():
        return None
    try:
        row = json.loads((path / MARKER).read_text())
    except (OSError, ValueError):
        return None
    if (
        not isinstance(row, dict)
        or row.get("format_version") != 1
        or row.get("name") != path.name
        or row.get("parent") != str(parent)
        or row.get("kind") != kind
        or type(row.get("created_ns")) is not int
        or not isinstance(row.get("state"), str)
        or row.get("state") not in {"active", "passed", "failed", "abandoned"}
    ):
        return None
    return row


def _pinned(path: Path) -> bool:
    pin = path / ".keep"
    return pin.exists() or pin.is_symlink()


def new_run(parent: Path, prefix: str, kind: str) -> Path:
    if not prefix or "/" in prefix or "\\" in prefix or not kind:
        raise ValueError("invalid managed artifact prefix or kind")
    parent = parent.resolve()
    parent.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix=prefix, dir=parent))
    lease = os.open(path / ".lease", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _write(
            path,
            {
                "format_version": 1,
                "name": path.name,
                "parent": str(parent),
                "kind": kind,
                "created_ns": time.time_ns(),
                "state": "active",
            },
        )
    except BaseException:
        os.close(lease)
        raise
    _HELD[path] = lease, kind
    current = _SESSION.get()
    if current is not None:
        current.paths.append(path)
    return path


def finish_run(path: Path, *, passed: bool) -> None:
    path = path.resolve()
    held = _HELD.pop(path, None)
    if held is None:
        return  # Explicit output directories are outside automatic retention.
    lease, kind = held
    try:
        row = _read(path, path.parent, kind)
        if row is None:
            raise ValueError("managed artifact identity changed")
        row["state"] = "passed" if passed else "failed"
        _write(path, row)
    finally:
        os.close(lease)
    prune(path.parent, kind)


def prune(parent: Path, kind: str, *, keep_success: int = 5, keep_failure: int = 5) -> None:
    if min(keep_success, keep_failure) < 1:
        raise ValueError("retain at least one successful and one failed run")
    parent = parent.resolve()
    lock = os.open(parent / ".retention.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    candidates: list[tuple[Path, dict[str, Any], int]] = []
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for path in parent.iterdir():
            if path in _HELD or _read(path, parent, kind) is None or _pinned(path):
                continue
            try:
                lease = os.open(path / ".lease", os.O_RDWR | os.O_NOFOLLOW)
            except OSError:
                continue
            try:
                fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(lease)
                continue
            try:
                row = _read(path, parent, kind)
                if row is not None and row["state"] == "active":
                    row["state"] = "abandoned"
                    _write(path, row)
            except BaseException:
                os.close(lease)
                raise
            if row is None:
                os.close(lease)
                continue
            candidates.append((path, row, lease))
        for failed, keep in ((False, keep_success), (True, keep_failure)):
            selected = sorted(
                (item for item in candidates if (item[1]["state"] != "passed") == failed),
                key=lambda item: (item[1]["created_ns"], item[0].name),
                reverse=True,
            )
            for path, _row, _lease in selected[keep:]:
                if not path.is_symlink() and not _pinned(path):
                    shutil.rmtree(path)
    finally:
        for _path, _row, lease in candidates:
            os.close(lease)
        os.close(lock)
