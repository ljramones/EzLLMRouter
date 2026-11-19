"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");
const {createRequire} = require("node:module");
const load = createRequire(path.join(process.env.EZLLMROUTER_JS_CONSUMER, "package.json"));
const {EzLLMRouterClient, EzLLMRouterError} = load("@cognitivedynamics/ezllmrouter-client");

(async () => {
  for (const mode of ["success", "redirect", "compressed", "oversize", "chunked", "truncated", "slow"]) {
    // The fixture supplies an explicit short caller deadline; it does not test
    // the client's default deadline or qualify a live endpoint.
    const client = new EzLLMRouterClient({
      baseUrl: process.env.EZLLMROUTER_TEST_ORIGIN, token: "synthetic-native-" + mode,
      fetchImpl: (url, options) => fetch(url, {...options, signal: AbortSignal.timeout(mode === "slow" ? 100 : 5000)}),
    });
    if (["success", "chunked"].includes(mode)) {
      assert.equal((await client.getCapabilities()).contract_version, "0.2");
    } else {
      await assert.rejects(client.getCapabilities(), error => error instanceof EzLLMRouterError &&
        ["TRANSPORT_OUTCOME_UNKNOWN", "INTERNAL_UNAVAILABLE"].includes(error.code) &&
        error.retry_guidance === "query_first", mode);
    }
  }
  console.log("JavaScript HTTP: actual fetch, redirects, response faults and caller deadline passed.");
})().catch(error => { console.error(error); process.exitCode = 1; });
