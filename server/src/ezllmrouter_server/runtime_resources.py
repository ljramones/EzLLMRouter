"""Standard-library ownership helpers shared by the service, worker and ingress."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import asyncio
import socket
import socketserver
import threading

MAX_CONNECTIONS = 32


class ServiceClosing(RuntimeError):
    pass


class AdmissionGate:
    """Stop new submissions and wait for callers already publishing durable work."""

    def __init__(self):
        self._condition = threading.Condition()
        self._closed = False
        self._active = 0

    @contextmanager
    def enter(self):
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

    def close(self):
        with self._condition:
            self._closed = True
            self._condition.notify_all()
            self._condition.wait_for(lambda: self._active == 0)


class BoundedExecutor:
    """Bound running plus queued work; accepted tasks drain during normal shutdown."""

    def __init__(self, *, max_workers, max_pending=64, thread_name_prefix):
        if max_pending < max_workers or max_workers < 1:
            raise ValueError("invalid executor capacity")
        self._slots = threading.BoundedSemaphore(max_pending)
        self._submission_lock = threading.Lock()
        self._closed = False
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix=thread_name_prefix
        )

    def submit(self, action, *args, **kwargs):
        with self._submission_lock:
            if self._closed:
                raise RuntimeError("execution pool is closed")
            if not self._slots.acquire(blocking=False):
                raise RuntimeError("execution capacity exhausted")
            ready = threading.Event()
            accepted = False

            def execute():
                # ThreadPoolExecutor can enqueue before thread creation fails.
                # Such a failed submit must never run provider work later.
                ready.wait()
                if accepted:
                    return action(*args, **kwargs)
                return None

            try:
                future = self._pool.submit(execute)
            except BaseException:
                self._closed = True
                ready.set()
                self._slots.release()
                raise
            accepted = True
            ready.set()
            future.add_done_callback(lambda _: self._slots.release())
            return future

    def shutdown(self, wait=True, *, cancel_futures=False):
        with self._submission_lock:
            self._closed = True
            pool = self._pool
        if pool is not None:
            pool.shutdown(wait=wait, cancel_futures=cancel_futures)
            if wait:
                with self._submission_lock:
                    self._pool = None


class LoopThread:
    """Own a loop from creation through partial startup and cooperative task cleanup."""

    def __init__(self, name):
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

    def _run(self):
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

    def submit(self, coroutine):
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
    def _wait(future, timeout):
        try:
            return future.result(timeout=timeout)
        except BaseException:
            future.cancel()
            raise

    def call(self, coroutine, *, timeout):
        return self._wait(self.submit(coroutine), timeout)

    def close(self, cleanup=None):
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


class BoundedThreadingMixIn(socketserver.ThreadingMixIn):
    daemon_threads = True
    block_on_close = False

    def __init__(self, *args, max_connections=MAX_CONNECTIONS, **kwargs):
        if type(max_connections) is not int or max_connections < 1:
            raise ValueError("max_connections must be a positive integer")
        self._connection_slots = threading.BoundedSemaphore(max_connections)
        self._active_connections = set()
        self._handler_threads = set()
        self._connections_lock = threading.Lock()
        self._connections_closed = False
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        with self._connections_lock:
            accepted = not self._connections_closed and self._connection_slots.acquire(
                blocking=False
            )
            if accepted:
                self._active_connections.add(request)
                thread = None
                try:
                    thread = threading.Thread(
                        target=self.process_request_thread,
                        args=(request, client_address),
                        daemon=self.daemon_threads,
                    )
                    self._handler_threads.add(thread)
                    thread.start()
                except BaseException:
                    self._active_connections.discard(request)
                    self._handler_threads.discard(thread)
                    self._connection_slots.release()
                    self.shutdown_request(request)
                    raise
        if not accepted:
            self.shutdown_request(request)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self._connections_lock:
                self._active_connections.discard(request)
                self._handler_threads.discard(threading.current_thread())
                self._connection_slots.release()

    def server_close(self):
        with self._connections_lock:
            self._connections_closed = True
            active = tuple(self._active_connections)
            threads = tuple(self._handler_threads)
        for stream in active:
            try:
                stream.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        try:
            super().server_close()
        finally:
            for thread in threads:
                if thread is not threading.current_thread():
                    thread.join()


class BoundedUnixServer(BoundedThreadingMixIn, socketserver.UnixStreamServer):
    allow_reuse_address = False
    request_queue_size = MAX_CONNECTIONS
