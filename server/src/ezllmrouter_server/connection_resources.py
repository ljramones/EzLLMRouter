"""Dependency-free connection limits shared by service, worker and ingress."""

import socket
import socketserver
import threading
import time

MAX_CONNECTIONS = 32


class BoundedThreadingMixIn(socketserver.ThreadingMixIn):
    daemon_threads = True
    block_on_close = False
    handler_join_timeout = 5.0

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
