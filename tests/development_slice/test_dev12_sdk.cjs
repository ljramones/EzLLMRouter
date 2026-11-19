"use strict";
// No-network CommonJS successor protocol distinctions against adopted fixtures.
const assert=require("node:assert/strict");
const path=require("node:path");
const root=path.resolve(__dirname,"../..");
const source=process.env.DEV12_JS_CLIENT_DIR||path.join(root,"clients/js");
const {DurankiClient,DurankiError}=require(path.join(source,"index.cjs"));
const vectors=require(path.join(root,"tests/fixtures/contracts/dev12-successor-01/vectors.json"));
const request=vectors.examples.find(item=>item.id==="DELEGATED_RERANK").request;
const completed=vectors.protocol_fixtures.find(item=>item.id==="COMPLETED").value;
const status=vectors.protocol_fixtures.find(item=>item.id==="STATUS_VALID_UNKNOWN_COST").value;
const failed=vectors.protocol_fixtures.find(item=>item.id==="FAILED_BEFORE_SEND").value;
const knownStatus=vectors.protocol_fixtures.find(item=>item.id==="STATUS_INVALID_OUTPUT_WITH_USAGE").value;
const clone=value=>structuredClone(value);

async function invoke(value,http=200,raw,kind="submit") {
  const bytes=raw??Buffer.from(JSON.stringify(value));
  const client=new DurankiClient({baseUrl:"http://synthetic.invalid",token:"test-only-token",
    fetchImpl:async()=>new Response(bytes,{status:http,headers:{"Duranki-Contract-Version":"0.3"}})});
  return kind==="submit"?client.submit_rerank(clone(request)):
    client.getSuccessorStatus({submission_id:status.handle.submission_id});
}
async function rejects(value,http=200,raw,kind="submit",guidance="query_first") {
  await assert.rejects(invoke(value,http,raw,kind),error=>{
    assert(error instanceof DurankiError);assert.equal(error.retry_guidance,guidance);return true;});
}
async function main(){
  assert.equal((await invoke(completed)).state,"completed");
  assert.equal((await invoke(status,200,undefined,"status")).submission_state,"completed");
  await rejects(completed,202);
  await rejects(status,202,undefined,"status");
  const foreign=clone(completed);foreign.result.results[0].candidate_id="doc.foreign";await rejects(foreign);
  const high=clone(completed);high.result.results[0].score="99";await rejects(high);
  const incoherent=clone(status);incoherent.attempts[0].settlement_state="calculated";
  await rejects(incoherent,200,undefined,"status");
  const duplicate=Buffer.from(JSON.stringify(completed).replace('"state":"completed"',
    '"state":"pending","state":"completed"'));
  await rejects(completed,200,duplicate);
  await rejects(completed,200,Buffer.from([0xff]));
  await rejects(completed,200,Buffer.from('{"state":"\\ud800"}'));
  const error={contract_version:"0.3",code:"POLICY_DENIED",correlation_id:"error.synthetic",
    retry_guidance:"query_first"};
  await rejects(error,403);
  const authentication={...error,retry_guidance:"never"};
  await rejects(authentication,401,undefined,"submit","never");
  await rejects(authentication,401,undefined,"status","never");
  const successor=require(path.join(source,"successor.cjs"));
  assert.equal(successor.errorValid(authentication,401,"submit"),true);
  assert.equal(successor.errorValid({...authentication,retry_guidance:"query_first"},401,"submit"),false);
  assert.equal(successor.errorValid({...authentication,code:"INTENT_PERSIST_FAILED"},401,"submit"),false);
  assert.equal(successor.errorValid({...authentication,extra:true},401,"submit"),false);
  const reordered=clone(request);reordered.operation={version:1,type:"rerank"};
  const reorderedClient=new DurankiClient({baseUrl:"http://synthetic.invalid",token:"test-only-token",
    fetchImpl:async()=>new Response(Buffer.from(JSON.stringify(completed)),{status:200,
      headers:{"Duranki-Contract-Version":"0.3"}})});
  assert.equal((await reorderedClient.submit_rerank(reordered)).state,"completed");
  for(const component of [
    {component:"document_units",presence:"absent"},
    {component:"document_units",presence:"null"},
    {component:"document_units",presence:"invalid",raw_digest:"sha256:"+"0".repeat(64)},
    {component:"document_units",presence:"known",quantity:1,evidence:"derived",source_ref:"receiver.synthetic"}]){
    const contradictory=clone(status),usage=contradictory.attempts[0].usage_revision;
    usage.components=[component];usage.cost_status="calculated";usage.amount_decimal="0.000200000";
    contradictory.attempts[0].settlement_state="calculated";
    await rejects(contradictory,200,undefined,"status");
  }
  assert.equal((await invoke(knownStatus,200,undefined,"status")).submission_state,"failed");
  const zeroUnknown=clone(knownStatus),zeroUsage=zeroUnknown.attempts[0].usage_revision;
  zeroUsage.components[0].quantity=0;zeroUsage.cost_status="unknown";
  zeroUnknown.attempts[0].settlement_state="unknown";delete zeroUsage.amount_decimal;
  assert.equal((await invoke(zeroUnknown,200,undefined,"status")).submission_state,"failed");
  for(const state of ["calculated","over_bound"]){
    const contradictory=clone(zeroUnknown),usage=contradictory.attempts[0].usage_revision;
    usage.cost_status=contradictory.attempts[0].settlement_state=state;
    usage.amount_decimal="0.000000000";
    await rejects(contradictory,200,undefined,"status");
  }
  const intent=clone(failed);intent.error={contract_version:"0.3",code:"INTENT_PERSIST_FAILED",
    correlation_id:"error.synthetic",retry_guidance:"query_first"};
  await assert.rejects(invoke(intent,503),cause=>{
    assert.equal(cause.code,"INTENT_PERSIST_FAILED");assert.equal(cause.attempt_id,intent.attempt_id);
    return true;});
  await assert.rejects(invoke({contract_version:"0.3",code:"WORK_VERSION_CONFLICT",
    correlation_id:"error.synthetic",retry_guidance:"never"},500),cause=>{
    assert.equal(cause.code,"INTERNAL_UNAVAILABLE");assert.equal(cause.retry_guidance,"query_first");
    return true;});
  for(const bySubmission of [true,false]){
    const selected=bySubmission?{submission_id:status.handle.submission_id}:
      {work_selector:Object.fromEntries(["task_id","step_id","step_revision","execution_generation"]
        .map(key=>[key,status.handle.work_key[key]]))};
    const foreign=clone(status);
    if(bySubmission)foreign.handle.submission_id="submission.foreign";
    else foreign.handle.work_key.step_id="step.foreign";
    let release;
    const gate=new Promise(resolve=>{release=resolve;});
    const client=new DurankiClient({baseUrl:"http://synthetic.invalid",token:"test-only-token",
      fetchImpl:async()=>{await gate;return new Response(Buffer.from(JSON.stringify(foreign)),
        {status:200,headers:{"Duranki-Contract-Version":"0.3"}});}});
    const pending=client.getSuccessorStatus(selected);
    if(bySubmission)selected.submission_id="submission.foreign";
    else selected.work_selector.step_id="step.foreign";
    release();
    await assert.rejects(pending,cause=>{assert.equal(cause.code,"INTERNAL_UNAVAILABLE");return true;});
  }
  process.stdout.write(JSON.stringify({status:"PASS",positive:6,negative:19,
    installed_package:!!process.env.DEV12_JS_CLIENT_DIR})+"\n");
}
main().catch(error=>{process.stderr.write(error.stack+"\n");process.exitCode=1;});
