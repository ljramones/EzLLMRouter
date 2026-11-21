"use strict";
const {runScript}=require("../../tools/javascript_vm_coverage.cjs");
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const root=path.resolve(__dirname,"../..");
class Element{
  constructor(tag,text){this.tag=tag;this.text=text;this.children=[];this.value="";this.dataset={};this.style={};this.selectedIndex=0;this.classList={add(){}};}
  append(...items){this.children.push(...items);}
  replaceChildren(...items){this.children=[...items];}
  addEventListener(name,callback){this[name]=callback;}
  setAttribute(){}
  toggleAttribute(){}
  get options(){return this.children.filter(x=>x.tag==="option");}
  focus(){this.focused=true;}
  reportValidity(){return true;}
  querySelector(selector){
    const found=[...this.walk()].find(x=>x.tag===selector.split("[")[0]&&x.name===selector.match(/name=([^\]]+)/)?.[1]);
    return found||null;
  }
  *walk(){yield this;for(const child of this.children){if(child instanceof Element)yield* child.walk();}}
}
const elements={"view-content":new Element("section"),"view-title":new Element("h1"),"view-message":new Element("p"),
  refresh:new Element("button"),logout:new Element("button")};
const model={configuration_ref:"cfg.demo",display_name:"Local synthetic fixture",kind:"synthetic_fixture",status:"enabled",
  revision:1,destination:{model:"model.demo"},current_price:null};
const principal={principal_id:"owner.local",display_name:"Larry Mitchell",kind:"human",status:"active",role:"registry_admin",
  credential_state:"local_operator",owner:"owner.local",revision:1,grant_summary:[]};
const models=[model],principals=[principal],grants=[];const operations=[];let inference=0;
const api=async(route,options)=>{
  if(route==="/operator/v1/models")return {items:models};
  if(route==="/operator/v1/principals")return {items:principals};
  if(route.startsWith("/operator/v1/models/"))return {model:models.find(x=>x.configuration_ref===decodeURIComponent(route.split("/").at(-1))),readiness:"not_connected",grants:[],history:[],prices:[]};
  if(route.startsWith("/operator/v1/principals/"))return {principal:principals.find(x=>x.principal_id===decodeURIComponent(route.split("/").at(-1))),grants,history:[]};
  if(route==="/operator/v1/registry"){
    const {action,subject,data}=options.body;operations.push(action);
    if(action==="register_catalogue")models.push({configuration_ref:subject,display_name:data.display_name,kind:"real_catalogue",
      status:"catalogued",revision:1,owner:data.owner,catalogue:{...data,price_reference:{...data.price,basis:"operator-entered reference",verified_on:null},
        published_api_model_id:data.api_model_id,observed_serving_version:data.model_version,provider_published_limits:{},notes:[data.notes]},
      source_links:[],reference_price_history:[]});
    if(action==="create_principal")principals.push({principal_id:subject,display_name:data.display_name,kind:data.kind,
      status:"inactive",role:data.role,owner:data.owner,credential_state:"unbound",revision:1,grant_summary:[],record_origin:"operator_entered"});
    if(action==="archive_model")models.find(x=>x.configuration_ref===subject).status="archived";
    if(action==="principal_state")principals.find(x=>x.principal_id===subject).status=data.status;
    if(action==="edit_catalogue_model"){const x=models.find(x=>x.configuration_ref===subject);x.display_name=data.display_name;x.catalogue.notes=[data.notes];x.revision++;}
    if(action==="edit_principal"){const x=principals.find(x=>x.principal_id===subject);x.display_name=data.display_name;x.revision++;}
    if(action==="correct_reference_price"){const x=models.find(x=>x.configuration_ref===subject);x.reference_price_history.push({price:x.catalogue.price_reference});x.catalogue.price_reference={...data,snapshot_id:"operator.corrected.test",basis:"operator-entered reference",verified_on:null};x.revision++;}
    if(action==="set_grant"){const old=grants.find(x=>x.configuration_ref===data.configuration_ref);
      if(old){Object.assign(old,data);old.revision++;}else grants.push({...data,revision:1});}
    return {record:{}};
  }
  if(route.startsWith("/operator/v1/access/explain?"))return {allowed:false,reason:"GRANT_MISSING",authority_revision:1};
  throw Error("unexpected route "+route);
};
const context=vm.createContext({Node:Element,window:{confirm:()=>true,addEventListener(){}},document:{querySelectorAll:()=>[]},
  $:id=>elements[id]||null,node:(tag,text)=>new Element(tag,text),clean:x=>x.replaceChildren(),
  panel:title=>{const x=new Element("section");x.append(new Element("h2",title));return x;},
  table:(headers,rows)=>{const x=new Element("table");x.rows=rows;for(const row of rows)for(const cell of row)if(cell instanceof Element)x.append(cell);return x;},badge:value=>new Element("span",value),
  definition:rows=>{const x=new Element("dl");x.rows=rows;return x;},
  actionButton:(label,callback)=>{const x=new Element("button",label);x.onclick=callback;return x;},
  entryForm:()=>new Element("form"),registryChange:async(action,subject,expected_revision,data)=>api("/operator/v1/registry",{body:{action,subject,expected_revision,data}}),
  api,message:()=>{},notify:()=>{},viewUi:{generation:0},state:{role:"registry_admin",view:"models",modelSearch:"",userSearch:""},
  models:null,users:null,render:async()=>{elements["view-content"].replaceChildren();await context[context.state.view]();},
  crypto:{randomUUID:()=>"operation.test."+operations.length},navigator:{clipboard:{writeText:async()=>{}}},URLSearchParams,
  listValue:value=>value.split(",").map(x=>x.trim()).filter(Boolean)});
runScript(fs.readFileSync(path.join(root,"web/catalogue_view.js"),"utf8"),context,{filename:path.join(root,"web/catalogue_view.js")});
runScript(fs.readFileSync(path.join(root,"web/crud_view.js"),"utf8"),context,{filename:path.join(root,"web/crud_view.js")});
const rootView=elements["view-content"];
const find=(text)=>[...rootView.walk()].find(x=>x.tag==="button"&&x.text===text);
const form=()=>[...rootView.walk()].find(x=>x.tag==="form");
async function submit(values){const f=form();assert(f,"form exists");for(const [name,value] of Object.entries(values)){const input=[...f.walk()].find(x=>x.name===name);assert(input,name);input.value=value;input.oninput?.();}await f.onsubmit({preventDefault(){}});}
(async()=>{
  await context.models();assert(find("Add model"),"add remains visible with fixtures hidden");
  find("Add model").onclick();assert(form(),"model form opens");assert([...form().walk()].some(x=>x.focused),"first field focused");
  await submit({local_key:"disposable",display_name:"Disposable model",vendor:"Test vendor",family:"Test family",
    api_model_id:"model.test",model_version:"v1",owner:"owner.local",notes:"Disposable test",
    snapshot_id:"test.v1",source_title:"Operator test",source_url:"https://example.org/test",
    band_0_label:"Test",band_0_input:"1",band_0_output:"2"});
  assert.equal(models.at(-1).status,"catalogued");assert(find("Add model"));
  find("Edit").onclick();await submit({display_name:"Edited disposable model"});assert.equal(models.at(-1).display_name,"Edited disposable model");
  find("Correct recorded price data").onclick();await submit({source_title:"Revised test source",source_url:"https://example.org/revised",
    band_0_input:"3",band_0_output:"4"});
  assert.equal(models.at(-1).catalogue.price_reference.snapshot_id,"operator.corrected.test");
  assert.equal(models.at(-1).reference_price_history[0].price.snapshot_id,"test.v1");
  find("Edit EzLLMRouter settings").onclick();const draft=form().querySelector("input[name=display_name]");draft.value="Discarded edit";draft.oninput();
  find("Cancel").onclick();await new Promise(resolve=>setImmediate(resolve));assert.equal(models.at(-1).display_name,"Edited disposable model");
  context.state.view="models";rootView.replaceChildren();await context.models();
  find("Delete…").onclick();await new Promise(resolve=>setImmediate(resolve));assert.equal(models.at(-1).status,"archived");
  context.state.view="users";rootView.replaceChildren();await context.users();assert(find("Add user / service"),"add user visible with fixtures hidden");
  find("Add user / service").onclick();await submit({principal_id:"user.disposable",display_name:"Disposable user",kind:"human",owner:"owner.local",role:"ordinary"});
  assert.equal(principals.at(-1).status,"inactive");assert(find("Manage model access"));
  find("Manage model access").onclick();await new Promise(resolve=>setImmediate(resolve));
  await submit({configuration_ref:"cfg.demo",status:"active",purposes:"execution",task_classes:"class.demo"});
  assert.equal(grants[0].status,"active");
  context.state.view="users";rootView.replaceChildren();await context.users();
  find("Manage model access").onclick();await new Promise(resolve=>setImmediate(resolve));
  await submit({status:"removed"});assert.equal(grants[0].status,"removed");
  context.state.view="users";rootView.replaceChildren();await context.users();
  [...rootView.walk()].filter(x=>x.tag==="button"&&x.text==="Delete…").at(-1).onclick();
  await new Promise(resolve=>setImmediate(resolve));assert.equal(principals.at(-1).status,"revoked");
  assert.deepEqual(operations,["register_catalogue","edit_catalogue_model","correct_reference_price","archive_model",
    "create_principal","set_grant","set_grant","principal_state"]);
  context.state.role="read_only_operator";context.state.view="models";rootView.replaceChildren();await context.models();
  assert(!find("Add model"));assert(!find("Delete…"));
  context.state.view="users";rootView.replaceChildren();await context.users();
  assert(!find("Add user / service"));assert(!find("Manage model access"));
  assert.equal(inference,0);console.log("CRUD screen controls, form focus, create/edit/archive and zero inference passed");
})().catch(error=>{console.error(error);process.exitCode=1;});
