"""A local PostgreSQL bundle cannot lose its reviewed source/output identity."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tools.gateway import driver_inputs, native_inputs, os_inputs

ROOT = Path(__file__).resolve().parents[2]


class DriverInputTests(unittest.TestCase):
    def data(self):
        return deepcopy(os_inputs.load_lock(ROOT))

    def test_selected_driver_matches_frozen_inventory_and_exact_native_features(self):
        data = self.data()
        driver_inputs.validate(data)
        driver_inputs.verify_frozen(ROOT, data)
        data["native_driver"]["features"]["gssapi"] = True
        with self.assertRaises(ValueError):
            driver_inputs.validate(data)

    def test_resealing_an_unsafe_recipe_or_unbound_ssl_parent_is_rejected(self):
        for change in ("path", "parent", "copy", "origin"):
            data = self.data()
            record = data["native_driver"]
            if change == "path":
                record["inputs"]["recipes"]["../escape.py"] = "0" * 64
            elif change == "parent":
                record["inputs"]["openssl_native_build"] = "0" * 64
            elif change == "copy":
                record["code"].pop(next(iter(record["code"])))
            else:
                next(iter(record["inputs"]["artifacts"].values()))["url"] = (
                    "https://example.invalid/unreviewed"
                )
            record["id"] = native_inputs.canonical(record["inputs"])
            with self.subTest(change=change), self.assertRaises(ValueError):
                driver_inputs.validate(data)

    def test_local_wheel_without_its_build_review_is_rejected(self):
        data = self.data()
        del data["native_driver"]
        with self.assertRaisesRegex(ValueError, "lacks"):
            driver_inputs.verify_frozen(ROOT, data)

    def test_output_bytes_and_unrecorded_files_are_not_accepted(self):
        data = self.data()
        with tempfile.TemporaryDirectory() as temporary:
            store = Path(temporary)
            record = data["native_driver"]
            path = store / "inputs/native-driver" / record["id"]
            path.mkdir(parents=True)
            (path / record["filename"]).write_bytes(b"unreviewed wheel")
            with self.assertRaisesRegex(ValueError, "identity"):
                driver_inputs.verify_outputs(store, data)
            (path / "extra").write_text("unexpected")
            with self.assertRaisesRegex(ValueError, "unexpected"):
                driver_inputs.verify_outputs(store, data)
