"""Operator integration handlers."""
from .common import (
    HTTPConnection,
    IntegrationError,
    NOT_HANDLED,
    cookies,
    csv,
    io,
    json,
    log_failure,
    parse_qs,
    route_id,
)

class IntegrationRoutes:

    def get_operator_v1_integration_vega_me(self, path, session, body, scope):
        if path.path == '/operator/v1/integration/vega-me' and (not path.query):
            if not self.application.integration_only or session[1]['role'] != 'registry_admin':
                return self._fail(404, 'NOT_FOUND')
            jar = cookies.SimpleCookie()
            try:
                jar.load(self.headers.get('Cookie', ''))
            except cookies.CookieError:
                return self._send(200, {'user': None})
            session_cookies = [f'{name}={morsel.value}' for name, morsel in jar.items() if name == 'm33_session' or name.startswith('m33_session_')]
            if not session_cookies:
                return self._send(200, {'user': None})
            connection = HTTPConnection('127.0.0.1', 3049, timeout=2)
            try:
                connection.request('GET', '/api/me', headers={'Cookie': '; '.join(session_cookies)})
                response = connection.getresponse()
                body = response.read(4097)
                if response.status != 200 or len(body) > 4096:
                    return self._send(200, {'user': None})
                identity = json.loads(body).get('user') or {}
                if not isinstance(identity.get('id'), str) or not isinstance(identity.get('name'), str):
                    return self._send(200, {'user': None})
                return self._send(200, {'user': {'id': identity['id'], 'name': identity['name']}})
            except (OSError, ValueError, json.JSONDecodeError):
                return self._send(200, {'user': None})
            finally:
                connection.close()
        return NOT_HANDLED

    def get_operator_v1_mach33_demo(self, path, session, body, scope):
        if path.path.startswith('/operator/v1/mach33-demo/'):
            if self.application.mach33_demo is None or session[1]['role'] not in ('registry_admin', 'read_only_operator'):
                return self._fail(404, 'NOT_FOUND')
            query = parse_qs(path.query, strict_parsing=True, keep_blank_values=True)
            if any((len(value) != 1 for value in query.values())):
                raise ValueError('invalid demo selector')
            if path.path == '/operator/v1/mach33-demo/report':
                selected = {key: values[0] for key, values in query.items() if key != 'export'}
                report = self.application.mach33_demo.report(selected)
                export = query.get('export', [None])[0]
                if export in (None, 'json'):
                    return self._send(200, report, extra=(('Content-Disposition', 'attachment; filename=ezllmrouter-scripted-demo-report.json'),) if export else ())
                if export == 'csv':
                    columns = ('demo_provenance', 'dataset_id', 'attempt_id', 'workflow_id', 'task_id', 'run_id', 'executing_actor_id', 'initiating_user_id', 'charging_owner_id', 'provider_id', 'model_id', 'started_at', 'ended_at', 'local_date', 'provider_result', 'usage_revision_id', 'usage_observed_at', 'usage_state', 'input_tokens', 'output_tokens', 'cost_state', 'currency', 'amount_decimal')
                    out = io.StringIO()
                    writer = csv.DictWriter(out, columns, extrasaction='ignore')
                    writer.writeheader()
                    writer.writerows(({**row, 'demo_provenance': self.application.mach33_demo.meta['required_banner']} for row in report['attempts']))
                    return self._send(200, out.getvalue().encode(), content_type='text/csv; charset=utf-8', extra=(('Content-Disposition', 'attachment; filename=ezllmrouter-scripted-demo-report.csv'),))
                raise ValueError('invalid demo export')
            if path.path == '/operator/v1/mach33-demo/workflow' and set(query) == {'workflow_id'}:
                try:
                    return self._send(200, self.application.mach33_demo.workflow(query['workflow_id'][0]))
                except KeyError:
                    return self._fail(404, 'NOT_FOUND')
            return self._fail(404, 'NOT_FOUND')
        return NOT_HANDLED

    def get_operator_v1_integration(self, path, session, body, scope):
        if self.application.registry and path.path.startswith('/operator/v1/integration/'):
            principal = self.application.registry.principal(session[1]['principal_id'])
            ledger = self.application.registry.integration
            if path.path == '/operator/v1/integration/datasets' and (not path.query):
                return self._send(200, ledger.datasets(principal))
            query = parse_qs(path.query, strict_parsing=True, keep_blank_values=True)
            allowed = {'dataset_id', 'actor_id', 'provider_account_id', 'task_id', 'model_id', 'initiating_user_id', 'root_run_id', 'run_id', 'from', 'to', 'export'} if path.path == '/operator/v1/integration/report' else {'dataset_id'}
            if any((len(values) != 1 for values in query.values())) or 'dataset_id' not in query or set(query) - allowed:
                raise ValueError('invalid integration selector')
            dataset_id = query['dataset_id'][0]
            if path.path == '/operator/v1/integration/connections':
                return self._send(200, self.application.registry.integration_credentials.list(principal, dataset_id))
            if path.path == '/operator/v1/integration/accounts':
                return self._send(200, ledger.accounts(principal, dataset_id))
            if path.path == '/operator/v1/integration/report':
                filters = {key: value[0] for key, value in query.items() if key not in ('dataset_id', 'export')}
                report = ledger.report(principal, dataset_id, filters, version='3')
                export = query.get('export', [None])[0]
                if export in (None, 'json'):
                    return self._send(200, report, extra=(('Content-Disposition', 'attachment; filename=duranki-integration-report.json'),) if export else ())
                if export == 'csv':
                    columns = ('dataset_id', 'platform_id', 'environment_id', 'owner_id', 'attempt_id', 'started_at', 'task_id', 'step_id', 'run_id', 'root_run_id', 'parent_run_id', 'actor_kind', 'actor_id', 'initiating_user_id', 'provider_account_id', 'model_id', 'context_ref', 'result_state', 'result_observed_at', 'task_outcome', 'task_outcome_observed_at', 'usage_revision', 'usage_observed_at', 'cost_status', 'currency', 'amount_decimal', 'native_units', 'cost_basis', 'price_ref', 'price_version', 'operation_family_version', 'operation_family', 'model_identity_state', 'logical_operation_id', 'attempt_role', 'predecessor_attempt_id', 'lineage_status', 'account_resolution_status', 'resolved_account_id', 'decision_ref', 'eligibility_evidence_status', 'eligibility_assessment', 'eligibility_record', 'selected_action', 'feature_snapshot_status', 'feature_snapshot_digest', 'feature_available_before_start', 'decision_snapshot_status', 'decision_snapshot_digest', 'usage_provenance', 'usage_state')
                    out = io.StringIO()
                    writer = csv.DictWriter(out, columns, extrasaction='ignore')
                    writer.writeheader()
                    for row in report['attempts']:
                        writer.writerow({key: json.dumps(value, sort_keys=True) if key in ('native_units', 'eligibility_record', 'selected_action') and value is not None else value for key, value in row.items()})
                    return self._send(200, out.getvalue().encode(), content_type='text/csv; charset=utf-8', extra=(('Content-Disposition', 'attachment; filename=duranki-integration-report.csv'),))
                raise ValueError('invalid report export')
            if path.path == '/operator/v1/integration/export' and set(query) == {'dataset_id'}:
                return self._send(200, ledger.dataset_export(principal, dataset_id, '3'), extra=(('Content-Disposition', 'attachment; filename=duranki-integration-dataset.json'),))
            return self._fail(404, 'NOT_FOUND')
        return NOT_HANDLED

    def post_operator_v1_integration(self, path, session, body, scope):
        if self.application.registry and self.path.startswith('/operator/v1/integration/'):
            if session[1]['role'] != 'registry_admin':
                return self._fail(403, 'ADMIN_REQUIRED')
            principal = self.application.registry.principal(session[1]['principal_id'])
            try:
                if self.path == '/operator/v1/integration/datasets':
                    status, result = self.application.registry.integration.create_dataset(principal, body)
                elif self.path == '/operator/v1/integration/connections':
                    result = self.application.registry.integration_credentials.connect(principal, body)
                    status = 201
                elif self.path.startswith('/operator/v1/integration/connections/'):
                    parts = self.path.split('/')
                    if len(parts) != 7 or parts[-1] not in ('save', 'refresh', 'replace', 'disable', 'retire'):
                        return self._fail(404, 'NOT_FOUND')
                    account_id = route_id(parts[-2])
                    result = getattr(self.application.registry.integration_credentials, parts[-1])(principal, account_id, body)
                    status = 200
                elif self.path == '/operator/v1/integration/accounts':
                    status, result = self.application.registry.integration.create_account(principal, body, '3' if 'allowed_operations' in body else '1')
                elif self.path.endswith('/permissions') and self.path.startswith('/operator/v1/integration/accounts/'):
                    account_raw = self.path[len('/operator/v1/integration/accounts/'):-len('/permissions')]
                    if '/' in account_raw:
                        return self._fail(404, 'NOT_FOUND')
                    status, result = self.application.registry.integration.set_account_permissions(principal, route_id(account_raw), body)
                elif self.path.endswith('/state') and self.path.startswith('/operator/v1/integration/accounts/'):
                    account_raw = self.path[len('/operator/v1/integration/accounts/'):-len('/state')]
                    if '/' in account_raw:
                        return self._fail(404, 'NOT_FOUND')
                    account_id = route_id(account_raw)
                    status, result = self.application.registry.integration.set_account_state(principal, account_id, body)
                else:
                    return self._fail(404, 'NOT_FOUND')
                return self._send(status, result)
            except IntegrationError as exc:
                return self._fail(exc.status, exc.code)
            except Exception:
                log_failure('operator_web.serve.Handler.do_POST.failed')
                return self._fail(503, 'INTEGRATION_UNAVAILABLE')
        return NOT_HANDLED
