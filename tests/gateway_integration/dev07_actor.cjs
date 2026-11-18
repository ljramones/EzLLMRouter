"use strict";
// Installed CommonJS client; private token arrives only on stdin.
const fs = require("node:fs");
const {DurankiClient} = require("@mach33/duranki-client");
const base = JSON.parse(fs.readFileSync(__dirname + "/request.json", "utf8"));
const value = JSON.parse(fs.readFileSync(0, "utf8"));
const keys = Object.keys(value).sort().join(",");
if (keys !== "configuration_ref,generation,mode,step_id,token" ||
    !["text","deny"].includes(value.mode) || typeof value.token !== "string" || value.token.length < 32 ||
    ![value.configuration_ref,value.generation,value.step_id].every(x => typeof x === "string" && /^[A-Za-z0-9._:-]{1,128}$/.test(x)))
  throw Error("invalid actor input");
const request = structuredClone(base);
request.requested_configuration_ref = value.configuration_ref;
request.execution_generation = value.generation;
request.step_id = value.step_id;

async function main() {
  const client = new DurankiClient({baseUrl:"http://127.0.0.1:8773", token:value.token});
  if (value.mode === "deny") {
    try { await client.submit(request, {wait_ms:3000}); }
    catch (error) {
      if (!error.code) throw error;
      console.log(JSON.stringify({kind:"denied", code:error.code, http_status:error.http_status,
        failure_stage:error.failure_stage, attempt_id:error.attempt_id,
        submission_id:error.handle?.submission_id}));
      return;
    }
    throw Error("denied actor was accepted");
  }
  const reply = await client.submit(request, {wait_ms:3000});
  let candidate = reply.candidate;
  if (reply.state === "pending") {
    for (let i=0; i<80 && !candidate; i++) {
      await new Promise(resolve=>setTimeout(resolve,50));
      const status = await client.getStatus({submission_id:reply.handle.submission_id});
      if (status.candidate_access === "present") candidate = status.candidate;
    }
  }
  if (!candidate) throw Error("candidate unavailable");
  const status = await client.getStatus({submission_id:reply.handle.submission_id});
  console.log(JSON.stringify({kind:"text", submission_ids:[reply.handle.submission_id],
    attempt_id:candidate.attempt_id, selected_model:candidate.served_destination.model,
    candidate_access:status.candidate_access,
    price_version:status.attempts[0].usage?.revision?.price_version,
    cost:status.attempts[0].usage?.revision?.cost, caller_lookups:0}));
}
main().catch(error=>{console.error("DEV-07 JS actor failed: "+error.name);process.exitCode=1;});
