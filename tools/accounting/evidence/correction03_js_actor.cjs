"use strict";
// Exact installed npm client against synthetic loopback accounting only.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const [base, tokenFile, packageRoot, mode = "seed"] = process.argv.slice(2);
const {IntegrationClient, IntegrationClientError} = require(packageRoot);
assert.equal(require(packageRoot + "/package.json").version, "0.2.2");
const token = fs.readFileSync(tokenFile, "utf8").trim();
const datasets = {mixed: "dataset.c03.mixed.linkfirst", pure: "dataset.c03.pure"};
const account = dataset => "account:" + dataset;
const at = "2099-01-01T00:00:10Z";
const root = dataset => ({integration_version: "2", dataset_id: dataset});
const start = (dataset, aid, task, logical, role = "initial", extra = {}) => ({
  ...root(dataset), event_id: "event." + aid, kind: "attempt_started", occurred_at: at,
  attempt_id: aid, started_at: at, task_id: task, step_id: "step.c03",
  run_id: "run." + task, root_run_id: "run." + task,
  actor_kind: "agent", actor_id: "agent.synthetic", provider_account_id: account(dataset),
  model_id: "model.synthetic", context_ref: "feature." + aid,
  operation_family_version: "1", operation_family: "generation",
  model_identity_state: "known", logical_operation_id: logical, attempt_role: role, ...extra
});
const link = (dataset, aid, logical, predecessor) => ({
  ...root(dataset), event_id: "link." + aid, kind: "lineage",
  occurred_at: at, attempt_id: aid, logical_operation_id: logical,
  attempt_role: "fallback", predecessor_attempt_id: predecessor
});
async function conflict(call) {
  try { await call(); } catch (error) {
    assert.ok(error instanceof IntegrationClientError);
    assert.equal(error.code, "EVENT_CONFLICT");
    assert.equal(error.httpStatus, 409);
    assert.equal(error.retryGuidance, "never");
    return {http_status: error.httpStatus, code: error.code, retry_guidance: error.retryGuidance};
  }
  assert.fail("expected EVENT_CONFLICT");
}
async function main() {
  const mixed = new IntegrationClient(base, token, {version: "2"});
  const legacy = new IntegrationClient(base, token, {version: "1"});
  const pure = new IntegrationClient(base, token, {version: "2"});
  const did = datasets.mixed;
  const old = {
    integration_version: "1", dataset_id: did, event_id: "event.mixed.legacy",
    kind: "attempt_started", occurred_at: at, attempt_id: "attempt.mixed.legacy",
    started_at: at, task_id: "task.mixed", step_id: "step.c03",
    run_id: "run.task.mixed", root_run_id: "run.task.mixed", actor_kind: "agent",
    actor_id: "agent.synthetic", provider_account_id: account(did),
    model_id: "model.synthetic", context_ref: "context.mixed.legacy"
  };
  let rejected = null;
  if (mode === "seed") {
    const claim = link(did, "attempt.mixed.legacy", "logical.mixed", "attempt.pending");
    const receipt = await mixed.submitObservation(claim);
    assert.equal(receipt.membership_at_receipt, "pending_start");
    rejected = await conflict(() => legacy.submitObservation(old));
    assert.deepEqual(await mixed.submitObservation(claim), receipt);
    assert.deepEqual(await mixed.recoverReceipt(did, claim.event_id), receipt);
    const unrelated = start(did, "attempt.mixed.unrelated", "task.unrelated", "logical.unrelated");
    assert.equal((await mixed.submitObservation(unrelated)).kind, "attempt_started");
    const pureDid = datasets.pure;
    await pure.submitObservation(link(pureDid, "attempt.pure.child", "logical.pure", "attempt.pure.parent"));
    await pure.submitObservation(start(pureDid, "attempt.pure.child", "task.pure", "logical.pure", "unknown"));
    await pure.submitObservation(start(pureDid, "attempt.pure.parent", "task.pure", "logical.pure"));
  } else if (mode === "probe") {
    rejected = await conflict(() => legacy.submitObservation(old));
  }
  assert.equal((await mixed.recoverReceipt(did, "link.attempt.mixed.legacy")).event_id,
    "link.attempt.mixed.legacy");
  assert.equal((await mixed.recoverReceipt(did, "event.attempt.mixed.unrelated")).kind,
    "attempt_started");
  assert.equal((await pure.recoverReceipt(datasets.pure, "event.attempt.pure.parent")).kind,
    "attempt_started");
  console.log(JSON.stringify({result: "PASS", mode, rejected_v1_after_v2_lineage: rejected,
    receipts_recovered: 3, new_accepted_events: mode === "seed" ? 5 : 0}));
}
main().catch(error => { console.error(error.stack || error.message); process.exitCode = 1; });
