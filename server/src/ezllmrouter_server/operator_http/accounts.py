"""Operator accounts handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast
from urllib.parse import SplitResult
from ..records import Record
from .context import OperatorContext, Session


from ..local_connectors import ConnectorError
from ..observability import log_failure
from ..user_management import UserError


class AccountsRoutes:
    def delete_user(
        self: OperatorContext, path: SplitResult, session: Session, body: Record, scope: str | None
    ) -> None:
        return self._user_write(body, session, delete=True)

    def delete_local_connector(
        self: OperatorContext, path: SplitResult, session: Session, body: Record, scope: str | None
    ) -> None:
        return self._local_connector_write(body, session, delete=True)

    def _user_write(
        self: OperatorContext, body: Record, session: Session, *, delete: bool = False
    ) -> None:
        if not self.application.accounts:
            return self._fail(404, "NOT_FOUND")
        actor = session[1]["principal_id"]
        operation: Callable[[str, str, Record], Record] | None
        try:
            if self.path == "/operator/v1/account/password" and (not delete):
                peer = self.client_address[0] if isinstance(self.client_address, tuple) else "local"
                self._accounts.change_password(actor, body, peer=peer)
                with self.application.session_lock:
                    item = self.application.sessions.pop(session[0], None)
                if item and item.get("wire_token"):
                    self._registry.revoke_local_operator_token(cast(str, item["wire_token"]))
                return self._send(
                    200,
                    {"authenticated": False, "password_changed": True},
                    extra=(
                        (
                            "Set-Cookie",
                            self._session_cookie("", 0),
                        ),
                    ),
                )
            if session[1]["role"] != "registry_admin":
                return self._fail(403, "ADMIN_REQUIRED")
            if self.path == "/operator/v1/users" and (not delete):
                return self._send(201, self._accounts.create(actor, body))
            parts = self.path[len("/operator/v1/users/") :].split("/")
            if len(parts) == 1 and parts[0]:
                operation = self._accounts.delete if delete else self._accounts.update
                return self._send(200, operation(actor, parts[0], body))
            if len(parts) == 2 and parts[1] == "password" and (not delete):
                return self._send(200, self._accounts.reset_password(actor, parts[0], body))
            return self._fail(404, "NOT_FOUND")
        except UserError as exc:
            return self._fail(exc.status, exc.code)
        except (ValueError, TypeError, KeyError):
            return self._fail(400, "INVALID_USER_CHANGE")
        except Exception:
            log_failure("operator_http.accounts.user_write.failed")
            return self._fail(503, "USER_MANAGEMENT_UNAVAILABLE")

    def _local_connector_write(
        self: OperatorContext, body: Record, session: Session, *, delete: bool = False
    ) -> None:
        if not self.application.local_connectors:
            return self._fail(404, "NOT_FOUND")
        actor = session[1]["principal_id"]
        operation: Callable[[str, str, Record], Record] | None
        try:
            if self.path == "/operator/v1/local-connectors/check" and (not delete):
                return self._send(200, self._connectors.availability(actor, body))
            if session[1]["role"] != "registry_admin":
                return self._fail(403, "ADMIN_REQUIRED")
            if self.path == "/operator/v1/local-connectors/find" and (not delete):
                return self._send(200, self._connectors.nearby(actor, body))
            if self.path == "/operator/v1/local-connectors" and (not delete):
                return self._send(201, self._connectors.create(actor, body))
            parts = self.path[len("/operator/v1/local-connectors/") :].split("/")
            if len(parts) == 1 and parts[0]:
                operation = self._connectors.delete if delete else self._connectors.update
                return self._send(200, operation(actor, parts[0], body))
            if len(parts) == 2 and parts[0] and (not delete):
                operation = {
                    "discover": self._connectors.discover,
                    "models": self._connectors.configure,
                }.get(parts[1])
                if operation:
                    return self._send(200, operation(actor, parts[0], body))
            return self._fail(404, "NOT_FOUND")
        except ConnectorError as exc:
            return self._fail(exc.status, exc.code)
        except (ValueError, TypeError, KeyError):
            return self._fail(400, "INVALID_CONNECTOR_CHANGE")
        except Exception:
            log_failure("operator_http.accounts.local_connector_write.failed")
            return self._fail(503, "CONNECTOR_UNAVAILABLE")

    def get_operator_v1_local_connectors(
        self: OperatorContext, path: SplitResult, session: Session, body: None, scope: str | None
    ) -> None:
        return self._send(200, self._connectors.list(session[1]["principal_id"]))

    def get_operator_v1_local_connectors_availability(
        self: OperatorContext, path: SplitResult, session: Session, body: None, scope: str | None
    ) -> None:
        return self._send(200, self._connectors.availability(session[1]["principal_id"]))

    def get_operator_v1_local_connectors_nearby(
        self: OperatorContext, path: SplitResult, session: Session, body: None, scope: str | None
    ) -> None:
        return self._send(200, self._connectors.nearby(session[1]["principal_id"]))

    def get_local_connector(
        self: OperatorContext, path: SplitResult, session: Session, body: None, scope: str | None
    ) -> None:
        connector_id = path.path[len("/operator/v1/local-connectors/") :]
        if "/" in connector_id or not connector_id:
            return self._fail(404, "NOT_FOUND")
        return self._send(200, self._connectors.get(session[1]["principal_id"], connector_id))

    def get_operator_v1_users(
        self: OperatorContext, path: SplitResult, session: Session, body: None, scope: str | None
    ) -> None:
        return self._send(200, self._accounts.list(session[1]["principal_id"]))

    def get_user(
        self: OperatorContext, path: SplitResult, session: Session, body: None, scope: str | None
    ) -> None:
        principal_id = path.path[len("/operator/v1/users/") :]
        if "/" in principal_id or not principal_id:
            return self._fail(404, "NOT_FOUND")
        return self._send(200, self._accounts.get(session[1]["principal_id"], principal_id))

    def post_operator_v1_users(
        self: OperatorContext, path: None, session: Session, body: Record, scope: str | None
    ) -> None:
        return self._user_write(body, session)

    def post_operator_v1_local_connectors(
        self: OperatorContext, path: None, session: Session, body: Record, scope: str | None
    ) -> None:
        return self._local_connector_write(body, session)
