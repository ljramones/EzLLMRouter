"use strict";
// Every number and row comes from one server-authorized report and cutoff.
const dev09TechnicalUsage=usage;
const costUi={tab:"overview",filters:{},page:1,agent:null};
const dev12Ui={filters:{},selected:null};
const costExact=value=>value===null||value===undefined?"Unknown":String(value);
const costState=value=>String(value||"Unknown").replaceAll("_"," ").replace(/^./,x=>x.toUpperCase());
const costAmounts=totals=>{
  const parts=Object.entries(totals.known_subtotals||{}).map(([currency,amount])=>currency+" "+amount);
  return (parts.length?parts.join(" + "):"No known amount")+` · ${totals.unknown_cost_attempts} unknown-cost attempt(s)`+
    (totals.estimated_attempts?` · ${totals.estimated_attempts} estimated`:"");
};
function costFilterQuery(extra={}){const query=new URLSearchParams({page:String(costUi.page),limit:"50"});
  for(const [key,value] of Object.entries({...costUi.filters,...extra}))if(value)query.set(key,value);
  return query;}
function costLink(label,callback){const button=node("button",label,"primary-link");button.type="button";button.onclick=callback;return button;}
function costBarChart(title,rows,currency="USD",metric="known subtotal by recorded attempt",countLabel="Attempts",onSelect=null){
  const box=panel(title),eligible=rows.map(row=>({row,amount:row.known_subtotals?.[currency]})).filter(x=>x.amount!==undefined),
    maximum=Math.max(0,...eligible.map(x=>Number(x.amount)).filter(Number.isFinite));
  box.append(node("p",`${currency} ${metric}. Bar lengths are visual; the exact table below is authoritative. Unknown costs remain separate.`,"scope-note"));
  if(!rows.length){box.append(node("p","No matching recorded costs.","empty"));return box;}
  const chart=node("div",undefined,"cost-bars");chart.setAttribute("role","img");
  chart.setAttribute("aria-label",`${title}; ${currency} known amounts. Exact values are in the following table.`);
  for(const item of eligible){const line=node("div",undefined,"cost-bar-row"),label=node("span",item.row.label||item.row.id),track=node("div",undefined,"cost-bar-track"),fill=node("span",undefined,"cost-bar-fill"),amount=node("span",`${currency} ${item.amount}`);
    const numeric=Number(item.amount);fill.style.width=maximum&&Number.isFinite(numeric)?`${Math.max(2,100*numeric/maximum)}%`:"2%";
    track.append(fill);line.append(label,track,amount);chart.append(line);}
  box.append(chart,table(["Source",metric+" · "+currency,"Unknown-cost attempts",countLabel],rows.map(row=>[
    onSelect?costLink(row.label||row.id,()=>onSelect(row)):row.label||row.id,
    row.known_subtotals?.[currency]??"No known amount",row.unknown_cost_attempts,row.attempts])));
  return box;
}
function costFilterControls(root,report,labels){const box=node("details",undefined,"panel cost-filters"),
  heading=node("summary",`Report filters · UTC · ${Object.keys(costUi.filters).length} active`),
  tools=node("div",undefined,"cost-filter-grid");
  box.append(heading);
  const choices={currency:[...new Set(report.attempts.map(x=>x.currency).filter(Boolean))],
    environment:report.groupings.environment.map(x=>x.id),provider:report.groupings.provider.map(x=>x.id),
    connection_id:report.groupings.connection_id.map(x=>x.id).filter(x=>x!=="__unknown__"),
    model:report.groupings.model.map(x=>x.id).filter(x=>x!=="__unknown__"),
    configuration_ref:report.groupings.configuration_ref.map(x=>x.id).filter(x=>x!=="__unknown__"),
    agent_id:report.agents.items.map(x=>x.agent_id),
    agent_version:[...new Set(report.agents.items.flatMap(x=>x.versions))],
    initiating_user_id:report.groupings.initiating_user_id.map(x=>x.id),
    charging_owner_id:report.groupings.charging_owner_id.map(x=>x.id),
    task_class:[...new Set(report.cohorts.map(x=>x.task_class))],
    purpose:[...new Set(report.attempts.map(x=>x.purpose).filter(Boolean))]};
  const names={from:"From · YYYY-MM-DDTHH:MM:SSZ",to:"To · exclusive UTC",cutoff:"Revision cutoff · UTC",
    currency:"Currency",environment:"Environment",provider:"Provider",connection_id:"API setup",
    model:"Served model",configuration_ref:"Exact deployment",agent_id:"Agent ID",agent_search:"Search agent inventory",
    agent_version:"Agent version",
    initiating_user_id:"Initiating user",charging_owner_id:"Charging owner",
    task_class:"Task class",purpose:"Purpose"};
  const controls={};
  for(const key of Object.keys(names)){const label=node("label",names[key]),input=node("input");
    input.type=key==="from"||key==="to"||key==="cutoff"?"text":"search";
    input.value=costUi.filters[key]||"";input.placeholder=key==="agent_search"?"Name or ID":key in choices?"Exact ID; leave blank for all":
      key==="cutoff"?report.cutoff:"YYYY-MM-DDTHH:MM:SSZ";
    if(key in choices){const datalist=node("datalist");datalist.id="cost-filter-"+key;
      for(const id of choices[key]){const option=node("option");option.value=id;
        option.label=labels?.models.get(id)?.display_name||labels?.principals.get(id)?.display_name||id;
        datalist.append(option);}input.setAttribute("list",datalist.id);label.append(input,datalist);}
    else label.append(input);
    controls[key]=input;tools.append(label);}
  box.append(tools);const actions=crudActions(crudButton("Apply filters",()=>{costUi.filters=Object.fromEntries(
      Object.entries(controls).map(([key,input])=>[key,input.value.trim()]).filter(([,value])=>value));costUi.page=1;render();},"action"),
    crudButton("Clear",()=>{costUi.filters={};costUi.page=1;costUi.agent=null;render();}));
  box.append(actions);root.append(box);
}
function costExportActions(root){const box=crudActions();
  for(const format of ["csv","json"]){box.append(crudButton("Export "+format.toUpperCase(),async()=>{
    try{const query=costFilterQuery({export:format}),response=await fetch("/operator/v1/usage-costs?"+query,
        {credentials:"same-origin",cache:"no-store",redirect:"error"});
      if(!response.ok)throw Error("Export request failed: "+response.status);
      const blob=await response.blob(),url=URL.createObjectURL(blob),link=node("a");
      link.href=url;link.download="ezllmrouter-usage-costs."+format;document.body.append(link);link.click();link.remove();
      setTimeout(()=>URL.revokeObjectURL(url),1000);
    }catch(error){message("Export unavailable: "+error.message,true);}}));}
  root.append(box);
}
function costGroupTable(title,rows,open){const box=panel(title);
  box.append(rows.length?table(["Source / exact ID","Known cost by currency","Unknown","Attempts"],rows.map(row=>[
    open?costLink(row.id,()=>open(row.id)):row.id,costAmounts(row),row.unknown_cost_attempts,row.attempts])):
    node("p","No matching attempts.","empty"));return box;}
function costAttemptTable(items){const box=panel("Contributing attempts · one row per attempt");
  box.append(items.length?table(["Attempt / task","Provider / model","Actor / user","Cost knowledge","Observed state"],items.map(item=>[
    compactIdentity(item.task_id||"Task unknown",item.attempt_id,()=>{
      if(window.location.pathname!=="/integration")return detail(item.submission_id);
      let inspector=box.querySelector(".cost-attempt-inspector");
      if(!inspector){inspector=panel("Selected attempt");inspector.classList.add("cost-attempt-inspector");box.append(inspector);}
      inspector.replaceChildren(node("h2","Selected attempt"),definition(Object.entries(item).map(([key,value])=>
        [key.replaceAll("_"," "),value&&typeof value==="object"?JSON.stringify(value):value])));
      inspector.scrollIntoView({block:"nearest"});
    }),
    compactIdentity(item.provider+" · "+(item.model||"Model unknown"),item.connection_id||item.configuration_ref),
    compactIdentity(item.agent_id+" · "+item.initiating_user_id,item.run_id||item.principal_id),
    item.cost_status==="unknown"?"Unknown":item.cost_status==="estimated"?
      item.currency+" "+item.estimated_amount_decimal+" · estimated":
      item.cost_status==="no_provider_charge"?"No provider charge · no intent":
      item.currency+" "+item.amount_decimal+" · "+item.cost_status,
    item.submission_state+" · "+item.dispatch_state])):node("p","No matching attempts.","empty"));return box;}
function costAgentDetail(root,report,labels){const agent=report.agents.items.find(item=>item.agent_id===costUi.agent);
  if(!agent){costUi.agent=null;return;}
  root.append(crudButton("← All agents",()=>{costUi.agent=null;render();}),
    panel(agent.display_name));
  const identity=panel("Identity and version");identity.append(definition([["Agent ID",agent.agent_id],
    ["Versions",agent.versions.join(", ")],["Responsible owner",agent.owner],
    ["Registry state",costState(agent.status)],["Instrumentation",costState(agent.instrumentation)],
    ["Activity",costState(agent.activity)],["Evidence reference",agent.instrumentation_ref]]));root.append(identity);
  if(state.role==="registry_admin"&&window.location.pathname!=="/integration")root.append(crudActions(crudButton(
    agent.status==="active"?"Archive agent…":"Restore agent",async()=>{
      const target=agent.status==="active"?"archived":"active";
      if(!window.confirm(`${target==="archived"?"Archive":"Restore"} ${agent.display_name}? Current permissions are still checked at send time.`))return;
      try{await registryChange("agent_state",agent.agent_id,agent.revision,
        {status:target,reason:"Operator change"});costUi.agent=null;render();}
      catch(error){message("Agent change rejected: "+error.message,true);}})));
  const use=panel("Usage & Costs");use.append(definition([["Direct",costAmounts(agent.direct)],
    ["Delegated",costAmounts(agent.delegated)],["Inclusive workflow",costAmounts(agent.inclusive_workflow)],
    ["Runs",agent.runs]]));root.append(use);
  const tasks=report.workflows.filter(run=>run.agent_id===agent.agent_id),work=panel("Tasks & Outcomes");
  work.append(tasks.length?table(["Run / task","State / outcome","Direct","Inclusive workflow"],tasks.map(run=>[
    compactIdentity(run.task_id,run.run_id),run.outcome?.verdict||run.status,
    costAmounts(run.direct),costAmounts(run.inclusive_workflow)])):
    node("p","No authorized runs recorded.","empty"));root.append(work);
  const attempts=report.attempts.filter(item=>item.agent_id===agent.agent_id),models=panel("Models used");
  models.append(attempts.length?table(["Model","Attempt","Cost"],attempts.map(item=>[
    labels.models.get(item.configuration_ref)?.display_name||item.model||"Unknown",
    item.attempt_id,item.cost_status==="unknown"?"Unknown":`${item.currency||""} ${item.amount_decimal||""}`])):
    node("p","No model attempts attributed to this agent.","empty"));root.append(models);
}
async function sourceConnectionCost(connection){
  const report=await api("/operator/v1/usage-costs?"+new URLSearchParams({connection_id:connection.connection_id})),
    box=panel("Usage & Costs · "+connection.display_name);
  box.append(node("p","Recorded through EzLLMRouter. This connection's model requests are separate from API access checks and discovery. Missing cost stays unknown.","scope-note"),
    definition([["Attempts",report.total.attempts],["Known cost subtotal",costAmounts(report.total)],
      ["Cost coverage",report.total.cost_coverage],["Scope",report.scope]]),
    crudActions(crudButton("Open filtered Usage & Costs",()=>{costUi.filters={connection_id:connection.connection_id};
      costUi.tab="providers";costUi.page=1;state.view="usage";render();})));
  return box;
}
async function sourceProviderCost(providerId){
  const report=await api("/operator/v1/usage-costs?"+new URLSearchParams({provider:providerId})),
    box=panel("Usage & Costs · "+providerId);
  box.append(definition([["Recorded attempts",report.total.attempts],
    ["Known cost subtotal",costAmounts(report.total)],["Cost coverage",report.total.cost_coverage]]),
    crudActions(crudButton("Open filtered Usage & Costs",()=>{costUi.filters={provider:providerId};
      costUi.tab="providers";costUi.page=1;state.view="usage";render();})));
  return box;
}
function dev12Query(extra={}){const query=new URLSearchParams();for(const [key,value] of Object.entries({...dev12Ui.filters,...extra}))if(value)query.set(key,value);return query;}
function dev12Inspector(item){const box=panel("Synthetic operation detail");
  const components=item.native_components.map(part=>part.component+": "+(part.quantity??part.presence)+
    (part.evidence?" · "+part.evidence:"")+(part.source_ref?" · "+part.source_ref:"")).join("; ")||"No native observation";
  box.append(definition([["Attempt",item.attempt_id],["Submission",item.submission_id],
    ["Operation",item.operation+" · "+item.input_role],["Workflow / run",item.root_workflow_id+" · "+item.run_id],
    ["Actor",item.actor_id],["Initiating user",item.initiating_user_id||"Absent · autonomous"],
    ["Charging owner",item.charging_owner_id],["Native usage",components],
    ["Price / usage",item.price_ref+" · "+item.usage_ref],
    ["Settlement",item.cost_status+(item.amount_decimal?" · fictional USD "+item.amount_decimal:"")],
    ["Reservation", "fictional USD "+item.reservation_decimal],
    ["Current exposure · "+item.exposure_state_as_of+" UTC",item.exposure_state],
    ["Result access",item.candidate_access]]));return box;}
async function dev12SyntheticUsage(root){let report;try{report=await api("/operator/v1/dev12-usage?"+dev12Query());}
  catch(error){if(error.message==="NOT_FOUND")return false;throw error;}
  const box=panel("Standalone retrieval · controlled synthetic profile");box.classList.add("dev12-report");
  box.append(node("p",`DEMO — controlled synthetic embedding and rerank operations. Fictional USD only; no commercial provider calls. Usage revision cutoff: ${report.usage_cutoff||"latest"}. Exposure and delivery states are current as of ${report.operational_as_of} UTC, independently of that cutoff. Delegation is caller-reported.`,"scope-note"));
  box.append(node("p","Management edits are disabled for this controlled synthetic report; authority changes use the separate registry flow.","scope-note"));
  const filters=node("details",undefined,"cost-filters"),fields=node("div",undefined,"cost-filter-grid"),controls={};
  filters.append(node("summary","Synthetic report filters · UTC"));
  const names={from:"From · UTC inclusive",to:"To · UTC exclusive",cutoff:"Usage revision cutoff · UTC",
    operation:"Operation",actor_id:"Actor",provider_ref:"Synthetic destination",initiating_user_id:"Initiating user",charging_owner_id:"Charging owner",
    root_workflow_id:"Workflow",configuration_ref:"Configuration",task_id:"Task",environment:"Environment"};
  for(const [key,name] of Object.entries(names)){const label=node("label",name),input=node("input");
    input.type="search";input.value=dev12Ui.filters[key]||"";
    input.placeholder=key==="from"||key==="to"||key==="cutoff"?"YYYY-MM-DDTHH:MM:SSZ":"Exact ID; blank for all";
    if(report.groupings[key]){const list=node("datalist");list.id="dev12-filter-"+key;
      for(const entry of report.groupings[key]){const choice=node("option");choice.value=entry.id;list.append(choice);}
      input.setAttribute("list",list.id);label.append(input,list);}else label.append(input);
    controls[key]=input;fields.append(label);}
  filters.append(fields,crudActions(crudButton("Apply synthetic filters",()=>{
    dev12Ui.filters=Object.fromEntries(Object.entries(controls).map(([key,input])=>[key,input.value.trim()]).filter(([,value])=>value));
    dev12Ui.selected=null;render();}),crudButton("Clear synthetic filters",()=>{dev12Ui.filters={};dev12Ui.selected=null;render();})));
  box.append(filters);
  const cards=node("div",undefined,"cards");cards.append(card("Known fictional USD",report.total.known_usd,true),
    card("Unique attempts",report.total.attempts),card("Unknown cost",report.total.unknown_cost_attempts),
    card("Over bound",report.total.over_bound_attempts),card("Explicit no send",report.total.not_sent_attempts),
    card("Current held reservations",report.total.current_held_reservations),
    card("Current held fictional USD",report.total.current_held_bound_usd));box.append(cards);
  const actions=crudActions();for(const format of ["csv","json"]){actions.append(crudButton("Export synthetic "+format.toUpperCase(),async()=>{
    try{const response=await fetch("/operator/v1/dev12-usage?"+dev12Query({export:format}),
      {credentials:"same-origin",cache:"no-store",redirect:"error"});if(!response.ok)throw Error(String(response.status));
      const blob=await response.blob(),url=URL.createObjectURL(blob),link=node("a");
      link.href=url;link.download="ezllmrouter-synthetic-usage."+format;document.body.append(link);link.click();link.remove();
      setTimeout(()=>URL.revokeObjectURL(url),1000);
    }catch(error){message("Synthetic export unavailable: "+error.message,true);}}));}box.append(actions);
  const rows=report.attempts.slice().reverse(),selected=rows.find(item=>item.attempt_id===dev12Ui.selected);
  const costText=item=>item.cost_status==="unknown"?"Unknown cost":item.cost_status==="not_sent"?"No send":
      "fictional USD "+item.amount_decimal+(item.cost_status==="over_bound"?" · over bound":"");
  const recent=node("div",undefined,"dev12-recent");
  for(const item of rows.slice(0,8)){const line=node("div",undefined,"dev12-row");
    line.append(costLink(item.operation+" · "+item.input_role+" · "+item.task_id,()=>{
      dev12Ui.selected=item.attempt_id;render();}),node("span",item.actor_id+" · "+item.root_workflow_id),
      node("span",costText(item)),node("span",item.submission_state+" · "+item.candidate_access));
    recent.append(line);}
  box.append(rows.length?recent:node("p","No authorized synthetic attempts match these filters.","empty"));
  if(selected)box.append(dev12Inspector(selected));
  if(rows.length>8){const full=node("details");full.append(node("summary",`All ${rows.length} synthetic attempts · exact records`),
    table(["Operation / task","Actor / workflow","Settlement","State"],rows.map(item=>[
      costLink(item.operation+" · "+item.input_role+" · "+item.task_id,()=>{dev12Ui.selected=item.attempt_id;render();}),
      item.actor_id+" · "+item.root_workflow_id,costText(item),item.submission_state+" · "+item.candidate_access])));
    box.append(full);}
  const groups=node("details");groups.append(node("summary","Actor, destination, initiating user, owner and workflow breakdowns"));
  for(const key of ["actor_id","provider_ref","initiating_user_id","charging_owner_id","root_workflow_id","configuration_ref","task_id","environment"])
    groups.append(table([key,"Known fictional USD","Unknown","Attempts"],report.groupings[key].map(row=>[
      row.id,row.known_usd,row.unknown_cost_attempts,row.attempts])));box.append(groups);
  const lineage=node("details");lineage.append(node("summary","Who delegated the work · inclusive costs overlap"),
    node("p","Direct cost counts attempts in this run. Total including delegated work unions each descendant attempt once. Parent and child totals overlap and should not be added.","scope-note"),
    table(["Run / parent","Direct fictional USD","Total including delegated work","Unknown"],report.workflows.map(run=>[
      run.run_id+" · "+(run.parent_run_id||"root"),run.direct.known_usd,
      run.total_including_delegated.known_usd,run.total_including_delegated.unknown_cost_attempts])));
  box.append(lineage);
  root.append(box);return true;
}
usage=async function dev09UsageCosts({embedded=false}={}){
  const root=$("view-content");if(!embedded)$("view-title").textContent="Usage & Costs";
  if(!embedded&&demoUi.open)return demoWorkspace();
  const hasDev12=embedded?false:await dev12SyntheticUsage(root);
  if(hasDev12){try{await api("/operator/v1/usage-costs?page=1&limit=1");}catch(error){if(error.message==="NOT_FOUND")return;throw error;}}
  root.append(node("p","Recorded through EzLLMRouter · synthetic activity is labelled. Known amounts are subtotals; unknown costs are never treated as zero. All dates and revision cutoffs are UTC.","scope-note"));
  if(!embedded){root.append(crudActions(crudButton("Open demo workspace",()=>{demoUi.open=true;demoUi.collection="team";demoUi.story="oren_opportunity";demoUi.time=null;demoUi.revision++;render();},"action")));
  const tabs=crudActions();for(const [key,label] of [["overview","Overview"],["providers","Providers"],
    ["models","Models"],["agents","Agents"],["people","People & teams"],["tasks","Tasks & workflows"],
    ["technical","Technical diagnostics"]]){const button=crudButton(label,()=>{costUi.tab=key;costUi.agent=null;render();},
      costUi.tab===key?"action":"quiet");button.setAttribute("aria-current",costUi.tab===key?"page":"false");tabs.append(button);}root.append(tabs);}
  if(costUi.tab==="technical")return dev09TechnicalUsage();
  const [report,labels]=await Promise.all([api("/operator/v1/usage-costs?"+costFilterQuery()),loadViewLabels()]);
  costFilterControls(root,report,labels);costExportActions(root);
  const total=report.total;
  if(!total.attempts){
    const empty=panel("No recorded attempts");empty.append(node("p",
      "This profile and filter have no recorded model attempts. Coverage is not applicable. Timeline, cumulative cost, and breakdowns appear here when authorized activity is recorded.","empty"));
    root.append(empty);return;
  }
  const cards=node("div",undefined,"cards");
  cards.append(card("Known cost subtotal",Object.entries(total.known_subtotals).map(([currency,value])=>currency+" "+value).join(" + ")||"No known amount",true),
    card("Unknown-cost attempts",total.unknown_cost_attempts),
    card("Estimated separately",Object.entries(total.estimated_subtotals).map(([currency,value])=>currency+" "+value).join(" + ")||"None",true),
    card("Cost coverage",total.attempts?total.cost_coverage:"Not applicable · no attempts"),
    card("Attempts",total.attempts),card("Agent attribution",
      `${report.attribution_coverage.registered_agent_attempts} registered · ${report.attribution_coverage.unknown_agent_attempts} unknown`,true),
    card("Outcome coverage",`${report.outcome_coverage.reported_root_runs}/${report.outcome_coverage.visible_root_runs} root runs`));
  if(costUi.tab==="overview")root.append(cards);
  else root.append(node("p",`Filtered native report · ${total.attempts.toLocaleString("en-US")} attempts · `+
    `${total.unknown_cost_attempts.toLocaleString("en-US")} unknown-cost attempts. Exact totals remain in exports.`,"scope-note"));
  root.append(node("p",`Spending during this period: ${report.period.from||"all time"} to ${report.period.to||"now"} (exclusive end). Usage revisions through ${report.cutoff}. Estimates are separate; allocated infrastructure and full operating cost are Not measured unless authorized inputs exist.`,"scope-note"));
  if(embedded&&(costUi.tab==="overview"||costUi.tab==="tasks")&&typeof accountingRecordedTrace==="function")root.append(accountingRecordedTrace(report.attempts.map(item=>({
    id:item.attempt_id,time:item.attempt_at,actor:item.agent_id,task:item.task_id,run:item.run_id,
    model:item.model,provider:item.provider,cost_status:item.cost_status,currency:item.currency,
    amount_decimal:item.amount_decimal,raw:item})),"Native EzLLMRouter"));
  if(costUi.tab==="overview"){
    root.append(costBarChart("Known cost over time",report.trend),
      costBarChart("Provider breakdown",report.groupings.provider),
      costGroupTable("Models",report.groupings.configuration_ref,id=>{costUi.filters.configuration_ref=id;costUi.tab="models";render();}));
    const ranking=report.agents.items.map(agent=>({id:agent.display_name,label:agent.display_name,
      ...agent.direct})).sort((a,b)=>Number(b.known_subtotals.USD||0)-Number(a.known_subtotals.USD||0));
    root.append(costBarChart("Direct agent cost ranking · additive rows",ranking),costAttemptTable(report.attempts.slice(-20).reverse()));
  }else if(costUi.tab==="providers"){
    root.append(costGroupTable("Providers",report.groupings.provider,id=>{costUi.filters.provider=id;render();}),
      costGroupTable("API setups",report.groupings.connection_id,id=>{costUi.filters.connection_id=id;render();}),
      costAttemptTable(report.attempts));
  }else if(costUi.tab==="models"){
    root.append(costGroupTable("Exact configurations",report.groupings.configuration_ref),
      costGroupTable("Served models",report.groupings.model),costAttemptTable(report.attempts));
  }else if(costUi.tab==="agents"){
    if(costUi.agent){costAgentDetail(root,report,labels);return;}
    const box=panel("All registered agents · direct cost rows are additive");
    box.append(report.agents.items.length?table(["Agent / exact ID","State / instrumentation","Runs / outcomes","Direct cost","Delegated","Inclusive workflow"],
      report.agents.items.map(agent=>[compactIdentity(agent.display_name,agent.agent_id,()=>{costUi.agent=agent.agent_id;render();}),
        [agent.status,agent.instrumentation,agent.activity].map(costState).join(" · "),
        `${agent.runs} / ${agent.outcome_coverage.reported} reported`,
        costAmounts(agent.direct),costAmounts(agent.delegated),costAmounts(agent.inclusive_workflow)])):
      node("p","No registered agents are visible in this scope.","empty"));
    box.append(node("p",`Showing page ${report.agents.page} of ${Math.max(1,Math.ceil(report.agents.total/report.agents.limit))} · ${report.agents.total} visible agents. Inclusive parent and child rows overlap and must not be summed.`,"scope-note"));
    const paging=crudActions(crudButton("Previous",()=>{costUi.page--;render();}),
      crudButton("Next",()=>{costUi.page++;render();}));
    paging.children[0].disabled=costUi.page<=1;paging.children[1].disabled=costUi.page*report.agents.limit>=report.agents.total;
    box.append(paging);root.append(box,costGroupTable("Direct actor buckets · unknown and human work remain separate",report.groupings.agent_id));
    if(state.role==="registry_admin"&&window.location.pathname!=="/integration")root.append(entryForm("Register an agent · no execution access granted",
      [{name:"agent_id",label:"Stable agent ID"},{name:"display_name",label:"Display name"},
       {name:"owner",label:"Responsible owner / team"},{name:"versions",label:"Versions · comma separated"}],
      "Register agent",values=>registryChange("register_agent",values.agent_id,0,
        {display_name:values.display_name,owner:values.owner,versions:listValue(values.versions)})));
  }else if(costUi.tab==="people"){
    root.append(costGroupTable("Initiating people · autonomous and unknown are separate",report.groupings.initiating_user_id),
      costGroupTable("Charging owners / teams",report.groupings.charging_owner_id),costAttemptTable(report.attempts));
  }else{
    const tasks=panel("Task cohort performance · task-start period, full attributable cost through cutoff");
    tasks.append(report.cohorts.length?table(["Comparable class / protocol","Agent / version","Accepted / total","Cohort attempt cost","Cost per accepted task","Coverage"],
      report.cohorts.map(row=>[compactIdentity(row.task_class,row.evaluation_ref),row.agent_id+" · "+row.agent_version,
        `${row.accepted}/${row.total_tasks} · ${row.rejected} rejected · ${row.abandoned} abandoned · ${row.unreported} unreported`,
        costAmounts(row.attempt_cost),row.efficiency.state==="complete"?row.efficiency.currency+" "+row.efficiency.cost_per_accepted_task:
          row.efficiency.state==="no_accepted_tasks"?"No accepted tasks":"Incomplete",
        row.sample_note])):node("p","No comparable recorded task cohorts.","empty"));root.append(tasks);
    const eligible=report.cohorts.filter(row=>row.efficiency.state==="complete"),
      currencies=[...new Set(eligible.map(row=>row.efficiency.currency))];
    for(const currency of currencies){root.append(costBarChart("Cost per accepted task · "+currency,
      eligible.filter(row=>row.efficiency.currency===currency).map(row=>({
        id:row.task_class+" · "+row.agent_id,label:row.task_class+" · "+row.agent_id+" "+row.agent_version,
        known_subtotals:{[currency]:row.efficiency.cost_per_accepted_task},
        unknown_cost_attempts:0,attempts:row.total_tasks})),currency,"cost per accepted task","Tasks in cohort"));}
    const metrics=panel("Descriptive outcomes · no automatic best-agent decision");
    metrics.append(report.cohorts.length?table(["Comparable cohort","Acceptance","Calls / accepted task",
      "Tokens / accepted task","Time to accepted","Instrumentation"],report.cohorts.map(row=>[
      compactIdentity(row.task_class+" · "+row.agent_id,row.evaluation_ref+" · "+row.agent_version),
      row.performance.acceptance_rate_percent+"% · "+row.accepted+"/"+row.total_tasks,
      row.performance.calls_per_accepted_task??"No accepted tasks",
      row.performance.tokens_per_accepted_task?
        `Input ${row.performance.tokens_per_accepted_task.input} · output ${row.performance.tokens_per_accepted_task.output}`:
        `Not measured · ${row.performance.token_coverage_attempts}/${row.attempt_cost.attempts} attempt(s)`,
      row.performance.median_seconds_to_accepted===null?"Not measured":
        `${row.performance.median_seconds_to_accepted}s median · `+
        (row.performance.p95_seconds_to_accepted===null?"p95 needs ≥20 observations":
          `${row.performance.p95_seconds_to_accepted}s p95`),
      `Retries, escalation, human intervention: Not measured · ${row.sample_note}`])):
      node("p","No recorded task outcomes in this scope.","empty"));root.append(metrics);
    const workflows=panel("Run lineage · direct, delegated and inclusive costs");
    workflows.append(report.workflows.length?table(["Task / run","Parent / agent","Outcome","Direct","Delegated","Inclusive"],
      report.workflows.map(run=>[compactIdentity(run.task_id,run.run_id),
        (run.parent_run_id||"Root")+" · "+(run.agent_id||"Direct human"),run.outcome?.verdict||run.status,
        costAmounts(run.direct),costAmounts(run.delegated),costAmounts(run.inclusive_workflow)])):
      node("p","No run metadata recorded in this scope.","empty"));root.append(workflows,costAttemptTable(report.attempts));
  }
};
