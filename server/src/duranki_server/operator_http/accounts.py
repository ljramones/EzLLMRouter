"""Operator accounts handlers."""
from .common import (ConnectorError, NOT_HANDLED, UserError, log_failure)

class AccountsRoutes:

    def _user_write(self, body, session, *, delete=False):
        if not self.application.accounts:
            return self._fail(404, 'NOT_FOUND')
        actor = session[1]['principal_id']
        try:
            if self.path == '/operator/v1/account/password' and (not delete):
                self.application.accounts.change_password(actor, body)
                with self.application.session_lock:
                    item = self.application.sessions.pop(session[0], None)
                if item and item.get('wire_token'):
                    self.application.registry.revoke_local_operator_token(item['wire_token'])
                return self._send(200, {'authenticated': False, 'password_changed': True}, extra=(('Set-Cookie', 'duranki_operator=; Path=/operator; HttpOnly; SameSite=Strict; Max-Age=0'),))
            if session[1]['role'] != 'registry_admin':
                return self._fail(403, 'ADMIN_REQUIRED')
            if self.path == '/operator/v1/users' and (not delete):
                return self._send(201, self.application.accounts.create(actor, body))
            parts = self.path[len('/operator/v1/users/'):].split('/')
            if len(parts) == 1 and parts[0]:
                operation = self.application.accounts.delete if delete else self.application.accounts.update
                return self._send(200, operation(actor, parts[0], body))
            if len(parts) == 2 and parts[1] == 'password' and (not delete):
                return self._send(200, self.application.accounts.reset_password(actor, parts[0], body))
            return self._fail(404, 'NOT_FOUND')
        except UserError as exc:
            return self._fail(exc.status, exc.code)
        except (ValueError, TypeError, KeyError):
            return self._fail(400, 'INVALID_USER_CHANGE')
        except Exception:
            log_failure('operator_web.serve.Handler._user_write.failed')
            return self._fail(503, 'USER_MANAGEMENT_UNAVAILABLE')

    def _local_connector_write(self, body, session, *, delete=False):
        if not self.application.local_connectors:
            return self._fail(404, 'NOT_FOUND')
        actor = session[1]['principal_id']
        try:
            if self.path == '/operator/v1/local-connectors/check' and (not delete):
                return self._send(200, self.application.local_connectors.availability(actor, body))
            if session[1]['role'] != 'registry_admin':
                return self._fail(403, 'ADMIN_REQUIRED')
            if self.path == '/operator/v1/local-connectors/find' and (not delete):
                return self._send(200, self.application.local_connectors.nearby(actor, body))
            if self.path == '/operator/v1/local-connectors' and (not delete):
                return self._send(201, self.application.local_connectors.create(actor, body))
            parts = self.path[len('/operator/v1/local-connectors/'):].split('/')
            if len(parts) == 1 and parts[0]:
                operation = self.application.local_connectors.delete if delete else self.application.local_connectors.update
                return self._send(200, operation(actor, parts[0], body))
            if len(parts) == 2 and parts[0] and (not delete):
                operation = {'discover': self.application.local_connectors.discover, 'models': self.application.local_connectors.configure}.get(parts[1])
                if operation:
                    return self._send(200, operation(actor, parts[0], body))
            return self._fail(404, 'NOT_FOUND')
        except ConnectorError as exc:
            return self._fail(exc.status, exc.code)
        except (ValueError, TypeError, KeyError):
            return self._fail(400, 'INVALID_CONNECTOR_CHANGE')
        except Exception:
            log_failure('operator_web.serve.Handler._local_connector_write.failed')
            return self._fail(503, 'CONNECTOR_UNAVAILABLE')

    def get_operator_v1_local_connectors(self, path, session, body, scope):
        if path.path == '/operator/v1/local-connectors' and (not path.query) and self.application.local_connectors:
            return self._send(200, self.application.local_connectors.list(session[1]['principal_id']))
        return NOT_HANDLED

    def get_operator_v1_local_connectors_availability(self, path, session, body, scope):
        if path.path == '/operator/v1/local-connectors/availability' and (not path.query) and self.application.local_connectors:
            return self._send(200, self.application.local_connectors.availability(session[1]['principal_id']))
        return NOT_HANDLED

    def get_operator_v1_local_connectors_nearby(self, path, session, body, scope):
        if path.path == '/operator/v1/local-connectors/nearby' and (not path.query) and self.application.local_connectors:
            return self._send(200, self.application.local_connectors.nearby(session[1]['principal_id']))
        return NOT_HANDLED

    def get_local_connector(self, path, session, body, scope):
        if path.path.startswith('/operator/v1/local-connectors/') and (not path.query) and self.application.local_connectors:
            connector_id = path.path[len('/operator/v1/local-connectors/'):]
            if '/' in connector_id or not connector_id:
                return self._fail(404, 'NOT_FOUND')
            return self._send(200, self.application.local_connectors.get(session[1]['principal_id'], connector_id))
        return NOT_HANDLED

    def get_operator_v1_users(self, path, session, body, scope):
        if path.path == '/operator/v1/users' and (not path.query) and self.application.accounts:
            return self._send(200, self.application.accounts.list(session[1]['principal_id']))
        return NOT_HANDLED

    def get_user(self, path, session, body, scope):
        if path.path.startswith('/operator/v1/users/') and (not path.query) and self.application.accounts:
            principal_id = path.path[len('/operator/v1/users/'):]
            if '/' in principal_id or not principal_id:
                return self._fail(404, 'NOT_FOUND')
            return self._send(200, self.application.accounts.get(session[1]['principal_id'], principal_id))
        return NOT_HANDLED

    def post_operator_v1_users(self, path, session, body, scope):
        if self.path in ('/operator/v1/users', '/operator/v1/account/password') or self.path.startswith('/operator/v1/users/'):
            return self._user_write(body, session)
        return NOT_HANDLED

    def post_operator_v1_local_connectors(self, path, session, body, scope):
        if self.path == '/operator/v1/local-connectors' or self.path.startswith('/operator/v1/local-connectors/'):
            return self._local_connector_write(body, session)
        return NOT_HANDLED
