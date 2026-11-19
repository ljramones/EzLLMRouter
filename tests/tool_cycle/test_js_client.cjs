"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const { EzLLMRouterClient, EzLLMRouterError } = require("@cognitivedynamics/ezllmrouter-client");
const vectors = JSON.parse(fs.readFileSync(__dirname + "/vectors.json", "utf8")).examples;
const request = JSON.parse(fs.readFileSync(__dirname + "/request.json", "utf8"));

async function check(reply, expectedCode) {
  let sends = 0;
  const client = new EzLLMRouterClient({ baseUrl: "http://synthetic.invalid", token: "synthetic",
    fetchImpl: async () => { sends++; return new Response(JSON.stringify(reply), {status: 200,
      headers: {"EzLLMRouter-Contract-Version": "0.2"}}); } });
  if (expectedCode) {
    await assert.rejects(client.submit(request), error => error instanceof EzLLMRouterError && error.code === expectedCode);
  } else {
    const result = await client.submit(request);
    assert.equal(result.candidate.output_blocks[0].kind, "tool_call");
    assert.equal(result.candidate.output_blocks[0].arguments.key, "synthetic");
  }
  assert.equal(sends, 1);
}

(async () => {
  await check(structuredClone(vectors.reply_tool));
  const malformed = structuredClone(vectors.reply_tool);
  malformed.candidate.output_blocks[0].arguments.key = 1;
  await check(malformed, "INTERNAL_UNAVAILABLE");
  const duplicate = structuredClone(vectors.reply_tool);
  duplicate.candidate.output_blocks.push({ ...duplicate.candidate.output_blocks[0], block_id: "block.call.2" });
  await check(duplicate, "INTERNAL_UNAVAILABLE");
  console.log(JSON.stringify({ test: "installed_js_tool_candidate", positive: 1, malformed_rejected: 2 }));
})().catch(error => { console.error(error); process.exitCode = 1; });
