"""Typed ownership and bounded scheduling for accepted execution work."""

from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from typing import Literal, ParamSpec, TypeVar, TypedDict, cast
import threading

P = ParamSpec("P")
R = TypeVar("R")


class PoolStatus(TypedDict):
    state: Literal["closed", "recovering", "ready"]
    inflight: int
    capacity: int
    submit_failures: int
    recoveries: int


class ServiceClosing(RuntimeError):
    pass


class AdmissionGate:
    """Stop new submissions and wait for callers already publishing durable work."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._closed = False
        self._active = 0

    @contextmanager
    def enter(self) -> Iterator[None]:
        with self._condition:
            if self._closed:
                raise ServiceClosing("service is closing")
            self._active += 1
        try:
            yield
        finally:
            with self._condition:
                self._active -= 1
                self._condition.notify_all()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()
            self._condition.wait_for(lambda: self._active == 0)


class BoundedExecutor:
    """Bound running plus queued work; accepted tasks drain during normal shutdown."""

    def __init__(self, *, max_workers: int, max_pending: int = 64, thread_name_prefix: str) -> None:
        if max_pending < max_workers or max_workers < 1:
            raise ValueError("invalid executor capacity")
        self._slots = threading.BoundedSemaphore(max_pending)
        self._submission_lock = threading.RLock()
        self._closed = False
        self._max_workers, self._thread_name_prefix = max_workers, thread_name_prefix
        self._max_pending = max_pending
        self._inflight = 0
        self._failed = False
        self._failures = self._recoveries = 0
        self._pool: ThreadPoolExecutor | None = self._new_pool()

    def _new_pool(self) -> ThreadPoolExecutor:
        return ThreadPoolExecutor(
            max_workers=self._max_workers, thread_name_prefix=self._thread_name_prefix
        )

    def _recover(self) -> None:
        if self._closed or not self._failed or self._inflight:
            return
        try:
            replacement = self._new_pool()
        except Exception:
            return  # Remains visibly unavailable; a later status/submit retries.
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=False)
        self._pool = replacement
        self._failed = False
        self._recoveries += 1

    def status(self) -> PoolStatus:
        with self._submission_lock:
            self._recover()
            return {
                "state": "closed" if self._closed else "recovering" if self._failed else "ready",
                "inflight": self._inflight,
                "capacity": self._max_pending,
                "submit_failures": self._failures,
                "recoveries": self._recoveries,
            }

    def _completed(self, _future: Future[R]) -> None:
        self._slots.release()
        with self._submission_lock:
            self._inflight -= 1
            self._recover()

    def submit(self, action: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> Future[R]:
        with self._submission_lock:
            if self._closed:
                raise RuntimeError("execution pool is closed")
            self._recover()
            if self._failed:
                raise RuntimeError("execution pool is recovering")
            pool = self._pool
            if pool is None:
                raise RuntimeError("execution pool is closed")
            if not self._slots.acquire(blocking=False):
                raise RuntimeError("execution capacity exhausted")
            ready = threading.Event()
            accepted = False

            def execute() -> R | None:
                # ThreadPoolExecutor can enqueue before thread creation fails.
                # Such a failed submit must never run provider work later.
                ready.wait()
                if accepted:
                    return action(*args, **kwargs)
                return None

            self._inflight += 1
            try:
                future = pool.submit(execute)
            except BaseException:
                self._failed = True
                self._failures += 1
                self._inflight -= 1
                ready.set()
                self._slots.release()
                self._recover()
                raise
            accepted = True
            ready.set()
            future.add_done_callback(self._completed)
            return cast(Future[R], future)

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        with self._submission_lock:
            self._closed = True
            pool = self._pool
        if pool is not None:
            pool.shutdown(wait=wait, cancel_futures=cancel_futures)
            if wait:
                with self._submission_lock:
                    self._pool = None
