"""Operator registry routes handlers."""
from .common import (
    ADAPTERS,
    NOT_HANDLED,
    PROVIDERS,
    RegistryConflict,
    UserError,
    log_failure,
    parse_qs,
)

class RegistryRoutes:

    def _registry_read(self, path, session):
        actor = session[1]['principal_id']
        role = session[1]['role']
        admin_view = role in ('registry_admin', 'read_only_operator')
        if path.path == '/operator/v1/providers' and (not path.query):
            if not admin_view:
                return self._fail(403, 'OPERATOR_REQUIRED')
            return self._send(200, {'providers': PROVIDERS, 'adapters': ADAPTERS})
        if path.path.startswith('/operator/v1/provider-validations/') and (not path.query):
            if not admin_view:
                return self._fail(403, 'OPERATOR_REQUIRED')
            operation_id = path.path.rsplit('/', 1)[1]
            value = self.application.projection.provider_validation(operation_id)
            return self._send(200, value) if value else self._fail(404, 'NOT_FOUND')
        if path.path == '/operator/v1/connections' and (not path.query):
            if not admin_view:
                return self._fail(403, 'OPERATOR_REQUIRED')
            return self._send(200, {'items': self.application.registry.list_connections()})
        if path.path == '/operator/v1/personal-campaign' and (not path.query):
            if actor != 'owner.local' or not getattr(self.application.registry, 'personal_campaign', None):
                return self._fail(403, 'OWNER_REQUIRED')
            return self._send(200, self.application.registry.personal_campaign.summary())
        if path.path.startswith('/operator/v1/connections/') and path.path.endswith('/inventory') and (not path.query):
            if not admin_view:
                return self._fail(403, 'OPERATOR_REQUIRED')
            connection_id = path.path[len('/operator/v1/connections/'):-len('/inventory')]
            if '/' in connection_id or not self.application.registry.connection(connection_id):
                return self._fail(404, 'NOT_FOUND')
            return self._send(200, self.application.registry.source_inventory(connection_id))
        if path.path.startswith('/operator/v1/connections/') and (not path.query):
            if not admin_view:
                return self._fail(403, 'OPERATOR_REQUIRED')
            connection_id = path.path[len('/operator/v1/connections/'):]
            if '/' in connection_id:
                raise ValueError('invalid connection path')
            connection = self.application.registry.connection(connection_id)
            if not connection:
                return self._fail(404, 'NOT_FOUND')
            return self._send(200, {'connection': connection, 'deployments': self.application.registry.deployments(connection_id), 'observations': self.application.registry.observations(connection_id), 'history': self.application.registry.history(connection_id)})
        if path.path == '/operator/v1/models' and (not path.query):
            models = self.application.registry.list_models()
            if not admin_view:
                models = [model for model in models if self.application.registry.explain(actor, model['configuration_ref'], 'execution', 'class.demo')['allowed']]
            return self._send(200, {'items': [{**model, 'readiness': self.application.registry.readiness(model), 'current_price': (self.application.registry.prices(model['configuration_ref']) or [None])[-1]} for model in models]})
        if path.path.startswith('/operator/v1/models/') and (not path.query):
            ref = path.path[len('/operator/v1/models/'):]
            if '/' in ref:
                raise ValueError('invalid model path')
            model = self.application.registry.model(ref)
            if not model:
                return self._fail(404, 'NOT_FOUND')
            if not admin_view and (not self.application.registry.explain(actor, ref, 'execution', 'class.demo')['allowed']):
                return self._fail(404, 'NOT_FOUND')
            grants = []
            if admin_view:
                grants = [self.application.registry.grant(principal['principal_id'], ref) for principal in self.application.registry.list_principals()]
            return self._send(200, {'model': model, 'readiness': self.application.registry.readiness(model), 'prices': self.application.registry.prices(ref), 'grants': [grant for grant in grants if grant], 'history': self.application.registry.history(ref) if admin_view else []})
        if path.path == '/operator/v1/principals' and (not path.query):
            principals = self.application.registry.list_principals() if admin_view else [self.application.registry.principal(actor)]
            models = {model['configuration_ref']: model for model in self.application.registry.list_models()}
            items = []
            for principal in principals:
                grants = [self.application.registry.grant(principal['principal_id'], ref) for ref in models]
                items.append({**principal, 'grant_summary': [{**grant, 'display_name': models[grant['configuration_ref']]['display_name'], 'readiness': self.application.registry.readiness(models[grant['configuration_ref']])} for grant in grants if grant]})
            return self._send(200, {'items': items})
        if path.path.startswith('/operator/v1/principals/') and (not path.query):
            principal_id = path.path[len('/operator/v1/principals/'):]
            if '/' in principal_id:
                raise ValueError('invalid principal path')
            if not admin_view and principal_id != actor:
                return self._fail(404, 'NOT_FOUND')
            principal = self.application.registry.principal(principal_id)
            if not principal:
                return self._fail(404, 'NOT_FOUND')
            models = {model['configuration_ref']: model for model in self.application.registry.list_models()}
            grants = [self.application.registry.grant(principal_id, ref) for ref in models]
            return self._send(200, {'principal': principal, 'grants': [{**grant, 'display_name': models[grant['configuration_ref']]['display_name'], 'readiness': self.application.registry.readiness(models[grant['configuration_ref']])} for grant in grants if grant], 'history': self.application.registry.history(principal_id) if admin_view else []})
        if path.path == '/operator/v1/access/explain':
            query = parse_qs(path.query, strict_parsing=True, keep_blank_values=True)
            if set(query) != {'principal_id', 'configuration_ref', 'purpose', 'task_class'} or any((len(values) != 1 for values in query.values())):
                raise ValueError('invalid explain query')
            principal_id = query['principal_id'][0]
            if not admin_view and principal_id != actor:
                return self._fail(404, 'NOT_FOUND')
            return self._send(200, self.application.registry.explain(principal_id, query['configuration_ref'][0], query['purpose'][0], query['task_class'][0]))
        return self._fail(404, 'NOT_FOUND')

    def get_registry_resource(self, path, session, body, scope):
        if self.application.registry and (path.path.startswith('/operator/v1/models') or path.path.startswith('/operator/v1/principals') or path.path.startswith('/operator/v1/connections') or path.path.startswith('/operator/v1/provider-validations/') or (path.path == '/operator/v1/personal-campaign') or (path.path == '/operator/v1/providers') or (path.path == '/operator/v1/access/explain')):
            return self._registry_read(path, session)
        return NOT_HANDLED

    def post_operator_v1_registry(self, path, session, body, scope):
        if self.application.registry and self.path == '/operator/v1/registry':
            if session[1]['role'] != 'registry_admin':
                return self._fail(403, 'ADMIN_REQUIRED')
            try:
                return self._send(200, self.application.registry.mutate(session[1]['principal_id'], body))
            except UserError as exc:
                return self._fail(exc.status, exc.code)
            except RegistryConflict:
                return self._fail(409, 'REGISTRY_CONFLICT')
            except ValueError:
                return self._fail(400, 'INVALID_REGISTRY_CHANGE')
            except PermissionError:
                return self._fail(403, 'ADMIN_REQUIRED')
            except Exception:
                log_failure('operator_web.serve.Handler.do_POST.failed')
                return self._fail(503, 'REGISTRY_UNAVAILABLE')
        return NOT_HANDLED

    def post_operator_v1_personal_campaign(self, path, session, body, scope):
        if self.application.registry and self.path == '/operator/v1/personal-campaign':
            if session[1]['principal_id'] != 'owner.local' or not getattr(self.application.registry, 'personal_campaign', None):
                return self._fail(403, 'OWNER_REQUIRED')
            try:
                if set(body) == {'action', 'configuration'} and body['action'] == 'configure':
                    result = self.application.registry.personal_campaign.configure('owner.local', body['configuration'])
                elif set(body) == {'action'} and body['action'] in ('active', 'paused', 'closed'):
                    result = self.application.registry.personal_campaign.transition('owner.local', body['action'])
                elif set(body) == {'action'} and body['action'] == 'reconcile':
                    result = {'reconciled_attempts': self.application.registry.personal_campaign.reconcile_recorded_usage('owner.local')}
                elif set(body) == {'action'} and body['action'] == 'revalidate':
                    result = self.application.registry.personal_campaign.revalidate('owner.local')
                else:
                    return self._fail(400, 'INVALID_CAMPAIGN')
                return self._send(200, result)
            except ValueError:
                return self._fail(409, 'CAMPAIGN_NOT_ELIGIBLE')
            except Exception:
                log_failure('operator_web.serve.Handler.do_POST.failed')
                return self._fail(503, 'CAMPAIGN_UNAVAILABLE')
        return NOT_HANDLED

    def post_operator_v1_provider_credential(self, path, session, body, scope):
        if self.application.registry and self.path == '/operator/v1/provider-credential':
            if session[1]['role'] != 'registry_admin':
                return self._fail(403, 'ADMIN_REQUIRED')
            if set(body) != {'operation_id', 'connection_id', 'expected_revision', 'mode', 'secret'}:
                return self._fail(400, 'INVALID_BODY')
            try:
                return self._send(200, self.application.registry.set_provider_credential(session[1]['principal_id'], body['connection_id'], body['expected_revision'], body['operation_id'], body['mode'], body['secret']))
            except RegistryConflict:
                return self._fail(409, 'REGISTRY_CONFLICT')
            except ValueError:
                return self._fail(400, 'INVALID_CREDENTIAL_CHANGE')
            except PermissionError:
                return self._fail(403, 'ADMIN_REQUIRED')
            except Exception:
                log_failure('operator_web.serve.Handler.do_POST.failed')
                return self._fail(503, 'CREDENTIAL_UNAVAILABLE')
        return NOT_HANDLED

    def post_operator_v1_provider_probe(self, path, session, body, scope):
        if self.application.registry and self.path == '/operator/v1/provider-probe':
            if session[1]['role'] != 'registry_admin':
                return self._fail(403, 'ADMIN_REQUIRED')
            if set(body) != {'operation_id', 'connection_id', 'expected_revision', 'operation'}:
                return self._fail(400, 'INVALID_BODY')
            try:
                return self._send(200, self.application.registry.probe_connection(session[1]['principal_id'], body['connection_id'], body['expected_revision'], body['operation_id'], body['operation']))
            except RegistryConflict:
                return self._fail(409, 'REGISTRY_CONFLICT')
            except ValueError:
                return self._fail(400, 'INVALID_PROBE')
            except PermissionError:
                return self._fail(403, 'ADMIN_REQUIRED')
            except Exception:
                log_failure('operator_web.serve.Handler.do_POST.failed')
                return self._fail(503, 'PROBE_UNAVAILABLE')
        return NOT_HANDLED

    def post_operator_v1_provider_validation(self, path, session, body, scope):
        if self.application.registry and self.path == '/operator/v1/provider-validation':
            if session[1]['role'] != 'registry_admin':
                return self._fail(403, 'ADMIN_REQUIRED')
            if not self.application.provider_validation or not self.application.registry.provider_execution_ready or set(body) != {'operation_id', 'connection_id', 'connection_revision', 'configuration_ref', 'configuration_revision', 'max_output_tokens', 'acknowledge_external_send'} or (body['acknowledge_external_send'] is not True) or (type(body['max_output_tokens']) is not int) or (not 1 <= body['max_output_tokens'] <= 32) or (type(body['connection_revision']) is not int) or (type(body['configuration_revision']) is not int):
                return self._fail(400, 'INVALID_VALIDATION_REQUEST')
            try:
                previous = self.application.projection.provider_validation(body['operation_id'])
                if previous:
                    if any((previous[key] != body[key] for key in ('connection_id', 'connection_revision', 'configuration_ref', 'configuration_revision', 'max_output_tokens'))):
                        return self._fail(409, 'VALIDATION_OPERATION_CONFLICT')
                    return self._send(200, previous)
                connection = self.application.registry.connection(body['connection_id'])
                model = self.application.registry.model(body['configuration_ref'])
                campaign = getattr(self.application.registry, 'personal_campaign', None)
                allowance = campaign.summary() if campaign else None
                if not connection or not model or connection['revision'] != body['connection_revision'] or (model['revision'] != body['configuration_revision']) or (model['destination'].get('connection_id') != body['connection_id']) or (model['destination'].get('adapter_id') != 'openai.responses.v1') or (campaign and (allowance['effective_state'] != 'active' or allowance['connection_id'] != body['connection_id'] or allowance['configuration_ref'] != body['configuration_ref'] or (allowance['principal_id'] != session[1]['principal_id']) or (body['max_output_tokens'] > allowance['max_output_tokens']))) or (not self.application.registry.explain(session[1]['principal_id'] if getattr(self.application.registry, 'personal_campaign', None) else self.application.provider_validation.principal_id, body['configuration_ref'], 'execution', 'class.demo')['allowed']):
                    return self._fail(409, 'VALIDATION_NOT_ELIGIBLE')
                fresh = self.application.projection.begin_provider_validation(body['operation_id'], body['connection_id'], body['connection_revision'], body['configuration_ref'], body['configuration_revision'], body['max_output_tokens'])
                if not fresh:
                    return self._send(200, self.application.projection.provider_validation(body['operation_id']))
            except ValueError:
                return self._fail(409, 'VALIDATION_OPERATION_CONFLICT')
            except Exception:
                log_failure('operator_web.serve.Handler.do_POST.failed')
                return self._fail(503, 'VALIDATION_UNAVAILABLE')
            live_candidate = None
            try:
                result = self.application.provider_validation.run(body['configuration_ref'], body['operation_id'], body['max_output_tokens'], lambda sid: self.application.projection.record_provider_validation_submission(body['operation_id'], sid), **{'token': session[1]['wire_token']} if session[1].get('wire_token') else {})
                state = result['state'] if type(result) is dict else result
                self.application.projection.finish_provider_validation(body['operation_id'], state)
                live_candidate = result.get('candidate') if type(result) is dict else None
            except Exception as exc:
                log_failure('operator_web.serve.Handler.do_POST.failed')
                handle = getattr(exc, 'handle', None)
                if type(handle) is dict and type(handle.get('submission_id')) is str:
                    self.application.projection.record_provider_validation_submission(body['operation_id'], handle['submission_id'])
                code = getattr(exc, 'code', None)
                state = 'failed' if code and getattr(exc, 'retry_guidance', None) == 'never' else 'outcome_unknown'
                self.application.projection.finish_provider_validation(body['operation_id'], state, code if type(code) is str else 'VALIDATION_UNAVAILABLE')
            response = self.application.projection.provider_validation(body['operation_id'])
            if live_candidate is not None:
                response = {**response, 'live_candidate': live_candidate}
                if response.get('submission_id'):
                    response['provider_model_reported'] = self.application.projection.detail(response['submission_id'], '*').get('provider_model_reported')
            return self._send(200, response)
        return NOT_HANDLED

    def post_operator_v1_provision(self, path, session, body, scope):
        if self.application.registry and self.path == '/operator/v1/provision':
            if session[1]['role'] != 'registry_admin':
                return self._fail(403, 'ADMIN_REQUIRED')
            if set(body) != {'operation_id', 'principal_id', 'expected_revision'}:
                return self._fail(400, 'INVALID_BODY')
            try:
                record, secret = self.application.registry.provision_credential(session[1]['principal_id'], body['principal_id'], body['expected_revision'], body['operation_id'])
                return self._send(200, {'record': record, 'one_time_credential': secret})
            except RegistryConflict:
                return self._fail(409, 'REGISTRY_CONFLICT')
            except ValueError:
                return self._fail(400, 'INVALID_REGISTRY_CHANGE')
            except Exception:
                log_failure('operator_web.serve.Handler.do_POST.failed')
                return self._fail(503, 'REGISTRY_UNAVAILABLE')
        return NOT_HANDLED
