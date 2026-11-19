"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vectorPath = fs.existsSync(path.join(__dirname, "vectors.json")) ? path.join(__dirname, "vectors.json") :
  path.join(__dirname, "../../tests/fixtures/contracts/wp-a-03-c01/DURANKI-WP-A-VECTORS-v0.3-CORRECTION-01.json");
const vectors = JSON.parse(fs.readFileSync(vectorPath, "utf8")).examples;
const { DurankiClient, DurankiError } = process.env.DURANKI_INSTALLED_CLIENT === "1" ?
  require("@mach33/duranki-client") : require("../../clients/js/index.cjs");

function clientFor(value, status = 200) {
  let calls = 0;
  const client = new DurankiClient({ baseUrl: "http://synthetic.invalid", token: "token.synthetic",
    fetchImpl: async () => {
      calls++;
      return { status, ok: status >= 200 && status < 300,
        headers: { get: () => "0.2" }, json: async () => value };
    } });
  return { client, calls: () => calls };
}
function availableUsage(attemptId) {
  const unknown = { state: "unknown" };
  return { state: "available", revision: { attempt_id: attemptId, revision: 1,
    usage_observation: "unknown", normalized_usage: {
      input_uncached: unknown, input_cache_read: unknown, input_cache_write: unknown,
      output_text: unknown, output_reasoning: unknown, other_billable: [] },
    usage_semantics_version: "synthetic.text.v1", price_version: "synthetic.unpriced.v1",
    cost: { status: "unknown", currency: "USD" }, recorded_at: "2030-01-01T00:00:00Z" } };
}
async function rejected(promise, code, selector) {
  try { await promise; assert.fail("expected rejection"); }
  catch (error) {
    assert.ok(error instanceof DurankiError);
    assert.equal(error.code, code);
    if (selector) assert.deepEqual(error.selector, selector);
  }
}
async function main() {
  const good = [
    [vectors.capabilities, c => c.getCapabilities()],
    [vectors.reply_delivered, c => c.submit(vectors.submit_text)],
    [vectors.status_present, c => c.getStatus({ submission_id: "submission.demo" })],
  ];
  for (const [value, action] of good) {
    const { client, calls } = clientFor(value);
    await action(client);
    assert.equal(calls(), 1);
  }
  const selector = { task_id: vectors.submit_text.task_id, step_id: vectors.submit_text.step_id,
    step_revision: vectors.submit_text.step_revision,
    execution_generation: vectors.submit_text.execution_generation };
  for (const value of [{ contract_version: "0.2", state: "delivered" },
    { contract_version: "0.2", state: "bogus" },
    { ...vectors.reply_delivered, candidate: { ...vectors.reply_delivered.candidate, output_blocks: [] } }]) {
    const { client, calls } = clientFor(value);
    await rejected(client.submit(vectors.submit_text), "INTERNAL_UNAVAILABLE", selector);
    assert.equal(calls(), 1);
  }
  const statusSelector = { submission_id: "submission.demo" };
  const invalidStatus = clientFor({ ...vectors.status_present, handle: {} });
  await rejected(invalidStatus.client.getStatus(statusSelector), "INTERNAL_UNAVAILABLE", statusSelector);
  for (const bad of [{ submission_id: "" }, { task_id: {}, step_id: "step.demo",
    step_revision: 1, execution_generation: "generation.demo" }]) {
    const { client, calls } = clientFor(vectors.status_present);
    await rejected(client.getStatus(bad), "SCHEMA_INVALID");
    assert.equal(calls(), 0);
  }
  const wrongWork = structuredClone(vectors.reply_delivered);
  wrongWork.handle.work_key.task_id = "task.other";
  const wrongUsage = structuredClone(vectors.reply_delivered);
  wrongUsage.candidate.usage = availableUsage("attempt.other");
  const wrongTime = structuredClone(vectors.reply_delivered);
  wrongTime.candidate.observed_at = "2030-99-99T99:99:99Z";
  const wrongVersion = { ...vectors.reply_delivered, contract_version: "9.9" };
  for (const value of [wrongWork, wrongUsage, wrongTime]) {
    const { client } = clientFor(value);
    await rejected(client.submit(vectors.submit_text), "INTERNAL_UNAVAILABLE", selector);
  }
  await rejected(clientFor(wrongVersion).client.submit(vectors.submit_text), "UNSUPPORTED_VERSION", selector);
  const otherStatus = structuredClone(vectors.status_present);
  otherStatus.handle.submission_id = "submission.other";
  await rejected(clientFor(otherStatus).client.getStatus(statusSelector), "INTERNAL_UNAVAILABLE", statusSelector);
  const mismatchedAttempt = structuredClone(vectors.status_present);
  mismatchedAttempt.attempts[0].usage = availableUsage("attempt.other");
  await rejected(clientFor(mismatchedAttempt).client.getStatus(statusSelector), "INTERNAL_UNAVAILABLE", statusSelector);
  const byWork = { task_id: vectors.submit_text.task_id, step_id: vectors.submit_text.step_id,
    step_revision: vectors.submit_text.step_revision, execution_generation: vectors.submit_text.execution_generation };
  await clientFor(vectors.status_present).client.getStatus(byWork);
  for (const handle of [{}, { submission_id: "submission.demo" },
    { submission_id: "submission.demo", work_key: null }, "invalid"]) {
    const badReply = { ...structuredClone(vectors.reply_delivered), handle };
    const badStatus = { ...structuredClone(vectors.status_present), handle };
    await rejected(clientFor(badReply).client.submit(vectors.submit_text), "INTERNAL_UNAVAILABLE", selector);
    await rejected(clientFor(badStatus).client.getStatus(byWork), "INTERNAL_UNAVAILABLE", byWork);
  }
  for (const kind of ["by_work", "by_id"]) {
    for (const returnOriginal of [true, false]) {
      let release, entered;
      const enteredPromise = new Promise(resolve => { entered = resolve; });
      const gate = new Promise(resolve => { release = resolve; });
      const selected = kind === "by_id" ? { submission_id: "submission.demo" } : { ...byWork };
      const original = { ...selected };
      let requestUrl;
      const client = new DurankiClient({ baseUrl: "http://synthetic.invalid", token: "token.synthetic",
        fetchImpl: async url => {
          requestUrl = url;
          entered();
          await gate;
          const value = structuredClone(vectors.status_present);
          if (!returnOriginal) {
            if (kind === "by_id") value.handle.submission_id = "submission.other";
            else value.handle.work_key.task_id = "task.other";
          }
          return { status: 200, ok: true, headers: { get: () => "0.2" }, json: async () => value };
        } });
      const pending = client.getStatus(selected);
      await enteredPromise;
      if (kind === "by_id") selected.submission_id = "submission.other";
      else selected.task_id = "task.other";
      assert.ok(requestUrl.includes(kind === "by_id" ? "/submission.demo" : "/task.demo/"));
      release();
      if (returnOriginal) assert.equal((await pending).handle.submission_id, "submission.demo");
      else await rejected(pending, "INTERNAL_UNAVAILABLE", original);
    }
  }
  const invalidCaps = clientFor({ ...vectors.capabilities, supported_features: ["bogus"] });
  await rejected(invalidCaps.client.getCapabilities(), "INTERNAL_UNAVAILABLE");
  let lostCalls = 0;
  const lost = new DurankiClient({ baseUrl: "http://synthetic.invalid", token: "token.synthetic",
    fetchImpl: async () => { lostCalls++; throw Error("synthetic transport loss"); } });
  await rejected(lost.submit(vectors.submit_text, { wait_ms: 0 }), "TRANSPORT_OUTCOME_UNKNOWN", selector);
  assert.equal(lostCalls, 1);
  for (const bad of [true, 30001]) {
    await rejected(lost.submit(vectors.submit_text, { wait_ms: bad }), "SCHEMA_INVALID");
    assert.equal(lostCalls, 1);
  }
  console.log(JSON.stringify({ test: "commonjs_response_validation", positives: 4,
    malformed_responses_rejected: 19, invalid_selectors_rejected_before_fetch: 2,
    selector_mutation_controls: 4, option_and_unknown_outcome_cases: 3, provider_calls: 0 }));
}
main().catch(error => { console.error(error); process.exitCode = 1; });
