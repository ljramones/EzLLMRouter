"use strict";
// Rehearse each DEV-05 CommonJS tool actor mode without a network request.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const actor = path.resolve(__dirname, "../tool_cycle/js_actor.cjs");
const request = JSON.parse(fs.readFileSync(path.resolve(__dirname, "../development_slice/request.json")));
const scenarios = JSON.parse(fs.readFileSync(path.resolve(__dirname, "../tool_cycle/scenarios.json")));
const code = fs.readFileSync(actor, "utf8");

async function run(mode, kind) {
  const stdout = [], stderr = [];
  let sends = 0, reads = 0, lookups = 0, clock = 0;
  const tool = {block_id: "block.call.1", kind: "tool_call", call_id: "call.lookup.1",
    tool_name: "lookup", arguments: {key: "synthetic"},
    source_labels: {lineage_ids: ["src.candidate.tool"], sensitivity: "confidential",
      restrictions: ["no.content.store"]}};
  const candidate = index => ({candidate_id: "candidate." + index,
    attempt_id: "attempt." + index, finish_reason: index === 1 ? "tool_calls" : "stop",
    served_destination: {configuration_ref: "cfg.demo", service: "litellm.dev04",
      endpoint: "127.0.0.1", model: "model.demo", model_version: "v1", processing_region: "local"},
    output_blocks: index === 1 ? [structuredClone(tool)] : [
      {kind: "assistant_text", text: "Lookup: synthetic",
        source_labels: {restrictions: ["no.content.store"]}}]});
  const reply = index => ({state: "delivered", handle: {submission_id: "submission." + index},
    candidate: candidate(index)});
  const status = index => ({candidate_access: mode === "no_store" ? "not_retained" : "present",
    ...(mode === "no_store" ? {} : {candidate: candidate(index)}),
    attempts: [{attempt_id: "attempt." + index,
      usage: {state: "available", revision: {attempt_id: "attempt." + index}}}]});
  class Client {
    async submit(work) {
      if (work.execution_generation === "gen.3" && mode === "no_store")
        throw Object.assign(Error("SOURCE_INVALID"), {code: "SOURCE_INVALID", http_status: 422});
      sends++;
      return reply(sends);
    }
    async getStatus(selector) {
      reads++;
      if (mode === "failure_status") return {submission_state: kind,
        attempts: [{attempt_id: "attempt.503", usage: {state: "not_recorded"}}],
        ...(kind === "failed_after_transmit" ? {terminal_failure: {code: "REMOTE_EXECUTION_FAILED"}} : {})};
      if (mode === "status" || mode === "by_work") return {candidate_access: "present",
        handle: {submission_id: "submission.1"}, candidate: {
        candidate_id: "candidate.1", attempt_id: "attempt.1",
        output_blocks: [{kind: kind || "tool_call"}]},
        attempts: [{usage: {state: "available"}}]};
      return status(selector.submission_id.endsWith(".1") ? 1 : 2);
    }
    async getCapabilities() {return {contract_version: "0.2"};}
  }
  const localProcess = {argv: mode === "by_work" ?
    [process.execPath, actor, mode, "step.dev03.js", "gen.1", kind] :
    [process.execPath, actor, mode,
      mode === "status" || mode === "failure_status" ? "submission.1" : undefined,
      kind], exitCode: 0, env: {EZLLMROUTER_SERVICE_URL: "http://service.invalid",
    EZLLMROUTER_RECEIVER_URL: "http://receiver.invalid", EZLLMROUTER_DEV_TOKEN: "synthetic"}};
  const sandbox = {__dirname: path.dirname(actor), process: localProcess,
    structuredClone, Date: class {static now() {clock += 5200; return clock;}},
    setTimeout: callback => {queueMicrotask(callback); return 1;},
    fetch: async () => ({ok: true, json: async () => ({arrivals: Array(sends).fill({})})}),
    console: {log: value => stdout.push(value), error: value => stderr.push(value)},
    require: name => {
      if (name === "@cognitivedynamics/ezllmrouter-client") return {EzLLMRouterClient: Client};
      if (name === "node:fs") return {readFileSync: filename =>
        filename.endsWith("/request.json") ? JSON.stringify(request) : JSON.stringify(scenarios)};
      throw Error("unexpected import " + name);
    }};
  await new vm.Script(code, {filename: actor}).runInNewContext(sandbox, {timeout: 2000});
  assert.equal(localProcess.exitCode, 0, stderr.join("\n"));
  assert.equal(stdout.length, 1, "single stdout JSON document required");
  const value = JSON.parse(stdout[0]);
  assert.equal(value.actor, "js");
  assert.equal(stderr.length, 0);
  const expectedSends = mode === "cycle" || mode === "no_store" ? 2 : 0;
  assert.equal(sends, expectedSends);
  if (mode === "cycle" || mode === "no_store") {
    assert.equal(value.caller_tool_executions, 1);
    assert.equal(value.provider_sends_delta, 2);
    lookups++;
  } else {
    assert.equal(value.caller_tool_executions, 0);
    assert.equal(value.provider_sends_delta, 0);
  }
  if (mode === "no_store") {
    assert.equal(value.forged_source_rejected, true);
    assert(value.negative_stable_ms >= 5000);
  }
  return {mode, sends, lookups, status_reads: reads, stdout_documents: stdout.length};
}

(async () => {
  const results = [];
  for (const [mode, kind] of [["cycle"], ["no_store"], ["status", "tool_call"],
                              ["status", "assistant_text"],
                              ["by_work", "tool_call"], ["by_work", "assistant_text"],
                              ["failure_status", "failed_after_transmit"],
                              ["failure_status", "outcome_unknown"]])
    results.push(await run(mode, kind));
  console.log(JSON.stringify({node: process.version, passed: results.length,
    real_network_calls: 0, results}));
})().catch(error => {console.error(error); process.exitCode = 1;});
