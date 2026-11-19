"use strict";
// Installed CommonJS client caller: the only JS code that executes lookup.
const fs = require("node:fs");
const { EzLLMRouterClient } = require("@cognitivedynamics/ezllmrouter-client");
const BASE = JSON.parse(fs.readFileSync(__dirname + "/request.json", "utf8"));
const CORPUS = JSON.parse(fs.readFileSync(__dirname + "/scenarios.json", "utf8"));
const CASE = CORPUS.cases.find(x => x.actor === "js");
const TOOL = CORPUS.tool_definition;
const RESULT_LABEL = CORPUS.result_source_labels;
const executions = [];
function lookup(args) {
  if (JSON.stringify(args) !== JSON.stringify(CASE.arguments)) throw Error("caller allowlist rejected arguments");
  executions.push({ tool: "lookup", arguments: args });
  return CASE.result;
}
async function observedCount() {
  const reply = await fetch(process.env.EZLLMROUTER_RECEIVER_URL + "/observations");
  if (!reply.ok) throw Error("receiver observation unavailable");
  return (await reply.json()).arrivals.length;
}
async function receive(client, request) {
  const reply = await client.submit(request, { wait_ms: 3000 });
  if (reply.state === "delivered") return reply;
  if (reply.state !== "pending") throw Error("no usable candidate");
  const until = Date.now() + 5000;
  while (Date.now() < until) {
    const status = await client.getStatus({ submission_id: reply.handle.submission_id });
    if (status.candidate_access === "present") return { state: "delivered", handle: reply.handle, candidate: status.candidate };
    if (status.submission_state !== "admitted") throw Error("terminal without usable candidate");
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  throw Error("candidate did not become available");
}
async function cycle(alternative = false) {
  const client = new EzLLMRouterClient({ baseUrl: process.env.EZLLMROUTER_SERVICE_URL, token: process.env.EZLLMROUTER_DEV_TOKEN });
  const before = await observedCount();
  const first = structuredClone(BASE);
  Object.assign(first, { step_id: CASE.step_id, execution_generation: alternative ? "gen.3" : "gen.1", requested_features: ["text", "tools"],
    tool_definitions: [TOOL], tool_choice: "auto" });
  first.messages[1].blocks[0].text = "Use lookup for synthetic.";
  const firstReply = await receive(client, first), firstCandidate = firstReply.candidate;
  if (executions.length || firstCandidate.finish_reason !== "tool_calls" || firstCandidate.output_blocks.length !== 1) throw Error("tool candidate invalid");
  const call = firstCandidate.output_blocks[0];
  if (call.kind !== "tool_call" || call.tool_name !== "lookup") throw Error("tool call invalid");
  const firstStatus = await client.getStatus({ submission_id: firstReply.handle.submission_id });
  if (firstStatus.candidate_access !== "present") throw Error("candidate not retained");
  const result = lookup(call.arguments);
  const second = structuredClone(first);
  second.execution_generation = alternative ? "gen.4" : "gen.2";
  const resultKind = alternative ? "result_value" : CASE.result_kind;
  const submittedResult = alternative ? { value: "synthetic" } : result;
  second.messages.push({ role: "assistant", blocks: [call] });
  second.messages.push({ role: "tool", blocks: [{ block_id: "block.result.1", kind: "tool_result", call_id: call.call_id,
    [resultKind]: submittedResult, source_labels: RESULT_LABEL }] });
  const secondReply = await receive(client, second), secondCandidate = secondReply.candidate;
  if (secondCandidate.output_blocks[0].text !== CASE.final_text) throw Error("final answer ignored result");
  const secondStatus = await client.getStatus({ submission_id: secondReply.handle.submission_id });
  const after = await observedCount();
  if (after - before !== CASE.model_posts || executions.length !== CASE.caller_tool_executions || firstCandidate.attempt_id === secondCandidate.attempt_id ||
      firstCandidate.candidate_id === secondCandidate.candidate_id) throw Error("attempt/send/tool count mismatch");
  for (const [status, candidate] of [[firstStatus, firstCandidate], [secondStatus, secondCandidate]]) {
    if (status.attempts[0].usage.state !== "available" || status.attempts[0].usage.revision.attempt_id !== candidate.attempt_id)
      throw Error("usage mismatch");
  }
  console.log(JSON.stringify({ actor: "js", variant: alternative ? "alternate" : "baseline", result_kind: resultKind,
    first_submission_id: firstReply.handle.submission_id,
    second_submission_id: secondReply.handle.submission_id, first_candidate_id: firstCandidate.candidate_id,
    second_candidate_id: secondCandidate.candidate_id, first_attempt_id: firstCandidate.attempt_id,
    second_attempt_id: secondCandidate.attempt_id, call_id: call.call_id,
    provider_sends_delta: after - before, caller_tool_executions: executions.length, result: submittedResult,
    destinations: [firstCandidate.served_destination, secondCandidate.served_destination],
    usage: [firstStatus.attempts[0].usage, secondStatus.attempts[0].usage] }));
}
async function status(submissionId, expectedKind = "tool_call") {
  const client = new EzLLMRouterClient({ baseUrl: process.env.EZLLMROUTER_SERVICE_URL, token: process.env.EZLLMROUTER_DEV_TOKEN });
  const before = await observedCount();
  const value = await client.getStatus({ submission_id: submissionId });
  const after = await observedCount();
  if (value.candidate_access !== "present" || after !== before || executions.length ||
      value.candidate.output_blocks[0].kind !== expectedKind) throw Error("cross read failed");
  console.log(JSON.stringify({ actor: "js", cross_read: submissionId,
    candidate_id: value.candidate.candidate_id, attempt_id: value.candidate.attempt_id,
    usage_state: value.attempts[0].usage.state,
    provider_sends_delta: 0, caller_tool_executions: 0 }));
}
async function statusByWork(stepId, generation, expectedKind) {
  const client = new EzLLMRouterClient({ baseUrl: process.env.EZLLMROUTER_SERVICE_URL, token: process.env.EZLLMROUTER_DEV_TOKEN });
  const before = await observedCount();
  const selector = {task_id: BASE.task_id, step_id: stepId,
    step_revision: BASE.step_revision, execution_generation: generation};
  const value = await client.getStatus(selector);
  const after = await observedCount();
  if (value.candidate_access !== "present" || after !== before || executions.length ||
      value.candidate.output_blocks[0].kind !== expectedKind ||
      value.attempts[0].usage.state !== "available") throw Error("by-work cross read failed");
  console.log(JSON.stringify({actor: "js", by_work: selector,
    submission_id: value.handle.submission_id,
    candidate_id: value.candidate.candidate_id, attempt_id: value.candidate.attempt_id,
    provider_sends_delta: 0, caller_tool_executions: 0}));
}
async function failureStatus(submissionId, expectedState) {
  const client = new EzLLMRouterClient({ baseUrl: process.env.EZLLMROUTER_SERVICE_URL, token: process.env.EZLLMROUTER_DEV_TOKEN });
  const before = await observedCount();
  const value = await client.getStatus({ submission_id: submissionId });
  const after = await observedCount();
  if (after !== before || executions.length || value.submission_state !== expectedState ||
      value.attempts.length !== 1 || value.attempts[0].usage.state !== "not_recorded" ||
      (expectedState === "failed_after_transmit" && value.terminal_failure?.code !== "REMOTE_EXECUTION_FAILED") ||
      (expectedState === "outcome_unknown" && "terminal_failure" in value))
    throw Error("cross failure status invalid");
  console.log(JSON.stringify({ actor: "js", cross_read: submissionId,
    submission_state: value.submission_state, attempt_id: value.attempts[0].attempt_id,
    usage_state: value.attempts[0].usage.state, provider_sends_delta: 0,
    caller_tool_executions: 0 }));
}
async function noStoreCycle() {
  const client = new EzLLMRouterClient({ baseUrl: process.env.EZLLMROUTER_SERVICE_URL, token: process.env.EZLLMROUTER_DEV_TOKEN });
  const before = await observedCount();
  const first = structuredClone(BASE);
  Object.assign(first, { step_id: "step.dev03.js.no_store", execution_generation: "gen.1",
    requested_features: ["text", "tools"], tool_definitions: [TOOL], tool_choice: "auto" });
  Object.assign(first.messages[1].blocks[0], { text: "Use lookup for synthetic.", source_labels: {
    lineage_ids: ["src.user.no_store"], sensitivity: "confidential", restrictions: ["no.content.store"] } });
  const firstReply = await receive(client, first);
  const call = firstReply.candidate.output_blocks[0];
  if (call.kind !== "tool_call" || call.source_labels.restrictions.join() !== "no.content.store") throw Error("live no-store call invalid");
  const firstStatus = await client.getStatus({ submission_id: firstReply.handle.submission_id });
  if (firstStatus.candidate_access !== "not_retained" || "candidate" in firstStatus) throw Error("no-store call retrievable");
  const result = lookup(call.arguments);
  const second = structuredClone(first);
  second.execution_generation = "gen.2";
  second.messages.push({ role: "assistant", blocks: [call] });
  second.messages.push({ role: "tool", blocks: [{ block_id: "block.result.1", kind: "tool_result",
    call_id: call.call_id, result_text: result, source_labels: RESULT_LABEL }] });
  const forged = structuredClone(second);
  forged.execution_generation = "gen.3";
  forged.messages[2].blocks[0].arguments.key = "forged";
  try { await client.submit(forged, { wait_ms: 3000 }); throw Error("forged live source accepted"); }
  catch (error) { if (error.code !== "SOURCE_INVALID" || error.http_status !== 422) throw error; }
  const negativeBefore = await observedCount();
  const stableStart = Date.now();
  await new Promise(resolve => setTimeout(resolve, 5200));
  await client.getCapabilities();
  const negativeAfter = await observedCount();
  const stableMs = Date.now() - stableStart;
  if (stableMs < 5000 || negativeBefore !== before + 1 || negativeAfter !== negativeBefore) throw Error("forged source sent to receiver");
  const finalReply = await receive(client, second), final = finalReply.candidate;
  if (final.output_blocks[0].text !== "Lookup: synthetic" ||
      final.output_blocks[0].source_labels.restrictions.join() !== "no.content.store") throw Error("no-store continuation invalid");
  const finalStatus = await client.getStatus({ submission_id: finalReply.handle.submission_id });
  const after = await observedCount();
  if (finalStatus.candidate_access !== "not_retained" || "candidate" in finalStatus ||
      after - before !== 2 || executions.length !== 1) throw Error("no-store result/usage count mismatch");
  console.log(JSON.stringify({ actor: "js", variant: "live_no_store", first_submission_id: firstReply.handle.submission_id,
    second_submission_id: finalReply.handle.submission_id, provider_sends_delta: after - before,
    caller_tool_executions: executions.length, forged_source_rejected: true,
    destinations: [firstReply.candidate.served_destination, final.served_destination],
    negative_stable_ms: stableMs, candidate_access: [firstStatus.candidate_access, finalStatus.candidate_access] }));
}
const mode = process.argv[2];
(mode === "cycle" ? cycle() : mode === "cycle_alt" ? cycle(true) :
  mode === "no_store" ? noStoreCycle() :
  mode === "status" && process.argv[3] ? status(process.argv[3], process.argv[4]) :
  mode === "by_work" && process.argv[3] && process.argv[4] && process.argv[5] ?
    statusByWork(process.argv[3], process.argv[4], process.argv[5]) :
  mode === "failure_status" && process.argv[3] && process.argv[4] ? failureStatus(process.argv[3], process.argv[4]) :
  Promise.reject(Error("usage: js_actor.cjs cycle | cycle_alt | no_store | status SUBMISSION_ID"))).catch(error => {
  console.error(error); process.exitCode = 1;
});
