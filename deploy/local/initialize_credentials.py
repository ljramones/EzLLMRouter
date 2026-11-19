"""Deliver host-private credentials to the service UID through a dedicated volume.

Runs only during explicit profile setup, with no network or host mounts. Input
is bounded stdin, never command arguments or environment variables.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import sys


def initialize(payload: bytes, directory: Path) -> None:
    if len(payload) > 8192:
        raise ValueError("credential input exceeds its size limit")
    saved = json.loads(payload)
    credentials, password = saved["credentials"], saved["operator_password"]
    if (set(credentials) != {"service_token", "synthetic_provider_key"}
            or not all(isinstance(value, str) and 32 <= len(value) <= 1024
                       for value in (*credentials.values(), password))):
        raise ValueError("invalid profile credentials")
    if directory.is_symlink():
        raise ValueError("credential volume must not be a symlink")
    # Root retains write access for atomic replacement on subsequent setup.
    # UID 10001 can traverse but cannot list the directory or modify the volume.
    directory.mkdir(mode=0o711, parents=True, exist_ok=True)
    os.chown(directory, 0, 0)
    directory.chmod(0o711)
    for name, content in (("credentials.json", json.dumps(credentials) + "\n"),
                          ("operator-password", password + "\n")):
        temporary = directory / ("." + name + "." + secrets.token_hex(12))
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content.encode("ascii"))
                stream.flush()
                os.fchown(stream.fileno(), 10001, 10001)
                os.fchmod(stream.fileno(), 0o400)
                os.fsync(stream.fileno())
            os.replace(temporary, directory / name)
        finally:
            temporary.unlink(missing_ok=True)
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


if __name__ == "__main__":
    initialize(sys.stdin.buffer.read(8193), Path("/run/ezllmrouter"))
