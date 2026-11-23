"""Strict, bounded cold-copy format for disposable qualification volumes only.

One physical USTAR parser validates and restores: no PAX, GNU extensions, links,
special files or extraction through tar utilities. Payloads never enter logs.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tarfile
import tempfile
from typing import BinaryIO

MAX_BYTES = 128 * 1024 * 1024
MAX_MEMBERS = 16384
OWNERS = frozenset({0, 10001})
CHUNK = 65536
DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


@dataclass(frozen=True)
class Entry:
    member: tarfile.TarInfo
    offset: int


def metadata(member: tarfile.TarInfo, owners: frozenset[int]) -> None:
    if (
        member.type not in {tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE}
        or member.uid not in owners
        or member.gid not in owners
        or member.mode < 0
        or member.mode & 0o7022
        or not isinstance(member.mtime, int)
        or member.mtime < 0
        or member.size < 0
        or member.size > MAX_BYTES
        or (member.isdir() and member.size != 0)
    ):
        raise ValueError("unsafe disposable volume metadata")


def validate(stream: BinaryIO, *, owners: frozenset[int] = OWNERS) -> list[Entry]:
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    if not 1024 <= size <= MAX_BYTES or size % 512:
        raise ValueError("invalid disposable volume archive size")
    stream.seek(0)
    entries = []
    names: dict[str, bool] = {}
    while True:
        header = stream.read(512)
        if header == bytes(512):
            tail = stream.read()
            if len(tail) < 512 or any(tail) or not entries:
                raise ValueError("invalid disposable volume archive terminator")
            return entries
        if len(header) != 512 or header[257:263] != b"ustar\0":
            raise ValueError("only physical USTAR headers are accepted")
        try:
            member = tarfile.TarInfo.frombuf(header, "utf-8", "strict")
        except (tarfile.HeaderError, UnicodeError, ValueError) as error:
            raise ValueError("invalid disposable volume header") from error
        metadata(member, owners)
        name = member.name.rstrip("/") if member.isdir() else member.name
        path = PurePosixPath(name)
        if (
            not name
            or name != str(path)
            or path.is_absolute()
            or ".." in path.parts
            or name in names
            or (name == "." and not member.isdir())
            or (str(path.parent) != "." and names.get(str(path.parent)) is not True)
            or len(entries) >= MAX_MEMBERS
        ):
            raise ValueError("unsafe disposable volume path")
        names[name] = member.isdir()
        offset = stream.tell()
        entries.append(Entry(member, offset))
        end = offset + ((member.size + 511) // 512) * 512
        if end > size - 1024:
            raise ValueError("truncated disposable volume payload")
        # Padding is part of this restricted format, rather than hidden data.
        stream.seek(offset + member.size)
        if any(stream.read(end - stream.tell())):
            raise ValueError("nonzero disposable volume padding")
        stream.seek(end)


def archive_members(path: Path) -> int:
    with path.open("rb") as stream:
        return len(validate(stream))


class BoundedWriter:
    def __init__(self, stream: BinaryIO):
        self.stream = stream
        self.bytes = 0

    def write(self, data: bytes) -> int:
        if self.bytes + len(data) > MAX_BYTES:
            raise ValueError("disposable volume archive exceeds byte limit")
        written = self.stream.write(data)
        if written != len(data):
            raise OSError("short archive write")
        self.bytes += written
        return written


def unchanged(before: os.stat_result, after: os.stat_result) -> bool:
    return all(
        getattr(before, key) == getattr(after, key)
        for key in (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_uid",
            "st_gid",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
    )


def create(root: Path, output: BinaryIO, *, owners: frozenset[int] = OWNERS) -> None:
    count = 0
    with tarfile.open(
        fileobj=BoundedWriter(output), mode="w|", format=tarfile.USTAR_FORMAT
    ) as archive:

        def add(fd: int, name: str) -> None:
            nonlocal count
            before = os.fstat(fd)
            member = tarfile.TarInfo(name)
            member.uid, member.gid = before.st_uid, before.st_gid
            member.mode = stat.S_IMODE(before.st_mode)
            member.mtime = int(before.st_mtime)
            directory = stat.S_ISDIR(before.st_mode)
            if not directory and (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1):
                raise ValueError("only unlinked regular files and directories may be copied")
            member.type = tarfile.DIRTYPE if directory else tarfile.REGTYPE
            member.size = 0 if directory else before.st_size
            metadata(member, owners)
            count += 1
            if count > MAX_MEMBERS:
                raise ValueError("too many disposable volume members")
            if directory:
                archive.addfile(member)
                for child in sorted(os.listdir(fd)):
                    child_stat = os.stat(child, dir_fd=fd, follow_symlinks=False)
                    if not (stat.S_ISREG(child_stat.st_mode) or stat.S_ISDIR(child_stat.st_mode)):
                        raise ValueError("special files and links cannot be archived")
                    child_fd = os.open(
                        child, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd
                    )
                    try:
                        if not unchanged(child_stat, os.fstat(child_fd)):
                            raise ValueError("source volume changed before opening member")
                        add(child_fd, child if name == "." else name + "/" + child)
                    finally:
                        os.close(child_fd)
            else:
                with os.fdopen(os.dup(fd), "rb") as payload:
                    archive.addfile(member, payload)
            if not unchanged(before, os.fstat(fd)):
                raise ValueError("source volume changed during cold copy")

        root_fd = os.open(root, DIRECTORY)
        try:
            add(root_fd, ".")
        finally:
            os.close(root_fd)


def parent_fd(root_fd: int, name: str) -> int:
    fd = os.dup(root_fd)
    try:
        for part in PurePosixPath(name).parent.parts:
            child = os.open(part, DIRECTORY, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def apply_metadata(fd: int, member: tarfile.TarInfo) -> None:
    current = os.fstat(fd)
    if (current.st_uid, current.st_gid) != (member.uid, member.gid):
        os.fchown(fd, member.uid, member.gid)
    os.fchmod(fd, member.mode)
    os.utime(fd, (member.mtime, member.mtime))
    os.fsync(fd)


def restore(
    root: Path, source: BinaryIO, expected: str, *, owners: frozenset[int] = OWNERS
) -> dict:
    if not isinstance(expected, str) or re.fullmatch("[0-9a-f]{64}", expected) is None:
        raise ValueError("invalid expected archive digest")
    # Hash and validate the whole stream before touching the destination. The
    # private spool also prevents a changed host file from bypassing validation.
    with tempfile.TemporaryFile() as stream:
        digest = hashlib.sha256()
        size = 0
        while chunk := source.read(CHUNK):
            size += len(chunk)
            if size > MAX_BYTES:
                raise ValueError("disposable volume archive exceeds byte limit")
            digest.update(chunk)
            stream.write(chunk)
        if not hmac.compare_digest(digest.hexdigest(), expected):
            raise ValueError("disposable volume archive digest mismatch")
        entries = validate(stream, owners=owners)
        root_fd = os.open(root, DIRECTORY)
        directories = []
        try:
            if os.listdir(root_fd):
                raise ValueError("restore destination must be empty")
            for entry in entries:
                member = entry.member
                name = member.name.rstrip("/") if member.isdir() else member.name
                if name == ".":
                    directories.append((name, member))
                    continue
                parent = parent_fd(root_fd, name)
                try:
                    leaf = PurePosixPath(name).name
                    if member.isdir():
                        os.mkdir(leaf, 0o700, dir_fd=parent)
                        directories.append((name, member))
                    else:
                        fd = os.open(
                            leaf,
                            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                            0o600,
                            dir_fd=parent,
                        )
                        with os.fdopen(fd, "wb") as output:
                            stream.seek(entry.offset)
                            remaining = member.size
                            while remaining:
                                chunk = stream.read(min(CHUNK, remaining))
                                if not chunk:
                                    raise ValueError("truncated disposable volume payload")
                                output.write(chunk)
                                remaining -= len(chunk)
                            output.flush()
                            apply_metadata(output.fileno(), member)
                finally:
                    os.close(parent)
            for name, member in reversed(directories):
                parent = parent_fd(root_fd, name)
                try:
                    fd = os.open(
                        "." if name == "." else PurePosixPath(name).name, DIRECTORY, dir_fd=parent
                    )
                    try:
                        apply_metadata(fd, member)
                    finally:
                        os.close(fd)
                finally:
                    os.close(parent)
            os.fsync(root_fd)
        finally:
            os.close(root_fd)
        return {"sha256": digest.hexdigest(), "members": len(entries), "bytes": size}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("create", "restore"))
    parser.add_argument("--sha256")
    args = parser.parse_args()
    if args.mode == "create":
        create(Path("/volume"), sys.stdout.buffer)
    else:
        print(json.dumps(restore(Path("/volume"), sys.stdin.buffer, args.sha256)))


if __name__ == "__main__":
    main()
