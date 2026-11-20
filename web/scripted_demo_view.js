"use strict";
// Read-only presentation of one immutable, isolated, synthetic activity scope.
const scriptedUi={report:null,detail:null,selected:null,time:null,playing:false,speed:4,timer:null,
  wallStart:0,simStart:0,request:0,listScroll:0,restoreList:false};
const scriptedFilters=["from_date","to_date","person_id","actor_id","provider_id","model_id","filter_workflow_id"];
const scriptedFmt=value=>value===null||value===undefined?"Unknown":String(value);
const scriptedCount=value=>Number(value||0).toLocaleString("en-US");
const scriptedMoney=value=>{const amount=Number(value||0),digits=amount!==0&&Math.abs(amount)<.01?6:2;
  return "USD "+amount.toLocaleString("en-US",{minimumFractionDigits:digits,maximumFractionDigits:digits});};
const scriptedStamp=value=>value?new Date(value).toLocaleString("en-CA",{timeZone:"America/Toronto",
  month:"short",day:"numeric",hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false})+" Toronto":"Unknown";
const scriptedSeconds=value=>`${String(Math.floor(value/60)).padStart(2,"0")}:${String(Math.floor(value%60)).padStart(2,"0")}`;
function scriptedQuery(params,extra={}){
  const query=new URLSearchParams();
  for(const key of scriptedFilters){const value=params.get(key);if(value)query.set(key==="filter_workflow_id"?"workflow_id":key,value);}
  for(const [key,value] of Object.entries(extra))query.set(key,value);
  return query;
}
function scriptedNavigate(changes){const params=new URLSearchParams(integrationRoute().params);
  for(const [key,value] of Object.entries(changes)){if(value)params.set(key,value);else params.delete(key);}
  params.set("source","demo");integrationGo("accounting",null,params);
}
function scriptedStop(){if(scriptedUi.playing)scriptedUi.time=scriptedNow();scriptedUi.playing=false;
  if(scriptedUi.timer){clearInterval(scriptedUi.timer);scriptedUi.timer=null;}}
function scriptedNow(){return Math.min(scriptedEnd(),scriptedUi.simStart+(performance.now()-scriptedUi.wallStart)*scriptedUi.speed/1000);}
function scriptedEnd(){const detail=scriptedUi.detail;if(!detail)return 0;
  return Math.max(1,...detail.timeline_events.map(event=>event.elapsed_seconds));}
function scriptedGroup(rows){return rows.map(row=>({id:row.id,label:row.display_name||row.id,
  known_subtotals:{USD:row.known_cost_subtotal_usd},unknown_cost_attempts:row.unknown_cost_attempts,
  attempts:row.attempts}));}
function scriptedGroupPanel(root,title,rows,filterKey){
  root.append(costBarChart(title,scriptedGroup(rows),"USD","known simulated subtotal","Attempts",
    filterKey?row=>scriptedNavigate({[filterKey]:row.id,workflow_id:""}):null));
}
function scriptedFiltersPanel(root,report,route){
  const active=scriptedFilters.filter(key=>route.params.has(key)).length;
  const details=node("details",undefined,"panel cost-filters");
  details.append(node("summary",`Demo filters · Toronto local dates · ${active} active`));
  const grid=node("div",undefined,"scripted-filter-grid"),controls={};
  const selections={person_id:report.people.map(item=>[item.id,item.display_name]),
    actor_id:report.agents.map(item=>[item.id,item.display_name]),
    provider_id:report.providers.map(item=>[item.id,item.display_name]),
    model_id:report.models.map(item=>[item.id,item.display_name]),
    filter_workflow_id:report.workflows.map(item=>[item.id,item.title+" · "+item.id])};
  for(const [key,title] of [["from_date","From local date"],["to_date","Through local date"],
    ["person_id","Initiating person"],["actor_id","Executing agent"],["provider_id","Simulated provider"],
    ["model_id","Model profile"],["filter_workflow_id","Workflow"]]){
    const label=node("label",title),input=node(key.endsWith("date")?"input":"select");
    if(key.endsWith("date"))input.type="date";
    else{const all=node("option","All");all.value="";input.append(all);
      for(const [id,name] of selections[key]){const option=node("option",name);option.value=id;input.append(option);}}
    input.value=route.params.get(key)||"";controls[key]=input;label.append(input);grid.append(label);
  }
  details.append(grid);
  const actions=node("div",undefined,"actions");
  actions.append(integrationButton("Apply filters",()=>scriptedNavigate(Object.fromEntries(
    Object.entries(controls).map(([key,input])=>[key,input.value]))),"action"),
    integrationButton("Clear filters",()=>scriptedNavigate(Object.fromEntries(scriptedFilters.map(key=>[key,""])))));
  details.append(actions);root.append(details);
}
function scriptedExports(root,route){const actions=node("div",undefined,"actions accounting-exports");
  for(const format of ["csv","json"])actions.append(integrationButton("Export demo "+format.toUpperCase(),async()=>{
    try{const query=scriptedQuery(route.params,{export:format});
      await integrationDownload("/operator/v1/scripted-demo/report?"+query,
        "ezllmrouter-demo-report."+format);}catch(error){if(error.staleView)return;message("Demo export unavailable: "+error.message,true);}
  }));root.append(actions);
}
function scriptedCards(root,report){const counts=report.counts,cards=node("div",undefined,"cards");
  for(const [label,value] of [["Workflows",scriptedCount(counts.workflows)],
    ["Attempts",scriptedCount(counts.attempts)],
    ["Known simulated USD",scriptedMoney(counts.known_cost_subtotal_usd)],
    ["Unknown cost",scriptedCount(counts.unknown_cost_attempts)],
    ["Input tokens",scriptedCount(counts.known_input_tokens)],
    ["Output tokens",scriptedCount(counts.known_output_tokens)]])cards.append(card(label,value,true));
  root.append(cards);
  const quality=node("details",undefined,"panel scripted-quality");quality.append(node("summary","Exact totals and accounting quality"),
    definition([["Exact known simulated USD",counts.known_cost_subtotal_usd],
      ["Explicit-zero attempts",scriptedCount(counts.explicit_zero_attempts)],
      ["Usage revisions",scriptedCount(counts.usage_revisions)],
      ["Replacement corrections",scriptedCount(counts.replacement_revisions)],
      ["Unknown usage attempts",scriptedCount(counts.unknown_usage_attempts)]]));root.append(quality);
}
function scriptedWorkflowChoices(root,report,selected){const wrap=node("div",undefined,"scripted-workflow-choice"),
  label=node("label","Inspect workflow"),select=node("select");select.setAttribute("aria-label","Inspect workflow");
  for(const item of report.workflows){const option=node("option",item.title+" · "+item.id);option.value=item.id;select.append(option);}
  if(!report.workflows.some(item=>item.id===selected)){
    const option=node("option",selected+" · outside current report filter");option.value=selected;select.append(option);}
  select.value=selected;select.onchange=()=>scriptedNavigate({workflow_id:select.value});label.append(select);wrap.append(label);root.append(wrap);
}
function scriptedSelected(){const events=scriptedUi.detail?.timeline_events||[];
  return events.find(item=>item.id===scriptedUi.selected)||events.filter(item=>item.elapsed_seconds<=scriptedUi.time).at(-1)||events[0];}
function scriptedTraceDraw(){const detail=scriptedUi.detail,holder=$("scripted-demo-trace");if(!detail||!holder)return;
  holder.replaceChildren();const end=scriptedEnd(),now=Math.min(scriptedUi.time??end,end),events=detail.timeline_events,
    steps=detail.observation_cost_steps,workflow=detail.workflow;
  const atSeconds=value=>(new Date(value)-new Date(workflow.started_at))/1000;
  const current=[...steps].reverse().find(step=>atSeconds(step.at)<=now);
  const controls=node("div",undefined,"scripted-playback");
  const toggle=integrationButton(scriptedUi.playing?"Pause":now>=end?"Replay":"Play",()=>{
    if(scriptedUi.playing){scriptedStop();scriptedTraceDraw();return;}
    if(scriptedUi.time>=end)scriptedUi.time=0;
    scriptedUi.simStart=scriptedUi.time;scriptedUi.wallStart=performance.now();scriptedUi.playing=true;
    scriptedUi.timer=setInterval(()=>{if(integrationRoute().params.get("source")!=="demo"){
      scriptedStop();return;}scriptedUi.time=scriptedNow();if(scriptedUi.time>=end)scriptedStop();scriptedTraceDraw();},250);
    scriptedTraceDraw();},"action");
  const seekLabel=node("label",`Seek · ${scriptedSeconds(now)} / ${scriptedSeconds(end)}`),seek=node("input");
  seek.type="range";seek.min="0";seek.max=String(end);seek.step="1";seek.value=String(Math.floor(now));
  seek.setAttribute("aria-label","Seek workflow elapsed time");seek.oninput=()=>{
    scriptedStop();scriptedUi.time=Number(seek.value);scriptedUi.selected=null;scriptedTraceDraw();};seekLabel.append(seek);
  const speedLabel=node("label","Speed"),speed=node("select");
  for(const value of [1,4,16,64]){const option=node("option",value+"×");option.value=value;speed.append(option);}
  speed.value=String(scriptedUi.speed);speed.onchange=()=>{
    if(scriptedUi.playing){scriptedUi.time=scriptedNow();scriptedUi.simStart=scriptedUi.time;
      scriptedUi.wallStart=performance.now();}scriptedUi.speed=Number(speed.value);};speedLabel.append(speed);
  controls.append(toggle,integrationButton("Start",()=>{scriptedStop();scriptedUi.time=0;
    scriptedUi.selected=null;scriptedTraceDraw();}),seekLabel,speedLabel);holder.append(controls);
  const live=node("div",undefined,"cards scripted-live-cards");
  live.append(card("At elapsed",scriptedSeconds(now)),card("Observed simulated USD",
    current?.known_cost_subtotal_usd||"0.000000000"),card("Unknown cost at cursor",
    current?.unknown_cost_attempts||0),card("Observed attempts",current?.observed_attempts||0));holder.append(live);
  const lanes=panel("Execution lanes · events and attempt spans"),track=node("div",undefined,"scripted-lanes");
  const actorIds=[...new Set(events.map(item=>item.actor_id).filter(Boolean))];
  for(const actorId of actorIds){const row=node("div",undefined,"scripted-lane"),name=node("span",
    scriptedUi.report?.agents.find(item=>item.id===actorId)?.display_name||
    scriptedUi.report?.people.find(item=>item.id===actorId)?.display_name||actorId),rail=node("div",undefined,"scripted-rail");
    for(const attempt of detail.attempts.filter(item=>item.executing_actor_id===actorId)){
      const start=atSeconds(attempt.started_at),finish=atSeconds(attempt.ended_at||attempt.started_at),bar=node("span",undefined,"scripted-span");
      bar.style.left=`${Math.max(0,100*start/end)}%`;bar.style.width=`${Math.max(.7,100*(finish-start)/end)}%`;
      bar.title=attempt.attempt_id+" · "+attempt.label;rail.append(bar);}
    for(const event of events.filter(item=>item.actor_id===actorId)){
      const mark=node("button","•","scripted-event"+(event.elapsed_seconds>now?" scripted-future":""));
      mark.type="button";mark.style.left=`${100*event.elapsed_seconds/end}%`;
      mark.title=event.kind+" · "+event.label+" · "+scriptedSeconds(event.elapsed_seconds);
      mark.setAttribute("aria-label",mark.title);mark.onclick=()=>{scriptedStop();scriptedUi.time=event.elapsed_seconds;
        scriptedUi.selected=event.id;scriptedTraceDraw();};rail.append(mark);}
    const cursor=node("span",undefined,"scripted-cursor");cursor.style.left=`${100*now/end}%`;rail.append(cursor);
    row.append(name,rail);track.append(row);}lanes.append(track);holder.append(lanes);
  const curve=panel("Known cost as usage was observed"),svg=document.createElementNS("http://www.w3.org/2000/svg","svg");
  svg.setAttribute("viewBox","0 0 1000 220");svg.setAttribute("role","img");
  svg.setAttribute("aria-label","Cumulative known simulated USD at usage observation time; exact observations follow.");
  const maximum=Math.max(.000000001,...steps.map(step=>Number(step.known_cost_subtotal_usd))),
    positions=steps.map(step=>[Math.max(0,Math.min(1000,1000*atSeconds(step.at)/end)),
      198-176*Number(step.known_cost_subtotal_usd)/maximum]);
  let d="M 0 198",last=198;
  for(const [x,y] of positions){d+=` H ${x.toFixed(2)} V ${y.toFixed(2)}`;last=y;}
  d+=` H 1000`;const path=document.createElementNS("http://www.w3.org/2000/svg","path");
  path.setAttribute("d",d);path.setAttribute("fill","none");path.setAttribute("stroke","var(--accent)");
  path.setAttribute("stroke-width","3");svg.append(path);
  const line=document.createElementNS("http://www.w3.org/2000/svg","line");
  line.setAttribute("x1",String(1000*now/end));line.setAttribute("x2",String(1000*now/end));
  line.setAttribute("y1","12");line.setAttribute("y2","205");line.setAttribute("stroke","var(--chart-cursor)");svg.append(line);
  curve.append(svg,node("p",`Final known subtotal USD ${detail.counts.known_cost_subtotal_usd}; ${steps.length} usage revisions; ${steps.length-detail.attempts.length} replacements. Unknown costs are separate.`,"scope-note"));holder.append(curve);
  const selected=scriptedSelected(),inspector=panel("Selected event and linked records");
  if(selected){inspector.append(definition(Object.entries(selected).map(([key,value])=>
    [key.replaceAll("_"," "),value])));
    const attempt=detail.attempts.find(item=>item.attempt_id===selected.attempt_id);
    if(attempt){inspector.append(node("h3","Attempt · "+attempt.attempt_id),definition([
      ["Task",attempt.task_id],["Run",attempt.run_id],["Executing actor",attempt.executing_actor_name],
      ["Initiating user",attempt.initiating_user_name],["Charging owner",attempt.charging_owner_id],
      ["Provider",attempt.provider_name],["Simulated provider account",attempt.provider_account_id],
      ["Model",attempt.model_name],["Result",attempt.provider_result],
      ["Effective usage revision",attempt.usage_revision_id],["Cost state",attempt.cost_state],
      ["Known simulated USD",attempt.amount_decimal===null?"Unknown":attempt.amount_decimal],
      ["Input tokens",attempt.input_tokens],["Output tokens",attempt.output_tokens]]));
      const history=detail.usage_revisions.filter(item=>item.attempt_id===attempt.attempt_id);
      if(history.length>1)inspector.append(node("h3","Revision history"),table(
        ["Revision","Observed · Toronto","Cost state","Amount · USD"],history.map(item=>[
          item.id,scriptedStamp(item.recorded_at),item.cost_state,item.amount===null?"Unknown":item.amount])));
    }
    const run=detail.runs.find(item=>item.id===selected.run_id);
    if(run)inspector.append(node("h3","Run lineage"),definition([
      ["Run",run.id],["Parent run",run.parent_run_id],["Actor",run.actor_id]]));
  }else inspector.append(node("p","No event at this time.","empty"));holder.append(inspector);
}
function scriptedWorkflowDetail(root,detail){const workflow=detail.workflow;
  const box=panel(workflow.title+" · "+workflow.id);box.append(definition([
    ["Started",scriptedStamp(workflow.started_at)],["Ended",scriptedStamp(workflow.ended_at)],
    ["Outcome",workflow.task_outcome],["Runs",detail.runs.length],["Attempts",detail.counts.attempts],
    ["Known simulated USD",detail.counts.known_cost_subtotal_usd],
    ["Unknown cost attempts",detail.counts.unknown_cost_attempts]]));root.append(box);
  const trace=node("div");trace.id="scripted-demo-trace";root.append(trace);scriptedTraceDraw();
  const sequence=panel("Workflow event trace · exact records");sequence.append(table(
    ["Toronto time","Elapsed","Actor","Kind","Event / link"],detail.timeline_events.map(event=>[
      costLink(scriptedStamp(event.at),()=>{scriptedStop();scriptedUi.time=event.elapsed_seconds;
        scriptedUi.selected=event.id;scriptedTraceDraw();}),scriptedSeconds(event.elapsed_seconds),event.actor_id,
      event.kind,event.label+" · "+event.id+(event.attempt_id?" · "+event.attempt_id:"")])));root.append(sequence);
  const attempts=panel("Contributing attempts · direct attribution");attempts.append(table(
    ["Attempt","Run / actor","Provider / model","Result","Cost state","Observed USD"],
    detail.attempts.map(item=>[item.attempt_id,item.run_id+" · "+item.executing_actor_name,
      item.provider_name+" · "+item.model_name,item.provider_result,item.cost_state,
      item.amount_decimal===null?"Unknown":item.amount_decimal])));root.append(attempts);
  const rollups=panel("Run attribution · direct, delegated and inclusive");rollups.append(table(
    ["Run / actor","Direct USD","Delegated USD","Inclusive USD","Inclusive unknown"],
    detail.run_rollups.map(row=>[row.run_id+" · "+row.actor_id,row.direct.known_cost_subtotal_usd,
      row.delegated.known_cost_subtotal_usd,row.inclusive.known_cost_subtotal_usd,
      row.inclusive.unknown_cost_attempts])));root.append(rollups);
  const revisions=panel("Usage observations and corrections");revisions.append(node("p",
    "Cumulative values replace the prior workflow subtotal at each observation. They are not additive charges; each attempt's effective amount is shown separately.","scope-note"));
  const amounts=new Map(detail.usage_revisions.map(item=>[item.id,item.amount]));
  revisions.append(table(["Observed · Toronto","Revision","Attempt","Revision amount · USD",
    "Cumulative workflow known cost · USD","Unknown"],
    detail.observation_cost_steps.map(step=>[scriptedStamp(step.at),step.revision_id,
      step.attempt_id,amounts.get(step.revision_id)??"Unknown",
      step.known_cost_subtotal_usd,step.unknown_cost_attempts])));root.append(revisions);
}
function scriptedScope(root,report,route,tab){
  const active=scriptedFilters.filter(key=>route.params.get(key)),scoped=active.length>0;
  const context=node("div",undefined,"scripted-scope");context.append(node("strong",
    `EzLLMRouter demo · ${scoped?"filtered report":"dataset report"} · ${scriptedCount(report.counts.attempts)} attempts · ${scriptedMoney(report.counts.known_cost_subtotal_usd)}`));
  context.append(node("span",`Toronto ${route.params.get("from_date")||report.first_local_date} through ${route.params.get("to_date")||report.last_local_date} · cutoff ${scriptedStamp(report.report_cutoff_utc)}`));
  if(scoped){const chips=node("div",undefined,"scripted-chips");for(const key of active){
    const value=route.params.get(key);const name=report.people.find(row=>row.id===value)?.display_name||
      report.agents.find(row=>row.id===value)?.display_name||report.providers.find(row=>row.id===value)?.display_name||
      report.models.find(row=>row.id===value)?.display_name||value;
    chips.append(node("span",`${key.replaceAll("_"," ")}: ${name}`,"pill"));}
    chips.append(integrationButton("Clear filters",()=>scriptedNavigate(Object.fromEntries(scriptedFilters.map(key=>[key,""])))));
    context.append(chips);}
  root.append(context);
}
function scriptedProvenance(root,report){const details=node("details",undefined,"panel scripted-provenance");
  details.append(node("summary","Demo provenance and reporting scope"),definition([
    ["Dataset",report.dataset_id],["Source",report.display_name],["Dates",report.first_local_date+" through "+report.last_local_date+" · "+report.display_timezone],
    ["Reporting cutoff",report.report_cutoff_utc],["Isolation","Synthetic file-backed demo. Owner accounting and Connections are excluded."],
    ["Notice",report.banner]]));root.append(details);}
function scriptedRelatedWorkflows(root,report,rows,title){const ids=new Set(rows.map(row=>row.workflow_id));
  const related=report.workflows.filter(row=>ids.has(row.id));const box=panel(title+" · "+related.length+" workflows");
  box.append(related.length?table(["Workflow / initiator","Started","Outcome","Matching attempts","Matching known USD"],
    related.slice(0,20).map(row=>[costLink(row.title+" · "+row.initiating_user_name,
      ()=>scriptedNavigate({tab:"tasks",workflow_id:row.id})),scriptedStamp(row.started_at),row.task_outcome,
      scriptedCount(row.attempts),row.known_cost_subtotal_usd])):node("p","No matching workflows.","empty"));
  if(related.length>20)box.append(integrationButton("See all matching workflows",()=>scriptedNavigate({tab:"tasks",workflow_id:""})));
  root.append(box);
}
function scriptedFilteredMeasure(rows){let known=0n,unknown=0;
  for(const row of rows){if(row.amount_decimal===null)unknown++;else known+=integrationAccountingAmount(row.amount_decimal);}
  return {attempts:rows.length,unknown,known:integrationAccountingDecimal(known)};
}
function scriptedWorkflowList(root,report,route){const search=(route.params.get("workflow_search")||"").trim().toLowerCase();
  const matches=report.workflows.filter(row=>[row.title,row.id,row.initiating_user_name,row.task_outcome]
    .some(value=>String(value||"").toLowerCase().includes(search)));
  const page=Math.min(Math.max(1,Number(route.params.get("workflow_page")||1)||1),Math.max(1,Math.ceil(matches.length/20)));
  const box=panel("Workflow list · "+matches.length+" matching");box.classList.add("scripted-workflow-list");
  const form=node("form",undefined,"scripted-workflow-search"),
    label=node("label","Search workflows"),input=node("input");input.type="search";input.value=route.params.get("workflow_search")||"";
  input.placeholder="Name, ID, initiator or outcome";label.append(input);form.append(label);
  form.append(integrationButton("Search",()=>scriptedNavigate({workflow_search:input.value,workflow_page:"",workflow_id:""}),"action"));
  form.onsubmit=event=>{event.preventDefault();scriptedNavigate({workflow_search:input.value,workflow_page:"",workflow_id:""});};box.append(form);
  box.append(matches.length?table(["Workflow / initiator","Started · Toronto","Outcome","Attempts","Known USD · exact","Unknown"],
    matches.slice((page-1)*20,page*20).map(row=>[
      costLink(row.title+" · "+row.initiating_user_name,()=>{
        scriptedUi.listScroll=window.scrollY;scriptedNavigate({workflow_id:row.id});}),
      scriptedStamp(row.started_at),row.task_outcome,scriptedCount(row.attempts),row.known_cost_subtotal_usd,
      scriptedCount(row.unknown_cost_attempts)])):node("p","No workflows match this search and report filter.","empty"));
  const nav=node("div",undefined,"pagination"),previous=integrationButton("Previous",()=>scriptedNavigate({workflow_page:String(page-1)})),
    next=integrationButton("Next",()=>scriptedNavigate({workflow_page:String(page+1)}));
  previous.disabled=page<=1;next.disabled=page*20>=matches.length;
  nav.append(previous,node("span",`Page ${page} of ${Math.max(1,Math.ceil(matches.length/20))}`),next);box.append(nav);root.append(box);
  if(report.corrected_workflow_ids.length)root.append(integrationButton("Inspect a corrected usage revision · "+report.corrected_workflow_ids[0],()=>
    scriptedNavigate({workflow_id:report.corrected_workflow_ids[0]})));
}
async function scriptedDemoView(root,route,tab){scriptedStop();const request=++scriptedUi.request,
  routeHash=window.location.hash,
  query=scriptedQuery(route.params),report=await api("/operator/v1/scripted-demo/report?"+query);
  if(request!==scriptedUi.request||window.location.hash!==routeHash)return;
  scriptedUi.report=report;scriptedUi.detail=null;
  root.append(node("p","SIMULATED EZLLMROUTER DEMO · isolated activity · no owner accounting or Connections records",
    "scope-note scripted-banner"));
  scriptedScope(root,report,route,tab);scriptedFiltersPanel(root,report,route);
  if(tab==="overview"){
    scriptedCards(root,report);
    scriptedGroupPanel(root,"Daily known simulated cost · 14 Toronto dates",report.by_local_date);
    const highlights=panel("Provider and model highlights");highlights.append(table(
      ["Dimension","Leading group","Attempts","Known USD · exact"],
      [["Provider",report.by_provider,"provider_id"],["Model",report.by_model,"model_id"]].map(([title,rows,key])=>{
        const top=rows.slice().sort((a,b)=>Number(b.known_cost_subtotal_usd)-Number(a.known_cost_subtotal_usd))[0];
        return top?[title,costLink(top.display_name,()=>scriptedNavigate({tab:key==="provider_id"?"providers":"models",
          [key]:top.id,workflow_id:""})),scriptedCount(top.attempts),top.known_cost_subtotal_usd]:[title,"None",0,"0"];})));
    root.append(highlights);
    const outcomes=panel("Results and outcomes");outcomes.append(definition([
      ["Provider results",JSON.stringify(report.counts.provider_results)],
      ["Workflow outcomes",JSON.stringify(report.counts.workflow_outcomes)],
      ["Unknown usage attempts",report.counts.unknown_usage_attempts]]));root.append(outcomes);
  }else if(tab==="providers"){
    scriptedGroupPanel(root,"Simulated provider comparison",report.by_provider,"provider_id");
    if(route.params.get("provider_id"))scriptedRelatedWorkflows(root,report,report.attempts,"Provider drilldown");
  }else if(tab==="models"){
    scriptedGroupPanel(root,"Model comparison · native usage and cost coverage",report.by_model,"model_id");
    const box=panel("Model native usage · matching attempts");box.append(table(
      ["Model","Input tokens","Output tokens","Unknown usage","Unknown cost"],report.by_model.map(row=>[
        row.display_name,scriptedCount(row.known_input_tokens),scriptedCount(row.known_output_tokens),
        scriptedCount(row.unknown_usage_attempts),scriptedCount(row.unknown_cost_attempts)])));root.append(box);
    if(route.params.get("model_id"))scriptedRelatedWorkflows(root,report,report.attempts,"Model drilldown");
  }else if(tab==="agents"){
    const ids=new Set(report.agents.map(item=>item.id));
    const agents=report.by_executing_actor_direct.filter(row=>ids.has(row.id));
    scriptedGroupPanel(root,"Executing agents · direct attempts and cost",agents,"actor_id");
    root.append(node("p","Direct values count each agent-executed attempt once. Delegated and inclusive run values are available in linked workflow details; inclusive parent and child totals overlap. Human-executed attempts are in People & teams.","scope-note"));
    if(route.params.get("actor_id"))scriptedRelatedWorkflows(root,report,report.attempts,"Associated agent workflows");
  }else if(tab==="people"){
    const scheduled=report.by_initiating_user.filter(row=>row.id==="demo.bucket.scheduled");
    const people=report.by_initiating_user.filter(row=>row.id!=="demo.bucket.scheduled");
    scriptedGroupPanel(root,"Initiating people · all attributed attempts",people,"person_id");
    const agentIds=new Set(report.agents.map(item=>item.id));
    const direct=scriptedFilteredMeasure(report.attempts.filter(row=>!agentIds.has(row.executing_actor_id)));
    const delegated=scriptedFilteredMeasure(report.attempts.filter(row=>agentIds.has(row.executing_actor_id)));
    const activities=panel("Matching activity by executor · additive attempts");activities.append(table(
      ["Executor category","Attempts","Known USD · exact","Unknown cost"],
      [["Direct human activity",direct],["Agent-executed work",delegated]].map(([name,item])=>[
        name,scriptedCount(item.attempts),item.known,scriptedCount(item.unknown)])));root.append(activities);
    if(scheduled.length){const system=panel("Scheduled activity · no initiating person");system.append(table(
      ["Source","Attempts","Known USD · exact","Unknown cost"],scheduled.map(row=>[
        costLink(row.display_name,()=>scriptedNavigate({person_id:row.id,workflow_id:""})),
        scriptedCount(row.attempts),row.known_cost_subtotal_usd,scriptedCount(row.unknown_cost_attempts)])));root.append(system);}
    if(route.params.get("person_id"))scriptedRelatedWorkflows(root,report,report.attempts,"Person or scheduled workflows");
  }else if(tab==="tasks"){
    const selected=route.params.get("workflow_id");
    if(!selected){scriptedWorkflowList(root,report,route);
      if(scriptedUi.restoreList){scriptedUi.restoreList=false;
        const position=scriptedUi.listScroll;setTimeout(()=>window.scrollTo(0,position),100);}}
    else{
      const back=()=>{scriptedUi.restoreList=true;scriptedNavigate({workflow_id:""});};
      root.append(integrationButton("← Back to workflow list",back,"quiet"));
      root.append(node("p","Selected workflow detail · full workflow across all attempts. The compact report context above reflects current filters and may cover a different scope.","scope-note"));
      const detail=await api("/operator/v1/scripted-demo/workflow?workflow_id="+encodeURIComponent(selected));
    if(request!==scriptedUi.request||window.location.hash!==routeHash)return;
    scriptedUi.detail=detail;scriptedUi.selected=null;scriptedUi.time=scriptedEnd();
    scriptedWorkflowDetail(root,detail);
      root.append(integrationButton("← Back to workflow list",back,"quiet"));
    }
  }
  scriptedProvenance(root,report);
  const exports=node("details",undefined,"panel scripted-export-details");
  exports.append(node("summary","Export exact report data"));scriptedExports(exports,route);root.append(exports);
}
