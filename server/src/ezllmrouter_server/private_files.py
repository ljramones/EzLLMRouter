"""Atomic, owner-only files for local secrets and bootstrap recovery."""

from __future__ import annotations

import os
from pathlib import Path
import secrets
import stat


def read_private(path: Path, *, limit: int = 8192) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
            raise ValueError("secret must be an owner-only regular file")
        value = stream.read(limit + 1)
        if len(value) > limit:
            raise ValueError("secret file exceeds its size limit")
        return value


def write_private(path: Path, value: bytes, *, replace: bool = False) -> None:
    """Publish complete bytes with mode 0600; never replace an existing secret implicitly."""
    temporary = path.with_name("." + path.name + "." + secrets.token_hex(12) + ".new")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def secret_text(path: Path, *, replace: bool = False) -> str:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.parent.stat().st_mode & 0o077:
        raise ValueError("secret directory must be owner-only")
    if replace or not path.exists():
        value = secrets.token_urlsafe(48)
        try:
            write_private(path, (value + "\n").encode("ascii"), replace=replace)
        except FileExistsError:
            if replace:
                raise
    return read_private(path).decode("ascii").strip()
