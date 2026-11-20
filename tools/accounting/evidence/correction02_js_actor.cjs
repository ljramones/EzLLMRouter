"use strict";
// Installed npm artifact, synthetic local HTTP only.
const assert=require("node:assert/strict");
const fs=require("node:fs");
const [base,tokenFile,packageRoot,mode="seed"]=process.argv.slice(2);
const {IntegrationClient,IntegrationClientError}=require(packageRoot);
const token=fs.readFileSync(tokenFile,"utf8").trim();
const dataset="dataset.integration.c02", account="account:c02:01";
const addSeconds=(stamp,n)=>new Date(Date.parse(stamp)+n*1000).toISOString().replace(/\.000Z$/u,"Z");
const root={integration_version:"2",dataset_id:dataset};
async function main(){
  const client=new IntegrationClient(base,token,{version:"2"});
  if(mode==="verify"){
    const receipt=await client.recoverReceipt(dataset,"event.TimeZ");
    const snapshot=await client.snapshot(dataset,"feature.base");
    assert.equal(receipt.kind,"attempt_started");
    assert.equal(snapshot.status,"captured");
    assert.equal(snapshot.features.task_category,"briefing");
    console.log(JSON.stringify({mode,result:"PASS",receipt:receipt.event_id,snapshot:snapshot.status}));
    return;
  }
  const answer=await client.eligibility(dataset,account,"model.synthetic");
  assert.equal(answer.usable,true);
  const decisionAt=answer.evaluated_at, startAt=addSeconds(decisionAt,1);
  const start={...root,event_id:"event.TimeZ",kind:"attempt_started",occurred_at:startAt,
    attempt_id:"attempt.base",started_at:startAt,task_id:"task.synthetic",step_id:"step.synthetic",
    run_id:"run.synthetic",root_run_id:"run.synthetic",actor_kind:"agent",actor_id:"agent.synthetic",
    provider_account_id:account,model_id:"model.synthetic",model_identity_state:"known",
    context_ref:"feature.base",operation_family_version:"1",operation_family:"generation",
    logical_operation_id:"logical.synthetic",attempt_role:"initial"};
  const receipt=await client.submitObservation(start);
  assert.equal(receipt.membership_at_receipt,"included");
  assert.deepEqual(await client.submitObservation(start),receipt);
  assert.deepEqual(await client.recoverReceipt(dataset,start.event_id),receipt);
  const feature={...root,snapshot_id:"feature.base",attempt_id:"attempt.base",snapshot_kind:"feature",
    status:"captured",schema_version:"1",producer_version:"producer.synthetic.1",provenance:"synthetic",
    source_at:decisionAt,available_at:decisionAt,classification:"low",
    retention_until:addSeconds(decisionAt,86400*30),source_expires_at:addSeconds(decisionAt,86400*30),
    features:{task_category:"briefing",modalities:["text"],input_size:{unit:"tokens",
      quantity_decimal:"10",provenance:"measured"}}};
  await client.submitSnapshot(feature);
  const evidence={status:"verified",eligibility_id:answer.eligibility_id};
  const decision={...root,event_id:"event.decision.base",kind:"decision",occurred_at:decisionAt,
    attempt_id:"attempt.base",decision_ref:"decision.base",selected_account_id:account,
    selected_model_id:"model.synthetic",policy_version:"policy.synthetic",eligibility_evidence:evidence};
  await client.submitObservation(decision);
  const decisionSnapshot={...feature,snapshot_id:"decision.base",snapshot_kind:"decision",
    selected_action:{selected_account_id:account,selected_model_id:"model.synthetic",
      policy_version:"policy.synthetic",eligibility_evidence:evidence}};
  delete decisionSnapshot.features;
  await client.submitSnapshot(decisionSnapshot);
  const usage={...root,event_id:"event.usage.base.1",kind:"usage",occurred_at:addSeconds(startAt,2),
    attempt_id:"attempt.base",usage_revision:1,usage_state:"known",cost_state:"unknown",
    usage_provenance:"provider_reported",native_units:[{unit:"input_tokens",quantity_decimal:"10"}]};
  await client.submitObservation(usage);
  for(const bad of [
    {...start,event_id:"event.wrong.ref",attempt_id:"attempt.wrong",context_ref:"feature.base"},
    {...root,event_id:"event.explicit.lineage",kind:"lineage",occurred_at:addSeconds(startAt,3),
      attempt_id:"attempt.base",logical_operation_id:"logical.synthetic",attempt_role:"fallback",
      predecessor_attempt_id:"attempt.future"}]){
    let code=null;
    try{await client.submitObservation(bad);}catch(error){
      assert.ok(error instanceof IntegrationClientError);code=error.code;}
    assert.equal(code,"EVENT_CONFLICT");
  }
  console.log(JSON.stringify({mode,result:"PASS",answer_id:answer.eligibility_id,
    decision_at:decisionAt,start_at:startAt,receipt:receipt.event_id,
    rejected_wrong_snapshot:true,rejected_explicit_lineage:true}));
}
main().catch(error=>{console.error(error.stack||error.message);process.exitCode=1;});
