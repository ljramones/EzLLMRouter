"""HTTP entry points with explicit routing; authentication precedes body reads."""

import json
from typing import TYPE_CHECKING, cast
from urllib.parse import urlsplit

from ..http_server import SafeHTTPRequestHandler
from ..integration_accounting import IntegrationError
from ..local_connectors import ConnectorError
from ..observability import log_failure
from ..user_management import UserError
from .accounts import AccountsRoutes
from .assets import AssetsRoutes
from .authentication import AuthenticationRoutes
from .integration import IntegrationRoutes
from .registry_routes import RegistryRoutes
from .reports import ReportsRoutes
from .routing import ROUTER, Route, Stage
from .transport import TransportRoutes

if TYPE_CHECKING:
    from .application import OperatorApplication


class OperatorHandler(
    TransportRoutes,
    AuthenticationRoutes,
    AccountsRoutes,
    RegistryRoutes,
    IntegrationRoutes,
    ReportsRoutes,
    AssetsRoutes,
    SafeHTTPRequestHandler,
):
    protocol_version = "HTTP/1.1"

    @property
    def application(self) -> "OperatorApplication":
        return cast("OperatorApplication", self.server.application)

    def _route(self, method, path, *, query=False):
        available = {
            name
            for name in ("accounts", "local_connectors", "registry", "successor_store")
            if getattr(self.application, name) is not None
        }
        return ROUTER.resolve(method, path, query=query, available=available)

    def _dispatch(
        self, route: Route | None, stage: Stage, *, path=None, session=None, body=None, scope=None
    ):
        if route is None or route.stage != stage:
            return False
        if route.roles and (session is None or session[1]["role"] not in route.roles):
            self._fail(403, "OPERATOR_REQUIRED")
            return True
        getattr(self, route.handler)(path, session, body, scope)
        return True

    @staticmethod
    def _integration_read_allowed(path):
        return path.startswith(
            ("/operator/v1/principals/", "/operator/v1/models/", "/operator/v1/connections/")
        ) or path in (
            "/operator/v1/usage-costs",
            "/operator/v1/models",
            "/operator/v1/principals",
            "/operator/v1/connections",
            "/operator/v1/access/explain",
            "/operator/v1/usage",
            "/operator/v1/demo-workspace",
        )

    @staticmethod
    def _ordinary_read_allowed(path):
        return path in (
            "/operator/v1/overview",
            "/operator/v1/activity",
            "/operator/v1/usage",
        ) or path.startswith("/operator/v1/activity/")

    def do_GET(self):
        if not self._origin_ok():
            return self._fail(403, "ORIGIN_REJECTED")
        path = urlsplit(self.path)
        if path.fragment:
            return self._fail(400, "INVALID_PATH")
        route = self._route("GET", path.path, query=bool(path.query))
        try:
            if self._dispatch(route, "asset", path=path):
                return
        except OSError:
            log_failure("operator_http.asset.unavailable")
            return self._fail(503, "ASSET_UNAVAILABLE")
        session = self._session()
        if not session:
            return self._fail(401, "AUTH_REQUIRED")
        try:
            if self._dispatch(route, "session", path=path, session=session):
                return
            if session[1].get("must_change_password"):
                return self._fail(403, "PASSWORD_CHANGE_REQUIRED")
            if self._dispatch(route, "account", path=path, session=session):
                return
            if self.application.integration_only and not self._integration_read_allowed(path.path):
                return self._fail(404, "NOT_FOUND")
            if self._dispatch(route, "resource", path=path, session=session):
                return
            scope = (
                ("*" if session[1]["role"] != "ordinary" else session[1]["principal_id"])
                if self.application.registry
                else None
            )
            if (
                self.application.registry
                and session[1]["role"] == "ordinary"
                and not self._ordinary_read_allowed(path.path)
            ):
                return self._fail(403, "OPERATOR_REQUIRED")
            if self._dispatch(route, "activity", path=path, session=session, scope=scope):
                return
        except (IntegrationError, UserError, ConnectorError) as exc:
            return self._fail(exc.status, exc.code)
        except (ValueError, KeyError, TypeError):
            return self._fail(400, "INVALID_SELECTOR")
        except Exception:
            log_failure(route.failure_event if route else "operator_http.read.failed")
            return self._fail(503, "METADATA_UNAVAILABLE")
        return self._fail(404, "NOT_FOUND")

    def do_POST(self):
        if not self._origin_ok(mutation=True) or urlsplit(self.path).query:
            self.close_connection = True
            return self._fail(403, "ORIGIN_REJECTED")
        session = None
        if self.path != "/operator/v1/login":
            session = self._session()
            if not session:
                self.close_connection = True
                return self._fail(401, "AUTH_REQUIRED")
            if not self._csrf_ok(session):
                self.close_connection = True
                return self._fail(403, "CSRF_REJECTED")
        try:
            body = self._body()
        except (ValueError, UnicodeError, json.JSONDecodeError):
            return self._fail(400, "INVALID_BODY")
        route = self._route("POST", self.path)
        if self._dispatch(route, "login", body=body):
            return
        session = self._session()
        if not session:
            return self._fail(401, "AUTH_REQUIRED")
        if not self._csrf_ok(session):
            return self._fail(403, "CSRF_REJECTED")
        if session[1].get("must_change_password") and self.path not in (
            "/operator/v1/account/password",
            "/operator/v1/logout",
        ):
            return self._fail(403, "PASSWORD_CHANGE_REQUIRED")
        if self._dispatch(route, "account_write", session=session, body=body):
            return
        if (
            self.application.integration_only
            and self.path != "/operator/v1/logout"
            and (not (self.path == "/operator/v1/registry" and body.get("action") == "set_grant"))
        ):
            return self._fail(404, "NOT_FOUND")
        if self._dispatch(route, "operation", session=session, body=body):
            return
        return self._fail(404, "NOT_FOUND")

    def do_DELETE(self):
        path = urlsplit(self.path)
        if not self._origin_ok(mutation=True) or path.query or path.fragment:
            self.close_connection = True
            return self._fail(403, "ORIGIN_REJECTED")
        session = self._session()
        if not session:
            self.close_connection = True
            return self._fail(401, "AUTH_REQUIRED")
        if not self._csrf_ok(session):
            self.close_connection = True
            return self._fail(403, "CSRF_REJECTED")
        try:
            body = self._body()
        except (ValueError, UnicodeError, json.JSONDecodeError):
            return self._fail(400, "INVALID_BODY")
        if session[1].get("must_change_password"):
            return self._fail(403, "PASSWORD_CHANGE_REQUIRED")
        route = self._route("DELETE", path.path)
        if self._dispatch(route, "delete", path=path, session=session, body=body):
            return
        return self._fail(404, "NOT_FOUND")
