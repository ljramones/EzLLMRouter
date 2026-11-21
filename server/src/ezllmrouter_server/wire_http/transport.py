"""Shared transport and authentication for the versioned wire APIs."""

from __future__ import annotations
from dataclasses import dataclass
from typing import cast
import socket
from socketserver import BaseServer
from .contracts import WorkCoordinator, WorkService
from ..records import Record
import json
import re
import uuid
from urllib.parse import urlsplit
from ..canonical import ContractError
from ..errors import RequestError
from ..http_server import SafeHTTPRequestHandler
from ..integration_accounting import IntegrationError
from ..observability import log_failure, log_rejection


@dataclass(frozen=True)
class WireApplication:
    coordinator: WorkCoordinator
    integration_only: bool = False


class WireTransport(SafeHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __init__(
        self,
        request: socket.socket,
        client_address: tuple[str, int],
        server: BaseServer,
        *,
        application: WireApplication,
    ) -> None:
        self.application = application
        super().__init__(request, client_address, server)

    @property
    def work_service(self) -> WorkService:
        coordinator = self.application.coordinator
        if self.selected_version == "0.3":
            if coordinator.successor is None:
                raise ContractError("UNSUPPORTED_VERSION", 426)
            return coordinator.successor
        return coordinator

    def log_message(self, *_args: object) -> None:
        return

    def _log_error(self, event: str, exc: Exception) -> None:
        if isinstance(exc, RequestError):
            log_rejection(event + ".rejected", code=exc.code, status=exc.status)
        else:
            log_failure(event + ".failed", exc)

    def _reply(self, status: int, value: Record) -> None:
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("EzLLMRouter-Contract-Version", value.get("contract_version", "0.2"))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, exc: Exception) -> None:
        if isinstance(exc, ContractError):
            code, status = (exc.code, exc.status)
        else:
            code, status = ("INTERNAL_UNAVAILABLE", 503)
        if status == 401 and code == "AUTHENTICATION_FAILED":
            self.close_connection = True
        if getattr(self, "selected_version", "0.2") == "0.3":
            if status == 401 and code == "AUTHENTICATION_FAILED":
                code = "POLICY_DENIED"
            if code not in {
                "UNSUPPORTED_VERSION",
                "MALFORMED_JSON",
                "SCHEMA_INVALID",
                "LIMIT_EXCEEDED",
                "SEMANTIC_INVALID",
                "CAPABILITY_UNSUPPORTED",
                "WORK_CONFLICT",
                "WORK_VERSION_CONFLICT",
                "NOT_FOUND_OR_FORBIDDEN",
                "POLICY_DENIED",
                "FINANCIAL_AUTH_REQUIRED",
                "PLAN_INVALID_OR_STALE",
                "FDC_REJECTED",
                "INTENT_PERSIST_FAILED",
                "RESULT_INVALID",
                "USAGE_UNKNOWN",
            }:
                code = "INTENT_PERSIST_FAILED"
            self._reply(
                status,
                {
                    "contract_version": "0.3",
                    "code": code,
                    "correlation_id": "error." + uuid.uuid4().hex,
                    "retry_guidance": getattr(
                        exc, "retry_guidance", "query_first" if status >= 500 else "never"
                    ),
                },
            )
        else:
            from ..core import public_error

            if code == "WORK_VERSION_CONFLICT":
                code = "WORK_CONFLICT"
            self._reply(
                status,
                {
                    "contract_version": "0.2",
                    "error": public_error(code, "query_first" if status >= 500 else "never"),
                },
            )

    def _context(self) -> Record:
        versions = self.headers.get_all("EzLLMRouter-Contract-Version")
        self.selected_version = versions[0] if versions and len(versions) == 1 else "0.2"
        if versions not in (["0.2"], ["0.3"]) or (
            versions == ["0.3"] and getattr(self.application.coordinator, "successor", None) is None
        ):
            raise ContractError("UNSUPPORTED_VERSION", 426)
        auth = self.headers.get_all("Authorization")
        if not auth or len(auth) != 1 or (not auth[0].startswith("Bearer ")):
            raise ContractError("AUTHENTICATION_FAILED", 401)
        return self.application.coordinator.authenticate(auth[0][7:])

    def _path(self) -> str:
        parsed = urlsplit(self.path)
        if parsed.query or parsed.fragment:
            raise ContractError("SCHEMA_INVALID", 400)
        return parsed.path

    def _integration_reply(
        self, status: int, value: Record | None, *, csv_body: bytes | None = None
    ) -> None:
        body = (
            csv_body
            if csv_body is not None
            else json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        self.send_response(status)
        self.send_header(
            "Content-Type",
            "text/csv; charset=utf-8"
            if csv_body is not None
            else "application/json; charset=utf-8",
        )
        self.send_header("Content-Length", str(len(body)))
        self.send_header(
            "EzLLMRouter-Integration-Version", getattr(self, "integration_version", "1")
        )
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.end_headers()
        self.wfile.write(body)

    def _integration_auth(self) -> Record:
        match = re.match("^/integration/v([123])/", urlsplit(self.path).path)
        self.integration_version = match[1] if match else "1"
        if (
            self.headers.get_all("EzLLMRouter-Integration-Version") != [self.integration_version]
            or not self.application.coordinator.registry
        ):
            raise IntegrationError("UNSUPPORTED_VERSION", 426)
        auth = self.headers.get_all("Authorization")
        if not auth or len(auth) != 1 or (not auth[0].startswith("Bearer ")):
            raise IntegrationError("AUTHENTICATION_FAILED", 401)
        try:
            return cast(
                Record, self.application.coordinator.registry.credential_principal(auth[0][7:])
            )
        except ContractError as exc:
            raise IntegrationError("AUTHENTICATION_FAILED", 401) from exc

    def _integration_error(self, exc: Exception) -> None:
        if isinstance(exc, IntegrationError):
            status, code, guidance = (exc.status, exc.code, exc.retry_guidance)
        else:
            status, code, guidance = (503, "INTERNAL_UNAVAILABLE", "query_first")
        if status == 401:
            self.close_connection = True
        self._integration_reply(
            status,
            {
                "integration_version": getattr(self, "integration_version", "1"),
                "error": {"code": code, "retry_guidance": guidance},
            },
        )

    def _json_bytes(self, maximum: int, *, integration: bool = False) -> bytes:
        error = IntegrationError if integration else ContractError
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get_all("Content-Type") != ["application/json"] and (not integration):
            raise error("SCHEMA_INVALID", 400)
        if (
            self.headers.get_all("Content-Type") != ["application/json"]
            or len(lengths or []) != 1
            or (not lengths[0].isascii())
            or (not lengths[0].isdigit())
            or (int(lengths[0]) > maximum)
            or self.headers.get_all("Transfer-Encoding")
        ):
            raise error("LIMIT_EXCEEDED", 413)
        body = self.read_body(int(lengths[0]))
        if len(body) != int(lengths[0]):
            raise error("SCHEMA_INVALID", 400)
        return body
