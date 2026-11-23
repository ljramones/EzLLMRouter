"""Hostile archive inputs must fail before a qualification volume is changed."""

import io
import hashlib
import os
from pathlib import Path
import tarfile
import tempfile
import unittest

from tools.qualification_storage import archive_members
from tools.volume_archive import create, restore, validate


class VolumeArchiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.owners = frozenset({os.getuid(), os.getgid()})

    def test_pax_and_file_ancestor_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "archive.tar"
            for variant in ("pax", "ancestor"):
                with tarfile.open(path, "w", format=tarfile.PAX_FORMAT) as archive:
                    member = tarfile.TarInfo("file")
                    member.uid = member.gid = 10001
                    member.mode = 0o600
                    if variant == "pax":
                        member.pax_headers = {"comment": "synthetic parser differential"}
                    archive.addfile(member, io.BytesIO())
                    if variant == "ancestor":
                        member = tarfile.TarInfo("file/child")
                        member.uid = member.gid = 10001
                        member.mode = 0o600
                        archive.addfile(member, io.BytesIO())
                with self.subTest(variant=variant), self.assertRaises(ValueError):
                    archive_members(path)

    def archive(self, members):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for name, kind, data in members:
                member = tarfile.TarInfo(name)
                member.type = kind
                member.uid, member.gid, member.mode = os.getuid(), os.getgid(), 0o700
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        return output.getvalue()

    def test_private_content_owners_modes_and_nested_directories_roundtrip(self):
        source, target = self.root / "source", self.root / "target"
        source.mkdir(mode=0o700)
        target.mkdir(mode=0o700)
        (source / "nested").mkdir(mode=0o750)
        payload = source / "nested" / "data"
        payload.write_bytes(b"synthetic\x00payload" * 5000)
        payload.chmod(0o640)
        output = io.BytesIO()
        create(source, output, owners=self.owners)
        data = output.getvalue()
        result = restore(
            target, io.BytesIO(data), hashlib.sha256(data).hexdigest(), owners=self.owners
        )
        self.assertEqual(result["members"], 3)
        self.assertEqual((target / "nested/data").read_bytes(), payload.read_bytes())
        for path in (".", "nested", "nested/data"):
            before, after = (source / path).stat(), (target / path).stat()
            self.assertEqual(
                (before.st_uid, before.st_gid, before.st_mode),
                (after.st_uid, after.st_gid, after.st_mode),
            )
            self.assertEqual(int(before.st_mtime), int(after.st_mtime))

    def test_hostile_or_changed_archive_leaves_destination_untouched(self):
        data = self.archive([("file", tarfile.REGTYPE, b"payload")])
        cases = [
            (data, "0" * 64),
            (data[:700], None),
            (data + data, None),
            (self.archive([("../escape", tarfile.REGTYPE, b"")]), None),
            (self.archive([("file", tarfile.SYMTYPE, b"")]), None),
            (self.archive([("file", tarfile.LNKTYPE, b"")]), None),
            (self.archive([("file", tarfile.FIFOTYPE, b"")]), None),
            (self.archive([("file", tarfile.GNUTYPE_SPARSE, b"")]), None),
            (
                self.archive(
                    [("file", tarfile.REGTYPE, b""), ("file/child", tarfile.REGTYPE, b"")]
                ),
                None,
            ),
        ]
        for index, (archive, digest) in enumerate(cases):
            target = self.root / str(index)
            target.mkdir()
            with self.subTest(index=index), self.assertRaises(ValueError):
                restore(
                    target,
                    io.BytesIO(archive),
                    digest or hashlib.sha256(archive).hexdigest(),
                    owners=self.owners,
                )
            self.assertEqual(list(target.iterdir()), [])
        self.assertFalse((self.root / "escape").exists())

    def test_existing_destination_and_symlink_root_are_not_overwritten(self):
        data = self.archive([("file", tarfile.REGTYPE, b"replacement")])
        target = self.root / "target"
        target.mkdir()
        (target / "file").write_bytes(b"original")
        with self.assertRaises(ValueError):
            restore(target, io.BytesIO(data), hashlib.sha256(data).hexdigest(), owners=self.owners)
        self.assertEqual((target / "file").read_bytes(), b"original")
        link = self.root / "link"
        link.symlink_to(target, target_is_directory=True)
        with self.assertRaises(OSError):
            restore(link, io.BytesIO(data), hashlib.sha256(data).hexdigest(), owners=self.owners)

    def test_source_links_special_files_and_mid_copy_mutation_are_rejected(self):
        from unittest.mock import patch

        source = self.root / "source"
        source.mkdir()
        payload = source / "file"
        payload.write_bytes(b"original")
        for kind in ("symlink", "hardlink", "fifo"):
            link = source / "link"
            if kind == "symlink":
                link.symlink_to(payload)
            elif kind == "hardlink":
                os.link(payload, link)
            else:
                os.mkfifo(link, 0o600)
            with self.subTest(kind=kind), self.assertRaises((ValueError, OSError)):
                create(source, io.BytesIO(), owners=self.owners)
            link.unlink()
        original = tarfile.TarFile.addfile

        def mutate(archive, member, fileobj=None):
            original(archive, member, fileobj)
            if member.name == "file":
                payload.write_bytes(b"changed!")

        with patch.object(tarfile.TarFile, "addfile", mutate), self.assertRaises(ValueError):
            create(source, io.BytesIO(), owners=self.owners)

    def test_byte_member_limits_duplicate_paths_and_padding_are_enforced(self):
        from unittest.mock import patch

        data = self.archive([("file", tarfile.REGTYPE, b"payload")])
        with patch("tools.volume_archive.MAX_BYTES", 1024), self.assertRaises(ValueError):
            validate(io.BytesIO(data), owners=self.owners)
        duplicate = self.archive([("file", tarfile.REGTYPE, b""), ("file", tarfile.REGTYPE, b"")])
        with self.assertRaises(ValueError):
            validate(io.BytesIO(duplicate), owners=self.owners)
        damaged = bytearray(data)
        damaged[519] = 1
        with self.assertRaises(ValueError):
            validate(io.BytesIO(damaged), owners=self.owners)
        with patch("tools.volume_archive.MAX_MEMBERS", 0), self.assertRaises(ValueError):
            validate(io.BytesIO(data), owners=self.owners)


if __name__ == "__main__":
    unittest.main()
