"""Shared synchronous HTTP response bounds; no redirects or automatic retries."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from collections.abc import Iterator, Mapping
from typing import Any

import httpx

DEFAULT_TIMEOUT = httpx.Timeout(connect=10, read=35, write=30, pool=10)
WIRE_RESPONSE_LIMIT = 1024 * 1024
SUCCESSOR_RESPONSE_LIMIT = 16 * 1024 * 1024
INTEGRATION_RESPONSE_LIMIT = 16 * 1024 * 1024
READ_CHUNK_BYTES = 64 * 1024


class ResponseReadError(ValueError):
    def __init__(self, status_code: int) -> None:
        super().__init__("response could not be read within protocol bounds")
        self.status_code = status_code


@dataclass(frozen=True)
class BufferedResponse:
    status_code: int
    headers: httpx.Headers
    content: bytes


@contextmanager
def _response(
    transport: Any, method: str, url: str, headers: dict[str, str], content: bytes | None
) -> Iterator[Any]:
    options: dict[str, Any] = {"headers": headers}
    if content is not None:
        options["content"] = content
    stream = getattr(transport, "stream", None)
    if callable(stream):
        with stream(method, url, **options) as response:
            yield response
    else:
        # Compatibility with request-only injected transports. Their buffering
        # happens outside this client; production HTTPX uses the streaming path.
        response = transport.request(method, url, **options)
        try:
            yield response
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()


def bounded_request(
    transport: Any,
    method: str,
    url: str,
    *,
    headers: Mapping[str, str],
    limit: int,
    content: bytes | None = None,
) -> BufferedResponse:
    headers = {**headers, "Accept-Encoding": "identity"}
    with _response(transport, method, url, headers, content) as response:
        status = response.status_code
        try:
            received_headers = httpx.Headers(response.headers)
            if received_headers.get("Content-Encoding", "identity").strip().lower() != "identity":
                raise ValueError("encoded responses are not supported")
            declared = received_headers.get("Content-Length")
            if declared is not None and (
                not declared.isascii() or not declared.isdecimal() or int(declared) > limit
            ):
                raise ValueError("invalid or excessive content length")
            raw = getattr(response, "iter_raw", None)
            if callable(raw) and not getattr(response, "is_stream_consumed", False):
                chunks = raw(chunk_size=min(READ_CHUNK_BYTES, limit + 1))
            else:
                chunks = (response.content,)
            body = bytearray()
            for chunk in chunks:
                if not isinstance(chunk, bytes) or len(chunk) > limit - len(body):
                    raise ValueError("response exceeds its byte limit")
                body.extend(chunk)
            if declared is not None and len(body) != int(declared):
                raise ValueError("response length mismatch")
            return BufferedResponse(status, received_headers, bytes(body))
        except Exception as cause:
            raise ResponseReadError(status) from cause
