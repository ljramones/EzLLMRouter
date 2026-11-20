"""Operator transport handlers."""

import json

from .common import _pairs, _reject_number, csv_bytes


class TransportRoutes:
    def log_message(self, *_args):
        return

    def _send(self, status, payload, *, content_type="application/json; charset=utf-8", extra=()):
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
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        )
        for name, value in extra:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def _fail(self, status, code):
        self._send(status, {"error": code})

    def _send_csv(self, filename, columns, rows):
        return self._send(
            200,
            csv_bytes(columns, rows),
            content_type="text/csv; charset=utf-8",
            extra=(("Content-Disposition", "attachment; filename=" + filename),),
        )

    def _origin_ok(self, mutation=False):
        hosts = self.headers.get_all("Host")
        if not hosts or len(hosts) != 1 or hosts[0] not in self.application.allowed_hosts:
            return False
        origin = self.headers.get("Origin")
        if mutation:
            return origin in self.application.allowed_origins
        return origin is None or origin in self.application.allowed_origins

    def _body_limit(self):
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

    def _body(self):
        lengths = self.headers.get_all("Content-Length")
        if (
            self.headers.get_all("Content-Type") != ["application/json"]
            or len(lengths or []) != 1
            or not lengths[0].isdigit()
            or not 0 < int(lengths[0]) <= self._body_limit()
            or self.headers.get_all("Transfer-Encoding")
        ):
            raise ValueError("body shape")
        value = json.loads(
            self.read_body(int(lengths[0])),
            object_pairs_hook=_pairs,
            parse_float=_reject_number,
            parse_constant=_reject_number,
        )
        if type(value) is not dict:
            raise ValueError("body shape")
        return value
