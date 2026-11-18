"use strict";
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const { DurankiClient, DurankiError } = require("@mach33/duranki-client");
const corpus = Object.fromEntries(JSON.parse(fs.readFileSync(path.join(__dirname, "scenarios.json"))).cases.map(x => [x.id, x]));
const base = JSON.parse(fs.readFileSync(path.join(__dirname, "request.json")));
const client = new DurankiClient({ baseUrl: process.env.DURANKI_SERVICE_URL, token: process.env.DURANKI_DEV_TOKEN });
async function arrivals() {
  const response = await fetch(process.env.DURANKI_RECEIVER_URL + "/observations", { redirect: "manual" });
  assert.equal(response.status, 200);
  return (await response.json()).arrivals;
}
async function waitArrivals(expected) {
  const deadline = Date.now() + 3000;
  while (true) {
    const observed = await arrivals();
    if (observed.length >= expected) return observed;
    if (Date.now() >= deadline) throw Error(`receiver did not reach ${expected} arrivals`);
    await new Promise(resolve => setTimeout(resolve, 25));
  }
}
async function noSendDrain(expected, durationMs = 500) {
  const start = performance.now(), deadline = start + durationMs;
  while (true) {
    const observed = await arrivals();
    assert.equal(observed.length, expected, "unexpected receiver send during negative drain");
    const remaining = deadline - performance.now();
    if (remaining <= 0) return { observed, elapsedMs: Math.round(performance.now() - start) };
    await new Promise(resolve => setTimeout(resolve, Math.min(25, remaining)));
  }
}
function requestFor(item) {
  const value = { ...structuredClone(base), step_id: item.step_id, execution_generation: item.execution_generation };
  if (Object.hasOwn(item, "total_timeout_ms")) value.generation_settings.total_timeout_ms = item.total_timeout_ms;
  return value;
}
async function main() {
  const mode = process.argv[2];
  assert.ok(require.resolve("@mach33/duranki-client").includes("node_modules"));
  if (mode === "capabilities") {
    const value = await client.getCapabilities();
    assert.deepEqual(value.supported_features, ["text"]);
    console.log(JSON.stringify({ actor: "js", mode, profile: value.profile,
      module: require.resolve("@mach33/duranki-client"), version: "0.0.1" }));
    return;
  }
  if (mode === "submit") {
    const item = corpus[process.argv[3]];
    const before = await arrivals();
    const value = await client.submit(requestFor(item), { wait_ms: item.wait_ms });
    assert.equal(value.state, item.expected_state);
    if (value.state === "delivered") {
      assert.equal(value.candidate.output_blocks[0].text, item.expected_text);
      assert.equal(value.candidate.usage.revision.cost.status, "unknown");
      if (item.candidate_access_after) {
        const status = await client.getStatus({ submission_id: value.handle.submission_id });
        assert.equal(status.candidate_access, item.candidate_access_after);
      }
    } else {
      assert.equal(value.pending_result_policy, item.pending_result_policy);
    }
    const after = await waitArrivals(before.length + item.receiver_delta);
    assert.equal(after.length, before.length + item.receiver_delta);
    console.log(JSON.stringify({ actor: "js", mode, case: item.id, state: value.state,
      submission_id: value.handle.submission_id, work_key: value.handle.work_key,
      attempt_id: value.candidate?.attempt_id, candidate_id: value.candidate?.candidate_id,
      receiver_before: before.length, receiver_after: after.length, receiver_last: after.at(-1) }));
    return;
  }
  if (mode === "failure") {
    const item = corpus[process.argv[3]], before = await arrivals();
    let caught;
    try { await client.submit(requestFor(item), { wait_ms: item.wait_ms }); }
    catch (error) { caught = error; }
    assert.ok(caught instanceof DurankiError);
    assert.equal(caught.code, item.expected_error);
    assert.equal(caught.failure_stage, item.failure_stage);
    assert.ok(caught.handle?.submission_id && caught.attempt_id);
    const snapshot = await client.getStatus({ submission_id: caught.handle.submission_id });
    assert.equal(snapshot.terminal_failure.code, caught.code);
    assert.equal(snapshot.terminal_attempt_id, caught.attempt_id);
    assert.equal(snapshot.candidate_access, "unavailable_due_failure");
    let after = await waitArrivals(before.length + item.receiver_delta), drainMs = null;
    if (item.receiver_delta === 0) {
      const drained = await noSendDrain(before.length); after = drained.observed; drainMs = drained.elapsedMs;
    }
    assert.equal(after.length, before.length + item.receiver_delta);
    console.log(JSON.stringify({ actor: "js", mode, case: item.id, code: caught.code,
      attempt_id: caught.attempt_id, receiver_before: before.length, receiver_after: after.length,
      negative_drain_ms: drainMs }));
    return;
  }
  if (mode === "status") {
    const item = corpus[process.argv[3]], sid = process.argv[4];
    const before = await arrivals();
    let byId, deadline = Date.now() + 8000;
    do {
      byId = await client.getStatus({ submission_id: sid });
      if (byId.submission_state === "completed") break;
      if (Date.now() >= deadline) throw Error("retained completion timeout");
      await new Promise(resolve => setTimeout(resolve, 50));
    } while (true);
    const selected = { task_id: base.task_id, step_id: item.step_id,
      step_revision: base.step_revision, execution_generation: item.execution_generation };
    const byWork = await client.getStatus(selected);
    assert.deepEqual(byId.handle, byWork.handle);
    assert.equal(byId.handle.submission_id, sid);
    assert.equal(byId.submission_state, "completed");
    assert.equal(byId.candidate.candidate_id, byWork.candidate.candidate_id);
    assert.equal(byId.attempts[0].usage.revision.cost.status, "unknown");
    assert.equal((await arrivals()).length, before.length);
    console.log(JSON.stringify({ actor: "js", mode, case: item.id, submission_id: sid,
      candidate_id: byId.candidate.candidate_id, attempt_id: byId.candidate.attempt_id,
      receiver_count: before.length }));
    return;
  }
  if (mode === "status_metadata") {
    const item = corpus[process.argv[3]], sid = process.argv[4];
    const before = await arrivals(), deadline = Date.now() + 8000;
    let snapshot;
    do {
      snapshot = await client.getStatus({ submission_id: sid });
      if (snapshot.submission_state === "completed") break;
      if (Date.now() >= deadline) throw Error("metadata completion timeout");
      await new Promise(resolve => setTimeout(resolve, 50));
    } while (true);
    assert.equal(snapshot.candidate_access, item.candidate_access_after);
    assert.equal(snapshot.result_unavailable_reason, item.result_unavailable_reason);
    assert.equal(Object.hasOwn(snapshot, "candidate"), false);
    assert.equal((await arrivals()).length, before.length);
    console.log(JSON.stringify({ actor: "js", mode, case: item.id, submission_id: sid,
      candidate_access: snapshot.candidate_access, reason: snapshot.result_unavailable_reason,
      receiver_count: before.length }));
    return;
  }
  if (mode === "auth") {
    const before = await arrivals();
    const invalid = new DurankiClient({ baseUrl: process.env.DURANKI_SERVICE_URL, token: "invalid.synthetic.token" });
    await assert.rejects(() => invalid.getCapabilities(), e => e instanceof DurankiError &&
      e.code === "AUTHENTICATION_FAILED" && e.http_status === 401);
    const drained = await noSendDrain(before.length);
    console.log(JSON.stringify({ actor: "js", mode, code: "AUTHENTICATION_FAILED",
      receiver_count: drained.observed.length, negative_drain_ms: drained.elapsedMs }));
    return;
  }
  throw Error("unknown mode");
}
if (require.main === module) {
  main().catch(e => { console.error(JSON.stringify({ actor: "js", error: e.message, code: e.code })); process.exitCode = 1; });
}
module.exports = { noSendDrain, requestFor };
