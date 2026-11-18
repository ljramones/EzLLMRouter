"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const crypto=require("node:crypto");
const [debugPort,origin,passwordFile,out]=process.argv.slice(2);
const password=fs.readFileSync(passwordFile,"utf8").trim();
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function main(){
  const targets=await (await fetch("http://127.0.0.1:"+debugPort+"/json/list")).json();
  const target=targets.find(x=>x.type==="page"&&x.url==="about:blank");
  assert(target?.webSocketDebuggerUrl);
  const ws=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{ws.addEventListener("open",resolve,{once:true});
    ws.addEventListener("error",reject,{once:true});});
  let next=0;const pending=new Map(),requests=[];
  ws.addEventListener("message",event=>{const p=JSON.parse(event.data);
    if(p.method==="Network.requestWillBeSent")requests.push({url:p.params.request.url,method:p.params.request.method});
    if(!p.id)return;const item=pending.get(p.id);if(!item)return;pending.delete(p.id);
    p.error?item.reject(Error(p.error.message)):item.resolve(p.result);});
  function call(method,params={}){return new Promise((resolve,reject)=>{const id=++next;
    pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});}
  async function evalJs(expression){const result=await call("Runtime.evaluate",{expression,returnByValue:true,awaitPromise:true});
    if(result.exceptionDetails)throw Error("browser evaluation failed");return result.result.value;}
  async function until(expression){for(let i=0;i<100;i++){if(await evalJs(expression))return;
    await delay(100);}throw Error("browser condition timed out");}
  try{
    await call("Page.enable");await call("Network.enable");
    await call("Emulation.setDeviceMetricsOverride",{width:1440,height:900,deviceScaleFactor:1,mobile:false});
    await call("Page.navigate",{url:origin+"/integration"});
    await until("!!document.getElementById('password')");
    await evalJs('document.getElementById("password").value='+JSON.stringify(password)+';document.getElementById("login-form").requestSubmit();');
    await until("!document.getElementById('workspace').hidden && document.getElementById('view-content').textContent.includes('0.055000000')");
    const desktop=await evalJs('({title:document.getElementById("view-title").textContent,text:document.getElementById("view-content").textContent,buttons:[...document.querySelectorAll("#view-content button")].map(x=>x.textContent)})');
    assert.equal(desktop.title,"External accounting");assert(desktop.text.includes("account.synthetic.01"));
    assert(desktop.text.includes("Unknown cost"));assert(desktop.buttons.includes("Make usable"));
    const image=await call("Page.captureScreenshot",{format:"png",captureBeyondViewport:false});
    fs.writeFileSync(out+"/integration-desktop.png",Buffer.from(image.data,"base64"));
    await call("Emulation.setDeviceMetricsOverride",{width:860,height:900,deviceScaleFactor:1,mobile:false});
    await delay(200);
    const narrow=await evalJs('({title:document.getElementById("view-title").textContent,offscreen:[...document.querySelectorAll("#view-content button,#view-content input,#view-content select")].filter(x=>{const r=x.getBoundingClientRect();return r.width>0&&r.height>0&&r.right<=0}).length})');
    assert.equal(narrow.title,"External accounting");assert.equal(narrow.offscreen,0);
    const second=await call("Page.captureScreenshot",{format:"png",captureBeyondViewport:false});
    fs.writeFileSync(out+"/integration-narrow.png",Buffer.from(second.data,"base64"));
    assert(requests.every(x=>x.url.startsWith(origin)||x.url==="about:blank"));
    assert.deepEqual(requests.filter(x=>x.method==="POST").map(x=>x.url),[origin+"/operator/v1/login"]);
    const sha=name=>crypto.createHash("sha256").update(fs.readFileSync(out+"/"+name)).digest("hex");
    console.log(JSON.stringify({result:"PASS",local_gets:requests.filter(x=>x.method==="GET").length,
      local_login_posts:1,desktop_sha256:sha("integration-desktop.png"),narrow_sha256:sha("integration-narrow.png")}));
  }finally{ws.close();}
}
main().catch(error=>{console.error(error.message);process.exitCode=1;});
