"use strict";
// Offline checks of the real actor + unchanged SDK bytes with fake fetch only.
// Usage: node this-file.cjs ACTOR_CJS SDK_CJS REQUEST_JSON
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
if (process.argv.length !== 5) throw Error("usage: node test.cjs ACTOR_CJS SDK_CJS REQUEST_JSON");
const [actorPath, sdkPath, requestPath] = process.argv.slice(2).map(p => path.resolve(p));
const code = fs.readFileSync(actorPath, "utf8");
const sdk = require(sdkPath);
const base = JSON.parse(fs.readFileSync(requestPath, "utf8"));
const copy = x => structuredClone(x);
const hash = p => crypto.createHash("sha256").update(fs.readFileSync(p)).digest("hex");
const tests = [
  ...["first", "after_tool", "after_destination", "after_guard"].map(mode => ({name: "delivered_"+mode, mode})),
  {name:"pending_first_poll", mode:"first", pending: true, waiting:0},
  {name:"pending_multiple_polls", mode:"first", pending:true, waiting:2},
  {name:"malformed_candidate_no_false_success", mode:"first", failure:"model", error:"INTERNAL_UNAVAILABLE"},
  {name:"malformed_json_no_false_success", mode:"first", failure:"json", error:"TRANSPORT_OUTCOME_UNKNOWN"},
  {name:"receiver_unavailable_no_submit", mode:"first", failure:"receiver", error:"receiver unavailable"},
];
function values(work) {
  const attemptId="attempt.stub", sid="submission.stub", observed="2030-01-01T00:00:00Z";
  const usage={state:"available", revision:{attempt_id:attemptId, revision:1,
    usage_observation:"partial", normalized_usage:{input_uncached:{state:"known",count:5},
      input_cache_read:{state:"unknown"}, input_cache_write:{state:"unknown"},
      output_text:{state:"known",count:2},output_reasoning:{state:"unknown"},
      other_billable:[{component:"unclassified",unit:"units",knowledge:{state:"unknown"}}]},
    usage_semantics_version:"synthetic.text.v1",price_version:"synthetic.unpriced.v1",
    cost:{currency:"USD",status:"unknown"},recorded_at:observed}};
  const handle={submission_id:sid,work_key:{principal_id:"svc.demo",task_id:work.task_id,
    step_id:work.step_id,step_revision:work.step_revision,execution_generation:work.execution_generation}};
  const candidate={candidate_id:"candidate.stub",attempt_id:attemptId,
    execution_generation:work.execution_generation,
    served_destination:{configuration_ref:"cfg.demo",service:"litellm.dev04",endpoint:"127.0.0.1",
      model:"model.demo",model_version:"v1",processing_region:"dev.local"},
    output_blocks:[{block_id:"block.output.1",kind:"assistant_text",text:"Hello.",
      source_labels:{lineage_ids:["src.output"],sensitivity:"internal",restrictions:[]}}],
    finish_reason:"stop",structural_status:"pass",observed_at:observed,usage};
  const reply={contract_version:"0.2",state:"delivered",handle,candidate};
  const pending={contract_version:"0.2",state:"pending",handle,pending_result_policy:"pollable_if_retained"};
  const status={contract_version:"0.2",handle,status_revision:4,submission_state:"completed",
    attempts:[{attempt_id:attemptId,execution_generation:work.execution_generation,attempt_revision:3,
      dispatch_state:"response_observed",delivery_state:"candidate_delivered",cancel_state:"none",
      settlement_state:"provisional",generation_state:"current",usage}],
    candidate_access:"present",candidate,updated_at:observed};
  const waiting=copy(status); delete waiting.candidate;
  waiting.submission_state="admitted";waiting.candidate_access="not_yet_available";
  waiting.attempts[0].delivery_state="none";waiting.attempts[0].usage={state:"not_recorded"};
  return {reply,pending,status,waiting};
}
function response(value,status=200,badJSON=false) {
  return new Response(badJSON ? "{invalid JSON" : JSON.stringify(value),
    {status,headers:{"EzLLMRouter-Contract-Version":"0.2"}});
}
async function run(test) {
  const out=[],err=[],calls=[];let arrivalCount=0, getCount=0, fixture;
  const fakeFetch=async (url,options={})=>{
    calls.push({url,method:options.method||"GET"});
    if(url==="http://receiver.test/observations")
      return test.failure==="receiver"?response({},503):response({arrivals:Array(arrivalCount).fill({})});
    if(url==="http://ezllmrouter.test/v1/submissions"&&options.method==="POST") {
      arrivalCount++;fixture=values(JSON.parse(options.body));
      if(test.failure==="model") fixture.reply.candidate.served_destination.model="openai/model.demo";
      return response(test.pending?fixture.pending:fixture.reply,test.pending?202:200,test.failure==="json");
    }
    if(url==="http://ezllmrouter.test/v1/submissions/submission.stub"&&options.method==="GET") {
      getCount++;return response(test.pending&&getCount<=test.waiting?fixture.waiting:fixture.status);
    }
    throw Error("unexpected fake transport request: "+url);
  };
  const localProcess={argv:[process.execPath,actorPath,test.mode],exitCode:0,
    env:{EZLLMROUTER_SERVICE_URL:"http://ezllmrouter.test",EZLLMROUTER_RECEIVER_URL:"http://receiver.test",
         EZLLMROUTER_DEV_TOKEN:"synthetic-unit-token"}};
  const sandbox={__dirname:path.dirname(actorPath),process:localProcess,fetch:fakeFetch,structuredClone,
    setTimeout:fn=>{queueMicrotask(fn);return 0;},
    console:{log:(...v)=>out.push(v.map(String).join(" ")),
             error:(...v)=>err.push(v.map(String).join(" "))},
    require:name=>{
      if(name==="@cognitivedynamics/ezllmrouter-client") return sdk;
      if(name==="node:fs") return {readFileSync:(p)=>{
        assert.equal(p,path.dirname(actorPath)+"/request.json");return JSON.stringify(base);}};
      throw Error("unexpected actor require: "+name);
    }};
  await new vm.Script(code,{filename:actorPath}).runInNewContext(sandbox,{timeout:5000});
  let assertionError=null;
  try {
    if(test.error) {
      assert.equal(localProcess.exitCode,1);assert.equal(out.length,0,"failure must not emit success result");
      assert(err.join("\n").includes(test.error));
      assert.equal(arrivalCount,test.failure==="receiver"?0:1);
    } else {
      assert.equal(localProcess.exitCode,0,err.join("\n"));
      assert.equal(out.length,1,"stdout must contain exactly one actor result, not diagnostics");
      const result=JSON.parse(out.join("\n"));
      assert.equal(result.actor,"installed-js");assert.equal(result.mode,test.mode);
      assert.equal(result.submission_id,"submission.stub");assert.equal(result.receiver_delta,1);
      const diagnostics=err.map(line=>JSON.parse(line));
      assert.equal(diagnostics.length,1+getCount);
      assert(diagnostics.every(d=>d.diagnostic==="ezllmrouter_http_response_shape"));
      assert.equal(arrivalCount,1);assert.equal(calls.filter(c=>c.method==="POST").length,1);
    }
  } catch(error) {assertionError=String(error);}
  return {name:test.name,passed:assertionError===null,error:assertionError,
    actor_exit:localProcess.exitCode,stdout_records:out.length,stderr_records:err.length,
    simulated_provider_sends:arrivalCount,real_network_calls:0,stdout:out.join("\n")+(out.length?"\n":""),
    stderr:err.join("\n")+(err.length?"\n":"")};
}
(async()=>{
  const results=[];for(const test of tests)results.push(await run(test));
  const failed=results.filter(r=>!r.passed).length;
  console.log(JSON.stringify({scope:"actual actor and unchanged SDK with fake fetch; no service/provider or Docker execution",
    node:process.version,actor_sha256:hash(actorPath),sdk_sha256:hash(sdkPath),
    passed:results.length-failed,failed,total:results.length,results},null,2));
  if(failed)process.exitCode=1;
})().catch(e=>{console.error(e);process.exitCode=1;});
