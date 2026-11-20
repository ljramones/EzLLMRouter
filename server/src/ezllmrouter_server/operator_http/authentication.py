"""Operator authentication handlers."""

import hmac
import secrets
import time
from contextlib import nullcontext
from http import cookies

from ..observability import log_failure
from ..canonical import ContractError
from ..user_management import ROLE_PERMISSIONS, UserError, username
from .application import OperatorSession
from .common import SESSION_SECONDS

SESSION_LIMIT = 64
SESSIONS_PER_PRINCIPAL = 4
ADMIN_SESSION_RESERVE = 8


class AuthenticationRoutes:
    def _make_session_room(self, item, discarded):
        """Called under the session lock after validating the new login."""
        sessions = self.application.sessions
        owned = sorted(
            (key for key, old in sessions.items() if old["principal_id"] == item["principal_id"]),
            key=lambda key: sessions[key]["expires"],
        )
        while len(owned) >= SESSIONS_PER_PRINCIPAL:
            discarded.append(sessions.pop(owned.pop(0)))
        ordinary = [key for key, old in sessions.items() if old["role"] != "registry_admin"]
        if item["role"] == "registry_admin" and len(sessions) >= SESSION_LIMIT and ordinary:
            oldest = min(ordinary, key=lambda key: sessions[key]["expires"])
            discarded.append(sessions.pop(oldest))
        elif (
            item["role"] != "registry_admin"
            and len(ordinary) >= SESSION_LIMIT - ADMIN_SESSION_RESERVE
        ):
            return False
        return len(sessions) < SESSION_LIMIT

    def _session_details(self, item):
        """Read current account state under the caller's database read gate."""
        details = {}
        if self.application.registry:
            principal = self.application.registry.principal(item["principal_id"])
            if not principal or principal["status"] != "active":
                return None
            details["role"] = principal["role"]
        if self.application.accounts:
            account = self.application.accounts.context(item["principal_id"])
            if item.get("user_auth_version") is not None and (
                not account or account["auth_version"] != item["user_auth_version"]
            ):
                return None
            if account:
                details.update(
                    username=account["username"],
                    display_name=account["display_name"],
                    must_change_password=bool(
                        item.get("named_login") and account["must_change_password"]
                    ),
                )
        return details

    def _revoke_session_tokens(self, items):
        for item in items:
            if self.application.registry and item.get("wire_token"):
                self.application.registry.revoke_local_operator_token(item["wire_token"])

    def _session(self):
        header = self.headers.get("Cookie", "")
        jar = cookies.SimpleCookie()
        try:
            jar.load(header)
            token = jar["ezllmrouter_operator"].value
        except (cookies.CookieError, KeyError):
            return None
        with self.application.session_lock:
            item = self.application.sessions.get(token)
            if not item:
                return None
            snapshot = item.copy()
        live = snapshot["expires"] > time.monotonic()
        registry = self.application.registry
        # Lock order is database, then a short session dictionary operation.
        # Logout may remove the session while account reads are in progress.
        with registry.store.database.read() if registry and live else nullcontext():
            details = self._session_details(snapshot) if live else None
            with self.application.session_lock:
                if self.application.sessions.get(token) is not item:
                    return None
                if details is not None and item["expires"] > time.monotonic():
                    item.update(details)
                    return token, dict(item)
                self.application.sessions.pop(token)
        self._revoke_session_tokens((snapshot,))
        return None

    def _session_payload(self, item):
        return {
            "authenticated": True,
            "csrf": item["csrf"],
            "role": item["role"],
            "principal_id": item["principal_id"],
            "username": item.get("username"),
            "display_name": item.get("display_name"),
            "must_change_password": item.get("must_change_password", False),
            "permissions": list(ROLE_PERMISSIONS.get(item["role"], ())),
            "user_management": self.application.accounts is not None,
        }

    def get_operator_v1_session(self, path, session, body, scope):
        return self._send(200, self._session_payload(session[1]))

    def post_operator_v1_login(self, path, session, body, scope):
        if (
            set(body) not in ({"password"}, {"username", "password"})
            or type(body["password"]) is not str
        ):
            return self._fail(400, "INVALID_BODY")
        peer = self.client_address[0] if isinstance(self.client_address, tuple) else "local"
        try:
            body["password"].encode("utf-8", "strict")
        except UnicodeError:
            return self._fail(400, "INVALID_BODY")
        subject = None
        if "username" in body:
            if self.application.accounts is None:
                return self._fail(401, "AUTH_FAILED")
            try:
                subject = username(body["username"])
            except UserError as exc:
                return self._fail(exc.status, exc.code)
        ticket = self.application.login_throttle.begin(peer, subject)
        if ticket is None:
            return self._fail(429, "LOGIN_RATE_LIMITED")
        outcome = {"failed": False, "success": False}
        try:
            return self._login(body, outcome)
        except Exception:
            log_failure("operator_http.authentication.unavailable")
            return self._fail(503, "AUTH_UNAVAILABLE")
        finally:
            self.application.login_throttle.finish(ticket, **outcome)

    def _login_rejected(self, outcome, status, code):
        outcome["failed"] = status == 401
        return self._fail(status, code)

    def _login(self, body, outcome):
        account = None
        named_login = "username" in body
        if named_login:
            if not self.application.accounts:
                return self._login_rejected(outcome, 401, "AUTH_FAILED")
            try:
                account = self.application.accounts.authenticate(body["username"], body["password"])
            except UserError as exc:
                return self._login_rejected(outcome, exc.status, exc.code)
            principal_id = account["principal_id"]
            principal = self.application.registry.principal(principal_id)
        elif hmac.compare_digest(self.application.password.encode(), body["password"].encode()):
            principal = (
                self.application.registry.principal(self.application.owner_id)
                if self.application.registry
                else None
            )
            if self.application.registry and (not principal or principal["status"] != "active"):
                return self._login_rejected(outcome, 401, "AUTH_FAILED")
            principal_id = self.application.owner_id
        elif self.application.registry:
            try:
                principal = self.application.registry.credential_principal(
                    body["password"], "human"
                )
                principal_id = principal["principal_id"]
            except ContractError as exc:
                if exc.status != 401:
                    raise
                return self._login_rejected(outcome, 401, "AUTH_FAILED")
        else:
            return self._login_rejected(outcome, 401, "AUTH_FAILED")
        if self.application.registry and (not principal or principal["status"] != "active"):
            return self._login_rejected(outcome, 401, "AUTH_FAILED")
        if self.application.accounts and (not account):
            account = self.application.accounts.context(principal_id)
        token, csrf = (secrets.token_urlsafe(32), secrets.token_urlsafe(32))
        item: OperatorSession = {
            "csrf": csrf,
            "principal_id": principal_id,
            "role": principal["role"] if principal else "registry_admin",
            "named_login": named_login,
            "username": account["username"] if account else None,
            "display_name": principal.get("display_name") if principal else None,
            "user_auth_version": account["auth_version"] if account else None,
            "must_change_password": bool(named_login and account["must_change_password"]),
            "wire_token": None,
            "expires": 0.0,
        }
        registry = self.application.registry
        discarded, failure, published = [], None, None
        with registry.store.database.read() if registry else nullcontext():
            details = self._session_details(item)
            if details is None:
                failure = (401, "AUTH_FAILED")
            else:
                item.update(details)
                if (
                    registry
                    and principal_id == self.application.owner_id
                    and item["role"] == "registry_admin"
                    and registry.personal_campaign
                    and not item["must_change_password"]
                ):
                    item["wire_token"] = registry.issue_local_operator_token(principal_id)
                with self.application.session_lock:
                    now = time.monotonic()
                    for key, old in tuple(self.application.sessions.items()):
                        if old["expires"] <= now:
                            discarded.append(self.application.sessions.pop(key))
                    if getattr(self.application, "_closing", False):
                        failure = (503, "SERVICE_UNAVAILABLE")
                        discarded.append(item)
                    elif not self._make_session_room(item, discarded):
                        failure = (429, "SESSION_LIMIT")
                        discarded.append(item)
                    else:
                        item["expires"] = now + SESSION_SECONDS
                        self.application.sessions[token] = item
                        published = dict(item)
        self._revoke_session_tokens(discarded)
        if failure:
            return self._fail(*failure)
        outcome["success"] = True
        return self._send(
            200,
            {**self._session_payload(published), "expires_in_seconds": SESSION_SECONDS},
            extra=(
                (
                    "Set-Cookie",
                    self._session_cookie(token, SESSION_SECONDS),
                ),
            ),
        )

    def post_operator_v1_logout(self, path, session, body, scope):
        if body:
            return self._fail(400, "INVALID_BODY")
        with self.application.session_lock:
            self.application.sessions.pop(session[0], None)
        if self.application.registry and session[1].get("wire_token"):
            self.application.registry.revoke_local_operator_token(session[1]["wire_token"])
        return self._send(
            200,
            {"authenticated": False},
            extra=(
                (
                    "Set-Cookie",
                    self._session_cookie("", 0),
                ),
            ),
        )
