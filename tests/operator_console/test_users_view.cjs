"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
class Element{
  constructor(tag){this.tag=tag;this.children=[];this.value="";this.textContent="";this.hidden=false;
    this.dataset={};this.listeners={};this.style={};this.classList={add(){},toggle(){}};}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.children=[...children];}
  addEventListener(name,fn){(this.listeners[name]??=[]).push(fn);}
  setAttribute(name,value){this[name]=value;}
  focus(){this.focused=true;}
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
for(const id of ["login-form","password-form"]){const button=new Element("button");button.type="submit";elements[id].append(button);}
const navigation=["connections","accounting","diagnostics","users","models"].map(view=>{
  const button=new Element("button");button.dataset.view=view;return button;});
const admin={principal_id:"owner.local",username:"admin",display_name:"Admin",role:"registry_admin",status:"active",
  revision:1,permissions:["users.manage"],must_change_password:true};
const users=[admin],requests=[];let temporary=true;
const session=()=>({authenticated:true,csrf:"csrf-test",role:admin.role,principal_id:admin.principal_id,
  username:admin.username,user_management:true,permissions:admin.permissions,must_change_password:temporary});
const context=vm.createContext({console,Node:Element,URLSearchParams,URL,Set,Date,setTimeout,clearTimeout,
  crypto:{randomUUID:()=>"operation-test"},history:{replaceState(){}},
  document:{getElementById:id=>elements[id],createElement:tag=>new Element(tag),
    querySelectorAll:()=>navigation,addEventListener(){}},
  window:{location:{pathname:"/integration",hash:"#/users"},addEventListener(){},confirm:()=>true},
  integrationViews:new Set(["connections","accounting","diagnostics","users"]),
  integrationRoute:()=>({view:"users",params:new URLSearchParams()}),integrationGo(){},
  sourceRoute:()=>null,sourceGo(){},sourceIndex:async()=>{},sourceDetail:async()=>{},providers:async()=>{},localConnectorsView:async()=>{},
  integrationView:async()=>{},integrationConnections:async()=>{},integrationAccounting:async()=>{},integrationDiagnostics:async()=>{},
  navigator:{clipboard:{writeText:async()=>{}}},
  fetch:async(url,options={})=>{
    const body=options.body?JSON.parse(options.body):null,method=options.method||"GET";
    requests.push({url,method,body,headers:options.headers});let value;
    if(url==="/operator/v1/login")value=session();
    else if(url==="/operator/v1/account/password"){temporary=false;value={authenticated:false,password_changed:true};}
    else if(url==="/operator/v1/users"&&method==="GET")value={items:users.map(user=>({...user})),roles:{}};
    else if(url==="/operator/v1/users"&&method==="POST"){
      const {password,...profile}=body;const user={...profile,principal_id:"user.new",revision:1,permissions:["activity.read_own"]};
      users.push(user);value=user;
    }else if(url==="/operator/v1/users/user.new/password")value={...users[1],revision:++users[1].revision};
    else if(url==="/operator/v1/users/user.new"&&method==="POST"){
      const {expected_revision,...profile}=body;Object.assign(users[1],profile);users[1].revision++;value=users[1];
    }else if(url==="/operator/v1/users/user.new"&&method==="DELETE")value=users.splice(1,1)[0];
    else throw Error("Unexpected request: "+method+" "+url);
    return {status:200,ok:true,json:async()=>JSON.parse(JSON.stringify(value))};
  }});
const root=path.resolve(__dirname,"../..");
for(const file of ["app.js","crud_view.js","users_view.js"])
  vm.runInContext(fs.readFileSync(path.join(root,"web",file),"utf8"),context,{filename:file});
const run=code=>vm.runInContext(code,context);
const buttons=label=>[...elements["view-content"].walk()].filter(item=>item.tag==="button"&&item.textContent===label);
const form=()=>elements["view-content"].querySelector("form");
async function submitForm(values){const selected=form();assert(selected,"user form exists");
  for(const [key,value] of Object.entries(values)){const input=selected.querySelector("input[name="+key+"]")||selected.querySelector("select[name="+key+"]");
    assert(input,key);input.value=value;input.oninput?.();}
  await selected.onsubmit({preventDefault(){}});return selected;
}
(async()=>{
  elements.username.value="admin";elements.password.value="ChangeMeNow!";
  await elements["login-form"].listeners.submit[0]({preventDefault(){}});
  assert.deepEqual(requests[0].body,{username:"admin",password:"ChangeMeNow!"});
  assert.equal(elements["password-view"].hidden,false);assert.equal(elements.workspace.hidden,true);
  assert.equal(elements["password-cancel"].hidden,true);assert.equal(elements.password.value,"");
  elements["current-password"].value="ChangeMeNow!";elements["new-password"].value="A new admin passphrase";
  elements["confirm-password"].value="does not match";
  const before=requests.length;await elements["password-form"].listeners.submit[0]({preventDefault(){}});
  assert.equal(requests.length,before,"mismatched passwords never send");
  elements["confirm-password"].value=elements["new-password"].value;
  await elements["password-form"].listeners.submit[0]({preventDefault(){}});
  assert.equal(requests.at(-1).headers["X-Duranki-CSRF"],"csrf-test");
  assert.equal(elements["login-view"].hidden,false);assert.equal(elements["new-password"].value,"");
  elements.password.value="A new admin passphrase";
  await elements["login-form"].listeners.submit[0]({preventDefault(){}});
  assert.equal(elements.workspace.hidden,false);assert.equal(buttons("Create user").length,1);
  assert.equal(buttons("Delete")[0].disabled,true,"last administrator deletion disabled");
  buttons("Create user")[0].onclick();
  const createdForm=await submitForm({username:"alice",display_name:"Alice",role:"ordinary",status:"active",
    password:"  A new user passphrase  ",password_confirm:"  A new user passphrase  "});
  const creation=requests.find(request=>request.method==="POST"&&request.url==="/operator/v1/users");
  assert.equal(creation.body.role,"ordinary");assert.equal(creation.body.password,"  A new user passphrase  ");
  assert.equal(createdForm.querySelector("input[name=password]").value,"","secret cleared after save");
  buttons("Reset password")[0].onclick();
  await submitForm({password:"Temporary replacement password",password_confirm:"Temporary replacement password"});
  assert(requests.some(request=>request.url==="/operator/v1/users/user.new/password"));
  buttons("Edit")[1].onclick();await submitForm({username:"alice",display_name:"Alice Updated",role:"read_only_operator",status:"suspended"});
  assert.equal(users[1].role,"read_only_operator");assert.equal(users[1].status,"suspended");
  await buttons("Delete")[1].onclick();assert.equal(users.length,1);
  assert(requests.some(request=>request.method==="DELETE"&&request.headers["X-Duranki-CSRF"]==="csrf-test"));
  const readsBefore=requests.filter(request=>request.url==="/operator/v1/users").length;
  await run('applyConsoleSession({csrf:"user-csrf",role:"ordinary",principal_id:"user.ordinary",username:"ordinary",user_management:true,permissions:["activity.read_own"]})');
  assert.equal(buttons("Create user").length,0);
  assert.equal(requests.filter(request=>request.url==="/operator/v1/users").length,readsBefore,"ordinary account view does not read other users");
  assert(navigation.filter(button=>!button.hidden).every(button=>button.dataset.view==="users"));
  console.log("User console: named sign-in, required password change, CRUD, reset, permission controls, and exact password preservation passed.");
})().catch(error=>{console.error(error);process.exitCode=1;});
