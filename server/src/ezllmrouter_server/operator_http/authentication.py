"""Operator authentication handlers."""
from .common import (
    NOT_HANDLED,
    ROLE_PERMISSIONS,
    SESSION_SECONDS,
    UserError,
    cookies,
    hmac,
    log_failure,
    secrets,
    time,
)

class AuthenticationRoutes:

    def _session(self):
        header = self.headers.get('Cookie', '')
        jar = cookies.SimpleCookie()
        try:
            jar.load(header)
            token = jar['ezllmrouter_operator'].value
        except (cookies.CookieError, KeyError):
            return None
        with self.application.session_lock:
            item = self.application.sessions.get(token)
            if not item:
                return None
            if item['expires'] <= time.monotonic():
                self.application.sessions.pop(token, None)
                return None
            if self.application.registry:
                principal = self.application.registry.principal(item['principal_id'])
                if not principal or principal['status'] != 'active':
                    self.application.sessions.pop(token, None)
                    return None
                item['role'] = principal['role']
            if self.application.accounts:
                account = self.application.accounts.context(item['principal_id'])
                if item.get('user_auth_version') is not None and (not account or account['auth_version'] != item['user_auth_version']):
                    self.application.sessions.pop(token, None)
                    if item.get('wire_token'):
                        self.application.registry.revoke_local_operator_token(item['wire_token'])
                    return None
                if account:
                    item['username'] = account['username']
                    item['display_name'] = account['display_name']
                    item['must_change_password'] = bool(item.get('named_login') and account['must_change_password'])
            return (token, item)

    def _session_payload(self, item):
        return {'authenticated': True, 'csrf': item['csrf'], 'role': item['role'], 'principal_id': item['principal_id'], 'username': item.get('username'), 'display_name': item.get('display_name'), 'must_change_password': item.get('must_change_password', False), 'permissions': list(ROLE_PERMISSIONS.get(item['role'], ())), 'user_management': self.application.accounts is not None}

    def get_operator_v1_session(self, path, session, body, scope):
        if path.path == '/operator/v1/session' and (not path.query):
            return self._send(200, self._session_payload(session[1]))
        return NOT_HANDLED

    def post_operator_v1_login(self, path, session, body, scope):
        if self.path == '/operator/v1/login':
            if set(body) not in ({'password'}, {'username', 'password'}) or type(body['password']) is not str:
                return self._fail(400, 'INVALID_BODY')
            peer = self.client_address[0] if isinstance(self.client_address, tuple) else 'local'
            if not self.application.login_throttle.allow(peer):
                return self._fail(429, 'LOGIN_RATE_LIMITED')
            account = None
            named_login = 'username' in body
            if named_login:
                if not self.application.accounts:
                    return self._fail(401, 'AUTH_FAILED')
                try:
                    account = self.application.accounts.authenticate(body['username'], body['password'])
                except UserError as exc:
                    return self._fail(exc.status, exc.code)
                principal_id = account['principal_id']
                principal = self.application.registry.principal(principal_id)
            elif hmac.compare_digest(self.application.password.encode(), body['password'].encode()):
                principal = self.application.registry.principal('owner.local') if self.application.registry else None
                if self.application.registry and (not principal or principal['status'] != 'active'):
                    return self._fail(401, 'AUTH_FAILED')
                principal_id = 'owner.local'
            elif self.application.registry:
                try:
                    principal = self.application.registry.credential_principal(body['password'], 'human')
                    principal_id = principal['principal_id']
                except Exception:
                    log_failure('operator_web.serve.Handler.do_POST.failed')
                    return self._fail(401, 'AUTH_FAILED')
            else:
                return self._fail(401, 'AUTH_FAILED')
            if self.application.accounts and (not account):
                account = self.application.accounts.context(principal_id)
            token, csrf = (secrets.token_urlsafe(32), secrets.token_urlsafe(32))
            with self.application.session_lock:
                for key in tuple(self.application.sessions):
                    if self.application.sessions[key]['expires'] <= time.monotonic():
                        self.application.sessions.pop(key)
                if len(self.application.sessions) >= 64:
                    return self._fail(429, 'SESSION_LIMIT')
                self.application.sessions[token] = {'csrf': csrf, 'expires': time.monotonic() + SESSION_SECONDS, 'principal_id': principal_id, 'role': principal['role'] if self.application.registry else 'registry_admin', 'named_login': named_login, 'username': account['username'] if account else None, 'display_name': principal.get('display_name') if principal else None, 'user_auth_version': account['auth_version'] if account else None, 'must_change_password': bool(named_login and account['must_change_password']), 'wire_token': self.application.registry.issue_local_operator_token(principal_id) if self.application.registry and principal_id == 'owner.local' and getattr(self.application.registry, 'personal_campaign', None) and (not (named_login and account['must_change_password'])) else None}
            return self._send(200, {**self._session_payload(self.application.sessions[token]), 'expires_in_seconds': SESSION_SECONDS}, extra=(('Set-Cookie', 'ezllmrouter_operator=' + token + '; Path=/operator; HttpOnly; SameSite=Strict; Max-Age=1800'),))
        return NOT_HANDLED

    def post_operator_v1_logout(self, path, session, body, scope):
        if self.path == '/operator/v1/logout':
            if body:
                return self._fail(400, 'INVALID_BODY')
            with self.application.session_lock:
                self.application.sessions.pop(session[0], None)
            if self.application.registry and session[1].get('wire_token'):
                self.application.registry.revoke_local_operator_token(session[1]['wire_token'])
            return self._send(200, {'authenticated': False}, extra=(('Set-Cookie', 'ezllmrouter_operator=; Path=/operator; HttpOnly; SameSite=Strict; Max-Age=0'),))
        return NOT_HANDLED
