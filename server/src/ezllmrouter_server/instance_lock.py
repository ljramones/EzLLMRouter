"""A canonical sidecar lease separates service/maintenance exclusion from SQLite locks."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
import stat
from types import TracebackType

from .errors import ServerError


class InstanceBusy(ServerError, RuntimeError):
    pass


class InstanceLease:
    def __init__(self, path: str | Path, *, exclusive: bool = False, create: bool = False):
        self.descriptor: int | None = None
        if str(path) == ":memory:":
            if exclusive:
                raise ValueError("maintenance requires a persistent database")
            return
        database = Path(path).resolve()
        if database.exists() and database.stat().st_nlink != 1:
            raise ValueError("hard-linked database paths are unsupported")
        if not create and not database.is_file():
            raise ValueError("an existing database is required")
        self.path = database.with_name(database.name + ".instance.lock")
        descriptor = os.open(
            self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, 0o600
        )
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_mode & 0o077
                or metadata.st_uid != os.geteuid()
                or metadata.st_nlink != 1
            ):
                raise ValueError("instance lease must be an owner-only regular file")
            try:
                fcntl.flock(
                    descriptor, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB
                )
            except BlockingIOError as exc:
                raise InstanceBusy("INSTANCE_IN_USE") from exc
            self.descriptor = descriptor
            self.verify()
        except BaseException:
            self.descriptor = None
            os.close(descriptor)
            raise

    def verify(self) -> None:
        if self.descriptor is not None:
            held, current = os.fstat(self.descriptor), self.path.lstat()
            if (held.st_dev, held.st_ino) != (current.st_dev, current.st_ino):
                raise RuntimeError("instance lease identity changed during open")

    def close(self) -> None:
        if self.descriptor is not None:
            descriptor, self.descriptor = self.descriptor, None
            os.close(descriptor)

    def __enter__(self) -> InstanceLease:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
