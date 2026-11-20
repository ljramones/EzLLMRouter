"use strict";
// Executes the exact unpacked CommonJS artifact; never loads repo client source.
const fs = require("node:fs");

async function main() {
  if (process.argv.length !== 3) throw Error("one bounded input file required");
  const input = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
  const {EzLLMRouterClient} = require(input.package_path);
  const client = new EzLLMRouterClient({baseUrl: input.base_url, token: input.token});
  if (input.action === "recover") {
    const observed = {};
    for (const [label, selector] of Object.entries(input.selectors)) {
      try { observed[label] = { status: await client.getSuccessorStatus(selector) }; }
      catch (error) { observed[label] = { error: { code: error.code || null,
        http_status: error.httpStatus ?? error.http_status ?? null,
        retry_guidance: error.retryGuidance ?? error.retry_guidance ?? null } }; }
    }
    if (input.duplicate_request) {
      try {
        observed.duplicate = { reply: input.duplicate_request.operation.type === "embedding.create" ?
          await client.submitEmbedding(input.duplicate_request, { wait_ms: 5000 }) :
          await client.submitRerank(input.duplicate_request, { wait_ms: 5000 }) };
      } catch (error) { observed.duplicate = { error: { code: error.code || null,
        http_status: error.httpStatus ?? error.http_status ?? null,
        retry_guidance: error.retryGuidance ?? error.retry_guidance ?? null } }; }
    }
    process.stdout.write(JSON.stringify(observed) + "\n");
    return;
  }
  if (input.action !== "submit") throw Error("unsupported installed-client action");
  const request = input.request;
  const reply = request.operation.type === "embedding.create" ?
    await client.submitEmbedding(request, {wait_ms: 5000}) :
    await client.submitRerank(request, {wait_ms: 5000});
  let status = await client.getSuccessorStatus({submission_id: reply.handle.submission_id});
  for (let i = 0; i < 100 && status.submission_state === "pending"; i++) {
    await new Promise(resolve => setTimeout(resolve, 50));
    status = await client.getSuccessorStatus({submission_id: reply.handle.submission_id});
  }
  process.stdout.write(JSON.stringify({reply, status}) + "\n");
}
main().catch(error => {
  process.stderr.write(JSON.stringify({error_type: error.name,
    code: error.code || null, message: error.message}) + "\n");
  process.exitCode = 1;
});
