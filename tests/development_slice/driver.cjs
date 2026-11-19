"use strict";
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const assert = require("node:assert/strict");
const { EzLLMRouterClient, EzLLMRouterError } = require("../../clients/js/index.cjs");
const token = process.env.EZLLMROUTER_DEV_TOKEN;
const service = process.env.EZLLMROUTER_SERVICE_URL || "http://service:8765";
const receiver = process.env.EZLLMROUTER_RECEIVER_URL || "http://receiver:8766";
const client = new EzLLMRouterClient({ baseUrl: service, token });

async function arrivals() {
  const r = await fetch(receiver + "/observations", { redirect: "manual" });
  assert.equal(r.status, 200);
  return (await r.json()).arrivals;
}
async function main() {
  const mode = process.argv[2] || "submit";
  const caps = await client.getCapabilities();
  assert.equal(caps.contract_version, "0.2");
  assert.deepEqual(caps.supported_features, ["text"]);
  if (mode === "status") {
    const snapshot = await client.getStatus({ submission_id: process.env.EZLLMROUTER_SUBMISSION_ID });
    assert.equal(snapshot.submission_state, "completed");
    assert.equal(snapshot.candidate.output_blocks[0].text, "Hello.");
    assert.equal((await arrivals()).length, 1);
    console.log(JSON.stringify({ test: "restart_status", submission_id: process.env.EZLLMROUTER_SUBMISSION_ID,
      status_revision: snapshot.status_revision, receiver_arrivals: (await arrivals()).length }));
    return;
  }
  if (["unauthorized", "mutation", "intent-failure"].includes(mode)) {
    const before = await arrivals();
    assert.equal(before.length, 1, "positive receiver control must precede silence check");
    const request = JSON.parse(fs.readFileSync(path.join(__dirname, "request.json"), "utf8"));
    let target = client, code, state;
    if (mode === "unauthorized") {
      target = new EzLLMRouterClient({ baseUrl: service, token: "invalid.synthetic.token" });
      code = "AUTHENTICATION_FAILED";
    } else if (mode === "mutation") {
      target = new EzLLMRouterClient({ baseUrl: process.env.EZLLMROUTER_MUTANT_URL, token });
      code = "FDC_REJECTED"; state = "failed_before_transmit";
    } else {
      target = new EzLLMRouterClient({ baseUrl: process.env.EZLLMROUTER_FAILSTORE_URL, token });
      code = "INTENT_PERSIST_FAILED"; state = "failed_before_transmit";
    }
    let caught;
    try { await target.submit(request, { wait_ms: 3000 }); } catch (err) { caught = err; }
    assert.ok(caught instanceof EzLLMRouterError);
    assert.equal(caught.code, code);
    if (state) {
      assert.equal(caught.failure_stage, "before_transmit");
      const snapshot = await target.getStatus({ submission_id: caught.handle.submission_id });
      assert.equal(snapshot.submission_state, state);
      assert.equal(snapshot.terminal_failure.code, code);
    }
    await new Promise(resolve => setTimeout(resolve, 500));
    assert.equal((await arrivals()).length, before.length);
    console.log(JSON.stringify({ test: mode, code, failure_stage: caught.failure_stage,
      submission_id: caught.handle?.submission_id, receiver_arrivals: before.length,
      observation_drain_ms: 500 }));
    return;
  }
  const request = JSON.parse(fs.readFileSync(path.join(__dirname, "request.json"), "utf8"));
  const before = await arrivals();
  const reply = await client.submit(request, { wait_ms: 3000 });
  assert.equal(reply.state, "delivered");
  assert.equal(reply.candidate.output_blocks[0].text, "Hello.");
  assert.equal(reply.candidate.usage.state, "available");
  const after = await arrivals();
  assert.equal(after.length, before.length + 1);
  const expected = fs.readFileSync(path.join(__dirname, "expected_request.txt"));
  assert.equal(after.at(-1).bytes, expected.length);
  assert.equal(after.at(-1).sha256, crypto.createHash("sha256").update(expected).digest("hex"));
  const status = await client.getStatus({ submission_id: reply.handle.submission_id });
  assert.equal(status.submission_state, "completed");
  assert.equal(status.candidate.candidate_id, reply.candidate.candidate_id);
  assert.equal((await arrivals()).length, after.length);
  console.log(JSON.stringify({ test: "js_python_receiver_roundtrip", submission_id: reply.handle.submission_id,
    attempt_id: reply.candidate.attempt_id, candidate_id: reply.candidate.candidate_id,
    usage: reply.candidate.usage, receiver_arrival: after.at(-1), status_revision: status.status_revision }));
}
main().catch(err => {
  console.error(JSON.stringify({ test: "driver", error: err.name, code: err.code, message: err.message,
    http_status: err.http_status, handle: err.handle, attempt_id: err.attempt_id }));
  process.exitCode = 1;
});
