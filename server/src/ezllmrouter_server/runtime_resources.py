"""Standard-library ownership helpers shared by the service, worker and ingress."""

from __future__ import annotations

from collections.abc import Coroutine
from concurrent.futures import Future
from typing import Any, TypeVar

import asyncio
import threading

from .execution_resources import (
    AdmissionGate as AdmissionGate,
    BoundedExecutor as BoundedExecutor,
    ServiceClosing as ServiceClosing,
)

from .connection_resources import (
    MAX_CONNECTIONS as MAX_CONNECTIONS,
    BoundedThreadingMixIn as BoundedThreadingMixIn,
    BoundedUnixServer as BoundedUnixServer,
)


T = TypeVar("T")


class LoopThread:
    """Own a loop from creation through partial startup and cooperative task cleanup."""

    def __init__(self, name: str) -> None:
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, name=name, daemon=True)
        self._close_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._closed = False
        try:
            self.thread.start()
        except BaseException:
            self.loop.close()
            raise

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_forever()
        finally:
            pending = asyncio.all_tasks(self.loop)
            for task in pending:
                task.cancel()
            if pending:
                # Cancellation-resistant tasks cannot block the owner's shutdown forever.
                self.loop.run_until_complete(asyncio.wait(pending, timeout=1))
            self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            self.loop.close()

    def submit(self, coroutine: Coroutine[Any, Any, T]) -> Future[T]:
        with self._state_lock:
            if self._closed:
                coroutine.close()
                raise RuntimeError("event loop is closed")
            try:
                return asyncio.run_coroutine_threadsafe(coroutine, self.loop)
            except BaseException:
                coroutine.close()
                raise

    @staticmethod
    def _wait(future: Future[T], timeout: float | None) -> T:
        try:
            return future.result(timeout=timeout)
        except BaseException:
            future.cancel()
            raise

    def call(self, coroutine: Coroutine[Any, Any, T], *, timeout: float | None) -> T:
        return self._wait(self.submit(coroutine), timeout)

    def close(self, cleanup: Coroutine[Any, Any, object] | None = None) -> None:
        with self._close_lock:
            with self._state_lock:
                if self._closed:
                    if cleanup is not None:
                        cleanup.close()
                    return
                self._closed = True
            try:
                if cleanup is not None:
                    future = asyncio.run_coroutine_threadsafe(cleanup, self.loop)
                    self._wait(future, 5)
            finally:
                self.loop.call_soon_threadsafe(self.loop.stop)
                self.thread.join(timeout=7)
                if self.thread.is_alive():
                    raise RuntimeError("event loop did not stop")
