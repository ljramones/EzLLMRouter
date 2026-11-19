"use strict";
const fs = require("node:fs");
const { DurankiClient } = require("@cognitivedynamics/ezllmrouter-client");

(async () => {
  const input = JSON.parse(fs.readFileSync(0, "utf8"));
  const client = new DurankiClient({ baseUrl: input.base_url, token: input.token });
  const runs = [];
  for (const row of input.rows) {
    const run = await client.startRun(row.run);
    const reply = await client.submitInRun(row.request, row.run.run_id, { wait_ms: 3000 });
    runs.push({run_id: run.run_id, submission_id: reply.handle.submission_id,
      state: reply.state});
  }
  let outcome = null;
  if (input.outcome) {
    outcome = await client.reportOutcome(input.outcome);
    const same = value => Object.keys(value).length === Object.keys(outcome).length &&
      Object.keys(outcome).every(key => value[key] === outcome[key]);
    if (!same(await client.reportOutcome(input.outcome)) ||
        !same(await client.getOutcomeReceipt(input.outcome.event_id)))
      throw Error("outcome duplicate or read receipt changed");
  }
  process.stdout.write(JSON.stringify({package: require.resolve("@cognitivedynamics/ezllmrouter-client"), runs, outcome}) + "\n");
})().catch(error => {
  process.stderr.write(`${error.code || error.name}: ${error.message}\n`);
  process.exitCode = 1;
});
