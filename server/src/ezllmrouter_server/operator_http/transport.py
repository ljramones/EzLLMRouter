"""Operator transport handlers."""

from __future__ import annotations

from typing import cast
from collections.abc import Iterable, Mapping, Sequence
from ..records import Record
from .context import OperatorContext, Session


import json
import hmac

from .common import _pairs, _reject_number, csv_bytes


class TransportRoutes:
    def _session_cookie(self: OperatorContext, token: str, max_age: int) -> str:
        return (
            "ezllmrouter_operator="
            + token
            + "; Path=/operator; HttpOnly; SameSite=Strict; Max-Age="
            + str(max_age)
            + ("; Secure" if self.application.secure_cookies else "")
        )

    def log_message(self: OperatorContext, *_args: object) -> None:
        return

    def _send(
        self: OperatorContext,
        status: int,
        payload: object,
        *,
        content_type: str = "application/json; charset=utf-8",
        extra: Iterable[tuple[str, str]] = (),
    ) -> None:
        data = (
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
            if not isinstance(payload, bytes)
            else payload
        )
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        )
        if self.application.secure_cookies:
            self.send_header("Strict-Transport-Security", "max-age=31536000")
        for name, value in extra:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def _fail(self: OperatorContext, status: int, code: str) -> None:
        self._send(status, {"error": code})

    def _send_csv(
        self: OperatorContext,
        filename: str,
        columns: Sequence[str],
        rows: Iterable[Mapping[str, object]],
    ) -> None:
        return self._send(
            200,
            csv_bytes(columns, rows),
            content_type="text/csv; charset=utf-8",
            extra=(("Content-Disposition", "attachment; filename=" + filename),),
        )

    def _origin_ok(self: OperatorContext, mutation: bool = False) -> bool:
        hosts = self.headers.get_all("Host")
        if not hosts or len(hosts) != 1 or hosts[0] not in self.application.allowed_hosts:
            return False
        origin = self.headers.get("Origin")
        if mutation:
            return origin in self.application.allowed_origins
        return origin is None or origin in self.application.allowed_origins

    def _csrf_ok(self: OperatorContext, session: Session) -> bool:
        values = self.headers.get_all("X-EzLLMRouter-CSRF")
        if not values or len(values) != 1:
            return False
        try:
            return hmac.compare_digest(
                values[0].encode("utf-8"), session[1]["csrf"].encode("utf-8")
            )
        except UnicodeError:
            return False

    def _body_limit(self: OperatorContext) -> int:
        if self.path.startswith("/operator/v1/local-connectors"):
            return 262144
        if self.path in (
            "/operator/v1/login",
            "/operator/v1/account/password",
            "/operator/v1/provider-credential",
        ) or self.path.startswith(("/operator/v1/users", "/operator/v1/integration/connections")):
            return 8192
        if self.path in ("/operator/v1/registry", "/operator/v1/provider-probe"):
            return 4096
        return 2048

    def _body(self: OperatorContext) -> Record:
        lengths = self.headers.get_all("Content-Length")
        if (
            self.headers.get_all("Content-Type") != ["application/json"]
            or len(lengths or []) != 1
            or not cast(list[str], lengths)[0].isascii()
            or not cast(list[str], lengths)[0].isdigit()
            or not 0 < int(cast(list[str], lengths)[0]) <= self._body_limit()
            or self.headers.get_all("Transfer-Encoding")
        ):
            raise ValueError("body shape")
        body = self.read_body(int(cast(list[str], lengths)[0]))
        if len(body) != int(cast(list[str], lengths)[0]):
            raise ValueError("truncated body")
        value = json.loads(
            body,
            object_pairs_hook=_pairs,
            parse_float=_reject_number,
            parse_constant=_reject_number,
        )
        if type(value) is not dict:
            raise ValueError("body shape")
        return value
