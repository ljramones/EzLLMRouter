"""HTTP listeners with a finite connection budget and bounded socket waits."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
from contextlib import suppress
import socket
import io
import time
import uuid

from .runtime_resources import BoundedThreadingMixIn as _BoundedThreadingMixIn

from .observability import REQUEST_CORRELATION, log_failure, log_http_request

REQUEST_TIMEOUT_SECONDS = 15
MAX_CONNECTIONS = 32


class BoundedThreadingMixIn(_BoundedThreadingMixIn):
    def handle_error(self, request, client_address):
        log_failure("http_connection_failed")


class BoundedHTTPServer(BoundedThreadingMixIn, HTTPServer):
    request_queue_size = MAX_CONNECTIONS


class _InputReader(io.RawIOBase):
    """Enforce the whole-input budget at every underlying socket read."""

    def __init__(self, raw, handler):
        self.raw, self.handler = raw, handler

    def readable(self):
        return True

    def readinto(self, buffer):
        deadline = self.handler._input_deadline
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.handler._expire_input()
                raise TimeoutError("HTTP input deadline expired")
            self.handler.connection.settimeout(remaining)
        return self.raw.readinto(buffer)

    def close(self):
        if not self.closed:
            self.raw.close()
        super().close()


class SafeHTTPRequestHandler(BaseHTTPRequestHandler):
    timeout = REQUEST_TIMEOUT_SECONDS

    def setup(self):
        super().setup()
        raw = self.rfile.detach() if isinstance(self.rfile, io.BufferedReader) else self.rfile
        self.rfile = io.BufferedReader(_InputReader(raw, self))
        self._input_deadline = None

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
        self._input_deadline = time.monotonic() + REQUEST_TIMEOUT_SECONDS
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
        self._input_deadline = None
        connection = getattr(self, "connection", None)
        if connection is not None:
            connection.settimeout(self.timeout)

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
