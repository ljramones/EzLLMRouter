"use strict";
// Read-only playback of server-projected fixture snapshots. No execution API is used here.
const demoUi={open:false,collection:"team",story:"oren_opportunity",person:"",actor:"",provider:"",
  time:null,speed:4,playing:false,wallStart:0,simStart:0,timer:null,selected:null,data:null,
  revision:0,expanded:new Set()};
const demoMoney=value=>"USD "+Number(value||0).toFixed(2);
const demoStamp=value=>`${String(Math.floor(value/60)).padStart(2,"0")}:${String(Math.floor(value)%60).padStart(2,"0")}`;
const demoName=id=>demoUi.data?.actors.find(item=>item.id===id)?.name||
  (id==="demo.team.mach33"?"Fictional demo team":id==="__unknown__"||id===null?
    "Autonomous / no initiating person":id||"None");
const demoStory=id=>demoUi.data?.stories.find(item=>item.id===id);
const demoRunName=id=>{if(!id)return "None · root";
  const run=demoUi.data?.snapshots.at(-1)?.workflows.find(item=>item.run_id===id);
  return run?.agent_id?demoName(run.agent_id):"Direct human request";};
const demoFiltered=()=>!!(demoUi.person||demoUi.actor||demoUi.provider);
function demoNow(){return Math.min(demoUi.data?.end||0,demoUi.simStart+(performance.now()-demoUi.wallStart)*demoUi.speed/1000);}
function demoStop(){if(demoUi.playing)demoUi.time=demoNow();demoUi.playing=false;
  if(demoUi.timer){clearInterval(demoUi.timer);demoUi.timer=null;}}
function demoSnapshot(){return [...demoUi.data.snapshots].reverse().find(item=>item.at<=demoUi.time)||demoUi.data.snapshots[0];}
function demoVisible(){return demoUi.open&&(state.view==="usage"||
  (state.view==="accounting"&&integrationRoute().params.get("source")==="classic"));}
async function demoWorkspace(){
  demoStop();const revision=demoUi.revision,query=new URLSearchParams({collection:demoUi.collection,story:demoUi.story});
  for(const key of ["person","actor","provider"])if(demoUi[key])query.set(key,demoUi[key]);
  const result=await api("/operator/v1/demo-workspace?"+query);
  if(revision!==demoUi.revision||!demoVisible())return;
  demoUi.data=result;demoUi.time=demoUi.time===null?result.end:Math.min(demoUi.time,result.end);
  demoUi.selected=null;demoDraw();
}
function demoChange(changes){
  demoStop();const changedCollection=changes.collection&&changes.collection!==demoUi.collection;
  Object.assign(demoUi,changes);
  if(changedCollection)demoUi.story=demoUi.collection==="legacy"?"main":demoUi.collection==="expanded"?"expanded_all":"team";
  demoUi.time=null;demoUi.selected=null;demoUi.expanded.clear();demoUi.revision++;
  if(state.view==="accounting"){
    const params=new URLSearchParams(integrationRoute().params);
    for(const key of ["collection","story","person","actor","provider"]){
      if(demoUi[key])params.set(key,demoUi[key]);else params.delete(key);
    }
    integrationGo("accounting",null,params);
  }else render();
}
function demoTick(){
  if(!demoVisible()){demoStop();return;}
  demoUi.time=demoNow();if(demoUi.time>=demoUi.data.end)demoStop();demoDraw();
}
function demoPlay(){
  if(demoUi.playing){demoStop();demoDraw();return;}
  if(demoUi.time>=demoUi.data.end)demoUi.time=0;
  demoUi.wallStart=performance.now();demoUi.simStart=demoUi.time;demoUi.playing=true;
  demoDraw();demoUi.timer=setInterval(demoTick,200);
}
function demoSeek(value){demoStop();demoUi.time=Math.max(0,Math.min(demoUi.data.end,Number(value)));
  demoUi.selected=null;demoDraw();}
function demoSpeed(value){if(demoUi.playing){demoUi.time=demoNow();demoUi.wallStart=performance.now();demoUi.simStart=demoUi.time;}
  demoUi.speed=Number(value);demoDraw();}
function demoSelect(id){const event=demoUi.data.events.find(item=>item.id===id);if(!event)return;
  demoStop();demoUi.time=event.at;demoUi.selected=id;demoDraw();}
function demoInspect(id){
  if(!demoUi.data?.events.some(item=>item.id===id))return;
  demoUi.selected=id;
  for(const item of document.querySelectorAll(".demo-selected"))item.classList.remove("demo-selected");
  for(const item of document.querySelectorAll("[data-demo-event]"))
    if(item.dataset.demoEvent===id)item.classList.add("demo-selected");
  const holder=document.querySelector("#demo-inspector-body");if(holder)holder.replaceChildren(demoInspectorContents(demoSnapshot()));
  const event=demoUi.data.events.find(item=>item.id===id),line=document.querySelector(".demo-selected-line");
  if(line)line.setAttribute("x1",String(1000*event.at/Math.max(1,demoUi.data.end)));
  if(line)line.setAttribute("x2",String(1000*event.at/Math.max(1,demoUi.data.end)));
}
function demoOption(select,id,label){const item=node("option",label);item.value=id;select.append(item);}
function demoSelectors(root,back){
  const nav=node("div",undefined,"demo-person-nav");
  nav.append(back);
  for(const [label,collection,story] of [["Team activity","team","team"],["Larry","team","main"],
    ["Oren","team","oren_opportunity"],["Brant","team","brant_prototype"],
    ["Andrew","team","andrew_delivery"]]){
    const button=crudButton(label,()=>demoChange({collection,story,person:"",actor:"",provider:""}),
      demoUi.collection===collection&&demoUi.story===story?"action":"quiet");nav.append(button);}
  root.append(nav);
  const box=node("div",undefined,"demo-selectors"),fields=[
    ["collection","Collection",[["team","Team activity · six overlapping stories"],
      ["expanded","Expanded collection · nine stories"],["legacy","Legacy reference · four stories"]]],
    ["story","Story",demoUi.collection==="legacy"?[["all","All four legacy stories"],
      ...demoUi.data.stories.map(item=>[item.id,item.name])]:demoUi.collection==="team"?
      [["team","Team activity · shared clock"],...demoUi.data.stories.filter(item=>
        ["main","oren_opportunity","brant_prototype","andrew_delivery","andrew_direct","scheduled_intelligence"].includes(item.id))
        .map(item=>[item.id,item.name])]:[["expanded_all","All nine expanded stories"],
        ...demoUi.data.stories.map(item=>[item.id,item.name])]],
    ["person","Person",[["","All initiating people"],...demoUi.data.actors.filter(item=>item.kind==="scripted user")
      .map(item=>[item.id,item.name]),["__autonomous__","Autonomous · no initiating person"]]],
    ["actor","Agent",[["","All executing agents"],...demoUi.data.actors.filter(item=>item.kind==="scripted agent")
      .map(item=>[item.id,item.name+" · "+(item.category||"synthetic example")])]],
    ["provider","Provider",[["","All providers"],...Object.keys(demoUi.data.rates)
      .map(id=>[id,id.replace("demo.provider.","").replace(/^./,letter=>letter.toUpperCase())+" · simulated"])]]];
  for(const [key,title,values] of fields){const label=node("label",title),select=node("select");
    select.setAttribute("aria-label",title);for(const [id,name] of values)demoOption(select,id,name);
    select.value=demoUi[key];select.onchange=()=>demoChange({[key]:select.value});label.append(select);box.append(label);}
  root.append(box);
}
function demoControls(root){
  const row=node("div",undefined,"demo-controls"),play=crudButton(demoUi.playing?"Pause":
    demoUi.time>=demoUi.data.end?"Replay":"Play",demoPlay,"action");
  const reset=crudButton("Reset to start",()=>demoSeek(0),"quiet");
  const sliderLabel=node("label",`Seek · ${demoStamp(demoUi.time)} / ${demoStamp(demoUi.data.end)}`),slider=node("input");
  slider.type="range";slider.min="0";slider.max=String(demoUi.data.end);slider.step="1";
  slider.value=String(Math.floor(demoUi.time));slider.setAttribute("aria-label","Seek simulated elapsed time");
  slider.oninput=()=>demoSeek(slider.value);sliderLabel.append(slider);
  const speedLabel=node("label","Speed"),speed=node("select");
  for(const value of [1,2,4,8])demoOption(speed,String(value),value+"×");
  speed.value=String(demoUi.speed);speed.onchange=()=>demoSpeed(speed.value);speedLabel.append(speed);
  row.append(play,reset,sliderLabel,speedLabel);root.append(row);
  root.append(node("p","1× = one simulated second per real second; 4× = four. Playback and seeking only reveal fixed records.","demo-playback-note"));
}
function demoEventKind(kind){if(["Request","Follow-up","Revision request"].includes(kind))return "message";
  if(kind==="Handoff"||kind==="Delegation")return "handoff";
  if(kind==="Review feedback")return "review";
  if(kind==="Acceptance"||kind==="Outcome")return "accept";
  return "usage";}
function demoGlyph(kind){return {message:"M",handoff:"↗",review:"!",accept:"✓",usage:"$"}[demoEventKind(kind)];}
function demoMatching(attempt){return (!demoUi.person||attempt.user===(demoUi.person==="__autonomous__"?null:demoUi.person))&&
  (!demoUi.actor||attempt.actor===demoUi.actor)&&(!demoUi.provider||attempt.provider===demoUi.provider);}
function demoTrack(attempts,events,{summary=false}={}){
  const track=node("div",undefined,"demo-track"+(summary?" demo-track-summary":""));
  const cursor=node("span",undefined,"demo-track-cursor");cursor.style.left=`${100*demoUi.time/Math.max(1,demoUi.data.end)}%`;
  track.append(cursor);
  for(const [index,attempt] of attempts.entries()){
    const event=demoUi.data.events.find(item=>item.at===attempt.usage_at&&item.attempt===attempt.id&&item.cost_event);
    const button=node("button",undefined,"demo-call"+(demoMatching(attempt)?"":" demo-context")+
      (attempt.start>demoUi.time?" demo-future":attempt.usage_at>demoUi.time?" demo-pending":"")+
      (summary?" demo-call-summary":""));
    button.type="button";button.style.left=`${100*attempt.start/Math.max(1,demoUi.data.end)}%`;
    button.style.width=`${Math.max(1,100*(attempt.at-attempt.start)/Math.max(1,demoUi.data.end))}%`;
    if(summary)button.style.top=(4+index%3*7)+"px";
    const label=attempt.short||"Call",cost=demoMoney(attempt.amount_decimal);
    button.textContent=summary?"":(attempt.at-attempt.start)/demoUi.data.end>.10?
      label+(attempt.usage_at<=demoUi.time?" · "+cost:""):"";
    button.title=`${demoName(attempt.actor)} · ${label} · ${attempt.duration}s · scripted ${cost} · usage at ${demoStamp(attempt.usage_at)}`;
    button.setAttribute("aria-label",button.title);
    if(event){button.dataset.demoEvent=event.id;button.onfocus=()=>demoInspect(event.id);
      button.onmouseenter=()=>demoInspect(event.id);button.onclick=()=>demoSelect(event.id);}
    track.append(button);}
  for(const event of events.filter(item=>item.at<=demoUi.time&&
      !["Model call start","Model call complete"].includes(item.kind))){
    const related=demoUi.data.attempts.find(item=>item.id===event.attempt),context=demoFiltered()&&
      (!related||!demoMatching(related));
    const kind=demoEventKind(event.kind),button=node("button",demoGlyph(event.kind),"demo-event demo-"+kind+
      (context?" demo-context":"")+
      (demoUi.selected===event.id?" demo-selected":"")+(event.at>demoUi.time?" demo-future":""));
    button.type="button";button.style.left=`${100*event.at/Math.max(1,demoUi.data.end)}%`;
    button.title=`${demoStamp(event.at)} · ${demoName(event.actor)} · ${event.label}`;
    button.setAttribute("aria-label",button.title);button.dataset.demoEvent=event.id;
    button.onfocus=()=>demoInspect(event.id);button.onmouseenter=()=>demoInspect(event.id);
    button.onclick=()=>demoSelect(event.id);track.append(button);}
  return track;
}
function demoLane(label,attempts,events,{summary=false}={}){
  const row=node("div",undefined,"demo-lane"+(summary?" demo-workflow-row":""));
  row.append(node("span",label,"demo-lane-label"),demoTrack(attempts,events,{summary}));return row;
}
function demoTimeline(){
  const box=panel("Participant timeline · shared simulated clock"),axis=node("div",undefined,"demo-time-axis");
  axis.append(node("span","Elapsed"));const ticks=node("div",undefined,"demo-ticks");
  for(let i=0;i<=4;i++){const label=node("span",demoStamp(demoUi.data.end*i/4));label.style.left=`${25*i}%`;ticks.append(label);}
  axis.append(ticks);box.append(axis);
  const ids=demoUi.data.selected_story_ids||[demoUi.story];
  if(ids.length>1){for(const storyId of ids){const info=demoStory(storyId),attempts=demoUi.data.attempts.filter(item=>item.story===storyId),
      events=demoUi.data.events.filter(item=>item.story===storyId&&["Request","Acceptance","Outcome","Handoff","Delegation"].includes(item.kind));
    const group=node("div",undefined,"demo-workflow-group"),head=node("div",undefined,"demo-workflow-head"),
      toggle=crudButton(demoUi.expanded.has(storyId)?"−":"+",()=>{
        if(demoUi.expanded.has(storyId))demoUi.expanded.delete(storyId);else demoUi.expanded.add(storyId);demoDraw();},"quiet");
    toggle.setAttribute("aria-label",(demoUi.expanded.has(storyId)?"Collapse ":"Expand ")+info.name);
    head.append(node("strong",info.name),node("span","Full "+demoMoney(info.total.known_subtotals.USD)+" · "+
      (info.person?demoName(info.person):"Autonomous"),"demo-workflow-note"),toggle);group.append(head);
    group.append(demoLane("Workflow",attempts,events,{summary:true}));
    if(demoUi.expanded.has(storyId))demoAppendParticipantLanes(group,storyId);
    box.append(group);}}
  else demoAppendParticipantLanes(box,ids[0]);
  const legend=node("p","M message · ↗ handoff · ! review · $ usage observed · ✓ scripted outcome · bars are call spans","demo-legend");
  box.append(legend);return box;
}
function demoAppendParticipantLanes(parent,storyId){
  const events=demoUi.data.events.filter(item=>item.story===storyId),attempts=demoUi.data.attempts.filter(item=>item.story===storyId);
  const involved=[...new Set([...events.map(item=>item.actor),...attempts.map(item=>item.actor)])];
  involved.sort((a,b)=>((a.startsWith("demo.user.")?0:1)-(b.startsWith("demo.user.")?0:1))||
    Math.min(...events.filter(item=>item.actor===a).map(item=>item.at),999)-
    Math.min(...events.filter(item=>item.actor===b).map(item=>item.at),999));
  for(const actor of involved)parent.append(demoLane(demoName(actor),attempts.filter(item=>item.actor===actor),
    events.filter(item=>item.actor===actor)));
}
function demoChart(){
  const box=panel("Cumulative simulated cost · usage observations"),svg=document.createElementNS("http://www.w3.org/2000/svg","svg");
  svg.setAttribute("viewBox","0 0 1000 165");svg.setAttribute("role","img");
  svg.setAttribute("aria-label",`Cumulative ${demoMoney(demoSnapshot().total.known_subtotals.USD)} at ${demoStamp(demoUi.time)}; exact table in Details.`);
  const max=Math.max(.01,Number(demoUi.data.snapshots.at(-1).total.known_subtotals.USD||0)),
    x=t=>1000*t/Math.max(1,demoUi.data.end),y=v=>135-110*Number(v||0)/max;
  const add=(tag,attrs,textValue)=>{const item=document.createElementNS("http://www.w3.org/2000/svg",tag);
    for(const [key,value] of Object.entries(attrs))item.setAttribute(key,String(value));
    if(textValue!==undefined)item.textContent=textValue;svg.append(item);return item;};
  for(let i=0;i<=4;i++)add("line",{x1:x(demoUi.data.end*i/4),x2:x(demoUi.data.end*i/4),y1:18,y2:140,
    stroke:"var(--border)","stroke-width":1});
  const points=demoUi.data.snapshots.filter(item=>item.at<=demoUi.time);
  let d="M0 135",last=0;for(const point of points){last=Number(point.total.known_subtotals.USD||0);
    d+=` H${x(point.at)} V${y(last)}`;}d+=` H${x(demoUi.time)}`;
  add("path",{d,fill:"none",stroke:"var(--accent)","stroke-width":4,"stroke-linejoin":"round"});
  add("line",{x1:x(demoUi.time),x2:x(demoUi.time),y1:16,y2:141,stroke:"var(--chart-cursor)","stroke-width":2});
  const selected=demoUi.data.events.find(item=>item.id===demoUi.selected);
  add("line",{class:"demo-selected-line",x1:selected?x(selected.at):-1,x2:selected?x(selected.at):-1,
    y1:16,y2:141,stroke:"var(--event-review)","stroke-width":2,"stroke-dasharray":"4 4"});
  add("circle",{cx:x(demoUi.time),cy:y(last),r:6,fill:"var(--chart-cursor)"});
  add("text",{x:8,y:18,fill:"var(--text)","font-size":15},demoMoney(max));
  add("text",{x:8,y:158,fill:"var(--text-muted)","font-size":13},"USD 0.00");
  box.append(svg,node("p","Cost steps at usage observation, including simultaneous calls. Messages, handoffs and acceptance leave plateaus.","demo-chart-note"));
  return box;
}
function demoInspectorContents(snap){
  const wrap=node("div"),event=demoUi.data.events.find(item=>item.id===demoUi.selected);
  if(!event){const info=demoStory(demoUi.data.selected_story_ids?.[0]);
    if(info?.summary)wrap.append(node("p",info.summary,"demo-inspector-lead"));
    wrap.append(node("p","Select or focus a call, marker or event row to inspect its fictional record.","empty"));return wrap;}
  const attempt=demoUi.data.attempts.find(item=>item.id===event.attempt),info=demoStory(event.story),
    included=attempt&&demoMatching(attempt),charged=attempt&&attempt.usage_at<=demoUi.time&&included,
    parent=attempt?.parent_run_id;
  wrap.append(node("p",event.kind+" · "+event.label,"demo-inspector-lead"));
  wrap.append(definition([["At",demoStamp(event.at)+" simulated"],["Actor",demoName(event.actor)],
    ["Handoff to",event.to?demoName(event.to):"None"],["Initiating person",attempt?.user?demoName(attempt.user):
      info.person?demoName(info.person):"None · scheduled"],
    ["Call duration",attempt?attempt.duration+" simulated seconds":"No model call"],
    ["Simulated amount",attempt?demoMoney(attempt.amount_decimal)+
      (charged?" · included at cursor":included?" · observed at "+demoStamp(attempt.usage_at):" · outside cost filter"):
      "USD 0.00 · no model attempt"],
    ["Provider / model",attempt?demoProvider(attempt.provider)+" / "+attempt.model:"No model attempt"],
    ["Tokens",attempt?`${attempt.input} input · ${attempt.output} output`:"No model attempt"],
    ["Task",info.name],["Executing run",demoRunName(attempt?.run)],
    ["Who delegated",demoRunName(parent)],["Root workflow",info.name],
    ["Charging owner",demoName(attempt?.owner||info.owner)],
    ["Usage observed",attempt?demoStamp(attempt.usage_at):"No usage record"]]));
  if(attempt){const technical=node("details",undefined,"demo-inspector-technical");
    technical.append(node("summary","Technical IDs and calculation basis"),definition([
      ["Attempt ID",attempt.id],["Task ID",attempt.task],["Run ID",attempt.run],
      ["Parent run ID",parent||"None"],["Root run ID",attempt.root_run_id],
      ["Owner ID",attempt.owner],["Rate reference",attempt.rate_ref],["Basis",attempt.basis]]));wrap.append(technical);}
  return wrap;
}
function demoProvider(id){return id?.replace("demo.provider.","").replace(/^./,value=>value.toUpperCase())||"Unknown";}
function demoMiniBars(title,rows,names){
  const box=panel(title),ordered=[...rows].sort((a,b)=>Number(b.known_subtotals.USD||0)-Number(a.known_subtotals.USD||0)),
    max=Math.max(.01,...ordered.map(item=>Number(item.known_subtotals.USD||0)));
  if(!ordered.length){box.append(node("p","No matching observed attempts at this cutoff.","empty"));return box;}
  for(const row of ordered){const line=node("div",undefined,"demo-mini-row"),label=node("span",names(row.id)),
    track=node("span",undefined,"demo-mini-track"),fill=node("span",undefined,"demo-mini-fill");
    fill.style.width=`${100*Number(row.known_subtotals.USD||0)/max}%`;track.append(fill);
    line.append(label,track,node("strong",demoMoney(row.known_subtotals.USD)));box.append(line);}
  return box;
}
function demoExport(format){
  const snap=demoSnapshot(),visible=new Set(snap.event_ids),payload={provenance:demoUi.data.label,
    fixture:demoUi.data.identity,collection:demoUi.collection,story:demoUi.story,
    filters:{person:demoUi.person||null,agent:demoUi.actor||null,provider:demoUi.provider||null},
    cutoff_seconds:Math.floor(demoUi.time),total:snap.total,full_total:snap.full_total,
    attempts:snap.attempts,events:demoUi.data.events.filter(item=>visible.has(item.id)),
    actor:snap.actor,provider:snap.provider,model:snap.model,user:snap.user,workflows:snap.workflows};
  let body,type;
  if(format==="json"){body=JSON.stringify(payload,null,2)+"\n";type="application/json";}
  else{const columns=["demo_provenance","fixture","collection","story_filter","cutoff_seconds",
      "attempt_id","story","task","run_id","parent_run_id","root_run_id","actor","agent_id","user","owner",
      "provider","model","input","output","start","at","usage_at","duration","rate_ref","currency","amount_decimal","basis"];
    const quote=value=>'"'+String(value??"").replaceAll('"','""')+'"';
    body=columns.join(",")+"\n"+snap.attempts.map(item=>columns.map(key=>quote({
      ...item,demo_provenance:demoUi.data.label,fixture:demoUi.data.identity,
      collection:demoUi.collection,story_filter:demoUi.story,cutoff_seconds:Math.floor(demoUi.time)}[key]))
      .join(",")).join("\n")+"\n";type="text/csv";}
  const url=URL.createObjectURL(new Blob([body],{type})),link=node("a");
  link.href=url;link.download=`ezllmrouter-DEMO-${demoUi.data.identity}-${demoUi.collection}-${demoUi.story}-${Math.floor(demoUi.time)}s.${format}`;
  document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function demoDetails(root,snap){
  const details=node("details",undefined,"demo-details"),summary=node("summary","Details · exact events, calls, delegation, rates and reference stories");
  details.append(summary);
  const eventBox=panel("Keyboard-accessible event log");
  eventBox.append(table(["Elapsed","Story","Participant","Event","Observed cost"],
    demoUi.data.events.filter(event=>snap.event_ids.includes(event.id)).map(event=>{
    const attempt=demoUi.data.attempts.find(item=>item.id===event.attempt),button=costLink(event.label,()=>demoSelect(event.id));
    button.onfocus=()=>demoInspect(event.id);button.onmouseenter=()=>demoInspect(event.id);
    return [demoStamp(event.at),demoStory(event.story).name,demoName(event.actor),button,
      attempt&&event.cost_event?(demoMatching(attempt)?demoMoney(attempt.amount_decimal):"Context · excluded"):
        "No charge"]; })));
  details.append(eventBox);
  const exact=panel("Exact cumulative cost at every scripted event");
  exact.append(table(["Elapsed","Filtered simulated USD","Full story USD","Observed calls"],
    demoUi.data.snapshots.map(item=>[demoStamp(item.at),demoMoney(item.total.known_subtotals.USD),
      demoMoney(item.full_total.known_subtotals.USD),item.total.attempts])));details.append(exact);
  const attempts=panel("Per-call records · unique attempts");
  attempts.append(snap.attempts.length?table(["Observation","Actor / initiating person","Run / parent","Provider / model","Tokens / duration","USD"],
    snap.attempts.map(item=>[demoStamp(item.usage_at),demoName(item.actor)+" / "+demoName(item.user),
      item.run+" / "+(item.parent_run_id||"Root"),demoProvider(item.provider)+" / "+item.model,
      `${item.input} in · ${item.output} out · ${item.duration}s`,demoMoney(item.amount_decimal)])):
    node("p","No matching cost-bearing attempts at this cutoff. Empty is not a measured zero for uninstrumented actors.","empty"));
  details.append(attempts);
  const lineage=panel("Who delegated the work");lineage.append(node("p",
    "Direct cost belongs to this run. Delegated cost belongs to its descendant runs. Total including delegated work counts each distinct attempt once; these columns overlap and must not be added.","scope-note"));
  lineage.append(table(["Run / participant","Parent run","Direct cost","Delegated cost","Total including delegated work"],
    snap.workflows.map(row=>[demoName(row.agent_id)+" · "+row.run_id,row.parent_run_id||"Root",
      demoMoney(row.direct.known_subtotals.USD),demoMoney(row.delegated.known_subtotals.USD),
      demoMoney(row.inclusive.known_subtotals.USD)])));details.append(lineage);
  const metadata=panel("Fixture, roster and completed reference amounts");
  metadata.append(node("p",`Fixture ${demoUi.data.identity} · ${demoUi.collection} collection. Legacy four-story subtotal ${demoMoney(demoUi.data.legacy_total?.known_subtotals.USD||demoUi.data.all_total.known_subtotals.USD)}; Team activity ${demoUi.data.team_total?demoMoney(demoUi.data.team_total.known_subtotals.USD):"Not in legacy fixture"}; expanded nine-story collection ${demoUi.data.expanded_total?demoMoney(demoUi.data.expanded_total.known_subtotals.USD):"Not in legacy fixture"}. These are overlapping views of unique attempts.`,"scope-note"));
  metadata.append(table(["Story","Scripted seconds","Calls","Simulated USD"],demoUi.data.stories.map(item=>[
    item.name,item.end,item.total.attempts,demoMoney(item.total.known_subtotals.USD)])));
  metadata.append(table(["Demo participant","Screenshot category / coverage"],demoUi.data.actors.map(item=>[
    item.name,item.category||item.coverage])));
  metadata.append(table(["Served model","Observed simulated USD"],snap.model.map(item=>[
    item.id,demoMoney(item.known_subtotals.USD)])));
  metadata.append(table(["Fictional provider / model","Input per 1,000 tokens","Output per 1,000 tokens"],
    Object.entries(demoUi.data.rates).map(([id,rate])=>[demoProvider(id)+" / "+rate.model,
      demoMoney(rate.input_per_1000_usd),demoMoney(rate.output_per_1000_usd)])));details.append(metadata);
  root.append(details);
}
function demoDraw(){
  if(!demoVisible()||!demoUi.data)return;
  const root=$("view-content");clean(root);$("view-title").textContent="Usage & Costs · scripted team demo";
  root.append(node("p",demoUi.data.label,"demo-banner"),node("p",
    "Familiar names are demo personas. Every request, handoff, result, decision, time and dollar amount here is fictional; no real accounts or agent capabilities are implied. Fixture: "+demoUi.data.identity+".","demo-truth"));
  const back=crudButton(state.view==="accounting"?"← Accounting":"← Operational Usage & Costs",()=>{
    demoStop();demoUi.open=false;demoUi.data=null;demoUi.revision++;
    if(state.view==="accounting"){
      const params=new URLSearchParams(integrationRoute().params);
      for(const key of ["collection","story","person","actor","provider"])params.delete(key);
      params.set("source","external");integrationGo("accounting",null,params);
    }else render();},"quiet");
  demoSelectors(root,back);
  const snap=demoSnapshot(),storyIds=demoUi.data.selected_story_ids||[demoUi.story],
    completed=new Set((snap.outcomes||demoUi.data.events.filter(item=>snap.event_ids.includes(item.id)&&
      ["Acceptance","Outcome"].includes(item.kind))).map(item=>item.story)),
    outcome=storyIds.length===1?(completed.has(storyIds[0])?demoStory(storyIds[0]).outcome:"Awaiting scripted outcome"):
      `${completed.size}/${storyIds.length} scripted outcomes`;
  const cards=node("div",undefined,"cards demo-cards");cards.append(card(demoFiltered()?"Filtered simulated cost":"Simulated task cost",
    demoMoney(snap.total.known_subtotals.USD)),card("Elapsed shared time",demoStamp(demoUi.time)+" / "+demoStamp(demoUi.data.end)),
    card("Observed model calls",snap.total.attempts),card("Outcome",outcome,true));
  if(demoFiltered())cards.append(card("Full story cost through cursor",demoMoney(snap.full_total.known_subtotals.USD)));
  root.append(cards);demoControls(root);
  const layout=node("div",undefined,"demo-visual-layout"),viz=node("div",undefined,"demo-viz"),
    inspector=panel("Selected event · fictional record"),inspectorBody=node("div");
  inspector.id="demo-inspector";inspectorBody.id="demo-inspector-body";
  viz.append(demoTimeline(),demoChart());inspector.append(inspectorBody);
  inspectorBody.append(demoInspectorContents(snap));layout.append(viz,inspector);root.append(layout);
  if(demoFiltered()&&snap.total.attempts===0){const coverage=demoUi.data.actors.find(item=>item.id===demoUi.actor)?.coverage;
    root.append(node("p",(coverage==="Not measured"?"Selected synthetic example is not measured. No observed cost is available.":
      "No matching observed model attempts at this cutoff. Context events remain visible but are not added to filtered cost.")+" Coverage: "+(coverage||"Scripted activity")+".","demo-empty-note"));}
  const breakdown=node("div",undefined,"demo-breakdowns");
  breakdown.append(demoMiniBars("Direct cost by executing participant",snap.actor,demoName),
    demoMiniBars("Provider cost",snap.provider,demoProvider),
    demoMiniBars("Cost by initiating person",snap.user,demoName));root.append(breakdown);
  root.append(crudActions(crudButton("Export demo JSON",()=>demoExport("json")),
    crudButton("Export demo CSV",()=>demoExport("csv"))));
  demoDetails(root,snap);
}
