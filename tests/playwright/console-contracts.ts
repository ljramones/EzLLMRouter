// Independently stated fields used by the console. Additional producer fields are allowed.
// These are consumer contracts, not snapshots of generated values or private credentials.
export type Shape = string | { [key: string]: Shape } | [Shape];
const text = 'string', integer = 'integer', bool = 'boolean', record = 'object';
const activity: Shape = { submission_id: text, principal_id: text, attempt_id: text,
  configuration_ref: 'string|null', task_id: text, step_id: text, step_revision: integer,
  execution_generation: text, submission_state: text, dispatch_state: text,
  content_store_allowed: bool, updated_at: text, error_code: 'string|null' };
const totals: Shape = { attempts: integer, known_cost_attempts: integer, unknown_cost_attempts: integer,
  estimated_attempts: integer, no_provider_charge_attempts: integer, known_subtotals: 'decimal-map',
  estimated_subtotals: 'decimal-map', cost_coverage: text };
export const views = ['Overview', 'Activity', 'Usage & Costs', 'External accounting',
  'External Providers', 'Local Connectors', 'Private Hosting', 'Office Labs', 'All Models',
  'Users & Permissions', 'Connections & Credentials', 'Configuration', 'Build & context'];

export const contracts: Record<string, Shape> = {
  '/operator/v1/connections': { items: [{ connection_id: text, display_name: text, provider_id: text,
    status: text, revision: integer, credential_state: text, settings: record }] },
  '/operator/v1/models': { items: [{ configuration_ref: text, display_name: text, 'kind?': text,
    status: text, revision: integer, capabilities: [text], purposes: [text], task_classes: [text],
    'source_links?': [{ title: text, url: text }], readiness: text }] },
  '/operator/v1/principals': { items: [{ principal_id: text, display_name: text, kind: text,
    owner: text, revision: integer, role: text, status: text, credential_state: text, grant_summary: [record] }] },
  '/operator/v1/overview': { profile: text, updated_at: text, service: { state: text }, worker: { state: text },
    sender: { state: text }, counts: { submissions: integer, completed: integer, known_failures: integer,
      unknown_outcomes: integer, blocked_before_send: integer }, recent: [activity],
    build: { commit: text, dirty: bool, fingerprint: text } },
  '/operator/v1/activity': { page: integer, limit: integer, total: integer, items: [activity] },
  '/operator/v1/usage-costs': { scope: text, cutoff: text, period: { from: 'string|null', to: 'string|null', timezone: text },
    total: totals, groupings: { provider: [totals], model: [totals], agent_id: [totals],
      initiating_user_id: [totals], charging_owner_id: [totals], task_id: [totals], root_run_id: [totals] }, attempts: [record] },
  '/operator/v1/retrieval-usage': { profile: text, contract_version: text, scope: record, filters: record,
    total: { attempts: integer, unknown_cost_attempts: integer, known_usd: 'decimal' },
    operational_as_of: text, groupings: record, workflows: [record], attempts: [record] },
  '/operator/v1/integration/datasets': { integration_version: text, items: [{ dataset_id: text,
    owner_id: text, platform_id: text, environment_id: text, ingest_principal_id: text, activated_at: text }] },
  '/operator/v1/integration/accounts': { integration_version: text, dataset_id: text, items: [{ account_id: text,
    dataset_id: text, owner_id: text, provider_id: text, allowed_models: [text], state: text, revision: integer }] },
  '/operator/v1/integration/connections': { items: [record] },
  '/operator/v1/integration/report': { integration_version: text, dataset_id: text, attempt_count: integer,
    unknown_cost_attempts: integer, known_total_by_currency: 'decimal-map', by_actor: record, by_account: record,
    by_root_workflow: record, attempts: [{ dataset_id: text, attempt_id: text, task_id: text, step_id: text,
      run_id: text, root_run_id: text, actor_id: text, provider_account_id: text, model_id: 'string|null',
      started_at: text, usage_state: text, cost_status: text, amount_decimal: 'decimal|null', currency: 'string|null' }] },
  '/operator/v1/local-connectors': { items: [{ connector_id: text, display_name: text,
    enabled: bool, selected_models: [text], discovery: { state: text, models: [record] } }], kinds: record },
  '/operator/v1/users': { items: [{ principal_id: text, display_name: text, username: text, role: text,
    status: text, revision: integer, must_change_password: bool, permissions: [text] }], roles: record },
  '/operator/v1/config': { configuration: { configuration_ref: text, service: text, endpoint: text,
    model: text, model_version: text, processing_region: text }, policy: { policy_version: text,
    registry_version: text, limit_version: text, recovery_policy_version: text }, capabilities: { text: bool,
      caller_owned_lookup: bool, configuration_editing: bool, approval_revocation: bool, real_provider: bool } },
  '/operator/v1/build': { profile: text, build: { commit: text, dirty: bool, fingerprint: text }, packages: record, environment: text },
};

export function validate(value: unknown, shape: Shape, at = '$'): void {
  const reject = () => { throw new Error('Console payload contract mismatch at ' + at); };
  if (typeof shape === 'string') {
    const decimal = (item: unknown) => typeof item === 'string' && /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/.test(item);
    const matches = shape.split('|').some(kind => {
      switch (kind) {
        case 'null': return value === null;
        case 'integer': return Number.isSafeInteger(value);
        case 'object': return value !== null && typeof value === 'object' && !Array.isArray(value);
        case 'decimal': return decimal(value);
        case 'decimal-map': return value !== null && typeof value === 'object' && !Array.isArray(value) && Object.values(value).every(decimal);
        case 'string': case 'boolean': return typeof value === kind;
        default: throw new Error('Unknown consumer contract type: ' + kind);
      }
    });
    if (!matches) reject();
  } else if (Array.isArray(shape)) {
    if (!Array.isArray(value)) return reject();
    value.forEach((item, index) => validate(item, shape[0], `${at}[${index}]`));
  } else {
    if (value === null || typeof value !== 'object' || Array.isArray(value)) return reject();
    for (const [field, child] of Object.entries(shape)) {
      const key = field.endsWith('?') ? field.slice(0, -1) : field;
      if (field.endsWith('?') && !Object.hasOwn(value, key)) continue;
      if (!Object.hasOwn(value, key)) throw new Error('Console payload missing ' + at + '.' + key);
      validate((value as Record<string, unknown>)[key], child, at + '.' + key);
    }
  }
}
