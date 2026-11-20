"""HTTP listeners with a finite connection budget and bounded socket waits."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
from contextlib import suppress
import socket
import socketserver
import threading
import time
import uuid

from .observability import REQUEST_CORRELATION, log_failure, log_http_request

REQUEST_TIMEOUT_SECONDS = 15
MAX_CONNECTIONS = 32


class BoundedThreadingMixIn(socketserver.ThreadingMixIn):
    daemon_threads = True
    block_on_close = False

    def __init__(self, *args, max_connections=MAX_CONNECTIONS, **kwargs):
        if type(max_connections) is not int or max_connections < 1:
            raise ValueError("max_connections must be a positive integer")
        self._connection_slots = threading.BoundedSemaphore(max_connections)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self._connection_slots.acquire(blocking=False):
            # Do not start a thread or attempt to read an excess connection.
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._connection_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._connection_slots.release()

    def handle_error(self, request, client_address):
        log_failure("http_connection_failed")


class BoundedHTTPServer(BoundedThreadingMixIn, HTTPServer):
    request_queue_size = MAX_CONNECTIONS


class SafeHTTPRequestHandler(BaseHTTPRequestHandler):
    timeout = REQUEST_TIMEOUT_SECONDS

    @property
    def diagnostic_id(self):
        if not getattr(self, "_diagnostic_id", None):
            self._diagnostic_id = "request." + uuid.uuid4().hex
        return self._diagnostic_id

    def handle_one_request(self):
        self._diagnostic_id = "request." + uuid.uuid4().hex
        self.command, self.path = "OTHER", "/"
        context = REQUEST_CORRELATION.set(self.diagnostic_id)
        self._response_status = 0
        started = time.monotonic()
        self._input_timer = threading.Timer(REQUEST_TIMEOUT_SECONDS, self._expire_input)
        self._input_timer.daemon = True
        self._input_timer.start()
        try:
            super().handle_one_request()
        finally:
            self._finish_input()
            log_http_request(
                getattr(self, "command", "OTHER"),
                getattr(self, "path", "/"),
                self._response_status,
                int((time.monotonic() - started) * 1000),
                self.diagnostic_id,
            )
            REQUEST_CORRELATION.reset(context)

    def _expire_input(self):
        with suppress(OSError):
            self.connection.shutdown(socket.SHUT_RDWR)

    def _finish_input(self):
        timer = getattr(self, "_input_timer", None)
        if timer is not None:
            timer.cancel()

    def parse_request(self):
        accepted = super().parse_request()
        if not accepted or self.command not in {"POST", "PUT", "PATCH", "DELETE"}:
            self._finish_input()
        return accepted

    def read_body(self, length):
        try:
            return self.rfile.read(length)
        finally:
            # Long model waits keep their contract deadline after input is complete.
            self._finish_input()

    def send_response(self, code, message=None):
        self._response_status = code
        super().send_response(code, message)
        self.send_header("X-Request-ID", self.diagnostic_id)

    def log_message(self, *_args):
        return  # Access events use allowlisted routes, never raw HTTP messages.

    def log_error(self, *_args):
        log_failure("http_request_failed")
