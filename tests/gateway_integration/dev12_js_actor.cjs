"use strict";
// Installed CommonJS package, same authenticated HTTP/guard/TLS route as Python.
const fs = require("node:fs");
const {DurankiClient} = require("/js/node_modules/@mach33/duranki-client");

async function main() {
  const {base_url, token, request} = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
  const client = new DurankiClient({baseUrl: base_url, token});
  const reply = request.operation.type === "embedding.create" ?
    await client.submitEmbedding(request, {wait_ms: 5000}) :
    await client.submitRerank(request, {wait_ms: 5000});
  let status = await client.getSuccessorStatus({submission_id: reply.handle.submission_id});
  for (let attempt = 0; attempt < 50 && status.submission_state === "pending"; attempt++) {
    await new Promise(resolve => setTimeout(resolve, 50));
    status = await client.getSuccessorStatus({submission_id: reply.handle.submission_id});
  }
  if (status.submission_state !== "completed") throw Error("installed CommonJS execution did not complete");
  process.stdout.write(JSON.stringify({reply, status}) + "\n");
}
main().catch(error => {process.stderr.write(JSON.stringify({error_type:error.name,code:error.code||null,
  message:error.message})+"\n");process.exitCode=1;});
