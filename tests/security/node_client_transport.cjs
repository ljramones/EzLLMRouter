"use strict";
// Run with a fixed Node 24 runtime; optionally resolve the clean installed package.
const assert = require("node:assert/strict");
const {createRequire} = require("node:module");
const fs = require("node:fs");
const path = require("node:path");

const fromConsumer = process.argv[2];
const consumer = fromConsumer && path.resolve(fromConsumer);
const load = consumer ? createRequire(path.join(consumer, "package.json")) : require;
const {EzLLMRouterClient, IntegrationClient} = consumer ? load("@cognitivedynamics/ezllmrouter-client") :
  require("../../clients/js");
const pkgPath = consumer ? path.join(consumer, "node_modules/@cognitivedynamics/ezllmrouter-client/package.json") :
  path.join(__dirname, "../../clients/js/package.json");
const pkg = JSON.parse(fs.readFileSync(pkgPath, "utf8"));
assert.equal(pkg.engines.node, ">=24.22.1 <25");

for (const baseUrl of ["http://user:pass@localhost:8765", "http://localhost:8765/path",
  "http://localhost:8765/?q=1", "http://localhost:8765/#fragment", "file:///tmp/service"]) {
  assert.throws(() => new EzLLMRouterClient({baseUrl, token: "synthetic"}), TypeError);
  assert.throws(() => new IntegrationClient(baseUrl, "synthetic", {version: "2"}), TypeError);
}

async function main() {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({url, options});
    throw new Error("synthetic transport stop before any network request");
  };
  const controlled = new EzLLMRouterClient({baseUrl: "http://localhost:8765/", token: "synthetic", fetchImpl});
  await assert.rejects(controlled.getStatus({submission_id: "synthetic.submission"}));
  await assert.rejects(controlled._extension("GET", "/v1/outcomes/synthetic", undefined, "receipt"));
  await assert.rejects(controlled._requestSuccessor("GET", "/v2/status/synthetic", undefined, undefined,
    undefined, "status"));
  const external = new IntegrationClient("http://localhost:8765/", "synthetic", {fetchImpl, version: "2"});
  await assert.rejects(external.report("synthetic.dataset"));
  assert.equal(calls.length, 4);
  for (const call of calls) {
    assert.ok(call.url.startsWith("http://localhost:8765/"));
    assert.equal(call.options.headers["Accept-Encoding"], "identity");
    assert.ok(["manual", "error"].includes(call.options.redirect));
  }
  console.log("fixed Node client origin and identity-encoding checks passed (4 transports, no network)");
}

main().catch(error => { console.error(error); process.exitCode = 1; });
