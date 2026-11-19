"use strict";
const assert = require("node:assert/strict");
const {createRequire} = require("node:module");
const path = require("node:path");
const {test} = require("node:test");

const consumer = process.env.EZLLMROUTER_JS_CONSUMER;
const load = consumer ? createRequire(path.join(consumer, "package.json")) : require;
const {EzLLMRouterClient, IntegrationClient} = consumer ?
  load("@cognitivedynamics/ezllmrouter-client") : require("../../clients/js");
const cases = require("./cases.json");
const origin = "http://synthetic.invalid";

for (const row of cases) {
  test(row.name, async () => {
    const calls = [];
    const fetchImpl = async (url, options) => {
      calls.push({method: options.method, path: url.slice(origin.length), headers: options.headers,
        body: options.body === undefined ? null : JSON.parse(options.body)});
      if (row.lost) throw Error("synthetic lost response");
      return new Response(row.raw ? Buffer.from(row.raw, "base64") : JSON.stringify(row.response),
        {status: row.status ?? 200, headers: {"EzLLMRouter-Contract-Version": row.wire ?? "0.2",
          "EzLLMRouter-Integration-Version": row.version ?? "1", ...row.response_headers}});
    };
    const client = row.integration ?
      new IntegrationClient(origin, "synthetic-token", {fetchImpl, version: row.version ?? "1"}) :
      new EzLLMRouterClient({baseUrl: origin, token: "synthetic-token", fetchImpl});
    const method = row.action.replace(/_([a-z])/g, (_, char) => char.toUpperCase());
    assert.equal(typeof client[method], "function", "missing public client operation");
    const args = structuredClone(row.args ?? []);
    if (Object.hasOwn(row, "wait_ms")) args.push({wait_ms: row.wait_ms});
    let observed;
    try {
      await client[method](...args);
      observed = {ok: true};
    } catch (error) {
      observed = {code: error.code ?? "SCHEMA_INVALID",
        retry_guidance: error.retry_guidance ?? error.retryGuidance ?? "never",
        http_status: error.http_status ?? error.httpStatus ?? 0,
        selector: error.selector ?? null, handle: error.handle ?? null};
    }
    observed.calls = calls;
    // The corpus is checked against Python separately. Compare errors, recovery
    // context and exact outgoing requests as well as positive acceptance.
    assert.deepEqual(observed, row.expected);
  });
}
