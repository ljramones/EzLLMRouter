"""Codec custody requires both reviewed copies and the actual native build parent."""

from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest

from tools.gateway import codec_inputs, native_inputs, os_inputs

ROOT = Path(__file__).resolve().parents[2]


class CodecInputTests(unittest.TestCase):
    def test_resealed_parent_source_recipe_copy_and_origin_substitutions_fail(self):
        original = os_inputs.load_lock(ROOT)
        for change in ("parent", "node", "source", "recipe", "copy", "origin", "version"):
            data = deepcopy(original)
            record = data["native_codec"]
            if change == "parent":
                record["inputs"]["native_build"] = "0" * 64
            elif change == "node":
                record["inputs"]["node_sha256"] = "0" * 64
            elif change == "source":
                record["inputs"]["artifacts"]["zstd-1.6.0.tar.gz"]["sha256"] = "0" * 64
            elif change == "recipe":
                record["inputs"]["recipes"]["../unreviewed.sh"] = "0" * 64
            elif change == "copy":
                del record["code"][codec_inputs.LIBRARY]
            elif change == "version":
                record["source_version"] = "1.5.7+ezllmrouter1"
            record["id"] = native_inputs.canonical(record["inputs"])
            selected = next(row for row in data["packages"] if "native_codec" in row)
            selected["native_codec"] = record["id"]
            selected["url"] = (
                "urn:ezllmrouter:native-codec:" + record["id"] + ":" + codec_inputs.PACKAGE
            )
            if change == "origin":
                selected["url"] = "https://example.invalid/unreviewed.deb"
            with self.subTest(change=change), self.assertRaises(ValueError):
                os_inputs.validate_lock(data)

    def test_selected_node_overrides_parent_and_old_formats_reject_codec_provenance(self):
        data = os_inputs.load_lock(ROOT)
        path, output = codec_inputs.node_output(Path("store"), data)
        self.assertIn("native-codec", path.parts)
        self.assertEqual(output["sha256"], data["native_codec"]["code"]["/usr/local/bin/node"])
        data["format"] = "ezllmrouter-debian-inputs-v3"
        with self.assertRaises(ValueError):
            os_inputs.validate_lock(data)

    def test_changed_linked_or_extra_outputs_fail_closed(self):
        for change in (None, "changed", "linked", "extra"):
            data = deepcopy(os_inputs.load_lock(ROOT))
            record = data["native_codec"]
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                store = Path(temporary)
                directory = codec_inputs.directory(store, record)
                directory.mkdir(parents=True)
                for name, row in record["outputs"].items():
                    payload = ("reviewed fixture " + name).encode()
                    (directory / name).write_bytes(payload)
                    row.update(bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
                target = directory / codec_inputs.NODE
                if change == "changed":
                    target.write_bytes(b"substituted")
                elif change == "linked":
                    target.rename(store / "linked")
                    target.symlink_to(store / "linked")
                elif change == "extra":
                    (directory / "extra").touch()
                if change is None:
                    codec_inputs.verify_outputs(store, data)
                else:
                    with self.assertRaises(ValueError):
                        codec_inputs.verify_outputs(store, data)
