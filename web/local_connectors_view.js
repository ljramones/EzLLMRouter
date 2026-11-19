"use strict";
const localUi={kinds:{},search:"",auto:true,generation:0,active:null};
const localProblems={LOCAL_ADDRESS_REQUIRED:"Use localhost, a private LAN address, or a Docker service on your network.",
  INVALID_SERVER_URL:"Enter an HTTP or HTTPS server URL without embedded credentials or a query.",
  USE_SERVER_ORIGIN_OR_V1:"Use the server origin. OpenAI-compatible servers may also use a /v1 base URL.",
  SERVER_NAME_NOT_RESOLVED:"The server name could not be resolved. Check the host or Docker network name.",
  SERVER_UNREACHABLE:"The server could not be reached. Check that it is running and its port is published.",
  SERVER_TIMEOUT:"The server did not respond in time. Check its address and try again.",
  SERVER_CHECK_BLOCKED:"The service environment blocked this connection. Availability could not be checked.",
  SERVER_TLS_FAILED:"The HTTPS certificate could not be verified. Check the server's certificate and trust settings.",
  SERVER_AUTHENTICATION_REQUIRED:"The server requires a valid API key. Edit this connector to set or replace it.",
  DISCOVERY_ENDPOINT_NOT_FOUND:"This server does not expose the selected inventory API. Check the server type and port.",
  REDIRECT_NOT_ALLOWED:"The server redirected the inventory request. Enter its final local address instead.",
  SERVER_RESPONSE_TOO_LARGE:"The inventory exceeds the supported response size.",
  INVALID_SERVER_RESPONSE:"The server returned an invalid model inventory.",
  DISCOVER_AND_SELECT_MODELS_FIRST:"Discover a complete inventory and choose models before enabling this connector.",
  CONNECTOR_CHANGED:"This connector changed. Refresh before saving.",
  CREDENTIAL_STORAGE_UNAVAILABLE:"Encrypted API-key storage is unavailable in this profile.",
  CREDENTIAL_UNAVAILABLE:"The saved API key could not be opened. Restore the original secret key or replace the API key."};
const localProblem=code=>localProblems[code]||code||"Discovery has not been run.";
const localPath=id=>"/operator/v1/local-connectors"+(id?"/"+encodeURIComponent(id):"");
function localStopAvailability(){
  localUi.generation++;const active=localUi.active;localUi.active=null;
  if(active){clearInterval(active.interval);clearTimeout(active.poll);}
}
function localAvailabilityCell(status){
  const box=node("div",undefined,"local-availability");box.setAttribute("role","status");
  localPaintAvailability(box,status);return box;
}
function localPaintAvailability(box,status={}){
  const stale=status.stale||status.checked_at&&Date.now()-Date.parse(status.checked_at)>45000;
  const kind=stale&&status.state!=="checking"?"stale":status.state||"unknown";
  const label={online:"Online",offline:"Offline",checking:"Checking…",attention:"Needs attention",
    blocked:"Check blocked",unknown:"Not checked",stale:"Check outdated"}[kind]||"Not checked";
  clean(box);box.append(node("span",label,"local-signal local-signal-"+kind));
  const checked=status.checked_at?"Checked "+new Date(status.checked_at).toLocaleTimeString()+
    (status.latency_ms===null||status.latency_ms===undefined?"":" · "+status.latency_ms+" ms"):"No check completed";
  box.append(node("small",checked));
  box.title=["attention","blocked","offline"].includes(kind)?localProblem(status.reason):checked;
}
function localStartAvailability(items,targets,nearbyBox=null){
  const active={generation:localUi.generation,route:window.location.pathname+window.location.hash,
    statuses:new Map(items.map(item=>[item.connector_id,item.availability])),targets,nearby:[],nearbyTargets:new Map(),busy:false};
  localUi.active=active;
  active.current=()=>localUi.active===active&&active.generation===localUi.generation&&state.view==="local_connectors"&&
    state.csrf&&!$("workspace").hidden&&window.location.pathname+window.location.hash===active.route;
  active.paint=()=>{for(const [id,cell] of targets)localPaintAvailability(cell,active.statuses.get(id));
    for(const item of active.nearby)localPaintAvailability(active.nearbyTargets.get(item.candidate_id),item.availability);};
  active.drawNearby=()=>{
    if(!nearbyBox)return;clean(nearbyBox);active.nearbyTargets.clear();
    nearbyBox.append(node("h2","Servers on this machine"),node("p","Checks common localhost ports. Server types shown for compatible APIs are suggestions; confirm the type when adding a connector.","scope-note"));
    nearbyBox.append(table(["Server","Address","Availability",""],active.nearby.map(item=>{
      const cell=localAvailabilityCell(item.availability);active.nearbyTargets.set(item.candidate_id,cell);
      const add=crudButton(item.saved_connector_id?"Models":"Add connector",()=>item.saved_connector_id?
        localOpenModels({connector_id:item.saved_connector_id}):localConnectorForm(null,item));
      add.disabled=!item.saved_connector_id&&!["online","attention"].includes(item.availability.state);
      return [item.display_name+" · "+item.hint,item.base_url,cell,add];
    })));
  };
  active.refresh=async({queue=false,force=false,find=false}={})=>{
    if(!active.current()||document.hidden)return;
    if(active.busy){if(find)active.findPending=true;return;}
    active.busy=true;clearTimeout(active.poll);
    try{
      if(items.length){const result=await api(localPath(queue?"check":"availability"),queue?
        {method:"POST",csrf:true,body:{...(items.length<=64?{connector_ids:items.map(item=>item.connector_id)}:{}),force}}:{});
        if(!active.current())return;
        for(const item of result.items)active.statuses.set(item.connector_id,item.availability);}
      if(find||active.nearby.length){
        const scan=find||queue;
        const result=await api(localPath(scan?"find":"nearby"),scan?{method:"POST",csrf:true,body:{force:find||force}}:{});
        if(!active.current())return;active.nearby=result.items;active.drawNearby();
      }
      active.paint();
      if([...active.statuses.values(),...active.nearby.map(item=>item.availability)].some(status=>status?.state==="checking"))
        active.poll=setTimeout(()=>active.refresh(),2000);
    }catch(error){if(error.staleView)return;if(active.current())message("Availability check failed: "+localProblem(error.message),true);}
    finally{active.busy=false;if(active.findPending){active.findPending=false;active.refresh({find:true});}}
  };
  active.interval=setInterval(()=>{if(active.current()){active.paint();if(localUi.auto)active.refresh({queue:true});}},15000);
  active.paint();if(localUi.auto)active.refresh({queue:true});return active;
}
function localAvailabilityControls(root,active){
  const auto=node("input");auto.type="checkbox";auto.checked=localUi.auto;
  auto.onchange=()=>{localUi.auto=auto.checked;if(auto.checked)active.refresh({queue:true});};
  const label=node("label",undefined,"local-auto-check");label.append(auto,node("span","Auto-check every 15 seconds"));
  root.append(crudActions(crudButton("Check now",()=>active.refresh({queue:true,force:true})),label));
}
document.addEventListener("visibilitychange",()=>{
  if(!document.hidden&&localUi.auto)localUi.active?.refresh({queue:true});
});
async function localOpenModels(item){
  if(!crudConfirmLeave())return;crudState.dirty=false;localStopAvailability();
  const generation=localUi.generation,route=window.location.pathname+window.location.hash;
  const currentView=()=>localUi.generation===generation&&state.view==="local_connectors"&&
    window.location.pathname+window.location.hash===route&&state.csrf;
  try{const current=await api(localPath(item.connector_id));
    if(!currentView())return;
    if(state.role==="registry_admin"){
      message("Reading models on "+current.display_name+"…");
      await api(localPath(item.connector_id)+"/discover",{method:"POST",csrf:true,body:{expected_revision:current.revision}});
    }
    if(currentView())localGo(item.connector_id);
  }catch(error){if(error.staleView)return;if(currentView()){await render();message("Could not read models: "+localProblem(error.message),true);}}
}
function localGo(id=null){
  if(!crudConfirmLeave())return;
  crudState.dirty=false;
  if(window.location.pathname==="/integration")return integrationGo("local_connectors",id);
  return sourceGo("#/local_connectors"+(id?"/"+encodeURIComponent(id):""));
}
function localStatus(item){return item.discovery.state==="failed"?"Needs attention":
  {connected:"Connected",disabled:"Disabled",needs_attention:"Needs attention",not_configured:"Choose models"}[item.status]||"Not configured";}
function localBytes(value){
  if(value===null||value===undefined)return "Unknown";
  if(value<1024)return value+" B";
  const unit=Math.min(4,Math.floor(Math.log(value)/Math.log(1024)));
  return (value/1024**unit).toFixed(1)+" "+["B","KiB","MiB","GiB","TiB"][unit];
}
async function localDiscover(item){
  if(!crudConfirmLeave())return;
  crudState.dirty=false;message("Discovering models on "+item.display_name+"…");
  try{await api(localPath(item.connector_id)+"/discover",{method:"POST",csrf:true,
    body:{expected_revision:item.revision}});await render();}
  catch(error){if(error.staleView)return;message("Discovery failed: "+localProblem(error.message),true);}
}
function localConnectorForm(record=null,preset=null){
  const kinds=localUi.kinds,initial=record?.kind||preset?.kind||"ollama";
  let savedId=null;
  const fields=[{name:"display_name",label:"Connection name",value:record?.display_name||preset?.display_name||kinds[initial].name+" local",maxLength:120},
    {name:"kind",label:"Server type",options:Object.entries(kinds).map(([id,spec])=>[id,spec.name]),value:initial},
    {name:"base_url",label:"Server URL",type:"url",value:record?.base_url||preset?.base_url||kinds[initial].default_url,maxLength:512},
    {name:"api_key",label:record?.credential_present?"API key · leave blank to keep the saved key":"API key · optional",type:"password",required:false,maxLength:4096}];
  if(record?.credential_present)fields.push({name:"remove_key",label:"Remove saved API key",type:"checkbox",required:false,value:false});
  const unconfirmed=reason=>({notice:{value:"Connector saved. Model discovery was not confirmed: "+
    localProblem(reason)+" Use Discover models on this connector to retry.",error:true}});
  const form=crudForm(record?"Edit local connector":"Add local connector",fields,record?"Save settings":"Connect and discover models",
    saved=>saved&&savedId?localGo(savedId):localGo(record?.connector_id),async values=>{
      const body={display_name:values.display_name,kind:values.kind,base_url:values.base_url};
      if(!record||values.api_key||values.remove_key)body.api_key=values.remove_key?"":values.api_key;
      if(record)body.expected_revision=record.revision;
      try{
        const item=await api(localPath(record?.connector_id),{method:"POST",csrf:true,body});
        savedId=item.connector_id;
        if(!record){
          try{const discovered=await api(localPath(item.connector_id)+"/discover",{method:"POST",csrf:true,body:{expected_revision:item.revision}});
            if(discovered.discovery?.state!=="observed")return unconfirmed(discovered.discovery?.reason);}
          catch(error){if(error.staleView)throw error;
            return unconfirmed(error.message);}
        }
      }catch(error){if(error.staleView)throw error;throw Error(localProblem(error.message));}
    });
  const type=form.box.querySelector("select[name=kind]"),url=form.box.querySelector("input[name=base_url]"),
    name=form.box.querySelector("input[name=display_name]");
  let previous=initial;const changed=type.onchange;
  type.onchange=event=>{changed?.(event);
    if(!url.value||url.value===kinds[previous].default_url)url.value=kinds[type.value].default_url;
    if(name.value===kinds[previous].name+" local")name.value=kinds[type.value].name+" local";
    previous=type.value;};
  form.box.append(node("p","For a published Ollama port use http://localhost:11434. If EzLLMRouter runs in a container, use a Docker service URL on the same network or host.docker.internal. Changing the server URL or type clears the old key and model selection unless you enter a key for the new endpoint. Discovery reads metadata; it does not download or run a model.","scope-note"));
  crudOpen(form);
}
async function localConfigure(item,selected,enabled){
  message("Saving local model selection…");
  try{await api(localPath(item.connector_id)+"/models",{method:"POST",csrf:true,
    body:{expected_revision:item.revision,selected_models:[...selected],enabled}});
    crudState.dirty=false;const refreshed=render(),generation=viewUi.generation;await refreshed;
    if(generation===viewUi.generation)notify(enabled?"Model choices saved. Connector enabled.":"Connector disabled.");
  }catch(error){if(error.staleView)return;message("Selection not saved: "+localProblem(error.message),true);}
}
async function localDelete(item){
  if(!window.confirm("Delete local connector "+item.display_name+"? Its saved API key will be removed. The container and its models will not be changed."))return;
  try{await api(localPath(item.connector_id),{method:"DELETE",csrf:true,body:{expected_revision:item.revision}});
    crudState.dirty=false;localGo();
  }catch(error){if(error.staleView)return;message("Deletion failed: "+localProblem(error.message),true);}
}
function localConnectorDetail(root,item,targets){
  root.append(crudButton("← Local Connectors",()=>localGo()));
  const admin=state.role==="registry_admin",discovery=item.discovery,models=discovery.models||[];
  const summary=panel(item.display_name);
  const availability=localAvailabilityCell(item.availability);targets.set(item.connector_id,availability);summary.append(availability);
  summary.append(definition([["Server",item.base_url],["Type",localUi.kinds[item.kind]?.name||item.kind],
    ["Status",localStatus(item)],["Server version",discovery.server_version||"Unknown"],
    ["Last discovery",discovery.checked_at||"Not checked"],["API key",item.credential_present?"Saved securely":"Not configured"]]));
  if(admin)summary.append(crudActions(crudButton("Discover models",()=>localDiscover(item),"action"),
    crudButton("Edit connector",()=>localConnectorForm(item)),
    ...(item.enabled?[crudButton("Disable connector",()=>localConfigure(item,new Set(item.selected_models),false))]:[]),
    crudButton("Delete connector",()=>localDelete(item))));
  root.append(summary);
  if(discovery.state==="failed")root.append(node("p",localProblem(discovery.reason),"error"));
  if(discovery.state==="not_checked")root.append(node("p","Choose Discover models to read the server's installed inventory.","scope-note"));
  if(discovery.state==="observed"&&!discovery.complete)root.append(node("p","The inventory is incomplete. Model selection cannot be enabled until complete discovery succeeds.","error"));
  if(discovery.warnings?.length)root.append(node("p","Installed inventory is available. Some optional server-version or loaded-model metadata could not be read.","scope-note"));
  const box=panel(item.kind==="ollama"?"Installed models":"Available models");
  box.append(node("p","Choose models for this connector. These choices do not grant access to users or prove a model can run in the server's available memory.","scope-note"));
  const available=new Set(models.map(model=>model.id)),selected=new Set(item.selected_models.filter(id=>available.has(id))),
    omitted=item.selected_models.filter(id=>!available.has(id));
  if(omitted.length)box.append(node("p","Previously selected models no longer present: "+omitted.join(", "),"error"));
  const searchLabel=node("label","Search models"),search=node("input");search.type="search";searchLabel.append(search);box.append(searchLabel);
  const holder=node("div"),count=node("p"),save=crudButton("Enable selected models",()=>localConfigure(item,selected,true),"action");
  const updateCount=()=>{count.textContent=selected.size+" selected · "+models.length+" discovered";
    save.disabled=!selected.size||discovery.state!=="observed"||!discovery.complete;};
  function draw(){clean(holder);const found=models.filter(model=>model.id.toLowerCase().includes(search.value.toLowerCase()));
    if(!models.length){holder.append(node("p",discovery.state==="observed"?
      "No models were returned. Install or expose models in your server, then discover again.":"No inventory has been discovered.","empty"));return;}
    holder.append(found.length?table(["Use","Model","Parameters / context","Quantization","Size","Loaded","VRAM"],found.map(model=>{
      const choice=node("input");choice.type="checkbox";choice.className="local-model-choice";choice.checked=selected.has(model.id);choice.disabled=!admin;
      choice.setAttribute("aria-label","Select "+model.id);choice.onchange=()=>{
        if(choice.checked)selected.add(model.id);else selected.delete(model.id);crudState.dirty=true;updateCount();};
      return [choice,model.id,model.parameter_size??model.context_window??"Unknown",model.quantization??"Unknown",
        localBytes(model.size_bytes),model.loaded===null||model.loaded===undefined?"Unknown":model.loaded?"Loaded":"Not loaded",localBytes(model.vram_bytes)];
    })):node("p","No matching models.","empty"));}
  search.oninput=draw;box.append(holder,count);if(admin)box.append(save);draw();updateCount();root.append(box);
}
async function localConnectorsView(){
  const generation=localUi.generation,root=$("view-content"),listing=await api(localPath());
  if(generation!==localUi.generation)return;
  localUi.kinds=listing.kinds;const targets=new Map();
  const route=window.location.pathname==="/integration"?integrationRoute():sourceRoute();
  if(route?.item){const item=listing.items.find(record=>record.connector_id===route.item);
    if(item){localConnectorDetail(root,item,targets);localAvailabilityControls(root,localStartAvailability([item],targets));}
    else root.append(node("p","Local connector not found.","empty"));return;}
  const tools=crudActions();if(state.role==="registry_admin")tools.append(crudButton("Add local connector",()=>localConnectorForm(),"action"));
  root.append(node("p","Connect to Ollama or another local model server through its published HTTP API. Supports LM Studio, vLLM, llama.cpp, LocalAI, and other OpenAI-compatible servers.","scope-note"),tools);
  const label=node("label","Search local connectors"),search=node("input");search.type="search";search.value=localUi.search;label.append(search);root.append(label);
  const box=panel("Local servers and containers"),nearbyBox=node("section",undefined,"panel");nearbyBox.hidden=true;root.append(box,nearbyBox);
  box.classList.add("local-connectors-list");nearbyBox.classList.add("local-nearby-list");
  function draw(){clean(box);targets.clear();box.append(node("h2","Local servers and containers"));
    const found=listing.items.filter(item=>[item.display_name,item.kind,item.base_url].join(" ").toLowerCase().includes(localUi.search.toLowerCase()));
    box.append(found.length?table(["Name","Server","Type","Availability","Configuration","Models",""],found.map(item=>{
      const cell=localAvailabilityCell(localUi.active?.statuses.get(item.connector_id)||item.availability);targets.set(item.connector_id,cell);return [
      item.display_name,item.base_url,listing.kinds[item.kind]?.name||item.kind,cell,localStatus(item),
      item.discovery.state==="observed"?(item.discovery.models||[]).length+" discovered · "+item.selected_models.length+" selected":"Not discovered",
      crudButton("Models",()=>localOpenModels(item))];})):node("p",listing.items.length?"No matching connectors.":"No local connectors yet. Add a server or choose Find local servers.","empty"));}
  search.oninput=()=>{localUi.search=search.value;draw();};draw();
  const active=localStartAvailability(listing.items,targets,nearbyBox);localAvailabilityControls(tools,active);
  if(state.role==="registry_admin")tools.append(crudButton("Find local servers",()=>{nearbyBox.hidden=false;return active.refresh({find:true});}));
}
