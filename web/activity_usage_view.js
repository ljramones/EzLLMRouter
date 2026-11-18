"use strict";
// Presentation over existing metadata. Sender observations are distinct from receipts.
function readableStep(identifier,provider=false){
  if(provider&&String(identifier||"").startsWith("step.provider.validation."))return "Provider validation";
  const parts=String(identifier||"").split(".");
  const value=parts.slice(1).filter(part=>!/^([a-f0-9]{16,}|dev0[0-9]-[0-9]{8}-[0-9]+)$/.test(part)).pop()||"operation";
  return (provider?"Provider ":"Synthetic ")+value.replaceAll(/[-_]+/g," ").replace(/\b\w/g,letter=>letter.toUpperCase());
}
function compactIdentity(label,identifier,click){
  const wrap=node("div",undefined,"compact-identity");
  const primary=click?node("button",label,"primary-link"):node("span",label,"primary-label");
  if(click){primary.type="button";primary.onclick=click;}
  const secondary=node("small",identifier||"No exact ID","compact-id mono");
  secondary.title=identifier||"";
  wrap.append(primary,secondary);return wrap;
}
function viewLabels(models,principals){
  return {models:new Map(models.map(item=>[item.configuration_ref,item])),
          principals:new Map(principals.map(item=>[item.principal_id,item]))};
}
async function loadViewLabels(){
  const [models,principals]=await Promise.all([api("/operator/v1/models"),api("/operator/v1/principals")]);
  return viewLabels(models.items,principals.items);
}
function principalCell(id,labels,provider=false){
  const value=labels?.principals.get(id),name=value?.display_name||"Unregistered synthetic principal";
  return compactIdentity(id!=="owner.local"&&!provider?name+" · Synthetic fixture":name,id);
}
function configurationCell(id,labels){
  if(!id)return node("span","No intent","muted");
  const value=labels?.models.get(id),name=value?.display_name||"Synthetic configuration";
  return compactIdentity(value?.kind==="provider_deployment"?name+" · Provider deployment":
    value?.kind==="real_catalogue"?name:name+" · Synthetic fixture",id);
}
activityRows = function(items,labels){
  return items.map(item=>{const provider=String(item.step_id||"").startsWith("step.provider.validation.")||
    labels?.models.get(item.configuration_ref)?.kind==="provider_deployment";
    return [compactIdentity(readableStep(item.step_id,provider),item.submission_id,()=>detail(item.submission_id)),
    principalCell(item.principal_id,labels,provider),configurationCell(item.configuration_ref,labels),
    badge(item.submission_state.replaceAll("_"," ")),
    node("time",item.updated_at?new Date(item.updated_at).toLocaleString():"Unavailable")
  ];});
};
activity = async function(){
  const root=$("view-content"),filter=node("div",undefined,"filter"),label=node("label","State"),select=node("select");
  for(const [value,title] of [["","All states"],["admitted","Admitted"],["completed","Completed"],["failed_before_transmit","Failed before send"],["failed_after_transmit","Failed after send"],["outcome_unknown","Outcome unknown"]]){
    const option=node("option",title);option.value=value;select.append(option);
  }
  select.value=state.filter;select.onchange=()=>{state.filter=select.value;state.page=1;render();};
  label.append(select);filter.append(label);root.append(filter);
  const query=new URLSearchParams({page:String(state.page),limit:"20"});
  if(state.filter)query.set("state",state.filter);
  if(state.activityPrincipal)query.set("principal_id",state.activityPrincipal);
  const [data,labels]=await Promise.all([api("/operator/v1/activity?"+query),loadViewLabels()]);
  root.append(node("p","Historical fixture activity is synthetic. Explicit provider validations are labelled separately. Open an operation for exact task, step, generation and attempt IDs.","scope-note"),
    data.items.length?table(["Operation","Principal","Configuration","State","Updated"],activityRows(data.items,labels)):node("p","No submissions match this filter.","empty"));
  const pages=node("div",undefined,"pagination"),prev=node("button","Previous"),next=node("button","Next");
  prev.disabled=state.page===1;next.disabled=state.page*data.limit>=data.total;
  prev.onclick=()=>{state.page--;render();};next.onclick=()=>{state.page++;render();};
  append(pages,prev,node("span",`Page ${data.page} · ${data.total} submissions`),next);root.append(pages);
};
usage = async function(){
  const [data,labels]=await Promise.all([api("/operator/v1/usage"+(state.usagePrincipal?"?principal_id="+encodeURIComponent(state.usagePrincipal):"")),loadViewLabels()]);
  const root=$("view-content"),cards=node("div",undefined,"cards");
  append(cards,card("Attempts",data.attempts),card("Intents persisted",data.intents_persisted),
    card("Final requests committed",data.final_requests_committed),
    card("First write observed",data.transmission_started_observed),
    card("No first write observed",data.no_first_write_observed),
    card("Write observation unknown",data.write_observation_unknown),
    card("Usage available",data.usage_available),card("Usage unknown",data.usage_unknown),
    card("Calculated cost (USD)",data.cost.known_subtotals.USD||"0",true),
    card("Cost unknown attempts",data.cost.unknown_attempts));root.append(cards);
  const meaning=panel("What the counts mean");
  meaning.append(node("p","An intent reserves work. A committed final request is a durable guard receipt before the lower send. First write means the trusted sender observed its local socket accept request bytes. No first write is an explicit sender observation; missing sender evidence remains unknown. Receiver arrivals are independent observations and are not inferred from these counts. Historical fixtures remain synthetic; explicit provider validations are separate requests.","scope-note"));
  root.append(meaning);
  const byStep=panel("Usage by operation");
  byStep.append(data.by_step.length?table(["Operation","Principal / configuration","Attempts","Intent / final request","First write","Token knowledge"],data.by_step.map(item=>{
    const provider=String(item.step_id||"").startsWith("step.provider.validation.")||
      (item.configuration_refs||[]).some(id=>labels?.models.get(id)?.kind==="provider_deployment");
    const identities=node("div",undefined,"compact-identity");
    for(const id of item.principal_ids||[])identities.append(principalCell(id,labels,provider));
    for(const id of item.configuration_refs||[])identities.append(configurationCell(id,labels));
    if(!identities.childNodes.length)identities.append(node("span","No intent or identity","muted"));
    return [compactIdentity(readableStep(item.step_id,provider),item.step_id),identities,item.attempts,
      node("span",`${item.intents_persisted} intent · ${item.final_requests_committed} committed`),
      node("span",`${item.transmission_started_observed} observed · ${item.no_first_write_observed} no write · ${item.write_observation_unknown} unknown`),
      node("span",`Input ${item.input_tokens_known} known (${item.input_unknown} unknown) · Output ${item.output_tokens_known} known (${item.output_unknown} unknown)`)
    ];
  })):node("p","No usage records yet.","empty"));root.append(byStep);
  if(data.truncated)root.append(node("p","This view is limited to the newest 10,000 submissions.","message"));
};
