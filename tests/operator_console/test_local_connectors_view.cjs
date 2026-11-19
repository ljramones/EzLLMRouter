"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
class Element{
  constructor(tag){this.tag=tag;this.children=[];this.textContent="";this.value="";this.dataset={};this.listeners={};
    this.style={};this.classList={add(){},toggle(){}};this.hidden=false;}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.children=[...children];}
  addEventListener(name,fn){(this.listeners[name]??=[]).push(fn);}
  setAttribute(key,value){this[key]=value;}
  focus(){}
  reportValidity(){return true;}
  get options(){return this.children.filter(child=>child.tag==="option");}
  *walk(){yield this;for(const child of this.children)if(child instanceof Element)yield* child.walk();}
  querySelector(selector){const tag=selector.split("[")[0],attribute=selector.match(/\[(\w+)=([^\]]+)\]/);
    return [...this.walk()].find(item=>item.tag===tag&&(!attribute||item[attribute[1]]===attribute[2]));}
}
const ids=["workspace","logout","login-view","login-error","login-form","username","password","view-title",
  "view-content","view-message","last-update","refresh","password-view","account-button","password-cancel",
  "password-note","password-error","password-form","current-password","new-password","confirm-password"];
const elements=Object.fromEntries(ids.map(id=>[id,new Element(id.endsWith("form")?"form":"div")]));
const navigation=["connections","local_connectors","accounting","diagnostics","users"].map(view=>{
  const button=new Element("button");button.dataset.view=view;return button;});
const kinds={ollama:{name:"Ollama",default_url:"http://localhost:11434"},
  lmstudio:{name:"LM Studio",default_url:"http://localhost:1234"},vllm:{name:"vLLM",default_url:"http://localhost:8000"},
  llamacpp:{name:"llama.cpp",default_url:"http://localhost:8080"},localai:{name:"LocalAI",default_url:"http://localhost:8080"},
  openai_compatible:{name:"Other OpenAI-compatible server",default_url:"http://localhost:8000"}};
const requests=[],items=[];let loseDiscoveryResponse=false,rejectDiscoveryCredential=false;
const timers=new Map();let timerId=0,healthState="online",healthCheckedAt=null;
const timer=(fn,delay,repeat)=>{const id=++timerId;timers.set(id,{fn,delay,repeat});return id;};
const context=vm.createContext({console,Node:Element,URLSearchParams,URL,Set,Map,Date,
  setTimeout:(fn,delay)=>timer(fn,delay,false),setInterval:(fn,delay)=>timer(fn,delay,true),
  clearTimeout:id=>timers.delete(id),clearInterval:id=>timers.delete(id),
  crypto:{randomUUID:()=>"operation-test"},history:{replaceState(){}},
  document:{getElementById:id=>elements[id],createElement:tag=>new Element(tag),querySelectorAll:()=>navigation,
    querySelector:()=>null,addEventListener(){}},
  window:{location:{pathname:"/integration",hash:"#/connections"},addEventListener(){},confirm:()=>true},
  integrationView:async()=>{},integrationAccounting:async()=>{},providers:async()=>{},
  navigator:{clipboard:{writeText:async()=>{}}},
  fetch:async(url,options={})=>{
    const method=options.method||"GET",body=options.body?JSON.parse(options.body):null;
    requests.push({url,method,body,headers:options.headers});let value;
    if(url==="/operator/v1/integration/datasets")value={items:[{dataset_id:"dataset.synthetic.local",activated_at:"2026-11-18T00:00:00Z"}]};
    else if(url.startsWith("/operator/v1/integration/connections?"))value={items:[]};
    else if(url==="/operator/v1/local-connectors/check"||url==="/operator/v1/local-connectors/availability")
      value={items:items.map(item=>({connector_id:item.connector_id,availability:{state:method==="POST"?"checking":healthState,
        checked_at:healthCheckedAt||new Date().toISOString(),latency_ms:12}}))};
    else if(url==="/operator/v1/local-connectors/find"||url==="/operator/v1/local-connectors/nearby")
      value={items:[{candidate_id:"nearby.8081",kind:"openai_compatible",base_url:"http://localhost:8081",
        display_name:"Local model API :8081",hint:"LocalAI test port",availability:{state:method==="POST"?"checking":"online"}},
        {candidate_id:"nearby.8080",kind:"openai_compatible",base_url:"http://localhost:8080",
        display_name:"Local model API :8080",hint:"Often llama.cpp or LocalAI",availability:{state:method==="POST"?"checking":"offline"}}]};
    else if(url==="/operator/v1/local-connectors"&&method==="GET")value={items,kinds};
    else if(url==="/operator/v1/local-connectors"&&method==="POST"){
      value={connector_id:"connector.local.test",display_name:body.display_name,kind:body.kind,base_url:body.base_url,
        revision:1,selected_models:[],credential_present:!!body.api_key,enabled:false,status:"not_configured",
        discovery:{state:"not_checked",models:[]}};items.push(value);
    }else if(url.endsWith("/discover")){
      const item=items[0];item.revision++;item.discovery=rejectDiscoveryCredential?
        {state:"failed",reason:"SERVER_AUTHENTICATION_REQUIRED",models:[],complete:false}:
        {state:"observed",complete:true,server_version:"0.12.0",loaded_inventory_available:true,
        models:[{id:"llama3.2:latest",parameter_size:"3.2B",quantization:"Q4_K_M",size_bytes:2019393189,loaded:true,vram_bytes:3100000000},
          {id:"qwen3:8b",size_bytes:5200000000,loaded:false}]};value=item;rejectDiscoveryCredential=false;
      if(loseDiscoveryResponse){loseDiscoveryResponse=false;throw TypeError("Discovery response lost");}
    }else if(url.endsWith("/models")){
      Object.assign(items[0],{selected_models:body.selected_models,enabled:body.enabled,
        status:body.enabled?"connected":"disabled",revision:items[0].revision+1});value=items[0];
    }else if(url==="/operator/v1/local-connectors/connector.local.test"&&method==="GET")value=items[0];
    else if(url==="/operator/v1/local-connectors/connector.local.test"&&method==="POST"){
      Object.assign(items[0],{display_name:body.display_name,kind:body.kind,base_url:body.base_url,
        credential_present:!!body.api_key,revision:items[0].revision+1,discovery:{state:"not_checked",models:[]},selected_models:[],enabled:false});value=items[0];
    }else if(url==="/operator/v1/local-connectors/connector.local.test"&&method==="DELETE")value=items.splice(0,1)[0];
    else throw Error("Unexpected request "+method+" "+url);
    return {ok:true,status:200,json:async()=>JSON.parse(JSON.stringify(value))};
  }});
const root=path.resolve(__dirname,"../..");
for(const file of ["app.js","crud_view.js","source_pages.js","integration_console.js","local_connectors_view.js"])
  vm.runInContext(fs.readFileSync(path.join(root,"web",file),"utf8"),context,{filename:file});
const run=code=>vm.runInContext(code,context);
const findButtons=label=>[...elements["view-content"].walk()].filter(item=>item.tag==="button"&&item.textContent===label);
const text=()=>[...elements["view-content"].walk()].map(item=>item.textContent).join(" ");
const form=()=>elements["view-content"].querySelector("form");
async function syncRoute(){await run('state.view=(window.location.pathname==="/integration"?integrationRoute():sourceRoute()).view;render()');}
async function settle(){for(let i=0;i<20;i++)await Promise.resolve();}
async function fireTimers(delay){await settle();for(const [id,task] of [...timers])if(task.delay===delay&&timers.has(id)){
  if(!task.repeat)timers.delete(id);await task.fn();}await settle();}
async function submit(values){const selected=form();assert(selected,"connector form exists");
  for(const [key,value] of Object.entries(values)){
    const input=selected.querySelector("input[name="+key+"]")||selected.querySelector("select[name="+key+"]");assert(input,key);
    if(input.type==="checkbox")input.checked=value;else input.value=value;input.oninput?.();}
  await selected.onsubmit({preventDefault(){}});return selected;
}
(async()=>{
  run('state.role="registry_admin";state.principal="owner.local";state.csrf="test-csrf";state.view="connections";showWorkspace()');
  await run('render()');assert.equal(elements["view-title"].textContent,"External Providers");
  assert.equal(findButtons("Add external provider").length,1);
  findButtons("Add external provider")[0].onclick();await run('render()');
  const externalProvider=form().querySelector("select");
  assert.deepEqual(externalProvider.options.map(option=>option.value),["openai","anthropic","xai"]);
  context.window.location.hash="#/local_connectors";await syncRoute();
  assert.equal(elements["view-title"].textContent,"Local Connectors");
  assert.equal(findButtons("Add external provider").length,0);
  assert.equal(requests.filter(request=>request.url.endsWith("/discover")).length,0);
  findButtons("Add local connector")[0].onclick();
  const type=form().querySelector("select[name=kind]"),url=form().querySelector("input[name=base_url]");
  assert(type.options.some(option=>option.value==="ollama"));
  assert(type.options.some(option=>option.value==="openai_compatible"));
  assert.equal(url.value,"http://localhost:11434");
  type.value="vllm";type.onchange({});assert.equal(url.value,"http://localhost:8000");
  url.value="http://inference:9000";type.value="lmstudio";type.onchange({});assert.equal(url.value,"http://inference:9000");
  await submit({display_name:"Dev Ollama",kind:"ollama",base_url:"http://localhost:11434",api_key:""});
  await syncRoute();
  const discoveryCount=()=>requests.filter(request=>request.url.endsWith("/discover")).length;
  assert.equal(discoveryCount(),1,"only the explicit connect action discovers models");
  assert(text().includes("Q4_K_M"));assert(text().includes("3.2B"));assert(text().includes("Loaded"));
  assert.equal(findButtons("Enable selected models")[0].disabled,true);
  await fireTimers(2000);assert(text().includes("Online"));
  const modelSearch=[...elements["view-content"].walk()].find(item=>item.type==="search");
  modelSearch.value="llama";modelSearch.oninput();
  const choice=[...elements["view-content"].walk()].find(item=>item["aria-label"]==="Select llama3.2:latest");
  choice.checked=true;choice.onchange();assert.equal(findButtons("Enable selected models")[0].disabled,false);
  healthState="offline";await fireTimers(15000);await fireTimers(2000);
  assert(text().includes("Offline"));assert.equal(choice.checked,true);assert.equal(modelSearch.value,"llama");
  assert([...elements["view-content"].walk()].includes(choice),"health updates preserve unsaved model choices and DOM");
  healthState="online";
  await findButtons("Enable selected models")[0].onclick();
  assert.deepEqual(requests.find(request=>request.url.endsWith("/models")).body.selected_models,["llama3.2:latest"]);
  assert.equal(discoveryCount(),1,"saving selection never runs discovery or inference");
  assert(text().includes("Connected"));
  run('state.role="read_only_operator"');await syncRoute();
  assert.equal(findButtons("Discover models").length,0);assert.equal(findButtons("Edit connector").length,0);
  assert([...elements["view-content"].walk()].filter(item=>item.className==="local-model-choice").every(item=>item.disabled));
  const previous=requests.length;context.window.location.pathname="/";await syncRoute();
  assert(text().includes("llama3.2:latest"),"detail works in the native console too");
  assert(requests.slice(previous).every(request=>["/operator/v1/local-connectors","/operator/v1/local-connectors/check"].includes(request.url)));
  run('state.role="registry_admin"');await syncRoute();findButtons("Edit connector")[0].onclick();
  const editForm=await submit({display_name:"Dev Ollama",kind:"ollama",base_url:"http://localhost:11434",api_key:"private-local-test-key"});
  assert.equal(editForm.querySelector("input[name=api_key]").value,"");await syncRoute();
  assert(text().includes("Saved securely"));assert(!text().includes("private-local-test-key"));
  await findButtons("Discover models")[0].onclick();assert.equal(discoveryCount(),2);
  context.window.location.hash="#/local_connectors";await syncRoute();await settle();
  await fireTimers(2000);assert(text().includes("Online"));
  const listSearch=[...elements["view-content"].walk()].find(item=>item.type==="search");
  listSearch.value="Dev";listSearch.oninput();await fireTimers(15000);await fireTimers(2000);
  assert.equal(listSearch.value,"Dev");assert([...elements["view-content"].walk()].includes(listSearch));
  healthCheckedAt=new Date(Date.now()-60000).toISOString();await findButtons("Check now")[0].onclick();await fireTimers(2000);
  assert(text().includes("Check outdated"),"an old Online observation must not stay green as current");healthCheckedAt=null;
  const auto=[...elements["view-content"].walk()].find(item=>item.type==="checkbox");
  auto.checked=false;auto.onchange();const paused=requests.length;await fireTimers(15000);
  assert.equal(requests.length,paused,"paused checks make no requests");
  auto.checked=true;auto.onchange();await settle();await fireTimers(2000);
  context.document.hidden=true;const hidden=requests.length;await fireTimers(15000);
  assert.equal(requests.length,hidden,"hidden page does not probe");context.document.hidden=false;
  await findButtons("Find local servers")[0].onclick();await settle();await fireTimers(2000);
  assert(text().includes("LocalAI test port"));assert.equal(findButtons("Add connector").length,2);
  assert.equal(findButtons("Add connector")[1].disabled,true,"offline scan candidate cannot be added accidentally");
  assert.equal(items.length,1,"finding servers never saves connectors");
  findButtons("Add connector")[0].onclick();assert.equal(form().querySelector("input[name=base_url]").value,"http://localhost:8081");
  const editing=requests.length;await fireTimers(15000);await fireTimers(2000);assert.equal(requests.length,editing,"editing stops polling");
  await findButtons("Cancel")[0].onclick();await syncRoute();await settle();
  await findButtons("Models")[0].onclick();await syncRoute();assert.equal(discoveryCount(),3,"Models refreshes selected server inventory");
  await findButtons("Delete connector")[0].onclick();await syncRoute();assert.equal(items.length,0);
  const creations=()=>requests.filter(request=>request.method==="POST"&&request.url==="/operator/v1/local-connectors").length;
  const beforeRejected=creations();findButtons("Add local connector")[0].onclick();rejectDiscoveryCredential=true;
  const rejectedForm=await submit({display_name:"Rejected credential",kind:"ollama",base_url:"http://localhost:11434",api_key:"rejected-test-key"});
  await syncRoute();
  assert.equal(items.length,1);assert.equal(items[0].enabled,false);assert.equal(items[0].discovery.state,"failed");
  assert.equal(form(),undefined,"a recorded failure retains the saved connector without a second creation form");
  assert(elements["view-message"].textContent.includes("Model discovery was not confirmed"));
  assert(elements["view-message"].textContent.includes("requires a valid API key"));
  assert(!elements["view-message"].textContent.includes("completed"));
  assert.equal(rejectedForm.querySelector("input[name=api_key]").value,"");
  assert(!text().includes("rejected-test-key"));
  await findButtons("Discover models")[0].onclick();
  assert.equal(creations(),beforeRejected+1,"recovery after a credential rejection reuses its connector");
  assert.equal(items[0].discovery.state,"observed");
  await findButtons("Delete connector")[0].onclick();await syncRoute();assert.equal(items.length,0);
  const beforeRecovery=creations();findButtons("Add local connector")[0].onclick();loseDiscoveryResponse=true;
  const recoveryForm=await submit({display_name:"Saved before disconnect",kind:"ollama",base_url:"http://localhost:11434",api_key:"temporary-test-key"});
  await syncRoute();
  assert.equal(creations(),beforeRecovery+1);assert.equal(items.length,1);
  assert.equal(form(),undefined,"a lost discovery response must not leave a second creation form open");
  assert(elements["view-message"].textContent.includes("Connector saved. Model discovery was not confirmed"));
  assert.equal(recoveryForm.querySelector("input[name=api_key]").value,"");
  await findButtons("Discover models")[0].onclick();
  assert.equal(creations(),beforeRecovery+1,"retrying discovery must reuse the saved connector");
  assert(text().includes("Q4_K_M"));assert(!text().includes("temporary-test-key"));
  await findButtons("Delete connector")[0].onclick();await syncRoute();assert.equal(items.length,0);
  assert(requests.filter(request=>request.method!=="GET").every(request=>request.headers["X-EzLLMRouter-CSRF"]==="test-csrf"));
  assert(!requests.some(request=>/api\/(pull|generate|chat)|chat\/completions/.test(request.url)));
  context.window.location.hash="#/connections";await syncRoute();const away=requests.length;
  await fireTimers(15000);await fireTimers(2000);assert.equal(requests.length,away,"navigation stops polling");
  run('showLogin()');assert.equal(run('localUi.active'),null);
  console.log("Connection pages: availability polling, pause/hidden/navigation lifecycle, preserved choices/search, localhost scan, Models refresh, permissions, and connector lifecycle passed.");
})().catch(error=>{console.error(error);process.exitCode=1;});
