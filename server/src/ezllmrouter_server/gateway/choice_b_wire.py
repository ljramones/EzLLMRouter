"""Small bounded JSON record used only by the DEV-04 Choice B Unix sockets."""

import json
import asyncio
import socket
import struct
import time
from datetime import datetime, timezone


LIMIT = 262144
MAX_ATTEMPT_TIMEOUT_MS = 300_000


def remaining_seconds(timeout_ms, deadline):
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


def _read_exact(stream, count, deadline=None):
    chunks = []
    while count:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("socket frame deadline expired")
            stream.settimeout(remaining)
        part = stream.recv(count)
        if not part:
            raise EOFError("incomplete DEV-04 socket record")
        chunks.append(part)
        count -= len(part)
    return b"".join(chunks)


def receive(stream, *, timeout=None):
    deadline = None if timeout is None else time.monotonic() + timeout
    size = struct.unpack("!I", _read_exact(stream, 4, deadline))[0]
    if not 0 < size <= LIMIT:
        raise ValueError("DEV-04 socket record size")
    value = json.loads(_read_exact(stream, size, deadline))
    if type(value) is not dict:
        raise ValueError("DEV-04 socket record shape")
    return value


def _frame(value):
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
        "utf-8"
    )
    if not 0 < len(raw) <= LIMIT:
        raise ValueError("DEV-04 socket record size")
    return struct.pack("!I", len(raw)) + raw


def send(stream, value, *, timeout=None):
    frame = _frame(value)
    if timeout is not None:
        stream.settimeout(timeout)
    stream.sendall(frame)


def exchange(path, value, timeout):
    deadline = time.monotonic() + timeout

    def remaining():
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise TimeoutError("socket exchange deadline expired")
        return seconds

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
        stream.settimeout(remaining())
        stream.connect(str(path))
        send(stream, value, timeout=remaining())
        return receive(stream, timeout=remaining())


async def async_exchange(path, value, timeout):
    # Owning the nonblocking socket in this task makes cancellation close it;
    # asyncio.to_thread would leave a blocked exchange alive until its timeout.
    loop = asyncio.get_running_loop()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
        stream.setblocking(False)

        async def read_exact(count):
            chunks = []
            while count:
                part = await loop.sock_recv(stream, count)
                if not part:
                    raise EOFError("incomplete DEV-04 socket record")
                chunks.append(part)
                count -= len(part)
            return b"".join(chunks)

        async with asyncio.timeout(timeout):
            await loop.sock_connect(stream, str(path))
            await loop.sock_sendall(stream, _frame(value))
            size = struct.unpack("!I", await read_exact(4))[0]
            if not 0 < size <= LIMIT:
                raise ValueError("DEV-04 socket record size")
            result = json.loads(await read_exact(size))
            if type(result) is not dict:
                raise ValueError("DEV-04 socket record shape")
            return result
