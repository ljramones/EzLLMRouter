"use strict";
// Deterministic v2 schema construction from the immutable v1 grammar.
const fs=require("node:fs");
const path=require("node:path");
const source=JSON.parse(fs.readFileSync(path.join(__dirname,"../integration-readiness-v1/schema.json"),"utf8"));
const s=structuredClone(source), d=s.$defs, ref=name=>({$ref:"#/$defs/"+name});
const id=ref("id"), utc=ref("utc"), decimal=ref("decimal");
s.$id="urn:mach33:duranki:external-accounting:2";
s.title="Duranki external accounting integration v2";
for(const name of ["activity","attempt_started","decision","result"])
  d[name].properties.integration_version.const="2";
// The lightweight service/client validators apply these cross-field conditions.
d.operation_family={type:"string",enum:["generation","embedding","speech_input","speech_output",
  "search","realtime","rerank","other","unknown"]};
d.attempt_started.required=d.attempt_started.required.filter(x=>x!=="model_id");
Object.assign(d.attempt_started.properties,{
  operation_family_version:{const:"1"},operation_family:ref("operation_family"),
  model_identity_state:{enum:["known","not_applicable","unknown"]},
  logical_operation_id:id,attempt_role:{enum:["initial","retry","fallback","fanout","unknown"]},
  predecessor_attempt_id:id
});
d.attempt_started.required.push("operation_family_version","operation_family","model_identity_state",
  "logical_operation_id","attempt_role");
d.decision.required=d.decision.required.filter(x=>x!=="selected_model_id");
d.eligibility_evidence={type:"object",additionalProperties:false,required:["status"],properties:{
  status:{enum:["verified","stale","denied","bypassed","unavailable"]},eligibility_id:id
}};
d.decision.properties.eligibility_evidence=ref("eligibility_evidence");
d.decision.required.push("eligibility_evidence");
d.usage_v2={type:"object",additionalProperties:false,required:["integration_version","event_id",
  "dataset_id","kind","occurred_at","attempt_id","usage_revision","usage_state","cost_state"],
  properties:{integration_version:{const:"2"},event_id:id,dataset_id:id,kind:{const:"usage"},
    occurred_at:utc,attempt_id:id,usage_revision:{type:"integer",minimum:1,maximum:9007199254740991},
    usage_state:{enum:["known","unknown"]},cost_state:{enum:["known","unknown"]},
    native_units:{type:"array",minItems:1,maxItems:32,items:ref("native_unit")},
    usage_provenance:{enum:["provider_reported","derived","estimated","reconciled"]},
    currency:{type:"string",pattern:"^[A-Z]{3}$"},amount_decimal:decimal,
    cost_basis:{enum:["provider_reported","derived","estimated","reconciled"]},
    price_ref:id,price_version:id,zero_basis:id}
};
d.account_resolution={type:"object",additionalProperties:false,
  required:["integration_version","event_id","dataset_id","kind","occurred_at","attempt_id","resolved_account_id"],
  properties:{integration_version:{const:"2"},event_id:id,dataset_id:id,
    kind:{const:"account_resolution"},occurred_at:utc,attempt_id:id,resolved_account_id:id}};
d.lineage={type:"object",additionalProperties:false,
  required:["integration_version","event_id","dataset_id","kind","occurred_at","attempt_id",
    "logical_operation_id","attempt_role","predecessor_attempt_id"],
  properties:{integration_version:{const:"2"},event_id:id,dataset_id:id,kind:{const:"lineage"},
    occurred_at:utc,attempt_id:id,logical_operation_id:id,
    attempt_role:{enum:["retry","fallback","fanout"]},predecessor_attempt_id:id}};
d.feature_fields={type:"object",additionalProperties:false,properties:{
  task_category:id,operation_category:id,modalities:{type:"array",minItems:1,maxItems:8,
    uniqueItems:true,items:{enum:["text","image","audio","video","structured","other"]}},
  input_size:{type:"object",additionalProperties:false,
    required:["unit","quantity_decimal","provenance"],properties:{
      unit:{enum:["tokens","bytes","characters"]},quantity_decimal:decimal,
      provenance:{enum:["measured","estimated"]}}},
  requested_output_tokens:{type:"integer",minimum:0,maximum:9007199254740991},
  latency_budget_ms:{type:"integer",minimum:0,maximum:9007199254740991},
  required_capabilities:{type:"array",minItems:1,maxItems:16,uniqueItems:true,items:id},
  agent_version:id,policy_version:id,configuration_version:id
}};
d.selected_action={type:"object",additionalProperties:false,
  required:["selected_account_id","policy_version","eligibility_evidence"],
  properties:{selected_account_id:id,selected_model_id:id,policy_version:id,
    eligibility_evidence:ref("eligibility_evidence")}};
d.snapshot={type:"object",additionalProperties:false,
  required:["integration_version","snapshot_id","dataset_id","attempt_id","snapshot_kind",
    "status","schema_version","producer_version","provenance","source_at","available_at",
    "classification","retention_until"],
  properties:{integration_version:{const:"2"},snapshot_id:id,dataset_id:id,attempt_id:id,
    snapshot_kind:{enum:["feature","decision"]},status:{enum:["captured","not_collected","unavailable"]},
    schema_version:{const:"1"},producer_version:id,provenance:{enum:["platform","derived","synthetic"]},
    source_at:utc,available_at:utc,classification:{enum:["low","internal","confidential"]},
    source_expires_at:utc,retention_until:utc,features:ref("feature_fields"),
    selected_action:ref("selected_action")}};
// Compatible report/export projections added by the 0.2.1 correction. These
// describe response values; they do not add fields to immutable event bodies.
d.report_usage_state={enum:["known","unknown","not_observed","legacy_absent"]};
d.report_eligibility_assessment={enum:["verified","stale","denied","indeterminate",
  "binding_conflict","not_assessed","missing","legacy_absent"]};
d.report_snapshot_status={enum:["captured","not_collected","unavailable","expired",
  "missing","binding_conflict"]};
d.report_lineage_status={enum:["linked","pending_predecessor","not_collected",
  "binding_conflict","legacy_absent"]};
d.event.oneOf=[ref("activity"),ref("attempt_started"),ref("decision"),ref("result"),
  ref("usage_v2"),ref("account_resolution"),ref("lineage")];
const output=JSON.stringify(s,null,2)+"\n";
for(const target of [
  path.join(__dirname,"schema.json"),
  path.join(__dirname,"../../../server/src/duranki_server/integration_schema_v2.json"),
  path.join(__dirname,"../../../clients/js/integration_schema_v2.json"),
  path.join(__dirname,"../../../clients/python/src/duranki_client/integration_schema_v2.json")])
  fs.writeFileSync(target,output);
