"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const {createRequire} = require("node:module");
const load = createRequire(path.join(process.env.EZLLMROUTER_JS_CONSUMER, "package.json"));
const {EzLLMRouterClient, EzLLMRouterError} = load("@cognitivedynamics/ezllmrouter-client");
const matrix = JSON.parse(fs.readFileSync(process.env.EZLLMROUTER_TEST_MATRIX, "utf8"));

(async () => {
  assert.equal(matrix.cases.length, 28);
  for (const row of matrix.cases) {
    const client = new EzLLMRouterClient({
      baseUrl: process.env[row.id === "untrusted_tls" ? "EZLLMROUTER_TEST_TLS_ORIGIN" : "EZLLMROUTER_TEST_ORIGIN"],
      token: "synthetic-native-" + row.id, timeoutMs: row.timeout_ms,
    });
    if (row.code === null) {
      assert.equal((await client.getCapabilities()).profile, "initial_1a@1", row.id);
    } else {
      await assert.rejects(client.getCapabilities(), error => {
        assert(error instanceof EzLLMRouterError, row.id);
        assert.equal(error.code, row.code, row.id);
        assert.equal(error.retry_guidance, row.retry_guidance, row.id);
        assert(row.http_status.includes(error.http_status ?? 0), `${row.id}: unexpected status ${error.http_status}`);
        return true;
      });
    }
  }
  console.log(`JavaScript: ${matrix.cases.length} shared native HTTP cases passed.`);
})().catch(error => { console.error(error); process.exitCode = 1; });
