"""Native provenance and output custody reject substitutions before Docker runs."""

from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest

from tools.gateway import native_inputs, os_inputs

ROOT = Path(__file__).resolve().parents[2]


class NativeInputTests(unittest.TestCase):
    def data(self):
        return deepcopy(os_inputs.load_lock(ROOT))

    def reseal(self, data):
        native = data["native_build"]
        native["id"] = native_inputs.canonical(native["inputs"])
        for row in data["packages"]:
            if "native_build" in row:
                row["native_build"] = native["id"]
                row["url"] = "urn:ezllmrouter:native-build:" + native["id"] + ":" + row["filename"]

    def test_native_inputs_bind_exact_recipes_and_parent_image(self):
        data = self.data()
        native_inputs.validate(data)
        native_inputs.verify_recipes(ROOT, data["native_build"])
        data["native_build"]["inputs"]["builder"] = "docker.io/library/python@sha256:" + "0" * 64
        self.reseal(data)
        with self.assertRaises(ValueError):
            native_inputs.validate(data)

    def test_resealed_unsafe_sources_or_incomplete_copy_bindings_are_rejected(self):
        for change in ("path", "url", "copy", "patch", "origin", "version"):
            data = self.data()
            native = data["native_build"]
            with self.subTest(change=change):
                if change == "path":
                    native["inputs"]["artifacts"]["../escape"] = next(
                        iter(native["inputs"]["artifacts"].values())
                    )
                elif change == "url":
                    next(iter(native["inputs"]["artifacts"].values()))["url"] = (
                        "http://example.invalid/source"
                    )
                elif change == "copy":
                    native["code"].pop()
                elif change == "patch":
                    next(iter(native["fixed_advisories"].values()))["patch_sha256"] = "0" * 64
                elif change == "origin":
                    row = next(row for row in data["packages"] if "native_build" in row)
                    row["url"] = "https://deb.debian.org/debian/pool/main/f/fake.deb"
                else:
                    native["node"]["version"] = "25.0.0"
                if change != "origin":
                    self.reseal(data)
                with self.assertRaises(ValueError):
                    native_inputs.validate(data)

    def test_old_lock_formats_cannot_approve_local_build_origins(self):
        data = self.data()
        data["format"] = "ezllmrouter-debian-inputs-v3"
        with self.assertRaises(ValueError):
            os_inputs.validate_lock(data)

    def test_runtime_output_bytes_links_and_extra_files_are_checked(self):
        for change in (None, "bytes", "link", "extra"):
            native = self.data()["native_build"]
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                store = Path(temporary)
                directory = native_inputs.directory(store, native)
                directory.mkdir(parents=True)
                for name, row in native["outputs"].items():
                    raw = ("reviewed fixture " + name).encode()
                    (directory / name).write_bytes(raw)
                    row.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
                node = directory / native["node"]["filename"]
                if change == "bytes":
                    node.write_bytes(node.read_bytes() + b"changed")
                elif change == "link":
                    target = store / "linked-fixture"
                    node.rename(target)
                    node.symlink_to(target)
                elif change == "extra":
                    (directory / "unreviewed").write_text("extra")
                if change is None:
                    native_inputs.verify_outputs(store, native)
                else:
                    with self.assertRaises(ValueError):
                        native_inputs.verify_outputs(store, native)
