"""Bounded waits for observable fixture state, with actionable failures."""

from collections.abc import Callable
import asyncio
import threading
import time
from typing import TypeVar

T = TypeVar("T")


def wait_for_value(
    read: Callable[[], T],
    ready: Callable[[T], bool],
    *,
    timeout: float = 3,
    message: str = "fixture state did not become ready",
) -> T:
    deadline = time.monotonic() + timeout
    wake = threading.Event()
    while True:
        value = read()
        if ready(value):
            return value
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AssertionError(message)
        wake.wait(min(0.005, remaining))


def wait_until(predicate: Callable[[], bool], *, timeout: float = 3) -> None:
    wait_for_value(predicate, bool, timeout=timeout)


async def async_wait_until(predicate: Callable[[], bool], *, timeout: float = 3) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0)
