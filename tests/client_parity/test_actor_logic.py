"""Installed-client actor controls for explicit attempt budget and drain time."""

import ast
import copy
import json
from pathlib import Path
import time
import types
import unittest
from unittest import mock

# Exercise the actor's actual pure helpers without importing its installed-only
# deployment assertions or constructing network clients in the development tree.
ROOT = Path(__file__).resolve().parents[2]
source = Path(__file__).with_name("integration_python.py")
tree = ast.parse(source.read_text())
actor = types.ModuleType("actor_logic_under_test")
actor.copy, actor.time = copy, time
actor.BASE = json.loads((ROOT / "tests/development_slice/request.json").read_text())
actor.CORPUS = {
    item["id"]: item for item in json.loads(source.with_name("scenarios.json").read_text())["cases"]
}


def no_network():
    raise AssertionError("Actor helper tests must inject receiver observations")


actor.arrivals = no_network
helpers = [
    node
    for node in tree.body
    if isinstance(node, ast.FunctionDef) and node.name in {"case_request", "no_send_drain"}
]
exec(compile(ast.Module(body=helpers, type_ignores=[]), str(source), "exec"), actor.__dict__)


class ActorLogic(unittest.TestCase):
    def test_pending_attempt_budget_is_in_submitted_request(self):
        for case in (
            "retained_pending",
            "no_store_expiry",
            "retained_pending_js",
            "no_store_expiry_js",
        ):
            with self.subTest(case=case):
                item = actor.CORPUS[case]
                request = actor.case_request(item)
                self.assertEqual(request["generation_settings"]["total_timeout_ms"], 3000)
                self.assertEqual(item["wait_ms"], 0)

    def test_no_send_drain_holds_for_at_least_500_ms(self):
        with mock.patch.object(actor, "arrivals", return_value=[]):
            start = time.monotonic()
            observed, elapsed = actor.no_send_drain(0)
        self.assertEqual(observed, [])
        self.assertGreaterEqual(elapsed, 500)
        self.assertGreaterEqual((time.monotonic() - start) * 1000, 500)

    def test_no_send_drain_rejects_new_arrival(self):
        with mock.patch.object(actor, "arrivals", side_effect=[[], [{"sequence": 1}]]) as fetch:
            with self.assertRaisesRegex(AssertionError, "unexpected receiver send"):
                actor.no_send_drain(0)
        self.assertEqual(fetch.call_count, 2)


if __name__ == "__main__":
    unittest.main()
