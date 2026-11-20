"use strict";
// Local Chrome DevTools check; screenshot contains only synthetic ledger data.
const fs = require("node:fs");
const expectedAttempts=Number(process.env.DEV12_EXPECTED_ATTEMPTS||"84");
const expectedKnown=process.env.DEV12_EXPECTED_KNOWN_USD||"0.346600164";

async function main() {
  const debugPort=process.env.DEV12_CHROME_DEBUG_PORT||"19222";
  const targets = await (await fetch("http://127.0.0.1:"+debugPort+"/json/list")).json();
  const target = targets.find(item => item.type === "page" && item.url === "about:blank") ||
    targets.find(item => item.type === "page");
  if (!target) throw Error("owned Chrome page absent");
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, {once:true});
    socket.addEventListener("error", reject, {once:true});
  });
  let sequence = 0;
  const pending = new Map();
  socket.addEventListener("message", event => {
    const packet = JSON.parse(event.data);
    if (!packet.id || !pending.has(packet.id)) return;
    const {resolve,reject} = pending.get(packet.id); pending.delete(packet.id);
    packet.error ? reject(Error(packet.error.message)) : resolve(packet.result);
  });
  const send = (method, params={}) => new Promise((resolve,reject) => {
    const id = ++sequence; pending.set(id,{resolve,reject});
    socket.send(JSON.stringify({id,method,params}));
  });
  const evaluate = async expression => {
    const value = await send("Runtime.evaluate", {expression,returnByValue:true,awaitPromise:true});
    if (value.exceptionDetails) throw Error("browser expression failed");
    return value.result.value;
  };
  const until = async expression => {
    for (let attempt=0;attempt<100;attempt++) {
      if (await evaluate(expression)) return;
      await new Promise(resolve=>setTimeout(resolve,100));
    }
    throw Error("browser condition timed out: "+expression+" · "+
      JSON.stringify(await evaluate("({body:document.body.innerText.slice(0,1200),message:document.getElementById('view-message')?.textContent})")));
  };
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Emulation.setDeviceMetricsOverride",{width:1440,height:900,deviceScaleFactor:1,mobile:false});
  await send("Page.navigate",{url:"about:blank"});
  await until("location.href==='about:blank'");
  await send("Page.navigate",{url:"http://127.0.0.1:18780/#/usage"});
  await until("location.host==='127.0.0.1:18780' && document.readyState==='complete' && typeof api==='function' && !!document.getElementById('password')");
  await evaluate("document.getElementById('password').value='dev12.synthetic.operator.'+'x'.repeat(32);document.getElementById('login-form').requestSubmit();true");
  await until("document.getElementById('workspace')?.hidden===false || !!document.getElementById('login-error')?.textContent");
  await until("document.getElementById('view-content')?.textContent.includes('Standalone retrieval · controlled synthetic profile')");
  await until(`document.getElementById('view-content')?.textContent.includes('${expectedKnown}')`);
  const exports = await evaluate("(async()=>{const root='/operator/v1/retrieval-usage';const report=await(await fetch(root,{credentials:'same-origin',cache:'no-store'})).json();const csv=await(await fetch(root+'?export=csv',{credentials:'same-origin',cache:'no-store'})).text();return {json:report.attempts.length,csv:csv.trim().split('\\n').length-1,known:report.total.known_usd,unknown:report.total.unknown_cost_attempts,no_send:report.total.not_sent_attempts}})()");
  if (exports.json!==expectedAttempts || exports.csv!==expectedAttempts || exports.known!==expectedKnown || exports.unknown!==1 || exports.no_send!==2)
    throw Error("browser JSON/CSV and control-state totals differ: "+JSON.stringify(exports));
  await evaluate("document.querySelector('.dev12-report .cost-filters').open=true;Array.from(document.querySelectorAll('.dev12-report label')).find(x=>x.textContent.startsWith('Actor')).querySelector('input').value='agent.vega';Array.from(document.querySelectorAll('.dev12-report button')).find(x=>x.textContent==='Apply synthetic filters').click();true");
  await until("document.querySelector('.dev12-report .cards')?.textContent.includes('51')");
  const filtered = await evaluate("document.querySelector('.dev12-report .cards').textContent");
  await evaluate("Array.from(document.querySelectorAll('.dev12-report button')).find(x=>x.textContent==='Clear synthetic filters').click();true");
  await until("document.querySelector('.dev12-report .cards')?.textContent.includes('84')");
  const original = await evaluate("({title:document.getElementById('view-title').textContent,summary:document.getElementById('view-content').textContent.slice(0,600),rows:document.querySelectorAll('#view-content table tbody tr').length,scrollWidth:document.documentElement.scrollWidth,innerWidth:innerWidth})");
  if (original.scrollWidth > original.innerWidth+2) throw Error("desktop controls clipped");
  const output = process.argv[2];
  fs.writeFileSync(output, Buffer.from((await send("Page.captureScreenshot",{format:"png",captureBeyondViewport:false})).data,"base64"));
  await evaluate("Array.from(document.querySelectorAll('#view-content button.primary-link')).find(b=>b.textContent.includes('embedding.create'))?.focus();true");
  const focused = await evaluate("document.activeElement?.outerHTML.slice(0,160)");
  if (!focused?.includes("button")) throw Error("synthetic attempt row did not receive keyboard focus");
  await send("Input.dispatchKeyEvent",{type:"rawKeyDown",key:"Enter",code:"Enter",windowsVirtualKeyCode:13,nativeVirtualKeyCode:13});
  await send("Input.dispatchKeyEvent",{type:"char",text:"\r",key:"Enter",code:"Enter",windowsVirtualKeyCode:13});
  await send("Input.dispatchKeyEvent",{type:"keyUp",key:"Enter",code:"Enter",windowsVirtualKeyCode:13,nativeVirtualKeyCode:13});
  await until("document.getElementById('view-content')?.textContent.includes('Synthetic operation detail')");
  await evaluate("Array.from(document.querySelectorAll('#view-content h2')).find(h=>h.textContent==='Synthetic operation detail')?.scrollIntoView({block:'start'});true");
  fs.writeFileSync(output.replace(/\.png$/, "-detail.png"),Buffer.from((await send("Page.captureScreenshot",{format:"png",captureBeyondViewport:false})).data,"base64"));
  await send("Emulation.setDeviceMetricsOverride",{width:860,height:900,deviceScaleFactor:1,mobile:false});
  await new Promise(resolve=>setTimeout(resolve,200));
  const narrow = await evaluate("({scrollWidth:document.documentElement.scrollWidth,innerWidth:innerWidth,controls:document.querySelectorAll('#view-content button').length})");
  if (narrow.scrollWidth > narrow.innerWidth+2 || !narrow.controls) throw Error("narrow controls clipped or absent");
  fs.writeFileSync(output.replace(/\.png$/, "-narrow.png"),Buffer.from((await send("Page.captureScreenshot",{format:"png",captureBeyondViewport:false})).data,"base64"));
  process.stdout.write(JSON.stringify({status:"PASS",desktop:original,narrow,exports,filtered,screenshots:[output,
    output.replace(/\.png$/,"-detail.png"),output.replace(/\.png$/,"-narrow.png")],
    provider_or_model_submissions:0})+"\n");
  socket.close();
}
main().catch(error=>{process.stderr.write(error.stack+"\n");process.exitCode=1;});
