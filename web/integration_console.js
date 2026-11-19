"use strict";
// The integration-only console reads stored data. Provider metadata calls and policy changes require explicit clicks.
const integrationUi={drafts:new Map(),add:false,addProvider:"openai",addName:"",setupDirty:false,
  demoReturnParams:null};
const integrationViews=new Set(["connections","local_connectors","accounting","diagnostics","users"]);
function integrationRoute(){
  const raw=window.location.hash.startsWith("#/")?window.location.hash.slice(2):"connections";
  const [path,query=""]=raw.split("?",2),parts=path.split("/");
  const view=integrationViews.has(parts[0])?parts[0]:"connections";
  let item=null;try{item=parts[1]?decodeURIComponent(parts[1]):null;}catch{}
  return {view,item,params:new URLSearchParams(query)};
}
function integrationHash(view,item=null,params=null){
  const query=new URLSearchParams(params||integrationRoute().params);
  const path="#/"+view+(item?"/"+encodeURIComponent(item):"");
  return path+(query.size?"?"+query.toString():"");
}
function integrationDiscardSetup(){return confirmViewLeave();}

function integrationGo(view,item=null,params=null){
  let targetParams=params;
  if(view!=="accounting"&&integrationRoute().view==="accounting"&&
      integrationRoute().params.get("source")==="demo"){
    targetParams=new URLSearchParams(integrationUi.demoReturnParams||integrationRoute().params);
    for(const key of ["workflow_id","filter_workflow_id","from_date","to_date","person_id",
      "actor_id","provider_id","model_id"])targetParams.delete(key);
    if(targetParams.get("source")==="demo")targetParams.set("source","external");
  }
  const hash=integrationHash(view,item,targetParams);
  return sourceGo(hash);
}
function integrationFixture(item){return String(item.discovery?.reason||"").startsWith("controlled_fixture_");}
function integrationStatus(item){
  if(item.state==="disabled")return "Disabled";
  if(item.discovery?.state!=="observed"||item.discovery?.has_more)return "Needs attention";
  if(!(item.selected_models?.length||item.allowed_operations?.length))return "Awaiting selection";
  return "Connected";
}
function integrationProvider(id){return {anthropic:"Anthropic",openai:"OpenAI",xai:"xAI"}[id]||id;}
function integrationButton(label,fn,style="quiet"){
  const button=node("button",label,style);button.type="button";button.onclick=fn;return button;
}
function integrationFeedback(parent,label,error=false){
  const note=node("p",label,error?"connection-error":"connection-feedback");note.setAttribute("role","status");parent.append(note);return note;
}
async function integrationContext(){
  const listing=await api("/operator/v1/integration/datasets");
  const items=listing.items.slice().sort((a,b)=>String(b.activated_at||"").localeCompare(String(a.activated_at||"")));
  const requested=integrationRoute().params.get(integrationRoute().view==="connections"?"connection_dataset_id":"dataset_id");
  const dataset=items.find(item=>item.dataset_id===requested)||items[0]||null;
  return {items,dataset};
}
function integrationCollection(root,context){
  const scope=integrationRoute().view==="connections"?"Connection scope":"Accounting collection";
  const picker=node("div",undefined,"integration-collection"),label=node("label",scope),select=node("select");
  select.setAttribute("aria-label",scope);
  for(const [index,item] of context.items.entries()){
    const synthetic=/(^|[._-])synthetic([._-]|$)/.test(item.dataset_id+" "+item.environment_id);
    const purpose=/credentials/.test(item.dataset_id)?"Provider connections workspace":
      /dataset\.local\.real\.vega[.-]/.test(item.dataset_id)?"Local Vega real accounting":"Accounting workspace "+(index+1);
    const option=node("option",purpose+" · "+(synthetic?"Synthetic":"Real"));
    option.title=item.dataset_id;
    option.value=item.dataset_id;select.append(option);
  }
  select.value=context.dataset.dataset_id;
  select.onchange=()=>{
    const route=integrationRoute(),params=new URLSearchParams(route.params);
    params.set(route.view==="connections"?"connection_dataset_id":"dataset_id",select.value);
    integrationGo(route.view,null,params);
  };
  label.append(select);picker.append(label);root.append(picker);
}
async function integrationShell(){
  const root=$("view-content"),routeHash=window.location.hash,routeView=integrationRoute().view,
    context=await integrationContext();
  if(window.location.hash!==routeHash||integrationRoute().view!==routeView)return null;
  if(!context.dataset){root.append(node("p","No collection is registered in this profile.","empty"));return null;}
  integrationCollection(root,context);
  return {root,datasetId:context.dataset.dataset_id,dataset:context.dataset,datasets:context.items};
}
async function integrationConnections(){
  const shell=await integrationShell();if(!shell)return;
  const {root,datasetId}=shell,route=integrationRoute();
  if(state.principal!=="owner.local"||state.role!=="registry_admin"){
    root.append(node("p","Provider connection management is available to the local owner administrator.","empty"));return;
  }
  const listing=await api("/operator/v1/integration/connections?dataset_id="+encodeURIComponent(datasetId));
  const ordinary=listing.items.filter(item=>!integrationFixture(item));
  if(route.item){const item=listing.items.find(value=>value.account_id===route.item&&!integrationFixture(value));
    if(!item){root.append(node("p","Connection not found in this collection.","empty"));return;}
    integrationEditor(root,datasetId,item,"connections");return;}
  const heading=node("div",undefined,"integration-head");
  heading.append(node("p","Connect third-party cloud APIs here. Ollama and other self-hosted servers are on the Local Connectors page.","scope-note"),
    integrationButton("Add external provider",()=>{if(integrationUi.add){if(!integrationDiscardSetup())return;
      integrationUi.add=false;}else integrationUi.add=true;render();},"action"));root.append(heading);
  if(integrationUi.add)integrationAdd(root,datasetId);
  const box=panel("External provider connections");box.classList.add("connection-list");
  if(!ordinary.length)box.append(node("p","No ordinary provider connections in this collection.","empty"));
  for(const item of ordinary){
    const row=node("div",undefined,"connection-row"),copy=node("div",undefined,"connection-row-copy");
    copy.append(node("strong",item.friendly_name||integrationProvider(item.provider)),
      node("small",integrationProvider(item.provider)));
    const status=node("span",integrationStatus(item),"pill"+(integrationStatus(item)==="Needs attention"?" warn":""));
    const count=node("span",item.state==="pending"?"No saved models":
      (item.selected_models?.length||0)+" selected model"+((item.selected_models?.length||0)===1?"":"s"),"connection-count");
    row.append(copy,status,count,integrationButton(item.state==="pending"?"Review connection":"Manage",()=>
      integrationGo("connections",item.account_id)));box.append(row);
  }
  root.append(box);
  root.append(integrationButton("Test connections in Diagnostics →",()=>integrationGo("diagnostics")));
}
function integrationAdd(root,datasetId){
  const box=panel("Add external provider"),form=node("form",undefined,"connection-add");
  const providerLabel=node("label","Provider"),provider=node("select");
  for(const [id,name] of [["openai","OpenAI"],["anthropic","Anthropic"],["xai","xAI"]]){
    const option=node("option",name);option.value=id;provider.append(option);
  }
  provider.value=integrationUi.addProvider;provider.onchange=()=>{integrationUi.addProvider=provider.value;integrationUi.setupDirty=true;};
  providerLabel.append(provider);
  const keyLabel=node("label","API key"),key=node("input");key.type="password";key.required=true;key.autocomplete="new-password";
  key.oninput=()=>integrationUi.setupDirty=true;
  keyLabel.append(key);
  const nameLabel=node("label","Friendly name"),name=node("input");name.maxLength=120;name.value=integrationUi.addName;
  name.oninput=()=>{integrationUi.addName=name.value;integrationUi.setupDirty=true;};nameLabel.append(name);
  const feedback=integrationFeedback(form,"");
  const actions=node("div",undefined,"actions"),connect=integrationButton("Connect and discover models",null,"action");connect.type="submit";
  actions.append(connect,integrationButton("Cancel",()=>{if(!integrationDiscardSetup())return;
    integrationUi.add=false;integrationUi.addName="";integrationUi.setupDirty=false;render();}));
  form.append(providerLabel,keyLabel,nameLabel,actions,feedback);
  form.onsubmit=async event=>{event.preventDefault();connect.disabled=true;feedback.textContent="Checking provider model list…";
    try{const item=await api("/operator/v1/integration/connections",{method:"POST",csrf:true,
      body:{dataset_id:datasetId,provider:provider.value,api_key:key.value,friendly_name:name.value,
        operation_id:"op."+crypto.randomUUID()}});
      key.value="";integrationUi.add=false;integrationUi.addName="";integrationUi.setupDirty=false;
      integrationGo("connections",item.account_id);
    }catch(error){if(error.staleView)return;key.value="";feedback.textContent="Connection check failed: "+error.message;
      feedback.className="connection-error";connect.disabled=false;}};
  box.append(form);root.append(box);
}
function integrationReason(item){
  if(item.discovery?.reason==="credential_rejected")return "The provider rejected the credential. Try a different key.";
  if(item.provider==="xai"&&item.discovery?.reason==="provider_rejected_request")
    return "xAI rejected the model-list request. Check that this key can access its inference model list; this response does not prove the key is invalid.";
  if(item.discovery?.has_more)return "The model list is incomplete. Refresh it before saving choices.";
  return "The model list is unavailable. Retry discovery or try a different key.";
}
function integrationKeyForm(item,datasetId){
  const form=node("form",undefined,"connection-replace"),label=node("label","New API key"),key=node("input");
  key.type="password";key.required=true;key.autocomplete="new-password";label.append(key);
  const save=integrationButton("Validate and save",null,"action");save.type="submit";
  const cancel=integrationButton("Cancel",()=>{key.value="";form.hidden=true;});
  const feedback=integrationFeedback(form,"");
  form.append(label,save,cancel,feedback);form.hidden=true;
  const open=integrationButton("Change API key",()=>{form.hidden=false;key.focus();});
  form.onsubmit=async event=>{event.preventDefault();save.disabled=true;feedback.textContent="Checking provider model list…";
    try{const reply=await api("/operator/v1/integration/connections/"+encodeURIComponent(item.account_id)+"/replace",
      {method:"POST",csrf:true,body:{dataset_id:datasetId,expected_revision:item.revision,api_key:key.value}});
      key.value="";
      if(reply.replacement){feedback.textContent="Replacement not saved. "+integrationReason({provider:item.provider,discovery:reply.replacement});
        feedback.className="connection-error";save.disabled=false;return;}
      const draft=integrationUi.drafts.get(item.account_id);
      if(draft&&draft.dirty)draft.revision=reply.revision;
      await render();
    }catch(error){if(error.staleView)return;key.value="";feedback.textContent="Key change failed: "+error.message;
      feedback.className="connection-error";save.disabled=false;}};
  return [open,form];
}
function integrationEditor(root,datasetId,item,section){
  const back=integrationButton("← "+(section==="diagnostics"?"Test connections":"External Providers"),()=>integrationGo(section));
  root.append(back);
  const box=panel(item.friendly_name+" · "+integrationProvider(item.provider));box.classList.add("connection-editor");
  const status=node("p",integrationStatus(item),"connection-state");box.append(status);
  const feedback=integrationFeedback(box,"");
  const technical=node("details",undefined,"connection-technical");technical.append(node("summary","Technical details"),
    definition([["Account ID",item.account_id],["Credential reference",item.credential_ref],
      ["Credential version",item.selected_version||"Pending"],["Policy revision",item.policy_revision],
      ["Record revision",item.revision],["Discovery state",item.discovery?.state],
      ["Discovery reason",item.discovery?.reason],["Last checked",item.discovery?.checked_at||"Never"],
      ["Discovered model IDs",(item.discovery?.models||[]).join(", ")||"None"]]));
  if(item.state==="pending"&&item.discovery?.state!=="observed"){
    box.append(node("p",integrationReason(item),"connection-error"));
    const actions=node("div",undefined,"actions");
    actions.append(integrationButton("Retry model discovery",async()=>{
      feedback.textContent="Checking provider model list…";
      try{await api("/operator/v1/integration/connections/"+encodeURIComponent(item.account_id)+"/refresh",
        {method:"POST",csrf:true,body:{dataset_id:datasetId,expected_revision:item.revision}});
        render();}catch(error){if(error.staleView)return;feedback.textContent="Retry failed: "+error.message;feedback.className="connection-error";}
    }));
    const [changeKey,keyForm]=integrationKeyForm(item,datasetId);
    actions.append(changeKey);
    box.append(actions,keyForm,technical);
    root.append(box);return;
  }
  const saved=new Set(item.selected_models||[]),available=new Set(item.discovery?.models||[]);
  let draft=integrationUi.drafts.get(item.account_id);
  if(!draft||draft.revision!==item.revision){draft=draft?.dirty?{...draft,revision:item.revision}:{revision:item.revision,models:new Set(saved),
    operations:new Set(item.allowed_operations||[]),dirty:false};integrationUi.drafts.set(item.account_id,draft);}
  if(item.state==="disabled")box.append(node("p","This connection is disabled. The current service has no enable action.","scope-note"));
  const controls=node("div",undefined,"connection-editor-controls"),count=node("strong",""),search=node("input");
  search.type="search";search.placeholder="Search models";search.setAttribute("aria-label","Search discovered models");
  controls.append(count,search);box.append(controls);
  const picker=node("div",undefined,"connection-models");box.append(picker);
  const models=item.discovery?.details?.length?item.discovery.details:(item.discovery?.models||[]).map(id=>({id,name:id}));
  function draw(){count.textContent=draft.models.size+" selected · "+saved.size+" saved";
    picker.replaceChildren();const needle=search.value.toLowerCase();
    for(const id of [...draft.models].filter(value=>!available.has(value))){
      const label=node("label",undefined,"connection-choice"),input=node("input");input.type="checkbox";input.checked=true;
      input.onchange=()=>{input.checked?draft.models.add(id):draft.models.delete(id);draft.dirty=true;draw();};
      label.append(input,node("span",id+" · unavailable in latest discovery; remove to save a changed policy"));picker.append(label);
    }
    for(const model of models.filter(row=>(row.id+" "+row.name).toLowerCase().includes(needle))){
      const label=node("label",undefined,"connection-choice"),input=node("input");input.type="checkbox";
      input.checked=draft.models.has(model.id);input.onchange=()=>{input.checked?draft.models.add(model.id):draft.models.delete(model.id);
        draft.dirty=true;draw();};
      const copy=node("span",undefined,"connection-choice-copy");copy.append(node("strong",model.name||model.id));
      if(model.id!==model.name)copy.append(node("small",model.id));label.append(input,copy);picker.append(label);
    }
    if(!picker.childNodes.length)picker.append(node("p",search.value?"No models match this search.":
      "No models were discovered. Refresh models to retry.","empty"));
  }
  search.oninput=draw;draw();
  if(item.discovery?.state!=="observed"||item.discovery?.has_more)box.append(node("p",integrationReason(item),"connection-error"));
  const speech=node("details",undefined,"connection-settings");speech.append(node("summary","Speech permissions"));
  for(const [op,title] of [["speech_input","Speech input"],["speech_output","Speech output"]]){
    if(item.provider!=="xai"&&!draft.operations.has(op))continue;
    const label=node("label",undefined,"connection-choice"),input=node("input");input.type="checkbox";
    input.checked=draft.operations.has(op);input.onchange=()=>{input.checked?draft.operations.add(op):draft.operations.delete(op);draft.dirty=true;};
    label.append(input,node("span",title+(item.provider==="xai"?" · permission only; execution separately qualified":
      " · saved permission; no qualified runtime route here")));speech.append(label);
  }
  box.append(speech);
  const actions=node("div",undefined,"actions"),save=integrationButton("Save model choices",async()=>{
    save.disabled=true;feedback.textContent="Saving…";
    try{const result=await api("/operator/v1/integration/connections/"+encodeURIComponent(item.account_id)+"/save",
      {method:"POST",csrf:true,body:{dataset_id:datasetId,expected_revision:item.revision,
        selected_models:[...draft.models],allowed_operations:[...draft.operations]}});
      integrationUi.drafts.delete(item.account_id);feedback.textContent="Saved "+result.selected_models.length+" model choices.";
      integrationGo(section);notify("Saved "+result.selected_models.length+" model choices.");
    }catch(error){if(error.staleView)return;feedback.textContent="Save failed: "+error.message+". Your choices remain here.";
      feedback.className="connection-error";save.disabled=false;}} ,"action");
  save.disabled=item.state==="disabled"||item.discovery?.state!=="observed"||item.discovery?.has_more;
  actions.append(save,integrationButton("Cancel",()=>{
    if(draft.dirty&&!window.confirm("Discard unsaved connection choices?"))return;
    integrationUi.drafts.delete(item.account_id);integrationGo(section);
  }));box.append(actions);
  const settings=node("details",undefined,"connection-settings");settings.append(node("summary","Connection settings"));
  settings.append(node("p","Saved keys cannot be viewed. Friendly-name editing and re-enabling are unavailable in this service.","scope-note"));
  settings.append(integrationButton("Refresh models",async()=>{
    feedback.textContent="Refreshing provider model list…";
    try{const updated=await api("/operator/v1/integration/connections/"+encodeURIComponent(item.account_id)+"/refresh",
      {method:"POST",csrf:true,body:{dataset_id:datasetId,expected_revision:item.revision}});
      draft.revision=updated.revision;draft.dirty=true;render();
    }catch(error){if(error.staleView)return;feedback.textContent="Refresh failed: "+error.message;feedback.className="connection-error";}
  }));
  if(item.state==="connected"){
    const [changeKey,keyForm]=integrationKeyForm(item,datasetId);
    settings.append(changeKey,keyForm,integrationButton("Disable connection",async()=>{
      if(!window.confirm("Disable this connection for new sends?"))return;
      try{await api("/operator/v1/integration/connections/"+encodeURIComponent(item.account_id)+"/disable",
        {method:"POST",csrf:true,body:{dataset_id:datasetId,expected_revision:item.revision}});
        integrationUi.drafts.delete(item.account_id);render();}
      catch(error){if(error.staleView)return;feedback.textContent="Disable failed: "+error.message;feedback.className="connection-error";}
    }));
  }
  box.append(settings,technical);root.append(box);
}
function integrationReportQuery(route,datasetId,extra={}){
  const query=new URLSearchParams({dataset_id:datasetId});
  for(const key of ["actor_id","provider_account_id","model_id","initiating_user_id",
    "task_id","root_run_id","run_id","from","to"]){
    const value=route.params.get(key);if(value)query.set(key,value);
  }
  for(const [key,value] of Object.entries(extra))query.set(key,value);
  return query;
}
async function integrationDownload(path,name){
  const response=await fetch(path,{credentials:"same-origin",cache:"no-store",redirect:"error"});
  if(!response.ok)throw Error("Export unavailable ("+response.status+")");
  const url=URL.createObjectURL(await response.blob()),anchor=node("a");
  anchor.href=url;anchor.download=name;document.body.append(anchor);anchor.click();anchor.remove();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function integrationMoney(values){return Object.entries(values||{}).map(([currency,value])=>currency+" "+value).join(" · ")||"No known amount";}
async function integrationDiagnostics(){
  const shell=await integrationShell();if(!shell)return;
  const {root,datasetId,dataset}=shell,route=integrationRoute();
  if(state.lastDiagnostic){const failure=panel("Last view-load failure");
    failure.append(definition([["When · UTC",state.lastDiagnostic.at],["View",state.lastDiagnostic.view],
      ["Request path",state.lastDiagnostic.path],["HTTP status",state.lastDiagnostic.status],
      ["Service code",state.lastDiagnostic.code]]));root.append(failure);}
  const collection=panel("Collection and service scope");collection.append(definition([
    ["Dataset",datasetId],["Environment",dataset.environment_id],["Activated",dataset.activated_at],
    ["Operator profile","Integration-only local service"],
    ["Vega adoption","Not exposed by this operator API; inspect Vega's authenticated diagnostics"],
    ["Pending telemetry","Not exposed by this operator API; inspect Vega's authenticated diagnostics"]]));root.append(collection);
  if(state.principal!=="owner.local")return;
  const listing=await api("/operator/v1/integration/connections?dataset_id="+encodeURIComponent(datasetId));
  const fixtures=listing.items.filter(integrationFixture);
  if(route.item){const item=fixtures.find(value=>value.account_id===route.item);
    if(item)integrationEditor(root,datasetId,item,"diagnostics");return;}
  const box=panel("Test connections");box.append(node("p","Controlled fixtures are separate from ordinary owner registrations.","scope-note"));
  if(!fixtures.length)box.append(node("p","No controlled test connections in this collection.","empty"));
  for(const item of fixtures){const row=node("div",undefined,"connection-row"),name=node("div",undefined,"connection-row-copy");
    name.append(node("strong",item.friendly_name),node("small","Test fixture · "+integrationProvider(item.provider)));
    row.append(name,node("span",integrationStatus(item),"pill"),
      integrationButton("Inspect test fixture",()=>integrationGo("diagnostics",item.account_id)));box.append(row);}
  root.append(box);
  const pending=listing.items.filter(item=>!integrationFixture(item)&&item.state==="pending");
  if(pending.length){const attention=panel("Ordinary connections needing attention");
    for(const item of pending)attention.append(node("p",item.friendly_name+" · "+integrationReason(item)));
    root.append(attention);}
}
window.addEventListener("beforeunload",event=>{
  if(integrationUi.setupDirty||[...integrationUi.drafts.values()].some(draft=>draft.dirty)){
    event.preventDefault();event.returnValue="";}
});
