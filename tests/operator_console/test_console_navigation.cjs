"use strict";
const {runScript}=require("../../tools/javascript_vm_coverage.cjs");
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const {test}=require("node:test");
const root=path.resolve(__dirname,"../..");
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
const response=(value,status=200)=>({ok:status<400,status,json:async()=>value});
async function settle(){for(let i=0;i<50;i++)await Promise.resolve();}

function harness({pathname="/",hash="#/users",complete=false}={}){
  let document,confirmResult=false,reader=async url=>{
    if(["/operator/v1/models","/operator/v1/principals","/operator/v1/users","/operator/v1/connections","/operator/v1/integration/datasets"].includes(url))return response({items:[]});
    throw Error("Unexpected request: "+url);
  };
  const requests=[],confirmations=[],windowEvents={},documentEvents={},hashEvents=[];
  class Element{
    constructor(tag){this.tag=tag;this.children=[];this._text="";this.value="";this.dataset={};this.attributes={};this.listeners={};this.hidden=false;this.style={};
      const classes=new Set();this.classList={add:(...names)=>names.forEach(name=>classes.add(name)),
        toggle:(name,on)=>on?classes.add(name):classes.delete(name),contains:name=>classes.has(name)};}
    get textContent(){return this._text+this.children.map(child=>child.textContent??String(child)).join("");}
    set textContent(value){this._text=String(value);this.children=[];}
    append(...children){this.children.push(...children);}
    replaceChildren(...children){this._text="";this.children=[...children];}
    setAttribute(key,value){this.attributes[key]=String(value);}
    getAttribute(key){return this.attributes[key]??null;}
    addEventListener(type,callback){(this.listeners[type]??=[]).push(callback);}
    focus(){document.activeElement=this;}
    reportValidity(){return true;}
    get options(){return this.children.filter(child=>child.tag==="option");}
    get childNodes(){return this.children;}
    *walk(){yield this;for(const child of this.children)if(child instanceof Element)yield* child.walk();}
    querySelectorAll(selector){const tag=selector.split("[")[0],attribute=selector.match(/\[([\w-]+)=([^\]]+)\]/);
      return [...this.walk()].filter(item=>item.tag===tag&&(!attribute||item[attribute[1]]===attribute[2]||item.getAttribute(attribute[1])===attribute[2]));}
    querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
  }
  const ids=["workspace","logout","login-view","login-error","login-form","username","password","view-title","view-content","view-message","last-update","refresh","skip-link",
    "password-view","account-button","password-cancel","password-note","password-error","password-form","current-password","new-password","confirm-password"];
  const elements=Object.fromEntries(ids.map(id=>[id,new Element(id.endsWith("form")?"form":"div")]));
  for(const id of ["login-form","password-form"]){const button=new Element("button");button.type="submit";elements[id].append(button);}
  const navigation=["overview","activity","usage","source_providers","models","users","connections","accounting","local_connectors"].map(view=>{
    const button=new Element("button");button.dataset.view=view;return button;});
  const location={pathname,search:""};let currentHash=hash;
  Object.defineProperty(location,"hash",{get:()=>currentHash,set:value=>{if(value!==currentHash){currentHash=value;hashEvents.push(value);}}});
  const history={replaceState(_state,_title,url){const parsed=new URL(url,"http://review.local"+pathname);currentHash=parsed.hash;location.search=parsed.search;}};
  document={title:"EzLLMRouter · Local operations",hidden:false,activeElement:null,getElementById:id=>elements[id],createElement:tag=>new Element(tag),
    querySelectorAll:selector=>selector==="#navigation button"?navigation:[],querySelector:()=>null,
    addEventListener:(type,callback)=>(documentEvents[type]??=[]).push(callback)};
  const context=vm.createContext({console,Node:Element,URLSearchParams,URL,Set,Map,Date,history,document,
    setTimeout:()=>1,clearTimeout(){},setInterval:()=>1,clearInterval(){},crypto:{randomUUID:()=>"review-operation"},
    window:{location,history,confirm:question=>{confirmations.push(question);return confirmResult;},addEventListener:(type,callback)=>(windowEvents[type]??=[]).push(callback)},
    navigator:{clipboard:{writeText:async()=>{}}},fetch:async(url,options={})=>{requests.push({url,options});return reader(url,options);},
    integrationView:async()=>{},integrationAccounting:async()=>{},providers:async()=>{},providerAccessStatus:()=>({label:"Not configured"})});
  const scripts=complete?[...fs.readFileSync(path.join(root,"web/index.html"),"utf8").matchAll(/src="\/([^"?]+\.js)"/g)].map(match=>match[1]):
    ["app.js","catalogue_view.js","activity_usage_view.js","crud_view.js","source_pages.js","integration_console.js","local_connectors_view.js","users_view.js"];
  for(let file of scripts){
    if(complete==="classic"&&file==="demo_workspace_team_view.js")file="demo_workspace_view.js";
    runScript(fs.readFileSync(path.join(root,"web",file),"utf8"),context,{filename:file});
  }
  const run=code=>vm.runInContext(code,context);
  run('state.csrf="review-session";state.role="ordinary";state.userManagement=true;state.username="Review user";state.view="users";localUi.auto=false;showWorkspace()');
  return {context,run,elements,document,requests,confirmations,location,windowEvents,documentEvents,
    read:fn=>{reader=fn;},confirm:value=>{confirmResult=value;},
    async flushHash(){while(hashEvents.length){hashEvents.shift();for(const callback of windowEvents.hashchange||[])callback();await settle();}},
    async dispatch(element,type,event={}){for(const callback of element.listeners[type]||[])await callback(event);await settle();},
    openDraft(){run('crudOpen(crudForm("Edit review record",[{name:"name",label:"Name",value:"Before"}],"Save",()=>render(),async()=>{}))');
      const form=elements["view-content"].querySelector("form"),input=form.querySelector("input[name=name]");input.value="Unsaved edit";input.oninput();return form;}};
}

test("every console script has real counter hits and preserves exact costs and owner-only controls",async()=>{
  for(const complete of [true,"classic"]){
    const h=harness({complete});await settle();
    h.run('state.role="ordinary";state.principal="user.review"');
    const before=h.requests.length;
    assert.equal(h.run('costExact("0.000000001")'),"0.000000001");
    assert.equal(h.run('integrationAccountingDecimal(integrationAccountingAmount("0.000000001"))'),"0.000000001");
    assert.match(h.run('integrationAccountingCost({cost_status:"unknown",usage_state:"known"})'),/Unknown cost/);
    assert.match(h.run('costAmounts({known_subtotals:{USD:"0.000000001"},unknown_cost_attempts:2})'),/USD 0\.000000001.*2 unknown/);
    assert.equal(h.run('scriptedSeconds(61)'),"01:01");
    assert.equal(h.run('demoStamp(61)'),"01:01");
    assert.match(h.run('demoName("__unknown__")'),/Autonomous/);
    h.run('demoStop()');
    assert.equal(h.run('providerAccessStatus({credential_state:"absent"}).label'),"Not set up");
    assert.equal(h.run('providerAccessStatus({credential_state:"present",revision:1,credential_version:1},[{operation:"access",connection_revision:1,credential_version:1,expires_at:"2099-01-01T00:00:00Z",state:"observed",observed_at:"2026-11-21T00:00:00Z"}]).label'),"API access verified");
    const denied=h.run('(()=>{const root=document.createElement("section");connectionRegistration(root,"dataset.synthetic",[],async()=>{});return root;})()');
    assert.match(denied.textContent,/Only the local owner/);
    assert.equal(denied.querySelector("form"),null);
    assert.equal(h.requests.length,before,"read-only controls performed a provider operation");
  }
});

test("Build & context renders current metadata without historical milestones",async()=>{
  for(const litellm of [null,"1.105.1"]){
    const h=harness(),data={
      profile:"LIVE SYNTHETIC DEVELOPMENT",
      build:{commit:"review-commit",tree:"review-tree",fingerprint:"review-fingerprint",dirty:false},
      packages:{server:"9.8.7",python_client:"6.5.4",litellm},
      environment:"local isolated synthetic HTTP/1.1"
    };
    h.read(url=>{assert.equal(url,"/operator/v1/build");return response(data);});
    h.run('state.role="registry_admin";state.view="build"');await h.run("render()");
    assert.equal(h.run("state.lastDiagnostic"),null);
    assert.equal(h.elements["view-title"].textContent,"Build & context");
    const content=h.elements["view-content"].textContent;
    for(const value of ["Running source and environment",data.build.commit,data.build.tree,
      data.build.fingerprint,data.environment,data.packages.server,data.packages.python_client,
      litellm??"Unavailable"])assert(content.includes(value),value);
    assert.doesNotMatch(content,/Unable to load current data|Milestone context/);
    assert.equal(h.elements["view-content"].getAttribute("aria-busy"),"false");
    assert.equal(h.document.activeElement,h.elements["view-title"]);
  }
});

test("exposure acknowledgement requires confirmation and preserves the reviewed revision and reason",async()=>{
  const h=harness();h.run('sourceDetail=async()=>{}');
  const call='sourceAcknowledgeExposure({id:"campaign.one",revision:7,currency:"USD"},{attempt_id:"attempt.unknown",bound_decimal:"0.001",cost_decimal:null})';
  h.run(call);assert.equal(h.requests.length,0);assert.equal(h.elements["view-content"].querySelector("form"),null);
  h.confirm(true);h.run(call);
  const form=h.elements["view-content"].querySelector("form");
  form.querySelector("input[name=reason]").value="Accept the unresolved possible charge";
  await form.onsubmit({preventDefault(){}});
  assert.equal(h.requests.length,1);
  assert.equal(h.requests[0].url,"/operator/v1/personal-campaign");
  assert.deepEqual(JSON.parse(h.requests[0].options.body),{
    action:"acknowledge_exposure",campaign_id:"campaign.one",attempt_id:"attempt.unknown",
    expected_revision:7,reason:"Accept the unresolved possible charge"
  });
  assert.match(h.confirmations[1],/full reservation.*USD 0\.001/);
});

test("late success, failure and expired-session responses cannot replace the current screen",async()=>{
  for(const outcome of ["success","failure","expired","network"]){
    const h=harness(),pending=deferred();h.read(url=>url==="/operator/v1/connections"?pending.promise:response({items:[]}));
    h.run('state.role="registry_admin";state.view="source_providers"');const previous=h.run("render()");await settle();
    h.run('state.role="ordinary";state.view="users"');await h.run("render()");
    if(outcome==="network")pending.reject(TypeError("Connection lost"));
    else pending.resolve(response(outcome==="success"?{items:[]}:{error:"OLD_REQUEST_FAILED"},outcome==="success"?200:outcome==="expired"?401:500));
    await previous;
    assert.equal(h.elements["view-title"].textContent,"Users & Permissions",outcome);
    assert.match(h.elements["view-content"].textContent,/Your account/);
    assert.doesNotMatch(h.elements["view-content"].textContent,/Commercial providers|Unable to load/);
    assert.equal(h.elements.workspace.hidden,false);assert.equal(h.run("state.lastDiagnostic"),null);
  }
});

test("late response bodies and old finally handlers cannot clear a newer loading state",async()=>{
  const h=harness(),oldBody=deferred(),newBody=deferred();let count=0;
  h.read(()=>({ok:true,status:200,json:()=>++count===1?oldBody.promise:newBody.promise}));
  h.run('state.view="source_providers"');const old=h.run("render()");await settle();const current=h.run("render()");await settle();
  oldBody.resolve({items:[]});await old;
  assert.equal(h.elements["view-content"].getAttribute("aria-busy"),"true");
  newBody.resolve({items:[]});await current;
  assert.equal(h.elements["view-content"].getAttribute("aria-busy"),"false");
});

test("opening a form invalidates an outstanding screen load",async()=>{
  const h=harness(),pending=deferred();h.read(()=>pending.promise);h.run('state.view="source_providers"');const load=h.run("render()");await settle();
  const form=h.openDraft();pending.resolve(response({items:[]}));await load;
  assert(h.elements["view-content"].querySelector("form")===form);
  assert.equal(h.elements["view-title"].textContent,"Edit review record");
});

test("browser Back and Forward protect edits in both console entry points",async()=>{
  for(const pathname of ["/","/integration"]){
    const h=harness({pathname});if(pathname==="/integration")h.run('state.role="read_only_operator"');
    await h.run("render()");const form=h.openDraft();
    h.location.hash=pathname==="/integration"?"#/accounting":"#/models";await h.flushHash();
    assert.equal(h.location.hash,"#/users");assert.equal(h.elements["view-content"].querySelector("form"),form);
    assert.equal(h.confirmations.length,1);assert.equal(h.run("crudState.dirty"),true);
    h.confirm(true);h.location.hash=pathname==="/integration"?"#/accounting":"#/models";await h.flushHash();
    assert.equal(h.run("crudState.dirty"),false);assert.equal(h.elements["view-content"].querySelector("form"),null);
    h.openDraft();h.confirm(false);h.location.hash="#/users";await h.flushHash();
    assert.equal(h.run("crudState.dirty"),true);assert.equal(h.confirmations.length,3);
  }
});

test("in-page navigation, Refresh, Sign out and password change respect unsaved edits",async()=>{
  const h=harness();await h.run("render()");const form=h.openDraft();
  assert.equal(h.run('sourceGo("#/models")'),false);assert.equal(h.location.hash,"#/users");
  await h.dispatch(h.elements.refresh,"click");await h.dispatch(h.elements.logout,"click");await h.dispatch(h.elements["account-button"],"click");
  assert.equal(h.elements["view-content"].querySelector("form"),form);assert.equal(h.requests.length,0);assert.equal(h.confirmations.length,4);
  h.confirm(true);h.run('sourceGo("#/models")');await h.flushHash();assert.equal(h.confirmations.length,5,"accepted app navigation prompts only once");
});

test("provider setup and model-choice drafts use the same navigation and reload protection",async()=>{
  const h=harness({pathname:"/integration"});await h.run("render()");
  h.run('integrationUi.add=true;integrationUi.setupDirty=true');assert.equal(h.run('integrationGo("accounting")'),false);
  h.run('integrationUi.add=false;integrationUi.setupDirty=false;integrationUi.drafts.set("account",{dirty:true})');
  assert.equal(h.run('integrationGo("accounting")'),false);
  let prevented=false;for(const fn of h.windowEvents.beforeunload)fn({preventDefault(){prevented=true;}});assert(prevented);
  h.confirm(true);h.run('integrationGo("accounting")');await h.flushHash();assert.equal(h.run("integrationUi.drafts.size"),0);
});

test("an in-flight save cannot be submitted twice or discarded by navigation",async()=>{
  const h=harness(),saved=deferred();let writes=0;h.context.save=()=>{writes++;return saved.promise;};
  h.run('crudOpen(crudForm("Edit",[{name:"name",label:"Name",value:"Review"}],"Save",()=>render(),save))');
  const form=h.elements["view-content"].querySelector("form"),submission=form.onsubmit({preventDefault(){}});
  await form.onsubmit({preventDefault(){}});h.confirm(true);assert.equal(h.run('sourceGo("#/models")'),false);assert.equal(writes,1);
  saved.resolve();await submission;assert.equal(h.run("crudState.saving"),false);assert.match(h.elements["view-message"].textContent,/Save completed/);
});

test("successful saves remain visible after refreshing and after a route change",async()=>{
  const h=harness();h.run('crudOpen(crudForm("Edit",[{name:"name",label:"Name",value:"Review"}],"Save",()=>render(),async()=>{}))');
  await h.elements["view-content"].querySelector("form").onsubmit({preventDefault(){}});
  assert.equal(h.elements["view-message"].textContent,"Save completed.");assert(h.elements["view-message"].classList.contains("success"));
  await h.run("render()");assert.equal(h.elements["view-message"].textContent,"Save completed.");
  h.run('sourceGo("#/models");notify("Connector saved.")');await h.flushHash();
  assert.equal(h.elements["view-message"].textContent,"Connector saved.");
});

test("a completed save does not put its success message on a screen opened during refresh",async()=>{
  const h=harness(),pending=deferred();h.read(()=>pending.promise);
  h.run('crudOpen(crudForm("Edit",[{name:"name",label:"Name",value:"Review"}],"Save",()=>{state.view="source_providers";return render();},async()=>{}))');
  const submission=h.elements["view-content"].querySelector("form").onsubmit({preventDefault(){}});await settle();
  h.run('state.view="users"');await h.run("render()");pending.resolve(response({items:[]}));await submission;
  assert.equal(h.elements["view-message"].textContent,"");
});

test("screen titles, busy state, keyboard focus and the skip link follow the active screen",async()=>{
  const h=harness();await h.run("render()");
  assert.equal(h.document.title,"Users & Permissions · EzLLMRouter");assert.equal(h.document.activeElement,h.elements["view-title"]);
  assert.equal(h.elements["view-content"].getAttribute("aria-busy"),"false");assert.equal(h.elements["skip-link"].hidden,false);
  h.elements.refresh.focus();let prevented=false;
  await h.dispatch(h.elements["skip-link"],"click",{preventDefault(){prevented=true;}});
  assert(prevented);assert.equal(h.document.activeElement,h.elements["view-title"]);assert.equal(h.location.hash,"#/users");
  h.run("accountChangePassword()");assert.equal(h.document.title,"Change password · EzLLMRouter");assert.equal(h.elements["skip-link"].hidden,true);
  await h.dispatch(h.elements["password-cancel"],"click");assert.equal(h.document.activeElement,h.elements["account-button"]);
});

test("sign-out invalidates pending reads and hides the authenticated skip link",async()=>{
  const h=harness(),pending=deferred();h.read(()=>pending.promise);h.run('state.view="source_providers"');const load=h.run("render()");await settle();
  h.run("showLogin()");pending.resolve(response({items:[]}));await load;
  assert.equal(h.document.title,"Sign in · EzLLMRouter");assert.equal(h.elements["skip-link"].hidden,true);assert.equal(h.elements.workspace.hidden,true);
  assert.equal(h.document.activeElement,h.elements.username);
});

test("a session-restoration response cannot reopen the workspace after sign-out",async()=>{
  const h=harness(),pending=deferred();h.read(()=>pending.promise);h.run("showLogin()");
  for(const callback of h.documentEvents.DOMContentLoaded)callback();await settle();h.run("showLogin()");
  pending.resolve(response({authenticated:true,csrf:"old-session",role:"ordinary",username:"Old user",user_management:true}));await settle();
  assert.equal(h.elements.workspace.hidden,true);assert.equal(h.run("state.csrf"),null);
});

test("asynchronous button actions quietly stop when their screen has been left",async()=>{
  const h=harness(),pending=deferred();h.read(()=>pending.promise);
  const button=h.run('crudButton("Read details",async()=>{await api("/operator/v1/models");message("Old details");})');
  const clicked=button.onclick();await settle();await h.run("render()");pending.resolve(response({items:[]}));
  await clicked;assert.equal(h.elements["view-message"].textContent,"");
});

test("manual sign-in takes precedence over a pending automatic session restoration",async()=>{
  const h=harness(),restore=deferred(),login=deferred();h.read(url=>url==="/operator/v1/session"?restore.promise:login.promise);
  h.run("showLogin()");for(const callback of h.documentEvents.DOMContentLoaded)callback();await settle();
  h.elements.username.value="new-user";h.elements.password.value="Review passphrase";
  const signingIn=h.elements["login-form"].listeners.submit[0]({preventDefault(){}});await settle();
  restore.resolve(response({authenticated:true,csrf:"old-session",role:"ordinary",username:"old-user",user_management:true}));await settle();
  assert.equal(h.run("state.csrf"),null);assert.equal(h.elements.workspace.hidden,true);
  login.resolve(response({authenticated:true,csrf:"new-session",role:"ordinary",username:"new-user",user_management:true}));await signingIn;
  assert.equal(h.run("state.username"),"new-user");assert.equal(h.elements.workspace.hidden,false);
});

test("an old save finishing after sign-out cannot unlock a newer save",async()=>{
  const h=harness(),old=deferred(),current=deferred();let writes=0;h.read(()=>++writes===1?old.promise:current.promise);
  const open=()=>h.run('crudOpen(crudForm("Edit",[{name:"name",label:"Name",value:"Review"}],"Save",()=>render(),()=>api("/operator/v1/users",{method:"POST",body:{}})))');
  open();const first=h.elements["view-content"].querySelector("form").onsubmit({preventDefault(){}});await settle();
  h.run('showLogin();state.csrf="new-session";state.role="ordinary";state.userManagement=true;showWorkspace()');
  open();const second=h.elements["view-content"].querySelector("form").onsubmit({preventDefault(){}});await settle();
  old.resolve(response({}));await first;assert(h.run("!!crudState.saving"));assert.equal(h.run('sourceGo("#/models")'),false);
  current.resolve(response({}));await second;assert.equal(h.run("crudState.saving"),false);
});
