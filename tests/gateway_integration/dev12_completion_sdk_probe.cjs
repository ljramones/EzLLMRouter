"use strict";
// No-network paired wire-0.3 status checks against the exact unpacked tarball.
const fs = require("node:fs");
const crypto = require("node:crypto");
const installed = process.argv[2], evidence = process.argv[3];
const { DurankiClient, DurankiError } = require(installed);
const fixtureBytes = fs.readFileSync(evidence);
const fixture = JSON.parse(fixtureBytes)["payload"]["live_target"]["python_status"];
const handle = fixture.handle;
const selectors = [
  { submission_id: handle.submission_id },
  { work_selector: Object.fromEntries(["task_id", "step_id", "step_revision",
    "execution_generation"].map(key => [key, handle.work_key[key]])) },
];
const hash = bytes => crypto.createHash("sha256").update(bytes).digest("hex");
const expected = { positive: "accepted", unknown_version: "UNSUPPORTED_VERSION",
  unknown_field: "INTERNAL_UNAVAILABLE" };

(async () => {
  const outcomes = [];
  for (const selector of selectors) for (const name of Object.keys(expected)) {
    const body = JSON.parse(JSON.stringify(fixture));
    let header = "0.3";
    if (name === "unknown_version") { body.contract_version = "0.4"; header = "0.4"; }
    if (name === "unknown_field") body.unregistered_field = "forbidden";
    const raw = Buffer.from(JSON.stringify(body));
    const requests = [];
    const fetchImpl = async (url, request) => {
      requests.push({ method: request.method, url,
        contract_version: request.headers["Duranki-Contract-Version"] });
      return { status: 200, headers: { get: () => header },
        arrayBuffer: async () => raw };
    };
    const client = new DurankiClient({ baseUrl: "http://127.0.0.1:1",
      token: "synthetic-local-only", fetchImpl });
    let observed;
    try {
      const value = await client.getSuccessorStatus(selector);
      observed = JSON.stringify(value) === JSON.stringify(body) ? "accepted" : "wrong_result";
    } catch (error) {
      observed = error instanceof DurankiError ? error.code : String(error);
    }
    outcomes.push({ case: name, selector: selector.submission_id ? "submission_id" : "work_selector",
      http_status: 200, response_header: header, exact_body_utf8: raw.toString("utf8"),
      body_sha256: hash(raw), observed, expected: expected[name], request: requests,
      passed: observed === expected[name] && requests.length === 1 });
  }
  process.stdout.write(JSON.stringify({ kind: "dev12_exact_tarball_sdk_probe_v1",
    tarball_root: installed, fixture_sha256: hash(fixtureBytes), outcomes }) + "\n");
  if (outcomes.some(row => !row.passed)) process.exitCode = 1;
})().catch(error => { process.stderr.write(String(error) + "\n"); process.exitCode = 1; });
