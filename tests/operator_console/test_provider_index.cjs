"use strict";
const {runScript}=require("../../tools/javascript_vm_coverage.cjs");
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const root=path.resolve(__dirname,"../.."),calls=[],view={children:[],append(...items){this.children.push(...items);}},
  title={textContent:""};
function element(tag,value){return {tag,value,children:[],append(...items){this.children.push(...items);}};}
const connection={connection_id:"conn.controlled",provider_id:"openai",provider_name:"OpenAI",
  display_name:"Controlled setup",settings:{location:"commercial"}};
const context=vm.createContext({state:{role:"registry_admin",view:"source_providers"},
  $:id=>id==="view-title"?title:view,node:element,panel:label=>element("panel",label),
  table:(headers,rows)=>element("table",{headers,rows}),
  crudActions:(...items)=>{const result=element("actions");result.append(...items);return result;},
  crudButton:label=>element("button",label),namedButton:label=>element("button",label),
  providerAccessStatus:(_connection,observations)=>({label:observations[0].state==="observed"?
    "API access verified":"Needs attention"}),
  api:async route=>{calls.push(route);
    if(route==="/operator/v1/connections")return {items:[connection]};
    if(route==="/operator/v1/connections/conn.controlled")return {observations:[{state:"observed"}]};
    if(route==="/operator/v1/models")return {items:[{kind:"real_catalogue",catalogue:{vendor:"Anthropic"}}]};
    throw Error(route);}});
runScript(fs.readFileSync(path.join(root,"web/source_pages.js"),"utf8"),context,{filename:path.join(root,"web/source_pages.js")});
(async()=>{
  const previousZone=process.env.TZ;
  try{
    process.env.TZ="UTC";
    assert.equal(context.sourceExpiry("2030-01-02T03:04"),"2030-01-02T03:04:00.000Z");
    for(const value of ["bad","2030-02-30T03:04"])
      assert.throws(()=>context.sourceExpiry(value),/not a valid local time/);
    process.env.TZ="America/Toronto";
    assert.throws(()=>context.sourceExpiry("2030-03-10T02:30"),/daylight-saving gap/);
    assert.throws(()=>context.sourceExpiry("2030-11-03T01:30"),/ambiguous/);
    assert.equal(context.sourceExpiry("2030-11-03T03:30"),"2030-11-03T08:30:00.000Z");
  }finally{if(previousZone===undefined)delete process.env.TZ;else process.env.TZ=previousZone;}
  await context.sourceIndex();
  assert.equal(title.textContent,"External Providers");
  assert.equal(view.children[1].children[0].value,"Add provider");
  const inventory=view.children.find(item=>item.tag==="panel").children[0].value;
  assert.deepEqual([...inventory.headers],["Provider","API setups","API access"]);
  assert.match(inventory.rows.find(row=>row[0].value==="OpenAI")[2],/Controlled setup: API access verified/);
  assert.match(inventory.rows.find(row=>row[0].value==="Anthropic")[2],/Not set up · reference catalogue only/);
  assert.deepEqual(calls,["/operator/v1/connections","/operator/v1/connections/conn.controlled",
    "/operator/v1/models"]);
  console.log("DEV-09 provider index access states and read-only requests passed");
})().catch(error=>{console.error(error);process.exitCode=1;});
