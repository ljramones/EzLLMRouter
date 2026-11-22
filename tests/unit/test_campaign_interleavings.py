"""Force both orders of campaign close versus admission without scheduling sleeps."""

from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
from tests.support import gate_checkpoint
from unittest.mock import patch

from ezllmrouter_server.canonical import ContractError
from tests.operator_console import test_personal_campaign as support


class ContendedGate:
    """Observe an actual failed acquire by the designated competing thread."""

    def __init__(self, original):
        self.original, self.local = original, threading.local()
        self.contended = threading.Event()

    def compete(self, function, *args):
        self.local.observe = True
        return function(*args)

    def acquire(self, *args, **kwargs):
        if getattr(self.local, "observe", False):
            self.local.observe = False
            if self.original.acquire(False):
                self.original.release()
                raise AssertionError("competitor did not encounter a held authority gate")
            self.contended.set()
        return self.original.acquire(*args, **kwargs)

    def release(self):
        self.original.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_):
        self.release()

    def __getattr__(self, name):
        return getattr(self.original, name)


class CampaignInterleavingTests(unittest.TestCase):
    setUp = support.CampaignTests.setUp
    _record = support.CampaignTests._record
    _reserve = support.CampaignTests._reserve

    def activate(self):
        self.campaign.configure("owner.local", self.config)
        self.campaign.transition("owner.local", "active")

    def test_reservation_commits_before_close_and_exposure_is_retained(self):
        self.activate()
        entered, release = threading.Event(), threading.Event()
        gate = ContendedGate(self.registry.send_authority.gate)
        self.registry.send_authority.gate = gate
        record = self._record("close-race")

        def reserve():
            def at_reservation(db, item):
                entered.set()
                if not gate_checkpoint(release, 3):
                    raise AssertionError("reservation checkpoint was not released")
                return self.campaign.reserve(db, item, 20, 16)

            # Match the real admission's authority-before-database lock order.
            with self.registry.send_authority.gate:
                self.store.create(record, reserve=at_reservation)

        with ThreadPoolExecutor(max_workers=2) as executor:
            reserved = executor.submit(reserve)
            try:
                self.assertTrue(entered.wait(2))
                closed = executor.submit(
                    gate.compete, self.campaign.transition, "owner.local", "closed"
                )
                self.assertTrue(gate.contended.wait(2), "close never contended on authority")
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
        gate = ContendedGate(self.registry.send_authority.gate)
        self.registry.send_authority.gate = gate
        original_audit = self.campaign._audit

        def audit(db, action, actor, **kwargs):
            if action == "closed":
                entered.set()
                if not gate_checkpoint(release, 3):
                    raise AssertionError("close checkpoint was not released")
            return original_audit(db, action, actor, **kwargs)

        def reserve():
            with self.registry.send_authority.gate:
                return self._reserve("after-close")

        with (
            patch.object(self.campaign, "_audit", side_effect=audit),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            closed = executor.submit(self.campaign.transition, "owner.local", "closed")
            try:
                self.assertTrue(entered.wait(2))
                pending = executor.submit(gate.compete, reserve)
                self.assertTrue(gate.contended.wait(2), "admission never contended on authority")
                self.assertFalse(pending.done())
            finally:
                release.set()
            self.assertEqual(closed.result(timeout=3)["state"], "closed")
            with self.assertRaises(ContractError):
                pending.result(timeout=3)
        self.assertEqual(self.campaign.summary()["request_count"], 0)
        self.assertIsNone(self.store.work_owner(self._record("after-close")["work_key"]))
        self.assertIsNone(self.store.get("submission.after-close"))
