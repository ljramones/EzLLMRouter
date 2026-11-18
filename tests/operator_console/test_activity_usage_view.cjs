"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const root=path.resolve(__dirname,"../.."),view={children:[],append(...parts){this.children.push(...parts);}};
function element(tag,value,cls){return {tag,value,cls,children:[],append(...parts){this.children.push(...parts);},get childNodes(){return this.children;}};}
const usage={attempts:2,intents_persisted:2,final_requests_committed:2,dispatched:2,
  transmission_started_observed:1,no_first_write_observed:1,write_observation_unknown:0,
  usage_available:1,usage_unknown:1,cost:{known_subtotals:{USD:"0.1"},unknown_attempts:1},truncated:false,
  by_step:[{step_id:"step.dev07-20261021-01.model-queued",principal_ids:["fixture.alpha"],
    configuration_refs:["cfg.demo"],attempts:1,intents_persisted:1,final_requests_committed:1,
    transmission_started_observed:0,no_first_write_observed:1,write_observation_unknown:0,
    input_tokens_known:0,input_unknown:1,output_tokens_known:0,output_unknown:1}]};
const context=vm.createContext({activityRows:null,activity:null,usage:null,
  state:{usagePrincipal:null,activityPrincipal:null,filter:"",page:1},node:element,append:(parent,...children)=>{parent.append(...children);return parent;},$:()=>view,api:async route=>{
    if(route==="/operator/v1/usage")return usage;
    if(route.startsWith("/operator/v1/activity?"))return {page:1,limit:20,total:1,items:[{
      step_id:"step.dev07-20261021-01.model-queued",submission_id:"submission."+"a".repeat(32),
      principal_id:"fixture.alpha",configuration_ref:"cfg.demo",submission_state:"failed_before_transmit",
      updated_at:"2026-10-21T00:00:00Z"}]};
    if(route==="/operator/v1/models")return {items:[{configuration_ref:"cfg.demo",display_name:"Local demo",kind:"synthetic_fixture"}]};
    if(route==="/operator/v1/principals")return {items:[{principal_id:"fixture.alpha",display_name:"Alpha fixture"}]};
    throw Error(route);
  },card:(label,value)=>element("card",{label,value}),panel:label=>element("panel",label),
  table:(headers,rows)=>element("table",{headers,rows}),badge:value=>element("badge",value),
  detail:()=>{},URLSearchParams});
vm.runInContext(fs.readFileSync(path.join(root,"web/activity_usage_view.js"),"utf8"),context);
const row=context.activityRows([{step_id:"step.dev07-20261021-01.model-queued",
  submission_id:"submission."+"a".repeat(32),principal_id:"fixture.alpha",configuration_ref:"cfg.demo",
  submission_state:"failed_before_transmit",updated_at:"2026-10-21T00:00:00Z"}],
  context.viewLabels([{configuration_ref:"cfg.demo",display_name:"Local demo",kind:"synthetic_fixture"}],
    [{principal_id:"fixture.alpha",display_name:"Alpha fixture"}]))[0];
assert.equal(row.length,5);
assert.equal(row[0].children[0].value,"Synthetic Model Queued");
assert.match(row[1].children[0].value,/Alpha fixture · Synthetic fixture/);
assert.match(row[2].children[0].value,/Local demo · Synthetic fixture/);
assert.equal(row[0].children[1].title,"submission."+"a".repeat(32));
const providerRow=context.activityRows([{step_id:"step.provider.validation.1234",
  submission_id:"submission.provider.test",principal_id:"svc.demo",
  configuration_ref:"cfg.provider.test",submission_state:"completed",
  updated_at:"2026-10-21T00:00:00Z"}],
  context.viewLabels([{configuration_ref:"cfg.provider.test",display_name:"Selected model",
    kind:"provider_deployment"}],[{principal_id:"svc.demo",display_name:"Test service"}]))[0];
assert.equal(providerRow[0].children[0].value,"Provider validation");
assert.equal(providerRow[1].children[0].value,"Test service");
assert.match(providerRow[2].children[0].value,/Selected model · Provider deployment/);
(async()=>{
  await context.usage();
  const cards=view.children.find(item=>item.cls==="cards");
  assert(cards.children.some(item=>item.value.label==="Final requests committed"&&item.value.value===2));
  assert(cards.children.some(item=>item.value.label==="First write observed"&&item.value.value===1));
  const table=view.children.find(item=>item.tag==="panel"&&item.value==="Usage by operation").children[0];
  assert.equal(table.value.rows[0][0].children[0].value,"Synthetic Model Queued");
  assert.match(table.value.rows[0][4].value,/0 observed · 1 no write/);
  view.children=[];
  await context.activity();
  const activityTable=view.children.find(item=>item.tag==="table");
  assert.equal(activityTable.value.headers[0],"Operation");
  assert.equal(activityTable.value.rows[0][0].children[0].value,"Synthetic Model Queued");
  assert.equal(activityTable.value.rows[0][0].children[1].title,"submission."+"a".repeat(32));
  console.log("activity/usage names, exact ID access and distinct receipt/first-write display passed");
})().catch(error=>{console.error(error);process.exitCode=1;});
