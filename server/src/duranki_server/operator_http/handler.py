"""HTTP entry points and ordered route dispatch; authentication precedes body reads."""
from .common import SafeHTTPRequestHandler
from .common import (
    ConnectorError,
    IntegrationError,
    NOT_HANDLED,
    UserError,
    hmac,
    json,
    log_failure,
    urlsplit,
)

from .transport import TransportRoutes
from .authentication import AuthenticationRoutes
from .accounts import AccountsRoutes
from .registry_routes import RegistryRoutes
from .integration import IntegrationRoutes
from .reports import ReportsRoutes
from .assets import AssetsRoutes

ASSET_ROUTES = ('get_assets',)
SESSION_ROUTES = ('get_operator_v1_session',)
ACCOUNT_READ_ROUTES = (
    'get_operator_v1_local_connectors',
    'get_operator_v1_local_connectors_availability',
    'get_operator_v1_local_connectors_nearby',
    'get_local_connector',
    'get_operator_v1_users',
    'get_user',
    'get_operator_v1_integration_vega_me',
    'get_operator_v1_mach33_demo',
    'get_operator_v1_integration',
)
RESOURCE_READ_ROUTES = (
    'get_operator_v1_dev12_usage',
    'get_operator_v1_demo_workspace',
    'get_operator_v1_usage_costs',
    'get_registry_resource',
)
ACTIVITY_READ_ROUTES = (
    'get_operator_v1_overview',
    'get_operator_v1_activity',
    'get_activity_detail',
    'get_operator_v1_usage',
    'get_operator_v1_config',
    'get_operator_v1_build',
    'get_operator_v1_launch',
)
LOGIN_ROUTES = ('post_operator_v1_login',)
ACCOUNT_WRITE_ROUTES = (
    'post_operator_v1_users',
    'post_operator_v1_local_connectors',
    'post_operator_v1_integration',
)
OPERATION_WRITE_ROUTES = (
    'post_operator_v1_logout',
    'post_operator_v1_registry',
    'post_operator_v1_personal_campaign',
    'post_operator_v1_provider_credential',
    'post_operator_v1_provider_probe',
    'post_operator_v1_provider_validation',
    'post_operator_v1_provision',
    'post_operator_v1_demos',
)

class OperatorHandler(TransportRoutes, AuthenticationRoutes, AccountsRoutes, RegistryRoutes, IntegrationRoutes, ReportsRoutes, AssetsRoutes, SafeHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    @property
    def application(self):
        return self.server.application

    def _dispatch(self, routes, *, path=None, session=None, body=None, scope=None):
        for name in routes:
            handled = getattr(self, name)(path, session, body, scope)
            if handled is not NOT_HANDLED:
                return handled
        return NOT_HANDLED

    @staticmethod
    def _integration_read_allowed(path):
        return path.startswith(("/operator/v1/principals/", "/operator/v1/models/",
                                "/operator/v1/connections/")) or path in (
            "/operator/v1/usage-costs", "/operator/v1/models", "/operator/v1/principals",
            "/operator/v1/connections", "/operator/v1/access/explain", "/operator/v1/usage",
            "/operator/v1/demo-workspace")

    @staticmethod
    def _ordinary_read_allowed(path):
        return path in ("/operator/v1/overview", "/operator/v1/activity", "/operator/v1/usage") or \
            path.startswith("/operator/v1/activity/")

    def do_GET(self):
        if not self._origin_ok():
            return self._fail(403, 'ORIGIN_REJECTED')
        path = urlsplit(self.path)
        if path.fragment:
            return self._fail(400, 'INVALID_PATH')
        handled = self._dispatch(ASSET_ROUTES, path=path, session=None, body=None, scope=None)
        if handled is not NOT_HANDLED:
            return handled
        session = self._session()
        if not session:
            return self._fail(401, 'AUTH_REQUIRED')
        try:
            handled = self._dispatch(SESSION_ROUTES, path=path, session=session, body=None, scope=None)
            if handled is not NOT_HANDLED:
                return handled
            if session[1].get('must_change_password'):
                return self._fail(403, 'PASSWORD_CHANGE_REQUIRED')
            handled = self._dispatch(ACCOUNT_READ_ROUTES, path=path, session=session, body=None, scope=None)
            if handled is not NOT_HANDLED:
                return handled
            if self.application.integration_only and not self._integration_read_allowed(path.path):
                return self._fail(404, 'NOT_FOUND')
            handled = self._dispatch(RESOURCE_READ_ROUTES, path=path, session=session, body=None, scope=None)
            if handled is not NOT_HANDLED:
                return handled
            scope = ('*' if session[1]['role'] != 'ordinary' else session[1]['principal_id']) if self.application.registry else None
            if (self.application.registry and session[1]["role"] == "ordinary" and
                    not self._ordinary_read_allowed(path.path)):
                return self._fail(403, 'OPERATOR_REQUIRED')
            handled = self._dispatch(ACTIVITY_READ_ROUTES, path=path, session=session, body=None, scope=scope)
            if handled is not NOT_HANDLED:
                return handled
        except (IntegrationError, UserError, ConnectorError) as exc:
            return self._fail(exc.status, exc.code)
        except (ValueError, KeyError, TypeError):
            return self._fail(400, 'INVALID_SELECTOR')
        except Exception:
            log_failure('operator_web.serve.Handler.do_GET.failed')
            return self._fail(503, 'METADATA_UNAVAILABLE')
        return self._fail(404, 'NOT_FOUND')

    def do_POST(self):
        if not self._origin_ok(mutation=True) or urlsplit(self.path).query:
            return self._fail(403, 'ORIGIN_REJECTED')
        session = None
        if self.path != '/operator/v1/login':
            session = self._session()
            if not session:
                self.close_connection = True
                return self._fail(401, 'AUTH_REQUIRED')
            if not hmac.compare_digest(self.headers.get('X-Duranki-CSRF', ''), session[1]['csrf']):
                self.close_connection = True
                return self._fail(403, 'CSRF_REJECTED')
        try:
            body = self._body()
        except (ValueError, UnicodeError, json.JSONDecodeError):
            return self._fail(400, 'INVALID_BODY')
        handled = self._dispatch(LOGIN_ROUTES, path=None, session=session, body=body, scope=None)
        if handled is not NOT_HANDLED:
            return handled
        session = self._session()
        if not session:
            return self._fail(401, 'AUTH_REQUIRED')
        if not hmac.compare_digest(self.headers.get('X-Duranki-CSRF', ''), session[1]['csrf']):
            return self._fail(403, 'CSRF_REJECTED')
        if session[1].get('must_change_password') and self.path not in ('/operator/v1/account/password', '/operator/v1/logout'):
            return self._fail(403, 'PASSWORD_CHANGE_REQUIRED')
        handled = self._dispatch(ACCOUNT_WRITE_ROUTES, path=None, session=session, body=body, scope=None)
        if handled is not NOT_HANDLED:
            return handled
        if self.application.integration_only and self.path != '/operator/v1/logout' and (not (self.path == '/operator/v1/registry' and body.get('action') == 'set_grant')):
            return self._fail(404, 'NOT_FOUND')
        handled = self._dispatch(OPERATION_WRITE_ROUTES, path=None, session=session, body=body, scope=None)
        if handled is not NOT_HANDLED:
            return handled
        return self._fail(404, 'NOT_FOUND')

    def do_DELETE(self):
        path = urlsplit(self.path)
        if not self._origin_ok(mutation=True) or path.query or path.fragment:
            self.close_connection = True
            return self._fail(403, 'ORIGIN_REJECTED')
        session = self._session()
        if not session:
            self.close_connection = True
            return self._fail(401, 'AUTH_REQUIRED')
        if not hmac.compare_digest(self.headers.get('X-Duranki-CSRF', ''), session[1]['csrf']):
            self.close_connection = True
            return self._fail(403, 'CSRF_REJECTED')
        try:
            body = self._body()
        except (ValueError, UnicodeError, json.JSONDecodeError):
            return self._fail(400, 'INVALID_BODY')
        if session[1].get('must_change_password'):
            return self._fail(403, 'PASSWORD_CHANGE_REQUIRED')
        if path.path.startswith('/operator/v1/users/'):
            return self._user_write(body, session, delete=True)
        if path.path.startswith('/operator/v1/local-connectors/'):
            return self._local_connector_write(body, session, delete=True)
        return self._fail(404, 'NOT_FOUND')
