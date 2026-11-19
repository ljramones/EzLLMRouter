"use strict";
// Installed package in a separate disposable container; no provider credential here.
const fs = require("node:fs");
const { EzLLMRouterClient } = require("@cognitivedynamics/ezllmrouter-client");
const inputPath = "/link/dev10-js-input.json";
const resultPath = "/link/dev10-js-result.json";
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

(async () => {
  for (let i = 0; i < 100 && !fs.existsSync(inputPath); i++) await wait(100);
  if (!fs.existsSync(inputPath)) throw Error("service readiness deadline");
  const input = JSON.parse(fs.readFileSync(inputPath, "utf8"));
  const client = new EzLLMRouterClient({ baseUrl: input.base_url, token: input.token });
  const first = await client.submit(input.request, { wait_ms: 10000 });
  if (first.state !== "delivered") throw Error("first response not delivered");
  const duplicate = await client.submit(input.request, { wait_ms: 10000 });
  const status = await client.getStatus({ submission_id: first.handle.submission_id });
  if (duplicate.handle.submission_id !== first.handle.submission_id ||
      status.submission_state !== "completed") throw Error("duplicate/status mismatch");
  fs.writeFileSync(resultPath, JSON.stringify({ state: first.state,
    submission_id: first.handle.submission_id, attempt_id: first.candidate.attempt_id,
    duplicate_same_submission: true, status: status.submission_state,
    installed_package: require.resolve("@cognitivedynamics/ezllmrouter-client") }));
  process.stdout.write(JSON.stringify({ status: "PASS", installed_commonjs: true,
    duplicate_same_submission: true }) + "\n");
})().catch(error => {
  process.stderr.write(`${error.code || error.name}: ${error.message}\n`);
  process.exitCode = 1;
});
