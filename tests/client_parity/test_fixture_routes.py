"""Check the approved synthetic route and unchanged adapter guard offline."""
from pathlib import Path
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/src"))
sys.path.insert(0, str(ROOT / "tests/development_slice"))

from native_adapter import NativeSyntheticAdapter
from synthetic_routes import fixture_destination

BASE = json.loads((ROOT / "tests/development_slice/fixture.json").read_text())["destination"]


class FixtureRoutes(unittest.TestCase):
    def test_approved_routes_bind_matching_destination_and_attempt_budget(self):
        for host in ("receiver", "receiver_delay", "receiver_fail"):
            with self.subTest(host=host):
                url = f"http://{host}:8766/v1/chat/completions"
                config = fixture_destination(BASE, url)
                self.assertEqual(config["endpoint"], host)
                self.assertEqual(BASE["endpoint"], "receiver")
                adapter = NativeSyntheticAdapter(url, config["endpoint"])
                described = adapter.describe(b"{}", 3000, config)
                self.assertEqual((described["url"], described["timeout_ms"]), (url, 3000))
                if host != "receiver":
                    with self.assertRaisesRegex(ValueError, "synthetic destination mismatch"):
                        NativeSyntheticAdapter(url, "receiver")

    def test_other_routes_rejected_before_adapter(self):
        for url in ("http://receiver_other:8766/v1/chat/completions",
                    "http://receiver:8767/v1/chat/completions",
                    "http://receiver:8766/other", "https://receiver:8766/v1/chat/completions"):
            with self.subTest(url=url):
                with self.assertRaisesRegex(ValueError, "unapproved synthetic fixture destination"):
                    fixture_destination(BASE, url)

    def test_pending_cases_declare_longer_attempt_budget(self):
        corpus = json.loads((ROOT / "tests/client_parity/scenarios.json").read_text())
        pending = [item for item in corpus["cases"] if item.get("expected_state") == "pending"]
        self.assertEqual(len(pending), 4)
        for item in pending:
            self.assertEqual(item["wait_ms"], 0)
            self.assertEqual(item["total_timeout_ms"], 3000)


if __name__ == "__main__":
    unittest.main()
