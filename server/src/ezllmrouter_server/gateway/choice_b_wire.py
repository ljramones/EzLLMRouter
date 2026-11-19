"""Small bounded JSON record used only by the DEV-04 Choice B Unix sockets."""
import json
import struct


LIMIT = 262144


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
