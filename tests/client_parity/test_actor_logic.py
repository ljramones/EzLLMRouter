"""Installed-client actor controls for explicit attempt budget and drain time."""
import time
import unittest
from unittest import mock

import integration_python as actor


class ActorLogic(unittest.TestCase):
    def test_pending_attempt_budget_is_in_submitted_request(self):
        for case in ("retained_pending", "no_store_expiry", "retained_pending_js", "no_store_expiry_js"):
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
