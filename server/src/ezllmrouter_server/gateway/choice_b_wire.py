"""Small bounded JSON record used only by the DEV-04 Choice B Unix sockets."""
import json
import struct
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


def _read_exact(stream, count):
    chunks = []
    while count:
        part = stream.recv(count)
        if not part:
            raise EOFError("incomplete DEV-04 socket record")
        chunks.append(part)
        count -= len(part)
    return b"".join(chunks)


def receive(stream):
    size = struct.unpack("!I", _read_exact(stream, 4))[0]
    if not 0 < size <= LIMIT:
        raise ValueError("DEV-04 socket record size")
    value = json.loads(_read_exact(stream, size))
    if type(value) is not dict:
        raise ValueError("DEV-04 socket record shape")
    return value


def send(stream, value):
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                     allow_nan=False).encode("utf-8")
    if not 0 < len(raw) <= LIMIT:
        raise ValueError("DEV-04 socket record size")
    stream.sendall(struct.pack("!I", len(raw)) + raw)
