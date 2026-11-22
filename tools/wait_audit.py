"""Test-only synchronization waits, excluding gates atomically released by a condition."""

from concurrent.futures import Future
import threading
from unittest.mock import patch


def install_waits(stack, auditor):
    def check(operation, timeout, released=None):
        if timeout is not None and timeout <= 0:
            return
        labels = {
            label
            for key, (label, _depth) in auditor.held().items()
            if key != id(released) and label != "password_slots"
        }
        if not labels:
            return
        # Thread.start's internal startup handshake is infrastructure, including
        # fixtures that start a competitor while deliberately holding a gate.
        if auditor.inside({("threading.py", "Thread.start")}):
            return
        if operation in {"Event.wait", "Condition.wait"} and auditor.inside(
            {("tests/support.py", "gate_checkpoint")}
        ):
            return
        auditor.fail(operation, labels)

    event_wait, condition_wait, join = (
        threading.Event.wait,
        threading.Condition.wait,
        threading.Thread.join,
    )

    def event(event, timeout=None):
        if event.is_set():
            return True
        check("Event.wait", timeout)
        return event_wait(event, timeout)

    def condition(condition, timeout=None):
        check("Condition.wait", timeout, condition._lock)
        return condition_wait(condition, timeout)

    def thread_join(thread, timeout=None):
        if thread is not threading.current_thread() and thread.is_alive():
            check("Thread.join", timeout)
        return join(thread, timeout)

    stack.enter_context(patch.object(threading.Event, "wait", event))
    stack.enter_context(patch.object(threading.Condition, "wait", condition))
    stack.enter_context(patch.object(threading.Thread, "join", thread_join))
    for name in ("result", "exception"):
        original = getattr(Future, name)

        def future(future, timeout=None, _original=original, _name=name):
            if not future.done():
                check("Future." + _name, timeout)
            return _original(future, timeout)

        stack.enter_context(patch.object(Future, name, future))
