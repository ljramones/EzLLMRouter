"""Bounded, disposable gateway diagnostics; never an accounting authority."""

from __future__ import annotations

from collections import OrderedDict
from .records import Record
import json
import os
from pathlib import Path
import threading

MAX_BYTES = 4 * 1024 * 1024
BACKUPS = 2
_CACHE: OrderedDict[str, tuple[list[tuple[int, int, int] | None], list[Record]]] = OrderedDict()
_CACHE_LOCK = threading.Lock()


def append_event(
    target: str | Path, row: Record, *, max_bytes: int = MAX_BYTES, backups: int = BACKUPS
) -> None:
    path = Path(target)
    encoded = json.dumps(row, separators=(",", ":"), ensure_ascii=True) + "\n"
    if len(encoded) > min(max_bytes, 65536):
        raise ValueError("diagnostic row too large")
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        size = 0
    if size + len(encoded) > max_bytes:
        for number in range(backups, 0, -1):
            source = path if number == 1 else Path(str(path) + "." + str(number - 1))
            try:
                source.replace(str(path) + "." + str(number))
            except FileNotFoundError:
                pass
    with path.open("a", encoding="utf-8") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())


def read_events(target: str | Path) -> list[Record]:
    """Cache a bounded tail of each retained file; old/missing facts stay unknown."""
    path = Path(target)
    paths = [Path(str(path) + "." + str(n)) for n in range(BACKUPS, 0, -1)] + [path]
    fingerprint: list[tuple[int, int, int] | None] = []
    for current in paths:
        try:
            stat = current.stat()
            fingerprint.append((stat.st_ino, stat.st_size, stat.st_mtime_ns))
        except FileNotFoundError:
            fingerprint.append(None)
    key = str(path.resolve())
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is not None and cached[0] == fingerprint:
            _CACHE.move_to_end(key)
            return cached[1]
    rows = []
    for current in paths:
        try:
            with current.open("rb") as stream:
                size = stream.seek(0, os.SEEK_END)
                start = max(0, size - MAX_BYTES)
                stream.seek(start)
                if start:
                    stream.readline(MAX_BYTES)
                raw = stream.read(MAX_BYTES)
        except OSError:
            continue
        for line in raw.splitlines():
            try:
                value = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            if type(value) is dict:
                rows.append(value)
    with _CACHE_LOCK:
        _CACHE[key] = (fingerprint, rows)
        _CACHE.move_to_end(key)
        while len(_CACHE) > 4:
            _CACHE.popitem(last=False)
    return rows
