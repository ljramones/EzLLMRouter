"""One owned HTTP session and exchange policy for every client protocol."""

from __future__ import annotations

import ssl
from types import TracebackType
from typing import Any, Self
from urllib.parse import urlsplit

import httpx

from ._deadline import DEFAULT_TOTAL_TIMEOUT, DeadlineHTTPTransport, total_timeout as check_timeout
from ._errors import ClientError
from ._http import DEFAULT_TIMEOUT, BufferedResponse, bounded_request
from ._json import strict_reply


class _Credential:
    __slots__ = ("value",)

    def __init__(self, value: str) -> None:
        self.value = value

    def __repr__(self) -> str:
        return "<redacted bearer credential>"


class ClientSession:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        transport: Any = None,
        timeout: Any = DEFAULT_TIMEOUT,
        total_timeout: float | None = DEFAULT_TOTAL_TIMEOUT,
        verify: ssl.SSLContext | str | bool = True,
    ) -> None:
        if type(base_url) is not str or type(token) is not str or not token:
            raise TypeError("base_url and token are required")
        try:
            parsed = urlsplit(base_url)
            port = parsed.port
            valid = (
                parsed.scheme in ("http", "https")
                and bool(parsed.hostname)
                and parsed.username is None
                and parsed.password is None
                and parsed.path in ("", "/")
                and not any(char in base_url for char in "?#\\")
                and not any(ord(char) <= 32 or ord(char) == 127 for char in base_url)
                and (port is None or 1 <= port <= 65535)
            )
        except ValueError:
            valid = False
        if not valid:
            raise TypeError("base_url must be an HTTP(S) origin without a path")
        if any(not 33 <= ord(char) <= 126 for char in token):
            raise TypeError("token must be a nonempty ASCII bearer credential")
        self.base_url = base_url.rstrip("/")
        self._credential = _Credential(token)
        self._total_timeout = check_timeout(total_timeout)
        if transport is None:
            self._transport = httpx.Client(
                timeout=timeout,
                transport=DeadlineHTTPTransport(verify=verify),
                follow_redirects=False,
                trust_env=False,
            )
        else:
            if verify is not True:
                raise TypeError("configure TLS verification on the injected transport")
            if not callable(getattr(transport, "request", None)):
                raise TypeError("transport must provide request")
            self._transport = transport
        self._closed = False

    def __repr__(self) -> str:
        return f"{type(self).__name__}(base_url={self.base_url!r}, closed={self._closed})"

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            close = getattr(self._transport, "close", None)
            if callable(close):
                close()

    def __enter__(self) -> Self:
        if self._closed:
            raise ClientError("CLIENT_CLOSED")
        return self

    def __exit__(
        self,
        _type: type[BaseException] | None,
        _value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _exchange(
        self,
        method: str,
        path: str,
        *,
        version_header: str,
        version_field: str,
        version: str,
        limit: int,
        error_type: type[ClientError],
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        selector: dict[str, Any] | None = None,
    ) -> tuple[BufferedResponse, dict[str, Any]]:
        if self._closed:
            raise error_type("CLIENT_CLOSED")
        request_headers = {
            **(headers or {}),
            version_header: version,
            "Authorization": "Bearer " + self._credential.value,
        }
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        try:
            response = bounded_request(
                self._transport,
                method,
                self.base_url + path,
                headers=request_headers,
                content=body,
                limit=limit,
                total_timeout=self._total_timeout,
            )
        except Exception as cause:
            raise error_type(
                "TRANSPORT_OUTCOME_UNKNOWN",
                getattr(cause, "status_code", None),
                "query_first",
                selector=selector,
            ) from cause
        try:
            value = strict_reply(response.content)
        except (AttributeError, TypeError, ValueError, OverflowError, RecursionError) as cause:
            raise error_type(
                "TRANSPORT_OUTCOME_UNKNOWN", response.status_code, "query_first", selector=selector
            ) from cause
        if (
            type(value) is not dict
            or value.get(version_field) != version
            or response.headers.get(version_header) != version
        ):
            correlation = (
                value["error"].get("correlation_id")
                if type(value) is dict and type(value.get("error")) is dict
                else None
            )
            raise error_type(
                "UNSUPPORTED_VERSION",
                response.status_code,
                correlation_id=correlation,
                selector=selector,
            )
        return response, value
