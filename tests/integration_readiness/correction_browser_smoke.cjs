"use strict";
// Focused installed operator UI route check. Browser may issue only local requests.
const assert=require("node:assert/strict"),fs=require("node:fs"),crypto=require("node:crypto");
const [debugPort,origin,passwordFile,out]=process.argv.slice(2);
const password=fs.readFileSync(passwordFile,"utf8").trim();
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function run(){
  const targets=await (await fetch("http://127.0.0.1:"+debugPort+"/json/list")).json();
  const target=targets.find(x=>x.type==="page"&&x.url==="about:blank");
  assert(target?.webSocketDebuggerUrl);
  const ws=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{ws.addEventListener("open",resolve,{once:true});
    ws.addEventListener("error",reject,{once:true});});
  let next=0;const pending=new Map(),requests=[];
  ws.addEventListener("message",event=>{const value=JSON.parse(event.data);
    if(value.method==="Network.requestWillBeSent")
      requests.push({url:value.params.request.url,method:value.params.request.method});
    if(!value.id)return;const item=pending.get(value.id);if(!item)return;pending.delete(value.id);
    value.error?item.reject(Error(value.error.message)):item.resolve(value.result);});
  function call(method,params={}){return new Promise((resolve,reject)=>{const id=++next;
    pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});}
  async function evaluate(expression){const result=await call("Runtime.evaluate",{expression,returnByValue:true,awaitPromise:true});
    if(result.exceptionDetails)throw Error("browser evaluation failed: "+expression);return result.result.value;}
  async function until(expression){for(let i=0;i<100;i++){if(await evaluate(expression))return;
    await delay(100);}throw Error("browser condition timed out: "+expression);}
  const row="[...document.querySelectorAll('#view-content tr')].find(x=>x.textContent.includes('account:operator:route'))";
  try{
    await call("Page.enable");await call("Network.enable");
    await call("Emulation.setDeviceMetricsOverride",{width:1440,height:900,deviceScaleFactor:1,mobile:false});
    await call("Page.navigate",{url:origin+"/integration"});
    await until("!!document.getElementById('password')");
    await evaluate('document.getElementById("password").value='+JSON.stringify(password)+
      ';document.getElementById("login-form").requestSubmit();');
    await until("!!("+row+")");
    assert.equal(await evaluate("("+row+").querySelector('button').textContent"),"Make usable");
    await evaluate("("+row+").querySelector('button').click()");
    await until("("+row+")?.querySelector('button')?.textContent==='Disable'");
    await evaluate("("+row+").querySelector('button').click()");
    await until("("+row+")?.querySelector('button')?.textContent==='Make usable'");
    const image=await call("Page.captureScreenshot",{format:"png",captureBeyondViewport:false});
    const output=out+"/integration-correction-encoded-account.png";
    fs.writeFileSync(output,Buffer.from(image.data,"base64"));
    await call("Emulation.setDeviceMetricsOverride",{width:860,height:900,deviceScaleFactor:1,mobile:false});
    await delay(150);
    const clipped=await evaluate('([...document.querySelectorAll("#view-content button,#view-content input,#view-content select")].filter(x=>{const r=x.getBoundingClientRect();return r.width>0&&r.height>0&&(r.right<=0||r.left>=innerWidth)}).length)');
    assert.equal(clipped,0);
    assert(requests.every(x=>x.url.startsWith(origin)||x.url==="about:blank"));
    const posts=requests.filter(x=>x.method==="POST");
    assert.equal(posts.length,3); // one login, two reversible account-state changes
    assert(posts.slice(1).every(x=>x.url.includes("account%3Aoperator%3Aroute/state")));
    const sha=crypto.createHash("sha256").update(fs.readFileSync(output)).digest("hex");
    console.log(JSON.stringify({result:"PASS",local_gets:requests.filter(x=>x.method==="GET").length,
      local_posts:posts.length,encoded_route:true,narrow_clipped_controls:clipped,screenshot_sha256:sha}));
  }finally{ws.close();}
}
run().catch(error=>{console.error(error.stack||error.message);process.exitCode=1;});
