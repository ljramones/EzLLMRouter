"use strict";
// Read-only CDP capture of the existing populated historical over-bound UI.
const assert=require("node:assert/strict");
const crypto=require("node:crypto");
const fs=require("node:fs");
const path=require("node:path");

const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const sha=raw=>crypto.createHash("sha256").update(raw).digest("hex");

async function connect(port,origin){
  const response=await fetch(`http://127.0.0.1:${port}/json/list`);
  assert(response.ok);
  const listing=await response.json();
  const blank=listing.find(item=>item.type==="page"&&
    (item.url==="about:blank"||item.url.startsWith(origin)));
  assert(blank?.webSocketDebuggerUrl,"isolated Chrome tab required");
  const socket=new WebSocket(blank.webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{socket.addEventListener("open",resolve,{once:true});
    socket.addEventListener("error",reject,{once:true});});
  let next=0;
  const waiting=new Map(),requests=[];
  socket.addEventListener("message",event=>{
    const value=JSON.parse(event.data);
    if(!value.id){if(value.method==="Network.requestWillBeSent")
      requests.push({method:value.params.request.method,url:value.params.request.url});return;}
    const pending=waiting.get(value.id);if(!pending)return;waiting.delete(value.id);
    value.error?pending.reject(Error(value.error.message)):pending.resolve(value.result);
  });
  const call=(method,params={})=>new Promise((resolve,reject)=>{
    const id=++next;waiting.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}));});
  const evaluate=async expression=>{
    const value=await call("Runtime.evaluate",{expression,returnByValue:true,awaitPromise:true});
    if(value.exceptionDetails)throw Error(value.exceptionDetails.exception?.description||
      value.exceptionDetails.text||"browser expression failed");
    return value.result.value;
  };
  const until=async(expression,label)=>{
    for(let n=0;n<100;n++){if(await evaluate(expression))return;await sleep(100);}
    throw Error(`browser wait expired: ${label}`);
  };
  return {call,evaluate,until,requests,close:()=>socket.close()};
}

async function main(output,port){
  const ready=JSON.parse(fs.readFileSync(path.join(output,"READY.json"),"utf8"));
  assert.equal(ready.origin,"http://127.0.0.1:8769");
  const browser=await connect(port,ready.origin);
  try{
    await browser.call("Page.enable");
    await browser.call("Runtime.enable");
    await browser.call("Network.enable");
    await browser.call("Emulation.setDeviceMetricsOverride",{width:1440,height:1000,
      deviceScaleFactor:1,mobile:false});
    await browser.call("Page.navigate",{url:ready.origin+"/"});
    await browser.until("!!document.querySelector('#login-form')","login form");
    await browser.until("typeof state==='object' && typeof render==='function'",
      "deferred console scripts");
    await browser.evaluate("(()=>{document.querySelector('#password').value="+
      JSON.stringify("dev12.report.only.synthetic."+"x".repeat(32))+";"+
      "document.querySelector('#login-form').requestSubmit();return true})()");
    try{
      await browser.until("!!document.querySelector('#workspace') && !document.querySelector('#workspace').hidden","authenticated workspace");
    }catch(error){
      const visible=await browser.evaluate("(()=>({error:document.querySelector('#login-error')?.textContent,"+
        "page:document.body.innerText.slice(0,500)}))()");
      throw Error(error.message+": "+JSON.stringify(visible));
    }
    await browser.evaluate("(()=>{document.querySelector('#navigation button[data-view=usage]').click();return true})()");
    await browser.until("!!document.querySelector('.dev12-report .dev12-row button')","populated synthetic row");
    const before=await browser.evaluate("(()=>({banner:document.querySelector('.dev12-report .scope-note')?.textContent,"+
      "row:document.querySelector('.dev12-report .dev12-row')?.textContent,"+
      "rows:document.querySelectorAll('.dev12-report .dev12-row').length}))()");
    assert.equal(before.rows,1);
    assert.match(before.banner,/DEMO.*Fictional USD only/);
    assert.match(before.row,/0\.000200000.*over bound/);
    await browser.evaluate("(()=>{document.querySelector('.dev12-report .dev12-row button').click();return true})()");
    await browser.until("[...document.querySelectorAll('.dev12-report h2')].some(x=>x.textContent==='Synthetic operation detail')",
      "selected historical detail");
    const detail=await browser.evaluate("(()=>{const section=[...document.querySelectorAll('.dev12-report section.panel')]"+
      ".find(x=>x.querySelector('h2')?.textContent==='Synthetic operation detail');"+
      "const terms=[...section.querySelectorAll('dt')],values=[...section.querySelectorAll('dd')];"+
      "const fields=Object.fromEntries(terms.map((x,i)=>[x.textContent,values[i].textContent]));"+
      "section.scrollIntoView({block:'center'});return {fields,text:section.textContent,"+
      "selectedRow:document.querySelector('.dev12-report .dev12-row')?.textContent,"+
      "banner:document.querySelector('.dev12-report .scope-note')?.textContent}})()");
    assert.match(detail.fields.Settlement,/over_bound.*fictional USD 0\.000200000/);
    assert.equal(detail.fields.Reservation,"fictional USD 0.000100000");
    assert.equal(detail.fields["Charging owner"],"team.dev12.c02.20261026.continue01");
    assert.match(detail.banner,/no commercial provider calls/);
    const screenshot=Buffer.from((await browser.call("Page.captureScreenshot",
      {format:"png",captureBeyondViewport:false})).data,"base64");
    assert(screenshot.length>1000&&screenshot.length<8_000_000);
    const screenshotName="historical-overbound-selected.png";
    fs.writeFileSync(path.join(output,screenshotName),screenshot,{flag:"wx"});
    const full=Buffer.from((await browser.call("Page.captureScreenshot",
      {format:"png",captureBeyondViewport:true})).data,"base64");
    assert(full.length>1000&&full.length<8_000_000);
    const fullName="historical-overbound-context.png";
    fs.writeFileSync(path.join(output,fullName),full,{flag:"wx"});
    const local=browser.requests.filter(item=>item.url.startsWith(ready.origin));
    const methods={};for(const item of local)methods[item.method]=(methods[item.method]||0)+1;
    assert.equal(methods.POST,1,"only synthetic operator login may POST");
    assert(local.every(item=>item.method==="GET"||item.url.endsWith("/operator/v1/login")));
    const observation={kind:"dev12_completion02_continue03_historical_overbound_render_v1",
      status:"PASS",fixture_source_sha256:ready.source_sha256,
      imported_campaign_id:ready.campaign_id,fixture_counts:ready.counts,
      viewport:{width:1440,height:1000},before,detail,
      screenshot:screenshotName,screenshot_bytes:screenshot.length,
      screenshot_sha256:sha(screenshot),local_request_methods:methods,
      context_screenshot:fullName,context_screenshot_bytes:full.length,
      context_screenshot_sha256:sha(full),
      local_request_paths:local.map(item=>({method:item.method,
        path:new URL(item.url).pathname})),model_submission_requests:0,
      sender_worker_receiver_started:false};
    fs.writeFileSync(path.join(output,"BROWSER-OBSERVATION.json"),
      JSON.stringify(observation,null,2)+"\n",{flag:"wx"});
    process.stdout.write(JSON.stringify({status:"PASS",screenshot:screenshotName,
      amount:detail.fields.Settlement,bound:detail.fields.Reservation,
      local_gets:methods.GET||0,local_posts:methods.POST||0})+"\n");
  }finally{browser.close();}
}

main(process.argv[2],Number(process.argv[3])).catch(error=>{console.error(error);process.exitCode=1;});
