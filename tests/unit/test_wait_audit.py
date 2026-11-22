"""Blocking synchronization must not hide work under a shared state gate."""

from concurrent.futures import Future, TimeoutError
import threading
import unittest

from tools.lock_audit import auditing
from tests.support import gate_checkpoint


class WaitAuditTests(unittest.TestCase):
    def test_only_explicit_fixture_event_checkpoints_bypass_the_wait_probe(self):
        with auditing() as auditor:
            gate = auditor.watch(threading.Lock(), "database")
            condition = threading.Condition(gate)
            with condition:
                self.assertFalse(condition.wait(0.001))
                self.assertIn(id(gate), auditor.held())
                self.assertFalse(gate_checkpoint(threading.Event(), 0.001))
                with self.assertRaisesRegex(AssertionError, "Event.wait"):
                    threading.Event().wait(0.001)

    def test_events_futures_conditions_and_joins_reject_before_blocking(self):
        with auditing() as auditor:
            gate = auditor.watch(threading.RLock(), "database")
            stop = threading.Event()
            thread = threading.Thread(target=lambda: stop.wait(3))
            thread.start()
            try:
                condition = threading.Condition()
                future = Future()
                for name, action in (
                    ("Event.wait", lambda: stop.wait(0.01)),
                    ("Future.result", lambda: future.result(0.01)),
                    ("Future.exception", lambda: future.exception(0.01)),
                    ("Thread.join", lambda: thread.join(0.01)),
                ):
                    with (
                        self.subTest(operation=name),
                        gate,
                        self.assertRaisesRegex(AssertionError, name),
                    ):
                        action()
                with condition, gate, self.assertRaisesRegex(AssertionError, "Condition.wait"):
                    condition.wait(0.01)
                self.assertEqual(len(auditor.violations), 5)
            finally:
                stop.set()
                thread.join(3)

    def test_completed_nonblocking_and_same_condition_release_controls(self):
        with auditing() as auditor:
            gate = auditor.watch(threading.RLock(), "database")
            condition = threading.Condition(gate)
            done, pending = Future(), Future()
            done.set_result(7)
            ready = threading.Event()
            ready.set()
            with gate:
                self.assertTrue(ready.wait())
                self.assertEqual(done.result(), 7)
                self.assertIsNone(done.exception())
                self.assertFalse(threading.Event().wait(0))
                with self.assertRaises(TimeoutError):
                    pending.result(0)
            with condition:
                self.assertFalse(condition.wait(0.001))
                self.assertIn(id(gate), auditor.held())
            other = auditor.watch(threading.RLock(), "authority")
            with condition, other, self.assertRaisesRegex(AssertionError, "authority"):
                condition.wait(0.001)
            self.assertEqual(auditor.violations[0]["locks"], ["authority"])
