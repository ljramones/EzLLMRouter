"use strict";
const assert = require("node:assert/strict");
const { performance } = require("node:perf_hooks");
process.env.DURANKI_SERVICE_URL = "http://synthetic.invalid";
process.env.DURANKI_DEV_TOKEN = "synthetic.component.token";
process.env.DURANKI_RECEIVER_URL = "http://receiver.invalid";
const { noSendDrain, requestFor } = require("./integration_js.cjs");
const cases = require("./scenarios.json").cases;

async function main() {
  for (const id of ["retained_pending", "no_store_expiry", "retained_pending_js", "no_store_expiry_js"]) {
    const item = cases.find(row => row.id === id);
    assert.equal(requestFor(item).generation_settings.total_timeout_ms, 3000);
    assert.equal(item.wait_ms, 0);
  }
  let calls = 0;
  globalThis.fetch = async () => { calls++; return new Response(JSON.stringify({ arrivals: [] }), { status: 200 }); };
  const start = performance.now();
  const drained = await noSendDrain(0);
  assert.ok(drained.elapsedMs >= 500 && performance.now() - start >= 500);
  assert.ok(calls >= 2);
  calls = 0;
  globalThis.fetch = async () => {
    calls++;
    return new Response(JSON.stringify({ arrivals: calls === 1 ? [] : [{ sequence: 1 }] }), { status: 200 });
  };
  await assert.rejects(() => noSendDrain(0), /unexpected receiver send/);
  assert.equal(calls, 2);
  console.log(JSON.stringify({ test: "actor_logic", pending_budget_cases: 4,
    negative_drain_ms: drained.elapsedMs, unexpected_send_rejected: true }));
}
main().catch(error => { console.error(error); process.exitCode = 1; });
