"use strict";
// Installed npm artifact only. Synthetic observations; never invokes a provider.
const assert=require("node:assert/strict");
const fs=require("node:fs");
const [base,tokenFile,packageRoot,mode="seed"]=process.argv.slice(2);
const {IntegrationClient}=require(packageRoot);
const token=fs.readFileSync(tokenFile,"utf8").trim();
const dataset="dataset.integration.correction.v2", account="account:correct:01";
const root={integration_version:"2",dataset_id:dataset};
async function main(){
  const client=new IntegrationClient(base,token,{version:"2"});
  if(mode==="verify"){
    const receipt=await client.recoverReceipt(dataset,"event.TimeZ");
    assert.equal(receipt.kind,"attempt_started");
    const snapshot=await client.snapshot(dataset,"feature.base");
    assert.equal(snapshot.status,"captured");
    assert.equal(snapshot.features.task_category,"briefing");
    console.log(JSON.stringify({mode,result:"PASS",receipt:receipt.event_id,snapshot:snapshot.status}));
    return;
  }
  const eligibility=await client.eligibility(dataset,account,"model.synthetic");
  assert.equal(eligibility.usable,true);
  const start={...root,event_id:"event.TimeZ",kind:"attempt_started",
    occurred_at:"2099-01-01T00:00:10Z",attempt_id:"attempt.base",started_at:"2099-01-01T00:00:10Z",
    task_id:"task.synthetic",step_id:"step.synthetic",run_id:"run.synthetic",root_run_id:"run.synthetic",
    actor_kind:"agent",actor_id:"agent.synthetic",provider_account_id:account,
    model_id:"model.synthetic",model_identity_state:"known",context_ref:"feature.base",
    operation_family_version:"1",operation_family:"generation",logical_operation_id:"logical.synthetic",
    attempt_role:"initial"};
  const receipt=await client.submitObservation(start);
  assert.equal(receipt.membership_at_receipt,"included");
  assert.deepEqual(await client.submitObservation(start),receipt);
  assert.deepEqual(await client.recoverReceipt(dataset,start.event_id),receipt);
  let invalid=false;
  try{await client.submitObservation({...start,event_id:"event.invalid.date",started_at:"2099-02-30T00:00:10Z"});}
  catch(error){invalid=error instanceof TypeError;}
  assert.equal(invalid,true);
  const feature={...root,snapshot_id:"feature.base",attempt_id:"attempt.base",snapshot_kind:"feature",
    status:"captured",schema_version:"1",producer_version:"producer.synthetic.1",provenance:"synthetic",
    source_at:"2099-01-01T00:00:01Z",available_at:"2099-01-01T00:00:02Z",
    classification:"low",retention_until:"2099-12-31T00:00:00Z",
    source_expires_at:"2099-12-31T00:00:00Z",
    features:{task_category:"briefing",modalities:["text"],input_size:{unit:"tokens",
      quantity_decimal:"10",provenance:"measured"}}};
  const saved=await client.submitSnapshot(feature);
  assert.equal((await client.submitSnapshot(feature)).snapshot_digest,saved.snapshot_digest);
  const evidence={status:"verified",eligibility_id:eligibility.eligibility_id};
  const decision={...root,event_id:"event.decision.base",kind:"decision",occurred_at:"2099-01-01T00:00:09Z",
    attempt_id:"attempt.base",decision_ref:"decision.base",selected_account_id:account,
    selected_model_id:"model.synthetic",policy_version:"policy.synthetic",eligibility_evidence:evidence};
  await client.submitObservation(decision);
  const decisionSnapshot={...feature,snapshot_id:"decision.base",snapshot_kind:"decision",
    available_at:"2099-01-01T00:00:09Z",selected_action:{selected_account_id:account,
      selected_model_id:"model.synthetic",policy_version:"policy.synthetic",eligibility_evidence:evidence}};
  delete decisionSnapshot.features;
  await client.submitSnapshot(decisionSnapshot);
  const usage={...root,event_id:"event.usage.base.1",kind:"usage",occurred_at:"2099-01-01T00:00:20Z",
    attempt_id:"attempt.base",usage_revision:1,usage_state:"known",cost_state:"unknown",
    usage_provenance:"provider_reported",native_units:[{unit:"input_tokens",quantity_decimal:"10"}]};
  await client.submitObservation(usage);
  const storedFeature=await client.snapshot(dataset,"feature.base");
  assert.equal(storedFeature.status,"captured");
  assert.equal(storedFeature.features.task_category,feature.features.task_category);
  assert.equal(storedFeature.features.input_size.quantity_decimal,feature.features.input_size.quantity_decimal);
  console.log(JSON.stringify({mode,result:"PASS",id:receipt.event_id,eligibility_id:eligibility.eligibility_id,
    native_unit:usage.native_units[0].quantity_decimal,snapshot_digest:saved.snapshot_digest}));
}
main().catch(error=>{console.error(error.stack||error.message);process.exitCode=1;});
