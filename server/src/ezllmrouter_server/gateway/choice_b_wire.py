"""Small bounded JSON record used only by the DEV-04 Choice B Unix sockets."""

from __future__ import annotations
from typing import Any, TYPE_CHECKING
import json
import os
from pathlib import Path
import asyncio
import socket
import struct
import time
from datetime import datetime, timezone

LIMIT = 262144
if TYPE_CHECKING or __package__ == "ezllmrouter_server.gateway":
    from ..execution_policy import MAX_ATTEMPT_TIMEOUT_MS as MAX_ATTEMPT_TIMEOUT_MS
else:
    from .execution_policy import MAX_ATTEMPT_TIMEOUT_MS as MAX_ATTEMPT_TIMEOUT_MS


def socket_path(kind: str, root: Path = Path("/link")) -> Path:
    if kind not in ("sender", "worker"):
        raise ValueError("unknown IPC role")
    return Path(os.environ.get("EZLLMROUTER_" + kind.upper() + "_SOCKET", root / (kind + ".sock")))


def remaining_seconds(timeout_ms: int, deadline: str) -> float:
    if type(timeout_ms) is not int or not 1 <= timeout_ms <= MAX_ATTEMPT_TIMEOUT_MS:
        raise ValueError("attempt timeout outside supported limits")
    if type(deadline) is not str:
        raise ValueError("attempt deadline required")
    expires = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
    if expires.tzinfo is None:
        raise ValueError("attempt deadline must include its timezone")
    remaining = min(timeout_ms / 1000, (expires - datetime.now(timezone.utc)).total_seconds())
    if remaining <= 0:
        raise TimeoutError("attempt deadline expired")
    return remaining


def _read_exact(stream: socket.socket, count: int, deadline: float | None = None) -> bytes:
    chunks = []
    while count:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("socket frame deadline expired")
            stream.settimeout(remaining)
        part = stream.recv(count)
        if not part:
            raise EOFError("incomplete gateway socket record")
        chunks.append(part)
        count -= len(part)
    return b"".join(chunks)


def _decode_record(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except RecursionError as error:
        raise ValueError("gateway socket record nesting") from error
    if type(value) is not dict:
        raise ValueError("gateway socket record shape")
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > 64:
            raise ValueError("gateway socket record nesting")
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    return value


def receive(stream: socket.socket, *, timeout: float | None = None) -> dict[str, Any]:
    deadline = None if timeout is None else time.monotonic() + timeout
    size = struct.unpack("!I", _read_exact(stream, 4, deadline))[0]
    if not 0 < size <= LIMIT:
        raise ValueError("gateway socket record size")
    return _decode_record(_read_exact(stream, size, deadline))


def _frame(value: dict[str, Any]) -> bytes:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
        "utf-8"
    )
    if not 0 < len(raw) <= LIMIT:
        raise ValueError("gateway socket record size")
    return struct.pack("!I", len(raw)) + raw


def send(stream: socket.socket, value: dict[str, Any], *, timeout: float | None = None) -> None:
    frame = _frame(value)
    if timeout is not None:
        stream.settimeout(timeout)
    stream.sendall(frame)


def exchange(path: str | Path, value: dict[str, Any], timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout

    def remaining() -> float:
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise TimeoutError("socket exchange deadline expired")
        return seconds

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
        stream.settimeout(remaining())
        stream.connect(str(path))
        send(stream, value, timeout=remaining())
        return receive(stream, timeout=remaining())


async def async_exchange(path: str | Path, value: dict[str, Any], timeout: float) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
        stream.setblocking(False)

        async def read_exact(count: int) -> bytes:
            chunks = []
            while count:
                part = await loop.sock_recv(stream, count)
                if not part:
                    raise EOFError("incomplete gateway socket record")
                chunks.append(part)
                count -= len(part)
            return b"".join(chunks)

        async with asyncio.timeout(timeout):
            await loop.sock_connect(stream, str(path))
            await loop.sock_sendall(stream, _frame(value))
            size = struct.unpack("!I", await read_exact(4))[0]
            if not 0 < size <= LIMIT:
                raise ValueError("gateway socket record size")
            return _decode_record(await read_exact(size))
