"use strict";
// The DEV-09 Usage & Costs controls are reused for authorized external observations.
const integrationAccountingTabs=[["overview","Overview"],["providers","Providers"],["models","Models"],
  ["agents","Agents"],["people","People & teams"],["tasks","Tasks & workflows"]];
const integrationAccountingFilters=["actor_id","provider_account_id","model_id","initiating_user_id",
  "task_id","root_run_id","run_id","from","to"];
function integrationAccountingLabel(id){
  if(!id)return "Unattributed";
  const value=String(id);
  if(value.startsWith("task.chat.dispatch.")||value.startsWith("run.chat.dispatch."))return "Vega chat workflow";
  if(value.startsWith("agent."))return value.slice(6).replace(/\b\w/g,c=>c.toUpperCase());
  if(value.startsWith("user:"))return "Unresolved Vega user · "+value.slice(5,13);
  if(value.startsWith("account."))return "Unresolved account · "+value.slice(-8);
  return value;
}
function integrationAccountingName(id,names){return names.get(id)||integrationAccountingLabel(id);}
function integrationAccountingTime(value){
  if(!value)return "Time unavailable";
  const date=new Date(value);
  return Number.isNaN(date.valueOf())?String(value):date.toLocaleString("en-US",{timeZone:"UTC",month:"short",day:"numeric",hour:"2-digit",minute:"2-digit",hour12:false})+" UTC";
}
function integrationAccountingWorkflowName(item){
  return String(item.root_run_id||item.task_id||"").includes("chat.dispatch.")?
    "Vega chat · "+integrationAccountingTime(item.started_at):
    "Workflow · "+integrationAccountingTime(item.started_at);
}
function integrationAccountingQuantity(value){
  const match=/^(-?)(\d+)(?:\.(\d+))?$/.exec(String(value));
  if(!match)return String(value);
  return match[1]+BigInt(match[2]).toLocaleString("en-US")+(match[3]?"."+match[3]:"");
}
function integrationAccountingScaledQuantity(value){
  return integrationAccountingQuantity(integrationAccountingDecimal(value).replace(/0+$/,"").replace(/\.$/,""));
}
function integrationAccountingUnits(item){
  if(item.usage_state!=="known"||!Array.isArray(item.native_units))return "Usage not reported";
  return item.native_units.map(unit=>integrationAccountingQuantity(unit.quantity_decimal)+" "+
    unit.unit.replaceAll("_"," ")).join(" · ");
}
function integrationAccountingUsage(rows){
  const units=new Map();let unknown=0;
  for(const item of rows){
    if(item.usage_state!=="known"||!Array.isArray(item.native_units)){unknown++;continue;}
    for(const unit of item.native_units){
      const count=integrationAccountingAmount(unit.quantity_decimal);
      units.set(unit.unit,(units.get(unit.unit)||0n)+count);
    }
  }
  return {units,unknown};
}
function integrationAccountingUsageText(rows){
  const usage=integrationAccountingUsage(rows);
  return ([...usage.units].map(([unit,count])=>integrationAccountingScaledQuantity(count)+" "+unit.replaceAll("_"," "))
    .concat(usage.unknown?[usage.unknown+" attempts without reported usage"]:[])).join(" · ")||"No reported usage";
}
function integrationAccountingCost(item){
  return item.cost_status==="known"?item.currency+" "+item.amount_decimal:
    item.usage_state==="known"?"Unknown cost · no monetary observation recorded":
      "Unknown cost · usage and amount not reported";
}
function integrationAccountingAmount(value){
  const match=/^(-?)(\d+)(?:\.(\d{1,9}))?$/.exec(String(value));
  return match?(match[1]==="-"?-1n:1n)*(BigInt(match[2])*1000000000n+
    BigInt((match[3]||"").padEnd(9,"0"))):0n;
}
function integrationAccountingDecimal(value){
  const sign=value<0n?"-":"",positive=value<0n?-value:value;
  return sign+String(positive/1000000000n)+"."+String(positive%1000000000n).padStart(9,"0");
}
function integrationAccountingGroups(rows,key,names=new Map()){
  const grouped=new Map();
  for(const item of rows){
    const id=item[key]||"__unknown__";
    if(!grouped.has(id))grouped.set(id,{id,label:integrationAccountingName(id,names),
      known:new Map(),unknown_cost_attempts:0,attempts:0,items:[]});
    const group=grouped.get(id);group.attempts++;
    group.items.push(item);
    if(item.cost_status==="known"&&item.currency&&item.amount_decimal!==null){
      group.known.set(item.currency,(group.known.get(item.currency)||0n)+
        integrationAccountingAmount(item.amount_decimal));
    }else group.unknown_cost_attempts++;
  }
  return [...grouped.values()].map(item=>({id:item.id,label:item.label,
    known_subtotals:Object.fromEntries([...item.known].map(([currency,value])=>
      [currency,integrationAccountingDecimal(value)])),
    unknown_cost_attempts:item.unknown_cost_attempts,attempts:item.attempts,items:item.items}));
}
function integrationAccountingNavigate(params){integrationGo("accounting",null,params);}
function integrationAccountingSet(key,value){
  const params=new URLSearchParams(integrationRoute().params);
  if(value)params.set(key,value);else params.delete(key);
  if(key==="tab")params.delete("workflow_id");
  if(key!=="page")params.delete("page");integrationAccountingNavigate(params);
}
function integrationAccountingGroup(root,title,rows,filterKey){
  const box=panel(title);
  box.append(rows.length?table(["Name / exact ID","Attempts","Reported native usage","Unknown cost","Known subtotal"],rows.map(row=>[
    filterKey?compactIdentity(row.label,row.id,()=>integrationAccountingSet(filterKey,row.id)):
      compactIdentity(row.label,row.id),row.attempts,integrationAccountingUsageText(row.items),
      row.unknown_cost_attempts,costAmounts(row)])):
    node("p","No matching recorded attempts.","empty"));root.append(box);
}
function integrationAccountingDates(params){
  const from=params.get("from"),to=params.get("to"),end=to?new Date(to):null;
  if(end)end.setUTCDate(end.getUTCDate()-1);
  return {from:from?.slice(0,10)||"",to:end&&!Number.isNaN(end.valueOf())?end.toISOString().slice(0,10):""};
}
function integrationAccountingFilterPanel(root,report,names){
  const route=integrationRoute(),box=node("details",undefined,"panel cost-filters"),
    active=integrationAccountingFilters.filter(key=>route.params.has(key)).length;
  box.open=route.params.get("filters_open")==="1";
  box.addEventListener("toggle",()=>{
    const params=new URLSearchParams(integrationRoute().params);
    if(box.open)params.set("filters_open","1");else params.delete("filters_open");
    history.replaceState(history.state,"",integrationHash("accounting",integrationRoute().item,params));
  });
  box.append(node("summary",`Report filters · UTC · ${active} active`));
  const chips=node("div",undefined,"accounting-filter-chips");
  const titles={provider_account_id:"Provider",model_id:"Model",actor_id:"Actor",
    initiating_user_id:"Person",task_id:"Task",root_run_id:"Workflow",run_id:"Run",from:"From",to:"Before"};
  for(const key of integrationAccountingFilters){
    const value=route.params.get(key);if(!value)continue;
    const label=key==="from"||key==="to"?value:integrationAccountingName(value,names);
    const chip=integrationButton(`${titles[key]}: ${label} ×`,()=>integrationAccountingSet(key,null));
    chip.title=`Remove ${titles[key]} filter · ${value}`;chip.classList.add("accounting-filter-chip");chips.append(chip);
  }
  if(active)chips.append(integrationButton("Clear all filters",()=>{
    const params=new URLSearchParams(integrationRoute().params);
    for(const key of integrationAccountingFilters)params.delete(key);
    integrationAccountingNavigate(params);
  }));
  if(active)root.append(chips);
  const grid=node("div",undefined,"cost-filter-grid"),controls={},dates=integrationAccountingDates(route.params);
  const fields=[["provider_account_id","Provider account"],["model_id","Model"],["actor_id","Agent or actor"],
    ["initiating_user_id","Person"],["task_id","Task"],["root_run_id","Workflow"],
    ["from","From date · inclusive UTC"],["to","Through date · inclusive UTC"]];
  for(const [key,title] of fields){
    const label=node("label",title),input=node("input");input.type=key==="from"||key==="to"?"date":"search";
    input.value=key==="from"||key==="to"?dates[key]:route.params.get(key)||"";
    if(input.type==="search"){
      input.placeholder="Search name or ID";
      const list=node("datalist");list.id="integration-filter-"+key;
      for(const id of [...new Set(report.attempts.map(row=>row[key]).filter(Boolean))]){
        const option=node("option");option.value=id;option.label=names.get(id)||integrationAccountingLabel(id);list.append(option);
      }
      input.setAttribute("list",list.id);label.append(input,list);
    }else label.append(input);
    controls[key]=input;grid.append(label);
  }
  const actions=node("div",undefined,"actions");
  const apply=integrationButton("Apply filters",()=>{
    const params=new URLSearchParams(route.params);
    for(const [key,input] of Object.entries(controls)){
      let value=input.value.trim();
      if(value&&input.type==="date"){
        const date=new Date(value+"T00:00:00Z");
        if(key==="to")date.setUTCDate(date.getUTCDate()+1);
        value=date.toISOString().replace(".000Z","Z");
      }
      if(value)params.set(key,value);else params.delete(key);
    }
    params.delete("page");integrationAccountingNavigate(params);
  },"action");actions.append(apply,integrationButton("Clear filters",()=>{
    const params=new URLSearchParams(route.params);
    for(const key of integrationAccountingFilters)params.delete(key);
    params.delete("page");integrationAccountingNavigate(params);
  }));
  const shortcuts=node("div",undefined,"actions");
  for(const [days,title] of [[7,"Last 7 days"],[30,"Last 30 days"],[90,"Last 90 days"]]){
    shortcuts.append(integrationButton(title,()=>{
      const today=new Date(),end=new Date(Date.UTC(today.getUTCFullYear(),today.getUTCMonth(),today.getUTCDate()+1)),
        start=new Date(end);start.setUTCDate(start.getUTCDate()-days);
      const params=new URLSearchParams(route.params);
      params.set("from",start.toISOString().replace(".000Z","Z"));
      params.set("to",end.toISOString().replace(".000Z","Z"));
      integrationAccountingNavigate(params);
    }));
  }
  shortcuts.append(integrationButton("All time",()=>{const params=new URLSearchParams(route.params);
    params.delete("from");params.delete("to");integrationAccountingNavigate(params);}));
  const advanced=node("details",undefined,"connection-technical");advanced.append(node("summary","Advanced exact IDs and UTC timestamps"));
  const exact=node("div",undefined,"cost-filter-grid"),advancedControls={};
  for(const key of integrationAccountingFilters){const label=node("label",key),input=node("input");
    input.value=route.params.get(key)||"";input.placeholder="Exact value";label.append(input);exact.append(label);
    advancedControls[key]=input;}
  advanced.append(exact,integrationButton("Apply exact filters",()=>{const params=new URLSearchParams(route.params);
    for(const [key,input] of Object.entries(advancedControls)){
      if(input.value.trim())params.set(key,input.value.trim());else params.delete(key);
    }params.delete("page");integrationAccountingNavigate(params);},"action"));
  box.append(grid,actions,shortcuts,advanced);root.append(box);
}
function integrationAccountingAttempts(root,report,names){
  const box=panel("Contributing attempts · one row per attempt"),route=integrationRoute();
  const sort=route.params.get("sort")==="oldest"?"oldest":"newest",rows=report.attempts.slice()
    .sort((a,b)=>(sort==="newest"?-1:1)*(String(a.started_at).localeCompare(String(b.started_at))||
      String(a.attempt_id).localeCompare(String(b.attempt_id))));
  const page=Math.max(1,Number(route.params.get("page")||1)||1),shown=rows.slice((page-1)*20,page*20);
  const sortLabel=node("label","Sort"),sortSelect=node("select");
  for(const [id,title] of [["newest","Newest first"],["oldest","Oldest first"]]){
    const option=node("option",title);option.value=id;sortSelect.append(option);}
  sortSelect.value=sort;sortSelect.onchange=()=>integrationAccountingSet("sort",sortSelect.value);
  sortLabel.append(sortSelect);box.append(sortLabel);
  box.append(shown.length?table(["Attempt / workflow","Provider / model","Actor / person","Provider result / task outcome","Reported usage","Cost"],
    shown.map(item=>[
      compactIdentity(integrationAccountingWorkflowName(item),item.attempt_id,
        ()=>integrationGo("accounting",item.attempt_id,route.params)),
      compactIdentity(integrationAccountingName(item.provider_account_id,names),
        integrationAccountingName(item.model_id,names)),
      compactIdentity(integrationAccountingName(item.actor_id,names),
        integrationAccountingName(item.initiating_user_id,names)),
      item.result_state+" / "+item.task_outcome,
      integrationAccountingUnits(item),integrationAccountingCost(item)])):
      node("p","No attempts match this collection and filter. The report remains available for other collections and dates.","empty"));
  const pagination=node("div",undefined,"pagination"),prev=integrationButton("Previous",()=>integrationAccountingSet("page",page-1)),
    next=integrationButton("Next",()=>integrationAccountingSet("page",page+1));
  prev.disabled=page===1;next.disabled=page*20>=rows.length;
  pagination.append(prev,node("span",`Page ${page} · ${rows.length} attempts`),next);box.append(pagination);root.append(box);
}
function integrationAccountingAttemptDetail(root,item,names){
  const back=integrationButton(integrationRoute().params.has("workflow_id")?"← Selected workflow":"← Report",
    ()=>integrationGo("accounting",null,integrationRoute().params));
  root.append(back);
  const box=panel("Attempt · "+item.attempt_id);
  box.append(definition([
    ["Workflow",integrationAccountingWorkflowName(item)],
    ["Start · recorded UTC second",item.started_at],
    ["Result observation · UTC",item.result_observed_at||"Not observed"],
    ["Usage observation · UTC",item.usage_observed_at||"Not observed"],
    ["Provider completion / duration","Not recorded by this accounting contract"],
    ["Initiating person",integrationAccountingName(item.initiating_user_id,names)],
    ["Executing actor",integrationAccountingName(item.actor_id,names)],
    ["Provider account",integrationAccountingName(item.provider_account_id,names)],
    ["Model",integrationAccountingName(item.model_id,names)],
    ["Provider result",item.result_state],["Task outcome",item.task_outcome],
    ["Native usage",integrationAccountingUnits(item)],
    ["Usage state / provenance",item.usage_state+" / "+(item.usage_provenance||"No provider usage")],
    ["Cost",integrationAccountingCost(item)],
    ["Attempt role",item.attempt_role||"Unknown"],
    ["Predecessor attempt",item.predecessor_attempt_id||"None recorded"]]));
  const exact=node("details",undefined,"demo-inspector-technical");
  exact.append(node("summary","Exact IDs and report fields"),definition(Object.entries(item)
    .map(([key,value])=>[key.replaceAll("_"," "),value&&typeof value==="object"?JSON.stringify(value):value])));
  box.append(exact);root.append(box);
}
function integrationAccountingWorkflowView(root,report,names){
  const route=integrationRoute(),selected=route.params.get("workflow_id"),groups=new Map();
  for(const item of report.attempts){
    const id=item.root_run_id||item.run_id||item.task_id;
    if(!groups.has(id))groups.set(id,[]);
    groups.get(id).push(item);
  }
  const workflowRows=[...groups].map(([id,items])=>({id,items,
    first:items.slice().sort((a,b)=>String(a.started_at).localeCompare(String(b.started_at)))[0]}))
    .sort((a,b)=>String(b.first.started_at).localeCompare(String(a.first.started_at)));
  if(selected){
    root.append(integrationButton("← Workflow list",()=>integrationAccountingSet("workflow_id",null)));
    const group=workflowRows.find(row=>row.id===selected);
    if(!group){root.append(node("p","This workflow is outside the current report filters.","empty"));return;}
    const {items,first}=group,usage=integrationAccountingUsage(items),summary=panel(integrationAccountingWorkflowName(first));
    summary.append(definition([
      ["Initiating person",integrationAccountingName(first.initiating_user_id,names)],
      ["Executing actors",[...new Set(items.map(row=>integrationAccountingName(row.actor_id,names)))].join(" · ")],
      ["Provider / model",[...new Set(items.map(row=>integrationAccountingName(row.provider_account_id,names)+
        " / "+integrationAccountingName(row.model_id,names)))].join(" · ")],
      ["Recorded start",first.started_at],
      ["Provider results",[...new Set(items.map(row=>row.result_state))].join(" · ")],
      ["Task outcome",[...new Set(items.map(row=>row.task_outcome))].join(" · ")],
      ["Attempts",items.length],
      ["Reported native usage",integrationAccountingUsageText(items)],
      ["Usage unavailable",usage.unknown+" attempts"],
      ["Known direct cost",integrationMoney(integrationAccountingGroups(items,"root_run_id")[0]?.known_subtotals)],
      ["Known cost including descendants",integrationMoney(report.by_run_including_descendants?.[selected])],
      ["Unknown cost",items.filter(row=>row.cost_status!=="known").length+" attempts"],
      ["Exact root workflow ID",selected]
    ]));root.append(summary);
    root.append(accountingRecordedTrace(items,names));
    integrationAccountingAttempts(root,{attempts:items},names);return;
  }
  const search=route.params.get("workflow_search")||"",controls=node("div",undefined,"accounting-workflow-search"),
    label=node("label","Search workflows"),input=node("input");
  input.type="search";input.value=search;input.placeholder="Name, person, ID, provider or model";
  input.onkeydown=event=>{if(event.key==="Enter")integrationAccountingSet("workflow_search",input.value.trim());};
  label.append(input);controls.append(label,integrationButton("Search",()=>integrationAccountingSet("workflow_search",input.value.trim())));
  if(search)controls.append(integrationButton("Clear search",()=>integrationAccountingSet("workflow_search",null)));
  root.append(controls);
  const filtered=workflowRows.filter(({id,items,first})=>!search||
    [id,first.task_id,first.initiating_user_id,integrationAccountingName(first.initiating_user_id,names),
      integrationAccountingWorkflowName(first),...items.flatMap(row=>[row.actor_id,row.model_id,row.provider_account_id])]
      .join(" ").toLowerCase().includes(search.toLowerCase()));
  const list=panel("Workflows · "+filtered.length+" in this scope");
  list.append(filtered.length?table(["Workflow / exact ID","Initiator","Start · UTC","Provider result / task outcome","Attempts","Reported usage","Cost"],
    filtered.map(({id,items,first})=>[
      compactIdentity(integrationAccountingWorkflowName(first),id,()=>integrationAccountingSet("workflow_id",id)),
      integrationAccountingName(first.initiating_user_id,names),integrationAccountingTime(first.started_at),
      [...new Set(items.map(row=>row.result_state))].join(" / ")+" · "+first.task_outcome,
      items.length,integrationAccountingUsageText(items),
      items.some(row=>row.cost_status!=="known")?"Unknown for "+items.filter(row=>row.cost_status!=="known").length+
        " attempts":integrationMoney(integrationAccountingGroups(items,"root_run_id")[0]?.known_subtotals)
    ])):node("p","No workflows match this search within the active report filters.","empty"));
  root.append(list);
}
function accountingRecordedTrace(items,names){
  const rows=items.slice().sort((a,b)=>String(a.started_at).localeCompare(String(b.started_at))||
    String(a.attempt_id).localeCompare(String(b.attempt_id)));
  const layout=node("div",undefined,"demo-visual-layout accounting-trace");
  const timeline=panel("Attempt activity · recorded starts"),inspector=panel("Selected attempt");
  const detail=node("div"),clusters=new Map();
  inspector.append(detail);layout.append(timeline,inspector);
  for(const item of rows){
    const key=item.started_at||"Time unavailable";
    if(!clusters.has(key))clusters.set(key,[]);
    clusters.get(key).push(item);
  }
  function inspect(item){
    const role=item.attempt_role||"unknown";
    detail.replaceChildren(node("p",integrationAccountingWorkflowName(item),"accounting-inspector-title"),
      definition([
        ["Attempt",item.attempt_id],["Start · UTC",item.started_at],
        ["Initiating person",integrationAccountingName(item.initiating_user_id,names)],
        ["Executing actor",integrationAccountingName(item.actor_id,names)],
        ["Provider account",integrationAccountingName(item.provider_account_id,names)],
        ["Model",integrationAccountingName(item.model_id,names)],
        ["Provider result",item.result_state],["Task outcome",item.task_outcome],
        ["Result event · UTC",item.result_observed_at||"Not observed"],
        ["Usage event · UTC",item.usage_observed_at||"Not observed"],
        ["Native usage",integrationAccountingUnits(item)],
        ["Usage provenance",item.usage_provenance||"Not reported"],
        ["Cost",integrationAccountingCost(item)],
        ["Attempt role",role],["Predecessor",item.predecessor_attempt_id||"None recorded"]
      ]),integrationButton("Open full attempt record",()=>integrationGo("accounting",item.attempt_id,integrationRoute().params)));
    for(const button of timeline.querySelectorAll("[data-attempt-id]"))
      button.classList.toggle("selected",button.dataset.attemptId===item.attempt_id);
  }
  for(const [time,peers] of clusters){
    const cluster=node("div",undefined,"accounting-time-cluster");
    cluster.append(node("strong",integrationAccountingTime(time)+" · "+peers.length+
      (peers.length===1?" attempt":" overlapping starts")));
    const choices=node("div",undefined,"accounting-time-choices");
    for(const item of peers){
      const button=integrationButton(item.attempt_id.slice(-8)+" · "+item.result_state+
        " · "+(item.usage_state==="known"?"usage reported":"usage unknown"),()=>inspect(item));
      button.dataset.attemptId=item.attempt_id;
      button.title=item.attempt_id+" · exact recorded start "+item.started_at;
      choices.append(button);
    }
    cluster.append(choices);timeline.append(cluster);
  }
  timeline.append(node("p","Groups share the exact recorded start second. Spacing is a list, not elapsed time. Result and usage event timestamps are shown in the selected attempt; provider completion and duration are not recorded.","demo-legend"));
  if(rows.length)inspect(rows[0]);
  return layout;
}
async function integrationAccounting(){
  const route=integrationRoute(),routeHash=window.location.hash,root=$("view-content"),source=["external","native","demo","classic"].includes(route.params.get("source"))?
    route.params.get("source"):route.params.get("tab")==="native"?"native":"external",
    tab=integrationAccountingTabs.some(([id])=>id===route.params.get("tab"))?route.params.get("tab"):"overview";
  const context=node("div",undefined,"integration-accounting-context"),label=node("label","Accounting source"),select=node("select");
  select.setAttribute("aria-label","Accounting source");
  for(const [id,title] of [["external","Vega and external observations"],["native","Native EzLLMRouter · this profile"],
    ["demo","EzLLMRouter demo · 14 days"],["classic","Original DEV-09 replay"]]){const option=node("option",title);option.value=id;select.append(option);}
  select.value=source;select.onchange=()=>{const params=source==="demo"&&integrationUi.demoReturnParams?
    new URLSearchParams(integrationUi.demoReturnParams):new URLSearchParams(route.params);
    params.set("source",select.value);params.delete("tab");params.delete("page");
    if(source==="demo")for(const key of ["workflow_id","filter_workflow_id","from_date","to_date",
      "person_id","actor_id","provider_id","model_id"])params.delete(key);
    integrationAccountingNavigate(params);};label.append(select);
  context.append(label,integrationButton("Open demo workspace",()=>{const params=new URLSearchParams(route.params);
    if(source!=="demo")integrationUi.demoReturnParams=new URLSearchParams(route.params);
    params.set("source","demo");params.delete("workflow_id");
    for(const key of ["collection","story","person","actor","provider","filter_workflow_id",
      "from_date","to_date","person_id","actor_id","provider_id","model_id"])params.delete(key);
    params.delete("tab");integrationAccountingNavigate(params);},"action"));root.append(context);
  if(source==="classic"){
    demoUi.open=true;
    for(const key of ["collection","story","person","actor","provider"]){
      const value=route.params.get(key);
      demoUi[key]=value||(key==="collection"?"team":key==="story"?"oren_opportunity":"");
    }
    await demoWorkspace();return;
  }
  demoStop();demoUi.open=false;
  const tabs=node("nav",undefined,"actions accounting-subnav");tabs.setAttribute("aria-label","Accounting sections");
  for(const [id,label] of integrationAccountingTabs){const button=integrationButton(label,()=>integrationAccountingSet("tab",id),
    id===tab?"action":"quiet");button.setAttribute("aria-current",id===tab?"page":"false");tabs.append(button);}
  root.append(tabs);
  if(source==="demo"){
    if(route.params.has("workflow_id")&&tab!=="tasks"){
      const params=new URLSearchParams(route.params);params.set("tab","tasks");
      integrationAccountingNavigate(params);return;
    }
    $("view-title").textContent="Accounting · "+integrationAccountingTabs.find(([id])=>id===tab)[1];
    await mach33DemoView(root,route,tab);return;
  }
  if(source==="native"){
    root.append(node("p","Native EzLLMRouter submissions in this operator profile. External observations are on the other Accounting sections. Other service profiles have separate stores and authorization.","scope-note"));
    costUi.tab=tab;await usage({embedded:true});$("view-title").textContent="Accounting · "+integrationAccountingTabs.find(([id])=>id===tab)[1];return;
  }
  const shell=await integrationShell();if(!shell||window.location.hash!==routeHash)return;
  const {datasetId,dataset,datasets}=shell;
  $("view-title").textContent="Accounting · "+integrationAccountingTabs.find(([id])=>id===tab)[1];
  const report=await api("/operator/v1/integration/report?"+integrationReportQuery(route,datasetId));
  if(window.location.hash!==routeHash)return;
  const names=new Map(),synthetic=/(^|[._-])synthetic([._-]|$)/.test(datasetId+" "+dataset.environment_id);
  if(state.role==="registry_admin"){
    const source=datasets.find(item=>item.dataset_id.includes("credentials"))||dataset;
    const metadata=await Promise.allSettled([
      api("/operator/v1/integration/connections?dataset_id="+encodeURIComponent(source.dataset_id)),
      api("/operator/v1/integration/vega-me")
    ]);
    if(metadata.some(item=>item.status==="rejected"&&item.reason.staleView))return;
    if(window.location.hash!==routeHash)return;
    if(metadata[0].status==="fulfilled")for(const item of metadata[0].value.items){
      names.set(item.account_id,(item.friendly_name||integrationProvider(item.provider))+
        " · "+integrationProvider(item.provider));
      if(report.attempts.some(row=>row.provider_account_id===item.account_id))
        for(const model of item.discovery?.details||[])if(model.id&&model.name&&
          (model.name!==model.id||!names.has(model.id)))names.set(model.id,model.name);
    }
    if(metadata[1].status==="fulfilled"){
      const person=metadata[1].value.user;
      if(person?.id&&person?.name)names.set("user:"+person.id,person.name);
    }
  }
  for(const item of report.attempts){
    if(item.task_id&&!names.has(item.task_id))names.set(item.task_id,integrationAccountingWorkflowName(item));
    if(item.root_run_id&&!names.has(item.root_run_id))names.set(item.root_run_id,integrationAccountingWorkflowName(item));
  }
  root.append(node("p",(synthetic?"Synthetic":"Real")+" collection · "+datasetId+
    " · "+report.attempt_count.toLocaleString("en-US")+" attempts in the current filters. "+
    "Native EzLLMRouter activity is in its own profile.","scope-note"));
  integrationAccountingFilterPanel(root,report,names);
  const exports=node("details",undefined,"panel accounting-export-details");
  exports.append(node("summary","Exact filtered report exports"));
  const exportActions=node("div",undefined,"actions accounting-exports");
  for(const format of ["csv","json"])exportActions.append(integrationButton("Export "+format.toUpperCase(),async()=>{
    try{await integrationDownload("/operator/v1/integration/report?"+
      integrationReportQuery(integrationRoute(),datasetId,{export:format}),"ezllmrouter-integration-report."+format);}
    catch(error){if(error.staleView)return;message(error.message,true);}
  }));
  exports.append(exportActions);root.append(exports);
  if(!report.attempt_count){
    root.append(node("p","No recorded attempts match this collection and filter. Remove a filter to widen the scope.","empty"));
    return;
  }
  if(route.item){
    const item=report.attempts.find(row=>row.attempt_id===route.item);
    if(item)integrationAccountingAttemptDetail(root,item,names);
    else root.append(node("p","Attempt is outside the current filters.","empty"));
    return;
  }
  const usage=integrationAccountingUsage(report.attempts),currencies=Object.keys(report.known_total_by_currency);
  const groups=key=>integrationAccountingGroups(report.attempts,key,names);
  if(tab==="overview"){
    const cards=node("div",undefined,"cards accounting-summary-cards");
    cards.append(card("Attempts",report.attempt_count),
      card("Provider completed",report.attempts.filter(item=>item.result_state==="completed").length),
      card("Usage unavailable",usage.unknown),
      card("Unknown cost",report.unknown_cost_attempts));
    for(const unit of ["input_tokens","output_tokens","cache_read_tokens","cache_write_tokens"]){
      if(usage.units.has(unit))cards.append(card(unit.replaceAll("_"," "),
        integrationAccountingScaledQuantity(usage.units.get(unit))));
    }
    for(const currency of currencies)cards.append(card("Known "+currency,report.known_total_by_currency[currency],true));
    root.append(cards);
    const activity=panel("Activity by UTC day"),days=new Map();
    for(const item of report.attempts){
      const day=item.started_at?.slice(0,10)||"Unknown day";
      if(!days.has(day))days.set(day,[]);
      days.get(day).push(item);
    }
    activity.append(table(["UTC day","Attempts","Reported usage","Provider results","Unknown cost"],
      [...days].map(([day,items])=>[day,items.length,integrationAccountingUsageText(items),
        [...new Set(items.map(item=>item.result_state))].join(" · "),
        items.filter(item=>item.cost_status!=="known").length])));
    root.append(activity);
    root.append(accountingRecordedTrace(report.attempts,names));
    const attempts=node("details",undefined,"panel accounting-records-disclosure");
    attempts.append(node("summary","Contributing attempts · exact records"));
    integrationAccountingAttempts(attempts,report,names);root.append(attempts);
  }else if(tab==="providers"){
    integrationAccountingGroup(root,"Provider comparison · account and usage",groups("provider_account_id"),"provider_account_id");
  }else if(tab==="models"){
    integrationAccountingGroup(root,"Model comparison · native usage and coverage",groups("model_id"),"model_id");
  }else if(tab==="agents"){
    integrationAccountingGroup(root,"Executing agents · direct attempts",groups("actor_id").filter(row=>
      row.items.some(item=>item.actor_kind==="agent"||String(item.actor_id).startsWith("agent."))),"actor_id");
    const other=groups("actor_id").filter(row=>row.items.every(item=>item.actor_kind!=="agent"&&
      !String(item.actor_id).startsWith("agent.")));
    if(other.length)integrationAccountingGroup(root,"Other executing actors · included in collection totals",other,"actor_id");
  }else if(tab==="people"){
    integrationAccountingGroup(root,"Initiating people · attributed attempts",groups("initiating_user_id"),"initiating_user_id");
    if([...new Set(report.attempts.map(item=>item.initiating_user_id))].some(id=>!names.has(id)))
      root.append(node("p","An unresolved user ID remains visible until this browser is signed into Vega as that exact user. The operator does not rename IDs by assumption.","scope-note"));
  }else if(tab==="tasks"){
    integrationAccountingWorkflowView(root,report,names);
  }
  if(["providers","models","agents","people"].includes(tab)){
    const attempts=node("details",undefined,"panel accounting-records-disclosure");
    attempts.append(node("summary","Contributing attempts · inspect exact records"));
    integrationAccountingAttempts(attempts,report,names);root.append(attempts);
  }
}
