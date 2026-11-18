'use strict';
const assert = require('node:assert/strict');
const { IntegrationClient } = require(process.env.SPEECH_V3_JS_CLIENT);
const client = new IntegrationClient(process.env.SPEECH_V3_BASE, process.env.SPEECH_V3_TOKEN,
  { version: '3' });
const dataset_id = process.env.SPEECH_V3_DATASET;
const account_id = process.env.SPEECH_V3_ACCOUNT;
const attempt_id = 'attempt.synthetic.speech.javascript';
const at = seconds => new Date(Date.now() + seconds * 1000).toISOString().replace(/\.\d{3}Z$/u, 'Z');

async function main() {
  const selector = { operation_family: 'speech_output', capability: 'synthesis',
    selection_kind: 'provider_selected' };
  const eligibility = await client.operationEligibility(dataset_id, account_id, selector);
  assert.equal(eligibility.usable, true);
  assert.equal(Object.hasOwn(eligibility, 'model_id'), false);
  const evidence = { status: 'verified', eligibility_id: eligibility.eligibility_id };
  const action = { selected_account_id: account_id, ...selector,
    policy_version: 'policy.synthetic.v3', eligibility_evidence: evidence };
  const time = at(2), done = at(3), source = at(0);
  const common = { integration_version: '3', dataset_id, attempt_id, schema_version: '1',
    producer_version: 'test.installed.v3', provenance: 'synthetic', source_at: source,
    available_at: source, classification: 'low', retention_until: at(86400) };
  await client.submitSnapshot({ ...common, snapshot_id: 'feature.synthetic.javascript',
    snapshot_kind: 'feature', status: 'not_collected' });
  await client.submitSnapshot({ ...common, snapshot_id: 'decision.synthetic.javascript',
    snapshot_kind: 'decision', status: 'captured', selected_action: action });
  const decision = { integration_version: '3', event_id: 'event.synthetic.javascript.decision',
    dataset_id, kind: 'decision', occurred_at: time, attempt_id,
    decision_ref: 'decision.synthetic.javascript', ...action };
  await client.submitObservation(decision);
  await client.submitObservation({ integration_version: '3', event_id: 'event.synthetic.javascript.start',
    dataset_id, kind: 'attempt_started', occurred_at: time, started_at: time, attempt_id,
    task_id: 'task.synthetic.javascript', step_id: 'step.synthetic.javascript',
    run_id: 'run.synthetic.javascript', root_run_id: 'run.synthetic.javascript',
    actor_kind: 'service', actor_id: 'service.synthetic.javascript', provider_account_id: account_id,
    context_ref: 'feature.synthetic.javascript', operation_family_version: '1',
    operation_family: 'speech_output', model_identity_state: 'unknown',
    logical_operation_id: 'operation.synthetic.javascript', attempt_role: 'initial' });
  await client.submitObservation({ integration_version: '3', event_id: 'event.synthetic.javascript.result',
    dataset_id, kind: 'result', occurred_at: done, attempt_id, result_state: 'completed' });
  const usage = { integration_version: '3', event_id: 'event.synthetic.javascript.usage',
    dataset_id, kind: 'usage', occurred_at: done, attempt_id, usage_revision: 1,
    usage_state: 'known', cost_state: 'unknown',
    native_units: [{ unit: 'characters', quantity_decimal: '8' }],
    usage_provenance: 'provider_reported' };
  await client.submitObservation(usage);
  assert.equal((await client.submitObservation(usage)).event_id, usage.event_id);
  console.log(JSON.stringify({ attempts: 1, provider_requests: 0 }));
}
main().catch(error => { console.error(error.code || error.message); process.exitCode = 1; });
