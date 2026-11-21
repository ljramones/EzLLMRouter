"""Force both orders of campaign close versus admission without scheduling sleeps."""

from concurrent.futures import ThreadPoolExecutor
import threading
import unittest

from ezllmrouter_server.canonical import ContractError
from tests.operator_console import test_personal_campaign as support


class CampaignInterleavingTests(unittest.TestCase):
    setUp = support.CampaignTests.setUp
    _record = support.CampaignTests._record
    _reserve = support.CampaignTests._reserve

    def activate(self):
        self.campaign.configure("owner.local", self.config)
        self.campaign.transition("owner.local", "active")

    def test_reservation_commits_before_close_and_exposure_is_retained(self):
        self.activate()
        entered, release, closing = threading.Event(), threading.Event(), threading.Event()
        record = self._record("close-race")

        def reserve():
            def at_reservation(db, item):
                entered.set()
                if not release.wait(3):
                    raise AssertionError("reservation checkpoint was not released")
                return self.campaign.reserve(db, item, 20, 16)

            # Match the real admission's authority-before-database lock order.
            with self.registry.send_authority.gate:
                self.store.create(record, reserve=at_reservation)

        def close():
            closing.set()
            return self.campaign.transition("owner.local", "closed")

        with ThreadPoolExecutor(max_workers=2) as executor:
            reserved = executor.submit(reserve)
            try:
                self.assertTrue(entered.wait(2))
                closed = executor.submit(close)
                self.assertTrue(closing.wait(2))
                self.assertFalse(closed.done())
            finally:
                release.set()
            reserved.result(timeout=3)
            self.assertEqual(closed.result(timeout=3)["state"], "closed")
        summary = self.campaign.summary()
        self.assertEqual(summary["request_count"], 1)
        self.assertEqual(summary["attempts"][0]["state"], "reserved")
        self.assertEqual(summary["outstanding_decimal"], summary["attempts"][0]["bound_decimal"])
        self.campaign.settle(
            record["attempt_id"],
            {"cost": {"status": "calculated", "currency": "USD", "amount_decimal": "0.001"}},
        )
        self.assertEqual(self.campaign.summary()["incurred_decimal"], "0.001")
        self.assertEqual(self.campaign.summary()["state"], "closed")

    def test_close_commits_before_waiting_admission_and_no_work_claim_leaks(self):
        self.activate()
        entered, release = threading.Event(), threading.Event()

        def reserve():
            entered.set()
            if not release.wait(3):
                raise AssertionError("admission checkpoint was not released")
            with self.registry.send_authority.gate:
                return self._reserve("after-close")

        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(reserve)
            try:
                self.assertTrue(entered.wait(2))
                self.campaign.transition("owner.local", "closed")
            finally:
                release.set()
            with self.assertRaises(ContractError):
                pending.result(timeout=3)
        self.assertEqual(self.campaign.summary()["request_count"], 0)
        self.assertIsNone(self.store.work_owner(self._record("after-close")["work_key"]))
        self.assertIsNone(self.store.get("submission.after-close"))
