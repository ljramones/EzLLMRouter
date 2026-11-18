"use strict";
// Administrator controls use the same authenticated registry endpoint as the original console.
const crudState={archivedModels:false,archivedUsers:false,dirty:false};
const crudAuditFacts=value=>value?Object.entries(value).map(([key,item])=>key.replaceAll("_"," ")+": "+item).join(" · "):"Earlier record · details not retained";
const crudIsFixtureUser=principal=>principal.record_origin!=="operator_entered"&&principal.principal_id!=="owner.local";
function crudButton(label,callback,style="quiet"){
  const button=node("button",label,style);button.type="button";button.onclick=callback;return button;
}
function crudActions(...buttons){const row=node("div",undefined,"actions");row.append(...buttons);return row;}
function crudRowActions(...buttons){const row=crudActions(...buttons);row.classList.add("crud-row-actions");return row;}
function crudDeletePrincipalButton(principal,impact,after,lastAdmin){
  const button=crudButton("Delete…",()=>crudRetire("principal",principal,impact,after));
  if(lastAdmin){button.disabled=true;button.title="The last active registry administrator cannot be deleted.";}
  return button;
}
function crudConfirmLeave(){return !crudState.dirty||window.confirm("Discard unsaved changes?");}
for(const button of [...document.querySelectorAll("#navigation button"),$("refresh"),$("logout")]){
  button.addEventListener("click",event=>{if(!crudConfirmLeave()){event.preventDefault();event.stopImmediatePropagation();}else crudState.dirty=false;},true);
}
window.addEventListener("beforeunload",event=>{if(crudState.dirty){event.preventDefault();event.returnValue="";}});
function crudForm(title,fields,save,onCancel,onSave){
  const box=panel(title),form=node("form",undefined,"registry-form"),controls={};
  for(const field of fields){
    const label=node("label",field.label),control=field.options||field.groups?node("select"):node(field.textarea?"textarea":"input");
    control.name=field.name;control.required=field.required!==false;
    if(field.options||field.groups){
      if(field.groups){for(const group of field.groups){const options=node("optgroup");options.label=group.label;
        for(const [value,name] of group.options){const item=node("option",name);item.value=value;options.append(item);}control.append(options);}}
      else for(const option of field.options){const [value,name]=Array.isArray(option)?option:[option,option];const item=node("option",name);item.value=value;control.append(item);}
      control.value=field.value??(field.groups?field.groups[0].options[0][0]:field.options[0][0]);}
    else{if(!field.textarea)control.type=field.type||"text";control.maxLength=field.maxLength||160;
      if(field.type==="checkbox")control.checked=field.value===true;else control.value=field.value??"";
      if(field.step)control.step=field.step;if(field.min!==undefined)control.min=field.min;}
    control.oninput=()=>{crudState.dirty=true;error.textContent="";};control.onchange=control.oninput;
    controls[field.name]=control;label.append(control);form.append(label);
  }
  const clearSecrets=()=>{for(const input of Object.values(controls))if(input.type==="password")input.value="";};
  const saveButton=crudButton(save,()=>{},"action"),cancel=crudButton("Cancel",()=>{if(crudConfirmLeave()){
    clearSecrets();crudState.dirty=false;onCancel();}});
  saveButton.type="submit";form.append(crudActions(saveButton,cancel));
  const error=node("p","","error");error.setAttribute("role","alert");form.append(error);
  let pending=null;
  form.onsubmit=async event=>{
    event.preventDefault();if(!form.reportValidity())return;
    const values=Object.fromEntries(Object.entries(controls).map(([key,input])=>
      [key,input.type==="checkbox"?input.checked:input.value.trim()]));
    const signature=JSON.stringify(values);
    if(!pending||pending.signature!==signature)pending={signature,id:crypto.randomUUID()};
    saveButton.disabled=true;cancel.disabled=true;error.textContent="";message("Saving registry change…");
    try{await onSave(values,pending.id);pending=null;crudState.dirty=false;message("Registry change committed.");await onCancel(true);}
    catch(exc){error.textContent=exc.message==="REGISTRY_CONFLICT"?"This record changed. Copy your edits and refresh before retrying.":"Change rejected: "+exc.message;message("Registry change was not confirmed.",true);}
    finally{clearSecrets();saveButton.disabled=false;cancel.disabled=false;}
  };
  box.append(form);return {box,first:Object.values(controls)[0]};
}
function crudOpen(form){clean($("view-content"));$("view-content").append(form.box);form.first.focus();}
async function crudMutation(action,subject,revision,data,operation){
  return api("/operator/v1/registry",{method:"POST",csrf:true,body:{operation_id:operation,action,subject,expected_revision:revision,data}});
}
async function crudRetire(kind,record,impact,after){
  const isModel=kind==="model",name=record.display_name,id=isModel?record.configuration_ref:record.principal_id;
  const effect=isModel?"It leaves the active catalogue and cannot be used for new grants or work.":"Its sessions, credential and grants cease authorizing access.";
  if(!window.confirm(`Delete ${name} (${id})? ${effect} ${impact} History remains retained. This cannot be undone.`))return;
  try{await registryChange(isModel?"archive_model":"principal_state",id,record.revision,
    isModel?{reason:"Administrator archive"}:{status:"revoked",reason:"Administrator deletion"});
    crudState.dirty=false;message("Deletion committed; history retained.");await after();}
  catch(error){message(error.message==="REGISTRY_CONFLICT"?"Record changed. Refresh before deleting.":"Deletion rejected: "+error.message,true);}
}
function crudPriceFields(price){
  const current=price?.bands||[{label:"Standard test reference",conditions:{},rates_usd_per_1000000_tokens:{input_uncached:"0",output:"0",input_cached:null}}];
  const fields=[{name:"snapshot_id",label:"New price snapshot ID",value:""},
    {name:"source_title",label:"Reference source title",value:""},
    {name:"source_url",label:"HTTPS source link",type:"url",value:""}];
  current.forEach((band,index)=>{const rates=band.rates_usd_per_1000000_tokens;
    fields.push({name:`band_${index}_label`,label:`Band ${index+1} label`,value:band.label},
      {name:`band_${index}_input`,label:`Band ${index+1} uncached input · USD / 1M`,value:rates.input_uncached??"",required:false},
      {name:`band_${index}_output`,label:`Band ${index+1} output · USD / 1M`,value:rates.output??"",required:false},
      {name:`band_${index}_cached`,label:`Band ${index+1} cached input · USD / 1M (blank = unknown)`,value:rates.input_cached??"",required:false},
      {name:`band_${index}_condition`,label:`Band ${index+1} condition / explanation`,value:band.conditions.definition||"",required:false});
    for(const [key,value] of Object.entries(rates).filter(([key])=>!["input_uncached","output","input_cached"].includes(key))){
      fields.push({name:`band_${index}_rate_${key}`,label:`Band ${index+1} ${key.replaceAll("_"," ")} · USD / 1M`,value:value??"",required:false});
    }
    for(const [key,value] of Object.entries(band.additional_rates||{})){
      fields.push({name:`band_${index}_extra_${key}`,label:`Band ${index+1} ${key.replaceAll("_"," ")}`,value:value??"",required:false});
    }
  });return {fields,current};
}
function crudPrice(values,current){return {snapshot_id:values.snapshot_id,source_title:values.source_title,source_url:values.source_url,
  bands:current.map((band,index)=>({...("calculation_basis" in band?{calculation_basis:band.calculation_basis}:{}),
    ...("additional_rates" in band?{additional_rates:Object.fromEntries(Object.keys(band.additional_rates).map(key=>[key,values[`band_${index}_extra_${key}`]||null]))}:{}),
    label:values[`band_${index}_label`],
    conditions:{...band.conditions,...(values[`band_${index}_condition`]?{definition:values[`band_${index}_condition`]}:{})},
    rates_usd_per_1000000_tokens:{...Object.fromEntries(Object.keys(band.rates_usd_per_1000000_tokens).filter(key=>!["input_uncached","output","input_cached"].includes(key)).map(key=>[key,values[`band_${index}_rate_${key}`]||null])),
      input_uncached:values[`band_${index}_input`]||null,
      output:values[`band_${index}_output`]||null,input_cached:values[`band_${index}_cached`]||null}}))};}
function crudCatalogueFields(record){const c=record?.catalogue;
  return [{name:"display_name",label:"Display name",value:record?.display_name||""},
    {name:"vendor",label:"Vendor",value:c?.vendor||""},{name:"family",label:"Family",value:c?.family||""},
    ...(!record?[{name:"api_model_id",label:"Exact published API model ID"},{name:"model_version",label:"Observed version or identifier"}]:[]),
    {name:"owner",label:"Responsible owner ID",value:record?.owner||"owner.local"},
    {name:"capabilities",label:"Descriptive capabilities (comma separated)",value:(c?.provider_published_capabilities||[]).join(","),required:false},
    {name:"context_window",label:"Advertised context tokens (blank = unknown)",type:"number",min:1,value:c?.provider_published_limits?.context_window_advertised??"",required:false},
    {name:"max_output",label:"Advertised maximum output tokens (blank = unknown)",type:"number",min:1,value:c?.provider_published_limits?.max_output_advertised??"",required:false},
    {name:"notes",label:"Operator note",value:c?.notes?.[0]||"Operator-entered reference"}];}
function crudCatalogueData(values){return {display_name:values.display_name,vendor:values.vendor,family:values.family,owner:values.owner,
  capabilities:listValue(values.capabilities),context_window:values.context_window?Number(values.context_window):null,
  max_output:values.max_output?Number(values.max_output):null,notes:values.notes};}
function crudModelForm(record=null,priceOnly=false){
  const price=crudPriceFields(priceOnly?record.catalogue.price_reference:null);
  const fields=priceOnly?price.fields.filter(field=>field.name!=="snapshot_id"):record?[
    {name:"display_name",label:"EzLLMRouter display name",value:record.display_name},
    {name:"notes",label:"Local operator note",value:record.catalogue.notes?.[0]||""}]:[
    {name:"local_key",label:"Unique local key (letters, numbers, dots or hyphens)"},...crudCatalogueFields(null),...price.fields];
  const title=priceOnly?"Correct recorded price data":record?"Edit EzLLMRouter settings":"Add disconnected catalogue model";
  const back=()=>record?catalogueModelDetail(record.configuration_ref):render();
  const form=crudForm(title,fields,"Save",back,async(v,operation)=>{
    if(priceOnly){const correction=crudPrice(v,price.current);delete correction.snapshot_id;
      await crudMutation("correct_reference_price",record.configuration_ref,record.revision,correction,operation);}
    else if(record)await crudMutation("edit_catalogue_model",record.configuration_ref,record.revision,
      {display_name:v.display_name,notes:v.notes},operation);
    else{
      const key=v.local_key.replace(/^catalogue\.operator\./,"");
      if(!/^[A-Za-z0-9._:-]{1,64}$/.test(key))throw Error("Use a valid unique local key.");
      const data={...crudCatalogueData(v),api_model_id:v.api_model_id,model_version:v.model_version,price:crudPrice(v,price.current)};
      await crudMutation("register_catalogue","catalogue.operator."+key,0,data,operation);
      state.modelSearch="";catalogueState.showTestModels=false;
    }
  });crudOpen(form);
}
function crudReferenceHistory(model){
  const snapshots=[...(model.reference_price_history||[]).map(item=>item.price),model.catalogue.price_reference],
    history=panel("Observed price history · published reference, not invoices"),tools=node("div",undefined,"catalogue-tools"),
    seriesLabel=node("label","Rate series"),series=node("select"),bandLabel=node("label","Rate band"),band=node("select"),
    chart=node("div",undefined,"price-history-chart"),exact=node("div");
  for(const [value,label] of [["input_uncached","Uncached input"],["output","Output"],["input_cached","Cached input"]]){
    const option=node("option",label);option.value=value;series.append(option);}
  const bands=[...new Set(snapshots.flatMap(item=>item.bands.map(b=>b.label)))];
  for(const name of bands){const option=node("option",name);option.value=name;band.append(option);}
  seriesLabel.append(series);bandLabel.append(band);tools.append(seriesLabel,bandLabel);history.append(tools,chart,exact);
  function draw(){clean(chart);clean(exact);const points=snapshots.map(item=>({item,
      rate:item.bands.find(b=>b.label===band.value)?.rates_usd_per_1000000_tokens[series.value]}));
    const present=points.filter(p=>p.rate!==null&&p.rate!==undefined),maximum=Math.max(0,...present.map(p=>Number(p.rate)));
    chart.setAttribute("role","img");chart.setAttribute("aria-label",`${series.options[series.selectedIndex].text} in ${band.value}, USD per one million tokens across ${snapshots.length} recorded observations`);
    for(const point of points){const row=node("div",undefined,"price-history-row"),label=node("span",point.item.verified_on||point.item.operator_recorded_at||"Date unknown"),bar=node("div",undefined,"price-history-track"),fill=node("span",undefined,"price-history-fill"),value=node("span",point.rate??"Gap · not measured");
      fill.style.width=point.rate==null?"0%":`${maximum?Math.max(2,100*Number(point.rate)/maximum):2}%`;
      bar.append(fill);row.append(label,bar,value);chart.append(row);}
    if(present.length<2)chart.append(node("p",present.length?"One observed price; no trend is established.":"No recorded values for this band and rate series.","scope-note"));
    exact.append(table(["Observed / recorded","Band","Input · USD / 1M","Output · USD / 1M","Cached input · USD / 1M","Snapshot"],
      snapshots.flatMap(item=>item.bands.map(b=>[item.verified_on||item.operator_recorded_at||"Date unknown",b.label,
        b.rates_usd_per_1000000_tokens.input_uncached??"Unknown",b.rates_usd_per_1000000_tokens.output??"Unknown",
        b.rates_usd_per_1000000_tokens.input_cached??"Unknown",item.snapshot_id]))));}
  series.onchange=draw;band.onchange=draw;draw();return history;
}
function crudPrincipalForm(record=null){
  const fields=record?[{name:"display_name",label:"Display name",value:record.display_name},
    {name:"owner",label:"Responsible / charging owner ID",value:record.owner}]:[
    {name:"principal_id",label:"Stable principal ID"},{name:"display_name",label:"Display name"},
    {name:"kind",label:"Identity kind",options:[["human","Person"],["service","Service"]]},
    {name:"owner",label:"Responsible / charging owner ID",value:"owner.local"},
    {name:"role",label:"Console role",options:[["ordinary","Ordinary (least privilege)"],["read_only_operator","Read-only operator"],["registry_admin","Registry administrator"]]}];
  const form=crudForm(record?"Edit user or service":"Add user / service",fields,"Save",()=>record?catalogueUserDetail(record.principal_id):render(),async(v,operation)=>{
    if(record)await crudMutation("edit_principal",record.principal_id,record.revision,{display_name:v.display_name,owner:v.owner},operation);
    else{await crudMutation("create_principal",v.principal_id,0,{display_name:v.display_name,kind:v.kind,owner:v.owner,role:v.role},operation);
      state.userSearch="";catalogueState.showTestUsers=false;}
  });
  if(!record){const kind=form.box.querySelector("select[name=kind]"),role=form.box.querySelector("select[name=role]");
    const changed=kind.onchange;kind.onchange=event=>{changed?.(event);const service=kind.value==="service";
      for(const option of role.options)if(option.value!=="ordinary")option.disabled=service;
      if(service)role.value="ordinary";};
  }
  crudOpen(form);
}
async function crudGrantForm(principal){
  const [modelsReply,detail]=await Promise.all([api("/operator/v1/models"),api("/operator/v1/principals/"+encodeURIComponent(principal.principal_id))]);
  const previous=new Set(detail.grants.map(g=>g.configuration_ref));
  const providerModels=modelsReply.items.filter(m=>m.kind==="provider_deployment"),sourceInfo=new Map();
  if(providerModels.length){const connections=(await api("/operator/v1/connections")).items;
    for(const connection of connections){const inventory=await api("/operator/v1/connections/"+encodeURIComponent(connection.connection_id)+"/inventory");
      for(const row of inventory.items)if(row.configuration_ref)sourceInfo.set(row.configuration_ref,{connection,row});}}
  const choices=modelsReply.items.filter(m=>{
    const source=sourceInfo.get(m.configuration_ref);
    return previous.has(m.configuration_ref)||(m.kind==="provider_deployment"&&source?.row.allowed&&
      source.connection.status==="active"&&m.status==="enabled")||
      (m.kind!=="provider_deployment"&&m.kind!=="real_catalogue"&&m.status==="enabled");});
  const groups=new Map(),eligible=new Set();
  for(const m of choices){const source=sourceInfo.get(m.configuration_ref);
    const usable=m.status==="enabled"&&(m.kind==="provider_deployment"?source?.row.allowed&&source.connection.status==="active":m.kind!=="real_catalogue");
    if(usable)eligible.add(m.configuration_ref);
    const group=source?sourceKind(source.connection)==="source_providers"?"Provider / "+source.connection.provider_name+" / "+source.connection.display_name+" ("+source.connection.connection_id+")":
      sourceKind(source.connection)==="source_private"?"Private Hosting / "+source.connection.display_name+" ("+source.connection.connection_id+")":
      "Office Lab / "+source.connection.settings.site+" / "+source.connection.display_name+" ("+source.connection.connection_id+")":
      m.kind==="provider_deployment"?"Historical blocked provider grants":m.kind==="real_catalogue"?"Historical reference grants":"Synthetic test fixtures";
    if(!groups.has(group))groups.set(group,[]);
    groups.get(group).push([m.configuration_ref,m.display_name+" · "+(usable?"permitted":"blocked; removal only")+" · "+m.configuration_ref]);}
  if(!choices.length){message("No source-permitted deployment is available for grants.",true);return;}
  const fields=[{name:"configuration_ref",label:"Source-permitted configuration",groups:[...groups].map(([label,options])=>({label,options}))},
    {name:"status",label:"Access state",options:[["active","Grant access"],["removed","Remove access"]]},
    {name:"purposes",label:"Permitted purposes (comma separated)",value:"execution"},
    {name:"task_classes",label:"Permitted task classes (comma separated)",value:"class.demo"}];
  const form=crudForm("Manage model access",fields,"Save grant",()=>catalogueUserDetail(principal.principal_id),async(v,operation)=>{
    const grant=detail.grants.find(g=>g.configuration_ref===v.configuration_ref);
    await crudMutation("set_grant",principal.principal_id,grant?.revision||0,{configuration_ref:v.configuration_ref,
      status:v.status,purposes:listValue(v.purposes),task_classes:listValue(v.task_classes)},operation);
  });
  const select=form.box.querySelector("select[name=configuration_ref]");
  if(select)select.onchange=()=>{const grant=detail.grants.find(g=>g.configuration_ref===select.value);
    const selected=choices.find(m=>m.configuration_ref===select.value),status=form.box.querySelector("select[name=status]");
    status.querySelector("option[value=active]")?.toggleAttribute("disabled",!eligible.has(select.value));
    if(grant){status.value=!eligible.has(select.value)?"removed":grant.status;
      form.box.querySelector("input[name=purposes]").value=grant.purposes.join(",");
      form.box.querySelector("input[name=task_classes]").value=grant.task_classes.join(",");}else status.value="active";};
  crudOpen(form);if(select)select.onchange();
}
models=async function crudModels(){
  const root=$("view-content"),all=(await api("/operator/v1/models")).items;
  const connections=state.role!=="ordinary"&&all.some(m=>m.kind==="provider_deployment")?
    (await api("/operator/v1/connections")).items:[],byConnection=new Map(connections.map(c=>[c.connection_id,c]));
  if(state.role==="registry_admin")root.append(crudActions(crudButton("Add model",()=>crudModelForm(),"action")));
  const tools=node("div",undefined,"catalogue-tools"),searchLabel=node("label","Search models, vendors or IDs"),search=node("input");
  search.type="search";search.value=state.modelSearch;searchLabel.append(search);
  tools.append(searchLabel,testToggle("Show test fixtures",all.filter(isTestModel).length,catalogueState.showTestModels,v=>{catalogueState.showTestModels=v;draw();}),
    testToggle("Show archived models",all.filter(m=>["archived","revoked"].includes(m.status)).length,crudState.archivedModels,v=>{crudState.archivedModels=v;draw();}));root.append(tools);
  const list=panel("All Models · cross-source reference");root.append(list);search.oninput=draw;
  function draw(){state.modelSearch=search.value;const needle=search.value.trim().toLowerCase();
    const found=all.filter(m=>(crudState.archivedModels||!["archived","revoked"].includes(m.status))&&
      (catalogueState.showTestModels||!isTestModel(m))&&[m.display_name,m.configuration_ref,m.catalogue?.vendor,m.catalogue?.family].join(" ").toLowerCase().includes(needle));
    clean(list);list.append(node("h2","All Models"),node("p","Secondary cross-source comparison. Reference catalogue records are research, not authenticated discovery. Source pages own connection permissions. Rates are USD per 1,000,000 tokens.","scope-note"));
    const rows=found.map(m=>{
      const rate=primaryRates(m),actions=crudRowActions(crudButton("View",()=>catalogueModelDetail(m.configuration_ref)));
      const source=byConnection.get(m.destination?.connection_id);
      if(source)actions.append(crudButton("Source",()=>sourceGo(sourceConnectionRoute(source))));
      if(state.role==="registry_admin"&&!["archived","revoked"].includes(m.status)){
        actions.append(crudButton("Edit",()=>m.catalogue?crudModelForm(m):catalogueModelDetail(m.configuration_ref)),
          crudButton("Delete…",()=>crudRetire("model",m,"Existing grants and prices remain recorded.",render)));
      }
      const condition=m.catalogue?m.catalogue.price_reference.bands[0].label+" · "+
        conditionText(m.catalogue.price_reference.bands[0].conditions)+" · "+
        (m.catalogue.price_reference.verified_on?"checked "+m.catalogue.price_reference.verified_on:"operator entered"):
        m.kind==="provider_deployment"?"Operator-approved schedule · actual cost remains unknown until full usage semantics":"Synthetic fixture price";
      const summary=node("span",condition,"truncate-two");summary.title=condition;
      return [namedButton(m.display_name,m.configuration_ref,()=>catalogueModelDetail(m.configuration_ref)),
        m.catalogue?m.catalogue.vendor+" · "+m.catalogue.family:
          m.kind==="provider_deployment"?"Provider deployment · "+m.destination.adapter_id:"Synthetic test fixture",
        rate?money(rate.input_uncached):m.current_price?money(m.current_price.rates.input_uncached):"Unknown",
        rate?money(rate.output):m.current_price?money(m.current_price.rates.output_text):"Unknown",
        summary,badge(m.catalogue?m.status+" · Not connected":
          m.kind==="provider_deployment"?"Provider · "+m.status:"Synthetic · "+m.status),actions];});
    if(found.length){const grid=table(["Model","Vendor / family","Input / 1M","Output / 1M","Condition / checked","State","Actions"],rows);grid.classList.add("crud-list-table");list.append(grid);}
    else list.append(node("p","No matching models. Add model remains available above.","empty"));
  }draw();
};
catalogueModelDetail=async function crudModelDetail(ref){
  const root=$("view-content");clean(root);$("view-title").textContent="Model & pricing detail";
  try{const data=await api("/operator/v1/models/"+encodeURIComponent(ref)),m=data.model,c=m.catalogue;
    const sourceReturn=state.view==="source_detail"?window.location.hash:null;
    root.append(crudButton(sourceReturn?"← Source models":"← Models & Pricing",()=>{
      if(sourceReturn)sourceGo(sourceReturn);else{state.view="models";sourceGo("#/models");}}));
    const provider=m.kind==="provider_deployment";
    const providerReady=!provider||(await api("/operator/v1/config")).capabilities.real_provider;
    const info=panel(m.display_name);info.append(definition([["State",m.status+(c?" · Not connected":provider?" · provider deployment":" · synthetic fixture")],["Stable reference",ref],["Revision",m.revision],["Owner",m.owner],
      ["Vendor / family",c?c.vendor+" · "+c.family:provider?m.destination.adapter_id:"Synthetic fixture"],["API model ID",c?.published_api_model_id||m.destination?.model],
      ["Version",c?.observed_serving_version||m.destination?.model_version],["Readiness",data.readiness]]));root.append(info);
    if(provider)root.append(crudActions(crudButton("View provider connection",()=>providerDetail(m.destination.connection_id))));
    const actions=crudActions(crudButton("History",()=>$("model-history").focus()));
    if(state.role==="registry_admin"&&!["archived","revoked"].includes(m.status)){
      actions.append(crudButton(c?"Edit EzLLMRouter settings":"Edit",()=>c?crudModelForm(m):crudSyntheticEdit(m)),
        crudButton(c?"Correct recorded price data":"Update prices",()=>c?crudModelForm(m,true):provider?crudProviderPrice(m):crudSyntheticPrice(m)),
        crudButton("Delete…",()=>crudRetire("model",m,`${data.grants.length} linked grants and ${data.history.length} audit events remain retained.`,()=>catalogueModelDetail(ref))));
      if(!c)for(const status of ["enabled","disabled"]){if(status!==m.status){const stateButton=crudButton(status==="enabled"?"Enable":"Disable",async()=>{
        if(!window.confirm(`Set ${m.display_name} to ${status}?`))return;
        try{await registryChange("model_state",ref,m.revision,{status,reason:"Administrator lifecycle change"});await catalogueModelDetail(ref);}catch(e){message(e.message,true);}});
        if(provider&&status==="enabled"&&!providerReady){stateButton.disabled=true;stateButton.title="Selected HTTPS worker and sender target validation is pending.";}
        actions.append(stateButton);}}
    }root.append(actions);
    if(c){const p=c.price_reference,prices=panel("Published reference prices · USD per 1,000,000 tokens");
      prices.append(node("p",p.basis==="operator-entered reference"?"Operator-entered reference; publisher verification not claimed.":"Publisher research reference; not an active billing schedule.","scope-note"));
      prices.append(table(["Band","Input","Output","Cached input","Conditions"],p.bands.map(b=>[b.label,money(b.rates_usd_per_1000000_tokens.input_uncached),money(b.rates_usd_per_1000000_tokens.output),money(b.rates_usd_per_1000000_tokens.input_cached),conditionText(b.conditions)])));
      for(const band of p.bands){
        const extras=Object.entries(band.rates_usd_per_1000000_tokens).filter(([key])=>!["input_uncached","output","input_cached"].includes(key));
        if(extras.length)prices.append(node("p",band.label+" additional token rates: "+extras.map(([key,value])=>key.replaceAll("_"," ")+" "+money(value)).join(" · ")+" USD / 1M.","scope-note"));
        if(band.additional_rates)prices.append(node("p",band.label+" additional units: "+Object.entries(band.additional_rates).map(([key,value])=>key.replaceAll("_"," ")+" "+money(value)).join(" · ")+".","scope-note"));
        if(band.calculation_basis)prices.append(node("p",band.label+" calculation: "+band.calculation_basis,"scope-note"));
      }
      prices.append(definition([["Snapshot",p.snapshot_id],["Verified on",p.verified_on||"Not publisher verified"],["Recorded",p.operator_recorded_at||"Original research seed"]]));root.append(prices);
      const sources=panel("Sources and notes"),sourceList=node("ul",undefined,"reference-source-list");
      for(const source of m.source_links||[]){const link=node("a",source.title+" · "+(source.checked_on?"checked "+source.checked_on:"operator entered"));link.href=source.url;link.target="_blank";link.rel="noopener noreferrer";
        const item=node("li");item.append(link);sourceList.append(item);}
      if(sourceList.children.length)sources.append(sourceList);
      for(const note of c.notes||[])sources.append(node("p",note));root.append(sources);
      const history=panel("Reference price history");for(const old of m.reference_price_history||[]){
        const detail=node("details"),summary=node("summary",old.price.snapshot_id+" · "+(old.price.verified_on?"checked "+old.price.verified_on:"operator entered"));detail.append(summary);
        detail.append(table(["Band","Input / 1M","Output / 1M","Cached / 1M","Conditions"],old.price.bands.map(b=>[
          b.label,money(b.rates_usd_per_1000000_tokens.input_uncached),money(b.rates_usd_per_1000000_tokens.output),money(b.rates_usd_per_1000000_tokens.input_cached),conditionText(b.conditions)])));
        for(const source of old.sources||[])detail.append(node("p",source.title+" · "+source.url,"scope-note"));history.append(detail);
      }
      if(!m.reference_price_history?.length)history.append(node("p","No replaced price snapshots.","empty"));root.append(history,crudReferenceHistory(m));
      const priceActions=crudActions();for(const source of m.source_links||[]){const link=node("a","View provider pricing · "+source.title,"quiet");link.href=source.url;link.target="_blank";link.rel="noopener noreferrer";priceActions.append(link);}
      priceActions.append(node("span","Price updates require checking the official source. Automated acquisition is not supported for this record.","scope-note"));root.append(priceActions);
      if(state.role!=="ordinary"){
        const connections=(await api("/operator/v1/connections")).items;
        const linked=[];
        for(const connection of connections){
          const detail=await api("/operator/v1/connections/"+encodeURIComponent(connection.connection_id));
          for(const deployment of detail.deployments)if(deployment.model_ref===ref)linked.push({connection,deployment});
        }
        const deploymentPanel=panel("Available through");deploymentPanel.append(linked.length?
          table(["Connection","Serving ID","Site","Execution state"],linked.map(({connection,deployment})=>[
            namedButton(connection.display_name,connection.connection_id,()=>providerDetail(connection.connection_id)),
            deployment.serving_id,deployment.site,deployment.execution_approved?"Approved":"Catalogued · Not approved"])):
          node("p","No provider deployment associated. Catalogue reference alone cannot execute.","empty"));
        root.append(deploymentPanel);
      }
    }else{const prices=panel(provider?"Approved schedule history · USD / 1M":"Synthetic price history");prices.append(data.prices.length?table(provider?
      ["Version","Ordinary input","Cached read","30-minute write","Total output","Contract","Source"]:
      ["Version","Input / 1M","Output / 1M","Source"],data.prices.map(p=>provider?
      [p.price_version,money(p.rates.input_uncached),p.rates.input_cache_read?money(p.rates.input_cache_read):"Unpriced",
       p.rates.input_cache_write_30m?money(p.rates.input_cache_write_30m):"Unpriced",money(p.rates.output_text),
       p.contract?.version||"Historical two-rate · ineligible for new paid test",p.source]:
      [p.price_version,money(p.rates.input_uncached),money(p.rates.output_text),p.source])):
      node("p",provider?"No approved price schedule. Configuration cannot be enabled.":"No published synthetic price.","empty"));root.append(prices);}
    const history=panel("Change history");history.id="model-history";history.tabIndex=-1;history.append(data.history.length?table(["Action","Actor","Time","Before","After"],data.history.map(h=>[h.action,h.actor,h.at,crudAuditFacts(h.before),crudAuditFacts(h.after)])):node("p","No changes recorded.","empty"));root.append(history);
  }catch(e){message("Model detail unavailable: "+e.message,true);}
};
function crudSyntheticEdit(m){const form=crudForm("Edit synthetic fixture label",[{name:"display_name",label:"Display name",value:m.display_name}],"Save",()=>catalogueModelDetail(m.configuration_ref),
  (v,id)=>crudMutation("edit_model",m.configuration_ref,m.revision,{display_name:v.display_name},id));crudOpen(form);}
function crudSyntheticPrice(m){const form=crudForm("Publish synthetic fixture price",[{name:"price_version",label:"New immutable price version"},
  {name:"input",label:"Uncached input · USD / 1M"},{name:"output",label:"Output · USD / 1M"}],"Publish",()=>catalogueModelDetail(m.configuration_ref),
  (v,id)=>crudMutation("publish_price",m.configuration_ref,m.revision,{price_version:v.price_version,currency:"USD",rates:{input_uncached:v.input,output_text:v.output},source:"synthetic fixture",usage_semantics_version:"synthetic.text.v1"},id));crudOpen(form);}
function crudProviderPrice(m){const form=crudForm("Approve provider rate schedule",[
  {name:"price_version",label:"New immutable price version"},
  {name:"input",label:"Ordinary input · USD / 1M"},
  {name:"read",label:"Cached read · USD / 1M"},
  {name:"write",label:"30-minute cache write · USD / 1M"},
  {name:"output",label:"All output including reasoning · USD / 1M"},
  {name:"input_ceiling",label:"Reviewed provider-enforced maximum input tokens",type:"number",min:1},
  {name:"output_ceiling",label:"Reviewed maximum output tokens (1–4096)",type:"number",min:1},
  {name:"price_source_url",label:"Exact model price and context source URL"},
  {name:"observed_on",label:"Source checked on (YYYY-MM-DD)"},
  {name:"acknowledge_settings",label:"I verified this exact model accepts temperature 0, implicit 30-minute caching, the stated context limit and single-tier rates",type:"checkbox",value:false}],"Publish",()=>catalogueModelDetail(m.configuration_ref),
  (v,id)=>crudMutation("publish_price",m.configuration_ref,m.revision,{price_version:v.price_version,
    currency:"USD",rates:{input_uncached:v.input,input_cache_read:v.read,
      input_cache_write_30m:v.write,output_text:v.output},
    source:"operator-approved provider schedule",usage_semantics_version:"openai.responses.text.cache.v2",
    contract:{version:"openai.responses.implicit-cache.v1",requested_model:m.destination.model,
      returned_models:[m.destination.model],cache_mode:"implicit_default_30m",
      input_token_ceiling:Number(v.input_ceiling),max_output_tokens:Number(v.output_ceiling),
      input_bound_basis:"provider_enforced_context_window",temperature_zero_supported:v.acknowledge_settings,
      price_conditions:"single_tier_no_modifiers",price_source_url:v.price_source_url,
      observed_on:v.observed_on}},id));
  form.box.insertBefore(node("p","Review the exact model's context limit, temperature 0 support, implicit cache lifetime and single-tier price conditions before publishing. A published rate is not an active allowance. Unsupported models remain unavailable for paid testing.","scope-note"),form.box.firstChild);
  crudOpen(form);}
users=async function crudUsers(){
  const root=$("view-content"),all=(await api("/operator/v1/principals")).items;
  const activeAdmins=all.filter(p=>p.role==="registry_admin"&&p.status==="active").length;
  if(state.role==="registry_admin")root.append(crudActions(crudButton("Add user / service",()=>crudPrincipalForm(),"action")));
  const tools=node("div",undefined,"catalogue-tools"),label=node("label","Search names or IDs"),search=node("input");search.type="search";search.value=state.userSearch;label.append(search);
  tools.append(label,testToggle("Show test fixtures",all.filter(crudIsFixtureUser).length,catalogueState.showTestUsers,v=>{catalogueState.showTestUsers=v;draw();}),
    testToggle("Show revoked identities",all.filter(p=>p.status==="revoked").length,crudState.archivedUsers,v=>{crudState.archivedUsers=v;draw();}));root.append(tools);
  const list=panel("People and services");root.append(list);search.oninput=draw;
  function draw(){state.userSearch=search.value;const needle=search.value.trim().toLowerCase();
    const found=all.filter(p=>(crudState.archivedUsers||p.status!=="revoked")&&(catalogueState.showTestUsers||!crudIsFixtureUser(p))&&
      [p.display_name,p.principal_id,p.kind,p.role].join(" ").toLowerCase().includes(needle));
    clean(list);list.append(node("h2","People and services"),node("p","Registration does not grant model access or bind a credential.","scope-note"));
    const rows=found.map(p=>{
      const grants=(p.grant_summary||[]).filter(g=>g.status==="active"),actions=crudRowActions(crudButton("View",()=>catalogueUserDetail(p.principal_id)));
      if(state.role==="registry_admin"&&p.status!=="revoked")actions.append(crudButton("Edit",()=>crudPrincipalForm(p)),
        crudButton("Manage model access",()=>crudGrantForm(p)),crudDeletePrincipalButton(p,
          `${grants.length} active grants remain recorded but unusable.`,render,
          p.role==="registry_admin"&&p.status==="active"&&activeAdmins===1));
      return [namedButton(p.display_name,p.principal_id,()=>catalogueUserDetail(p.principal_id)),(crudIsFixtureUser(p)?"Synthetic fixture · ":"")+p.kind+" · "+p.role,badge(p.status),
        grants.length?grants.map(g=>g.display_name).join(", "):"No active grants",actions];});
    if(found.length){const grid=table(["Name","Kind / role","Status","Model access","Actions"],rows);grid.classList.add("crud-list-table");list.append(grid);}
    else list.append(node("p","No matching identities. Add user / service remains available above.","empty"));
  }draw();
};
catalogueUserDetail=async function crudUserDetail(id){
  const root=$("view-content");clean(root);$("view-title").textContent="User & access detail";
  try{const data=await api("/operator/v1/principals/"+encodeURIComponent(id)),p=data.principal;
    root.append(crudButton("← Users & Access",()=>{state.view="users";render();}));
    const info=panel(p.display_name);info.append(definition([["Stable ID",p.principal_id],["Kind",p.kind],["Role",p.role],["Status",p.status],
      ["Credential",p.credential_state],["Owner",p.owner],["Revision",p.revision]]));root.append(info);
    const actions=crudActions(crudButton("History",()=>$("user-history").focus()));
    if(state.role==="registry_admin"&&p.status!=="revoked"){
      const all=(await api("/operator/v1/principals")).items;
      const lastAdmin=p.role==="registry_admin"&&p.status==="active"&&
        all.filter(item=>item.role==="registry_admin"&&item.status==="active").length===1;
      actions.append(crudButton("Edit",()=>crudPrincipalForm(p)),crudButton("Manage model access",()=>crudGrantForm(p)),
        crudDeletePrincipalButton(p,`${data.grants.length} grants remain recorded but unusable.`,()=>catalogueUserDetail(id),lastAdmin));
      if(p.kind==="human")actions.append(crudButton("Change role",()=>{const form=crudForm("Change console role",[{name:"role",label:"Role",options:["ordinary","read_only_operator","registry_admin"],value:p.role}],"Save",()=>catalogueUserDetail(id),
        (v,op)=>crudMutation("set_role",id,p.revision,{role:v.role},op));crudOpen(form);}));
      for(const status of ["active","suspended"]){if(status!==p.status)actions.append(crudButton(status==="active"?"Activate":"Suspend",async()=>{
        if(!window.confirm(`Set ${p.display_name} to ${status}?`))return;
        try{await registryChange("principal_state",id,p.revision,{status,reason:"Administrator lifecycle change"});await catalogueUserDetail(id);}catch(e){message(e.message,true);}}));}
      if(p.credential_state!=="local_operator")actions.append(crudButton("Provision one-time credential",async()=>{
        if(!window.confirm(`Generate a new one-time credential for ${p.display_name}? Existing binding will be replaced.`))return;
        try{const result=await api("/operator/v1/provision",{method:"POST",csrf:true,body:{operation_id:crypto.randomUUID(),principal_id:id,expected_revision:p.revision}});
          if(result.one_time_credential){const output=node("p","One-time credential (store privately): "+result.one_time_credential,"credential-once mono");output.tabIndex=-1;root.append(output);output.focus();}
        }catch(e){message("Provisioning failed: "+e.message,true);}}));
    }root.append(actions);
    const links=crudActions(crudButton("View activity",()=>{state.activityPrincipal=id;state.view="activity";render();}),
      crudButton("View usage",()=>{state.usagePrincipal=id;state.view="usage";render();}));root.append(links);
    const grants=panel("Explicit model access");
    if(data.grants.length){const models=(await api("/operator/v1/models")).items,
        byRef=new Map(models.map(m=>[m.configuration_ref,m]));
      const providerGrants=data.grants.some(g=>byRef.get(g.configuration_ref)?.kind==="provider_deployment");
      const connections=providerGrants&&state.role!=="ordinary"?(await api("/operator/v1/connections")).items:[],
        byConnection=new Map(connections.map(c=>[c.connection_id,c])),grouped=new Map();
      for(const grant of data.grants){const model=byRef.get(grant.configuration_ref),
          connection=byConnection.get(model?.destination?.connection_id);
        const source=connection?sourceKind(connection)==="source_providers"?"Provider / "+connection.provider_name+" / "+connection.display_name:
          sourceKind(connection)==="source_private"?"Private Hosting / "+connection.display_name:
          "Office Lab / "+connection.settings.site+" / "+connection.display_name:
          model?.kind==="provider_deployment"?"Provider deployment · source unavailable":"Synthetic or historical configuration";
        const explain=await api("/operator/v1/access/explain?"+new URLSearchParams({principal_id:id,
          configuration_ref:grant.configuration_ref,purpose:"execution",task_class:"class.demo"}));
        const rows=grouped.get(source)||[];rows.push([namedButton(grant.display_name||model?.display_name||grant.configuration_ref,
          grant.configuration_ref,()=>catalogueModelDetail(grant.configuration_ref)),grant.status,
          explain.allowed?"Allowed":explain.reason.replaceAll("_"," "),
          grant.purposes.join(", ")+" · "+grant.task_classes.join(", "),grant.revision]);grouped.set(source,rows);}
      for(const [source,rows] of grouped){grants.append(node("h3",source),table(["Model / exact ID","Grant","Current eligibility","Scope","Revision"],rows));}
      grants.append(node("p","Recorded grants remain visible when a source is disallowed or a connection is disabled. Removing a grant preserves history.","scope-note"));
    }else grants.append(node("p","No model grants.","empty"));root.append(grants);
    const explain=entryForm("Explain access (read only)",[{name:"configuration_ref",label:"Configuration reference",value:data.grants[0]?.configuration_ref||"cfg.demo"},
      {name:"purpose",label:"Purpose",value:"execution"},{name:"task_class",label:"Task class",value:"class.demo"}],"Explain",async v=>{
      const result=await api("/operator/v1/access/explain?"+new URLSearchParams({principal_id:id,...v}));message((result.allowed?"Allowed":"Denied")+": "+result.reason+" · authority revision "+result.authority_revision);return false;});root.append(explain);
    const history=panel("Registry history");history.id="user-history";history.tabIndex=-1;history.append(data.history.length?table(["Action","Actor","Time","Revision"],data.history.map(h=>[h.action,h.actor,h.at,h.new_revision])):node("p","No changes recorded.","empty"));root.append(history);
  }catch(e){message("Identity detail unavailable: "+e.message,true);}
};
