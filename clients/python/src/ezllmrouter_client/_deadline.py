"""Per-exchange deadlines through public HTTPX/HTTPcore transport interfaces."""

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
import math
import socket
import ssl
import time
from typing import Any

import httpcore
import httpx

DEFAULT_TOTAL_TIMEOUT = 60.0
_deadline: ContextVar[float | None] = ContextVar("ezllmrouter_http_deadline", default=None)


def total_timeout(value: float | None) -> float | None:
    if value is None:
        return None
    if type(value) not in (int, float):
        raise ValueError("total_timeout must be finite and positive, or None")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError("total_timeout must be finite and positive, or None") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError("total_timeout must be finite and positive, or None")
    return number


@contextmanager
def deadline_scope(seconds: float | None) -> Iterator[None]:
    seconds = total_timeout(seconds)
    token = _deadline.set(None if seconds is None else time.monotonic() + seconds)
    try:
        yield
    finally:
        _deadline.reset(token)


def remaining(
    timeout: float | None = None, error: type[Exception] = httpcore.ReadTimeout
) -> float | None:
    deadline = _deadline.get()
    if deadline is None:
        return timeout
    budget = deadline - time.monotonic()
    if budget <= 0:
        raise error("total HTTP deadline exceeded")
    return budget if timeout is None else min(timeout, budget)


_ERRORS = {
    httpcore.ConnectTimeout: httpx.ConnectTimeout,
    httpcore.ReadTimeout: httpx.ReadTimeout,
    httpcore.WriteTimeout: httpx.WriteTimeout,
    httpcore.PoolTimeout: httpx.PoolTimeout,
    httpcore.ConnectError: httpx.ConnectError,
    httpcore.ReadError: httpx.ReadError,
    httpcore.WriteError: httpx.WriteError,
    httpcore.LocalProtocolError: httpx.LocalProtocolError,
    httpcore.RemoteProtocolError: httpx.RemoteProtocolError,
    httpcore.UnsupportedProtocol: httpx.UnsupportedProtocol,
}


@contextmanager
def _mapped_errors() -> Iterator[None]:
    try:
        yield
    except tuple(_ERRORS) as exc:
        for source, target in _ERRORS.items():
            if isinstance(exc, source):
                raise target(str(exc)) from exc
        raise


class _DeadlineStream(httpcore.NetworkStream):
    def __init__(self, stream: httpcore.NetworkStream):
        self.stream = stream

    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        value = self.stream.read(max_bytes, timeout=remaining(timeout, httpcore.ReadTimeout))
        remaining(error=httpcore.ReadTimeout)
        return value

    def write(self, buffer: bytes, timeout: float | None = None) -> None:
        if not buffer:
            return
        budget = remaining(timeout, httpcore.WriteTimeout)
        network_socket = self.stream.get_extra_info("socket")
        if network_socket is None:
            self.stream.write(buffer, timeout=budget)
        else:
            # sendall applies its timeout to the entire buffer. SyncBackend's
            # write loop would restart that timeout after every partial send.
            try:
                network_socket.settimeout(budget)
                network_socket.sendall(buffer)
            except socket.timeout as exc:
                raise httpcore.WriteTimeout("HTTP write timed out") from exc
            except OSError as exc:
                raise httpcore.WriteError("HTTP write failed") from exc
        remaining(error=httpcore.WriteTimeout)

    def start_tls(
        self,
        ssl_context: ssl.SSLContext,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> httpcore.NetworkStream:
        stream = self.stream.start_tls(
            ssl_context, server_hostname, timeout=remaining(timeout, httpcore.ConnectTimeout)
        )
        try:
            remaining(error=httpcore.ConnectTimeout)
        except BaseException:
            stream.close()
            raise
        return _DeadlineStream(stream)

    def get_extra_info(self, info: str) -> Any:
        return self.stream.get_extra_info(info)

    def close(self) -> None:
        self.stream.close()


class _DeadlineBackend(httpcore.NetworkBackend):
    def __init__(self, backend: httpcore.NetworkBackend):
        self.backend = backend

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.NetworkStream:
        stream = self.backend.connect_tcp(
            host,
            port,
            timeout=remaining(timeout, httpcore.ConnectTimeout),
            local_address=local_address,
            socket_options=socket_options,
        )
        try:
            # Synchronous DNS/address fallback may return after its budget.
            # Never send using a connection that arrived after the deadline.
            remaining(error=httpcore.ConnectTimeout)
        except BaseException:
            stream.close()
            raise
        return _DeadlineStream(stream)


class _ResponseStream(httpx.SyncByteStream):
    def __init__(self, response: httpcore.Response):
        self.response = response

    def __iter__(self) -> Iterator[bytes]:
        with _mapped_errors():
            yield from self.response.iter_stream()

    def close(self) -> None:
        with _mapped_errors():
            self.response.close()


class DeadlineHTTPTransport(httpx.BaseTransport):
    def __init__(
        self,
        *,
        backend: httpcore.NetworkBackend | None = None,
        verify: ssl.SSLContext | str | bool = True,
    ):
        if not isinstance(verify, (ssl.SSLContext, str, bool)):
            raise TypeError("verify must be an SSLContext, CA file path or boolean")
        self.pool = httpcore.ConnectionPool(
            max_connections=100,
            max_keepalive_connections=20,
            keepalive_expiry=5.0,
            ssl_context=httpx.create_ssl_context(verify=verify, trust_env=False),
            retries=0,
            network_backend=_DeadlineBackend(backend or httpcore.SyncBackend()),
        )

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        timeouts = request.extensions.get("timeout", {})
        errors = {
            "connect": httpcore.ConnectTimeout,
            "read": httpcore.ReadTimeout,
            "write": httpcore.WriteTimeout,
            "pool": httpcore.PoolTimeout,
        }
        with _mapped_errors():
            extensions = {
                **request.extensions,
                "timeout": {
                    phase: remaining(timeouts.get(phase), error) for phase, error in errors.items()
                },
            }
            response = self.pool.handle_request(
                httpcore.Request(
                    method=request.method,
                    url=httpcore.URL(
                        scheme=request.url.raw_scheme,
                        host=request.url.raw_host,
                        port=request.url.port,
                        target=request.url.raw_path,
                    ),
                    headers=request.headers.raw,
                    content=request.stream,
                    extensions=extensions,
                )
            )
        return httpx.Response(
            response.status,
            headers=response.headers,
            stream=_ResponseStream(response),
            extensions=response.extensions,
        )

    def close(self) -> None:
        with _mapped_errors():
            self.pool.close()
