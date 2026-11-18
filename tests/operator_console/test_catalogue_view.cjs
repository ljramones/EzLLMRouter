"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname,"../..");
const seed = JSON.parse(fs.readFileSync(path.join(root,"docs/development/dev-07/DURANKI-REAL-MODEL-CATALOGUE-20261021.json")));
const sources = Object.fromEntries(seed.sources.map(source=>[source.id,source]));
const records = seed.models.map(entry=>({configuration_ref:"catalogue."+entry.catalogue_key,
  display_name:entry.display_name,kind:"real_catalogue",status:"catalogued",readiness:"not_connected",
  catalogue:entry,source_links:entry.source_refs.map(ref=>sources[ref])}));
const fixture = {configuration_ref:"cfg.demo",display_name:"Legacy synthetic demo",status:"enabled",
  readiness:"synthetic_http1_ready",destination:{model:"model.demo"},current_price:null};
function element(tag,text,className){return {tag,text,className,children:[],append(...children){this.children.push(...children);},replaceChildren(){this.children=[];},setAttribute(){},addEventListener(name,callback){this[name]=callback;}};}
const view = element("section"),title = element("h1"),message = element("p");
const api = async route => {
  if(route==="/operator/v1/models")return {items:[...records,fixture]};
  if(route==="/operator/v1/principals")return {items:[
    {principal_id:"owner.local",display_name:"Larry Mitchell",kind:"human",role:"registry_admin",status:"active",grant_summary:[]},
    {principal_id:"svc.demo",display_name:"Local demo service",kind:"service",role:"ordinary",status:"active",
      grant_summary:[{display_name:"Legacy synthetic demo",status:"active",readiness:"synthetic_http1_ready"}]}]};
  if(route.startsWith("/operator/v1/models/")){const model=records.find(m=>m.configuration_ref===route.split("/").at(-1));return {model,readiness:"not_connected",history:[],grants:[],prices:[]};}
  throw Error("unexpected API path "+route);
};
const context = vm.createContext({
  models:null,users:null,state:{role:"registry_admin",modelSearch:"",userSearch:"",view:"models"},
  node:element,$:id=>id==="view-content"?view:id==="view-title"?title:message,
  api,clean:box=>box.replaceChildren(),panel:heading=>{const box=element("section");box.append(element("h2",heading));return box;},
  table:(headers,rows)=>({tag:"table",headers,rows}),badge:value=>element("span",value),
  entryForm:()=>element("form"),actionButton:(label,callback)=>{const button=element("button",label);button.onclick=callback;return button;},
  definition:rows=>({tag:"dl",rows}),message:()=>{},registryChange:()=>{},listValue:()=>[],
  navigator:{clipboard:{writeText:async()=>{}}},URLSearchParams,crypto:{randomUUID:()=>"uuid"},
});
vm.runInContext(fs.readFileSync(path.join(root,"web/catalogue_view.js"),"utf8"),context);
function findTable(box){for(const item of box.children||[]){if(item.tag==="table")return item;const inner=findTable(item);if(inner)return inner;}return null;}
(async()=>{
  await context.models();
  let rows=findTable(view).rows;
  assert.equal(rows.length,12,"default list shows all 12 researched models");
  assert.equal(rows[0][0].children[0].text,"Claude Opus 5.5");
  assert.equal(rows[0][1],"Anthropic · Claude");
  assert.equal(rows[0][2],"$4");
  assert.equal(rows[0][3],"$20");
  assert.equal(rows[0][4],"$0.20");
  assert.equal(rows[0][6].text,"Catalogued · Not connected");
  assert(!rows.some(row=>row[0].children[0].text==="Legacy synthetic demo"));
  const modelToggle=view.children[0].children[1].children[0];
  modelToggle.checked=true;modelToggle.change();
  assert.equal(findTable(view).rows.length,13,"fixture toggle reveals synthetic configuration");
  view.replaceChildren();
  await context.users();
  rows=findTable(view).rows;
  assert.equal(rows.length,1,"test identities are separate by default");
  assert.equal(rows[0][0].children[0].text,"Larry Mitchell");
  const userToggle=view.children[0].children[1].children[0];
  userToggle.checked=true;userToggle.change();
  assert.equal(findTable(view).rows.length,2,"fixture toggle reveals test service");
  view.replaceChildren();
  await context.catalogueModelDetail("catalogue.anthropic.claude-haiku-5-5");
  rows=findTable(view).rows;
  assert.equal(rows.length,2,"Haiku boundary bands remain visible");
  assert.match(rows[0][4],/100,000/);
  assert.match(rows[1][4],/>100,000/);
  assert.equal(rows[0][1],"$0.10");
  assert.equal(rows[1][1],"$0.50");
  assert.equal(context.conditionText({prompt_tokens_lte:100000}),"Prompt ≤100,000 tokens");
  assert.equal(context.conditionText({prompt_tokens_gt:100000}),"Prompt >100,000 tokens");
  assert.equal(context.conditionText({input_tokens_lte:272000}),"Input ≤272,000 tokens");
  assert.equal(context.conditionText({input_tokens_gt:272000}),"Input >272,000 tokens");
  assert.match(context.conditionText({rate_period:"peak",weekday_intervals:["01:00–04:00"]}),/UTC weekdays/);
  assert.match(context.conditionText({publisher_date_through:"2026-11-30"}),/2026-11-30/);
  console.log("catalogue display: 12 real models, owner name, fixture separation and boundary conditions passed");
})().catch(error=>{console.error(error);process.exitCode=1;});
