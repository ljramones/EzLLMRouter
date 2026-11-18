"use strict";
// The server projects a fixed fictional fixture. This controller only reveals snapshots.
const demoUi={open:false,story:"main",actor:"",provider:"",time:null,speed:1,playing:false,
  selected:null,data:null,timer:null,revision:0};
const demoMoney=value=>"USD "+Number(value||0).toFixed(2);
const demoStamp=seconds=>`${String(Math.floor(seconds/60)).padStart(2,"0")}:${String(seconds%60).padStart(2,"0")}`;
const demoName=id=>demoUi.data?.actors.find(item=>item.id===id)?.name||
  (id==="__unknown__"?"Autonomous / no initiating human":id||"None recorded");
function demoStop(){demoUi.playing=false;if(demoUi.timer){clearInterval(demoUi.timer);demoUi.timer=null;}}
function demoSnapshot(){return [...demoUi.data.snapshots].reverse().find(item=>item.at<=demoUi.time)||demoUi.data.snapshots[0];}
async function demoWorkspace(){
  demoStop();const revision=demoUi.revision,query=new URLSearchParams({story:demoUi.story});
  if(demoUi.actor)query.set("actor",demoUi.actor);
  if(demoUi.provider)query.set("provider",demoUi.provider);
  const result=await api("/operator/v1/demo-workspace?"+query);
  if(revision!==demoUi.revision||!demoUi.open||state.view!=="usage")return;
  demoUi.data=result;
  demoUi.time=demoUi.time===null?demoUi.data.end:Math.min(demoUi.time,demoUi.data.end);
  demoDraw();
}
function demoChange({story=demoUi.story,actor=demoUi.actor,provider=demoUi.provider}={}){
  demoStop();demoUi.story=story;demoUi.actor=actor;demoUi.provider=provider;
  demoUi.time=null;demoUi.selected=null;demoUi.revision++;render();
}
function demoTick(){
  if(!demoUi.open||state.view!=="usage"){demoStop();return;}
  demoUi.time=Math.min(demoUi.data.end,demoUi.time+demoUi.speed);
  if(demoUi.time>=demoUi.data.end)demoStop();
  demoDraw();
}
function demoPlay(){
  if(demoUi.playing){demoStop();demoDraw();return;}
  if(demoUi.time>=demoUi.data.end)demoUi.time=0;
  demoUi.playing=true;demoDraw();demoUi.timer=setInterval(demoTick,250);
}
function demoExport(format){
  const snap=demoSnapshot(),visible=new Set(snap.event_ids),payload={provenance:demoUi.data.label,
    fixture:demoUi.data.identity,story:demoUi.story,actor_filter:demoUi.actor||null,
    provider_filter:demoUi.provider||null,cutoff_seconds:demoUi.time,total:snap.total,
    attempts:snap.attempts,events:demoUi.data.events.filter(item=>visible.has(item.id)),
    actor:snap.actor,provider:snap.provider,user:snap.user,workflows:snap.workflows};
  let body,type;
  if(format==="json"){body=JSON.stringify(payload,null,2)+"\n";type="application/json";}
  else{const columns=["demo_provenance","fixture","cutoff_seconds","attempt_id","story","at","actor","user","owner","run","task","provider","model","input","output","duration","currency","amount_decimal","basis"];
    const quote=value=>'"'+String(value??"").replaceAll('"','""')+'"';
    body=columns.join(",")+"\n"+snap.attempts.map(item=>columns.map(key=>quote({
      ...item,demo_provenance:demoUi.data.label,fixture:demoUi.data.identity,
      cutoff_seconds:demoUi.time}[key])).join(",")).join("\n")+"\n";
    type="text/csv";}
  const url=URL.createObjectURL(new Blob([body],{type})),link=node("a");
  link.href=url;link.download=`ezllmrouter-demo-${demoUi.data.identity}-${demoUi.story}-${demoUi.time}s.${format}`;
  document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function demoSelect(id){
  const event=demoUi.data.events.find(item=>item.id===id);
  if(!event)return;
  demoStop();demoUi.time=event.at;demoUi.selected=id;demoDraw();
}
function demoChart(snap){
  const box=panel("Cumulative simulated cost · step at model attempt completion");
  const svg=document.createElementNS("http://www.w3.org/2000/svg","svg");
  svg.setAttribute("viewBox","0 0 820 220");svg.setAttribute("role","img");
  svg.setAttribute("aria-label",`Cumulative simulated USD through ${demoStamp(demoUi.time)}: ${demoMoney(snap.total.known_subtotals.USD)}. Exact values follow in a table.`);
  const maximum=Math.max(0.01,Number(demoUi.data.snapshots.at(-1).total.known_subtotals.USD||0));
  const x=value=>45+750*value/Math.max(1,demoUi.data.end),y=value=>180-145*Number(value||0)/maximum;
  const line=(tag,attrs)=>{const item=document.createElementNS("http://www.w3.org/2000/svg",tag);
    for(const [key,value] of Object.entries(attrs))item.setAttribute(key,String(value));svg.append(item);return item;};
  line("path",{d:"M45 35 V180 H795",fill:"none",stroke:"#7894a1","stroke-width":1});
  const points=demoUi.data.snapshots.filter(item=>item.at<=demoUi.time);
  let path="M45 180",prior=0;
  for(const point of points){const cost=Number(point.total.known_subtotals.USD||0);
    path+=` H${x(point.at)} V${y(cost)}`;prior=cost;}
  path+=` H${x(demoUi.time)}`;
  line("path",{d:path,fill:"none",stroke:"#5bd4bc","stroke-width":4,"stroke-linejoin":"round"});
  line("circle",{cx:x(demoUi.time),cy:y(prior),r:6,fill:"#ffd887"});
  for(const [label,tx,ty] of [["USD "+maximum.toFixed(2),5,38],["USD 0.00",5,185],["00:00",45,208],[demoStamp(demoUi.data.end),752,208]]){
    const item=line("text",{x:tx,y:ty,fill:"#d7e7ed","font-size":12});item.textContent=label;}
  box.append(svg,node("p","The line changes only when a scripted model attempt completes. Parent spans and messages add no charge.","scope-note"));
  box.append(table(["Elapsed","Cumulative simulated USD","Completed calls"],points.map(point=>[
    demoStamp(point.at),demoMoney(point.total.known_subtotals.USD),point.total.attempts])));
  return box;
}
function demoTimeline(snap){
  const box=panel("Workflow timeline · simulated elapsed time and participant lanes"),visible=new Set(snap.event_ids);
  box.append(node("p","Markers are scripted events. Bars show call spans, not continuous model activity. Select a marker or table event to seek and inspect it.","scope-note"));
  const lanes=node("div",undefined,"demo-lanes"),participants=demoUi.data.actors.filter(actor=>
    demoUi.data.events.some(event=>event.actor===actor.id));
  for(const actor of participants){const row=node("div",undefined,"demo-lane"),label=node("strong",actor.name),track=node("div",undefined,"demo-track");
    for(const attempt of demoUi.data.attempts.filter(item=>item.actor===actor.id && item.start<=demoUi.time)){
      const span=node("span",undefined,"demo-span");span.style.left=`${100*attempt.start/Math.max(1,demoUi.data.end)}%`;
      span.style.width=`${100*(Math.min(demoUi.time,attempt.at)-attempt.start)/Math.max(1,demoUi.data.end)}%`;
      span.title=`${attempt.id} · scripted call span ${demoStamp(attempt.start)}–${demoStamp(attempt.at)}`;
      track.append(span);}
    for(const event of demoUi.data.events.filter(item=>item.actor===actor.id&&visible.has(item.id))){
      const button=node("button","●","demo-marker"+(demoUi.selected===event.id?" selected":""));
      button.type="button";button.style.left=`${100*event.at/Math.max(1,demoUi.data.end)}%`;
      button.setAttribute("aria-label",`${demoStamp(event.at)} ${actor.name}: ${event.label}`);
      button.title=`${demoStamp(event.at)} · ${event.label}`;button.onclick=()=>demoSelect(event.id);track.append(button);}
    row.append(label,track);lanes.append(row);}
  box.append(lanes);
  box.append(table(["Elapsed","Participant","Event","Simulated cost added"],demoUi.data.events.filter(event=>visible.has(event.id)).map(event=>{
    const attempt=snap.attempts.find(item=>item.id===event.attempt);
    const isCompletion=attempt&&attempt.at===event.at;
    return [demoStamp(event.at),demoName(event.actor),costLink(event.kind+" · "+event.label,()=>demoSelect(event.id)),
      isCompletion?demoMoney(attempt.amount_decimal):demoMoney(0)];})));
  return box;
}
function demoDetails(snap){
  const box=panel("Selected event · drill-down"),event=demoUi.data.events.find(item=>item.id===demoUi.selected);
  if(!event){box.append(node("p","Select a timeline marker or event row to inspect its source record.","empty"));return box;}
  const attempt=demoUi.data.attempts.find(item=>item.id===event.attempt),story=demoUi.data.stories.find(item=>item.id===event.story),
    completed=attempt&&snap.attempts.some(item=>item.id===attempt.id),filtered=attempt&&!completed&&attempt.at<=demoUi.time;
  box.append(definition([["Activity",event.kind+" · "+event.label],["Elapsed",demoStamp(event.at)],
    ["Actor",demoName(event.actor)],["Initiating user",attempt?.user?demoName(attempt.user):
      event.story==="vega_scheduled"?"None · autonomous":demoName(event.story==="main"?"demo.user.larry":"demo.user.maya")],
    ["Charging owner",attempt?.owner||"No model charge at this event"],
    ["Task / class",attempt?.task||story?.task_class],["Run",attempt?.run||story?.root_run],
    ["Parent run",attempt?.run&&demoUi.data.snapshots.at(-1).workflows.find(row=>row.run_id===attempt.run)?.parent_run_id||"None"],
    ["Provider / model",attempt?attempt.provider+" / "+attempt.model:"No model attempt"],
    ["Token usage",attempt?`${attempt.input} input · ${attempt.output} output`:"No model attempt"],
    ["Call duration",attempt?attempt.duration+" simulated seconds":"No model attempt"],
    ["Amount",completed?demoMoney(attempt.amount_decimal):filtered?"Outside current cost filter":
      attempt?"Revealed at completion":"USD 0.00 · no model attempt"],
    ["Cost basis",attempt?.basis||"No model attempt"],["Attempt ID",attempt?.id||"None"]]));
  return box;
}
function demoDraw(){
  if(!demoUi.open||state.view!=="usage"||!demoUi.data)return;
  const root=$("view-content");clean(root);$("view-title").textContent="Usage & Costs · demo workspace";
  root.append(node("p",demoUi.data.label,"demo-banner"),node("p",`Fixture ${demoUi.data.identity} · fixed fictional participants, models and rates · no credentials, provider traffic or saved operational attempts.`,"scope-note"));
  const actions=crudActions(crudButton("Return to operational Usage & Costs",()=>{demoStop();demoUi.open=false;demoUi.data=null;demoUi.revision++;render();},"quiet"));root.append(actions);
  const selectors=node("div",undefined,"demo-selectors"),storyLabel=node("label","Story"),storySelect=node("select");
  for(const item of [{id:"all",name:"All four stories"},...demoUi.data.stories]){
    const option=node("option",item.name);option.value=item.id;storySelect.append(option);}
  storySelect.value=demoUi.story;storySelect.onchange=()=>demoChange({story:storySelect.value});storyLabel.append(storySelect);selectors.append(storyLabel);
  for(const [key,labelText,choices] of [["actor","Actor",demoUi.data.actors],["provider","Provider",Object.keys(demoUi.data.rates).map(id=>({id,name:id}))]]){
    const label=node("label",labelText),select=node("select");const any=node("option","All "+labelText.toLowerCase()+"s");any.value="";select.append(any);
    for(const choice of choices){const option=node("option",choice.name);option.value=choice.id;select.append(option);}
    select.value=demoUi[key];select.onchange=()=>demoChange({[key]:select.value});label.append(select);selectors.append(label);}
  root.append(selectors);
  const snap=demoSnapshot(),complete=demoUi.time>=demoUi.data.end,
    outcome=demoUi.story==="all"?"Four scripted outcomes":demoUi.data.stories.find(item=>item.id===demoUi.story)?.outcome;
  const cards=node("div",undefined,"cards");cards.append(card("Simulated task cost",demoMoney(snap.total.known_subtotals.USD)),
    card("Elapsed time",`${demoStamp(demoUi.time)} / ${demoStamp(demoUi.data.end)}`),
    card("Model calls",snap.total.attempts),card("Outcome",complete?outcome:"Scripted workflow in progress",true));root.append(cards);
  const controls=node("div",undefined,"demo-controls"),play=crudButton(demoUi.playing?"Pause":"Play",demoPlay,"action"),
    restart=crudButton("Restart replay",()=>{demoStop();demoUi.time=0;demoUi.selected=null;demoUi.playing=true;demoDraw();demoUi.timer=setInterval(demoTick,250);}),
    reset=crudButton("Reset to start",()=>{demoStop();demoUi.time=0;demoUi.selected=null;demoDraw();});
  const sliderLabel=node("label",`Time slider · ${demoStamp(demoUi.time)}`),slider=node("input");
  slider.type="range";slider.min="0";slider.max=String(demoUi.data.end);slider.step="1";slider.value=String(demoUi.time);
  slider.setAttribute("aria-label","Demo elapsed time in simulated seconds");slider.oninput=()=>{
    demoStop();demoUi.time=Number(slider.value);demoUi.selected=null;demoDraw();};sliderLabel.append(slider);
  const speedLabel=node("label","Playback speed"),speed=node("select");
  for(const value of [1,2,4]){const option=node("option",value+"×");option.value=String(value);speed.append(option);}
  speed.value=String(demoUi.speed);speed.onchange=()=>{demoUi.speed=Number(speed.value);};speedLabel.append(speed);
  controls.append(play,restart,reset,sliderLabel,speedLabel);root.append(controls);
  root.append(node("p","Playback is presentation only. 1× advances one simulated second every 250 ms; speed changes no cost. Filters apply to model costs while timeline events retain story context.","scope-note"));
  root.append(demoTimeline(snap),demoChart(snap),demoDetails(snap));
  root.append(costBarChart("Direct cost by actor · additive",snap.actor),
    costBarChart("Provider breakdown · additive",snap.provider),
    costBarChart("Initiating user attribution · same attempts, not extra spend",snap.user));
  const lineage=panel("Run lineage · inclusive contains direct and delegated; do not add columns");
  lineage.append(table(["Run / actor","Parent","Direct USD","Delegated USD","Inclusive USD"],snap.workflows.map(row=>[
    row.run_id+" · "+demoName(row.agent_id),row.parent_run_id||"Root",
    demoMoney(row.direct.known_subtotals.USD),demoMoney(row.delegated.known_subtotals.USD),
    demoMoney(row.inclusive.known_subtotals.USD)])));root.append(lineage);
  const attempts=panel("Contributing scripted attempts · per-call simulated USD");
  attempts.append(snap.attempts.length?table(["Completion","Attempt / task","Actor / initiating user","Provider / model","Tokens","Amount"],snap.attempts.map(item=>[
    demoStamp(item.at),item.id+" · "+item.task,demoName(item.actor)+" · "+demoName(item.user),
    item.provider+" · "+item.model,`${item.input} in / ${item.output} out`,demoMoney(item.amount_decimal)])):
    node("p","No model attempts completed at this cutoff. Simulated cost is USD 0.00.","empty"));root.append(attempts);
  const coverage=panel("Demo actor coverage");coverage.append(table(["Actor","Coverage"],demoUi.data.actors.filter(item=>item.kind==="scripted agent").map(item=>[
    item.name,item.coverage])));root.append(coverage);
  const stories=panel("Completed reference stories · fictional fixture, separate from playback cutoff");
  stories.append(table(["Story","Scripted elapsed","Calls","Simulated USD"],demoUi.data.stories.map(item=>[
    costLink(item.name,()=>demoChange({story:item.id})),demoStamp(item.end),item.total.attempts,
    demoMoney(item.total.known_subtotals.USD)])));
  stories.append(node("p",`Completed collection reference: ${demoMoney(demoUi.data.all_total.known_subtotals.USD)} across ${demoUi.data.all_total.attempts} attempts. This is the same attempt set seen in “All four stories”, not an added charge.`,"scope-note"));root.append(stories);
  root.append(crudActions(crudButton("Export demo JSON",()=>demoExport("json")),
    crudButton("Export demo CSV",()=>demoExport("csv"))));
}
