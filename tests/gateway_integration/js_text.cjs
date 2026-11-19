"use strict";
// Installed CommonJS client; only the private EzLLMRouter service is called.
const fs = require("node:fs");
const { EzLLMRouterClient } = require("@cognitivedynamics/ezllmrouter-client");
const BASE = JSON.parse(fs.readFileSync(__dirname + "/request.json", "utf8"));

async function count() {
  const response = await fetch(process.env.EZLLMROUTER_RECEIVER_URL + "/observations");
  if (!response.ok) throw Error("receiver unavailable");
  return (await response.json()).arrivals.length;
}

async function diagnosticFetch(url, options) {
  const response = await fetch(url, options);
  const diagnostic = { diagnostic: "ezllmrouter_http_response_shape",
    method: options.method, status: response.status };
  try {
    const value = await response.clone().json();
    if (value && typeof value === "object" && !Array.isArray(value)) {
      diagnostic.keys = Object.keys(value).sort();
      diagnostic.state = value.state;
      const candidate = value.candidate;
      if (candidate && typeof candidate === "object") {
        diagnostic.candidate_keys = Object.keys(candidate).sort();
        const destination = candidate.served_destination;
        if (destination && typeof destination === "object") {
          diagnostic.served_destination = {
            service: destination.service, endpoint: destination.endpoint, model: destination.model,
          };
        }
        diagnostic.output_kinds = Array.isArray(candidate.output_blocks) ?
          candidate.output_blocks.map(block => block.kind) : null;
      }
    }
  } catch { diagnostic.shape_unavailable = true; }
  // Preserve stdout as one machine-readable actor result.
  console.error(JSON.stringify(diagnostic));
  return response;
}

async function receive(client, request) {
  const reply = await client.submit(request, { wait_ms: 3000 });
  if (reply.state === "delivered") return reply;
  if (reply.state !== "pending") throw Error("unexpected submission state");
  for (let i = 0; i < 80; i++) {
    const status = await client.getStatus({ submission_id: reply.handle.submission_id });
    if (status.candidate_access === "present") return { handle: reply.handle, candidate: status.candidate };
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  throw Error("candidate unavailable");
}

async function main() {
  const mode = process.argv[2];
  if (!["first", "after_tool", "after_destination", "after_guard"].includes(mode))
    throw Error("usage: js_text.cjs first|after_tool|after_destination|after_guard");
  const client = new EzLLMRouterClient({ baseUrl: process.env.EZLLMROUTER_SERVICE_URL,
    token: process.env.EZLLMROUTER_DEV_TOKEN, fetchImpl: diagnosticFetch });
  const before = await count();
  const request = structuredClone(BASE);
  request.step_id = mode === "first" ? "step.dev04.js.text" : "step.dev04.js.control." + mode;
  const reply = await receive(client, request);
  const status = await client.getStatus({ submission_id: reply.handle.submission_id });
  const after = await count();
  if (after !== before + 1 || reply.candidate.output_blocks[0].text !== "Hello." ||
      status.candidate_access !== "present" || status.attempts[0].usage.state !== "available" ||
      status.attempts[0].usage.revision.attempt_id !== reply.candidate.attempt_id)
    throw Error("real gateway text/usage/receiver assertion failed");
  console.log(JSON.stringify({ actor: "installed-js", mode,
    submission_id: reply.handle.submission_id, attempt_id: reply.candidate.attempt_id,
    candidate_id: reply.candidate.candidate_id, receiver_delta: after - before,
    served_destination: reply.candidate.served_destination,
    usage: status.attempts[0].usage }));
}

main().catch(error => { console.error(error); process.exitCode = 1; });
