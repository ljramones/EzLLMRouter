"""Dependency-free connection limits shared by service, worker and ingress."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import socket
import socketserver
import threading
import time

MAX_CONNECTIONS = 32


class BoundedThreadingMixIn(socketserver.ThreadingMixIn):
    daemon_threads = True
    block_on_close = False
    handler_join_timeout = 5.0

    if TYPE_CHECKING:
        # Supplied by the concrete socketserver base later in the MRO.
        def shutdown_request(self, request: Any) -> None: ...

    def __init__(self, *args: Any, max_connections: int = MAX_CONNECTIONS, **kwargs: Any) -> None:
        if type(max_connections) is not int or max_connections < 1:
            raise ValueError("max_connections must be a positive integer")
        self._connection_slots = threading.BoundedSemaphore(max_connections)
        self._active_connections: set[socket.socket] = set()
        self._handler_threads: set[threading.Thread] = set()
        self._connections_lock = threading.Lock()
        self._connections_closed = False
        super().__init__(*args, **kwargs)

    def process_request(
        self,
        request: Any,
        client_address: str | tuple[str, int] | tuple[str, int, int, int],
    ) -> None:
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
                    self._handler_threads.discard(cast(threading.Thread, thread))
                    self._connection_slots.release()
                    self.shutdown_request(request)
                    raise
        if not accepted:
            self.shutdown_request(request)

    def process_request_thread(
        self,
        request: Any,
        client_address: str | tuple[str, int] | tuple[str, int, int, int],
    ) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self._connections_lock:
                self._active_connections.discard(request)
                self._handler_threads.discard(threading.current_thread())
                self._connection_slots.release()

    def server_close(self) -> None:
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
            deadline = time.monotonic() + self.handler_join_timeout
            for thread in threads:
                if thread is not threading.current_thread():
                    thread.join(timeout=max(0, deadline - time.monotonic()))
            if any(
                thread.is_alive() and thread is not threading.current_thread() for thread in threads
            ):
                raise RuntimeError("connection handlers did not stop within shutdown deadline")


class BoundedUnixServer(BoundedThreadingMixIn, socketserver.UnixStreamServer):
    allow_reuse_address = False
    request_queue_size = MAX_CONNECTIONS
