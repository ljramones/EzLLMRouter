"use strict";
/*
 * Independent, read-only Chrome DevTools capture for the disposable DEV-12
 * Completion 02 operator. It connects to an already running browser and
 * target. It never starts either one, and never invokes a model route.
 *
 * Example (credential supplied privately through the environment):
 * node tests/operator_console/dev12_completion_browser.cjs \
 *   --root /Users/larrymitchell/Mach33/Duranki-artifacts/<run> \
 *   --mode t64 --debug-port <owned Chrome port> \
 *   --browser-url http://127.0.0.1:<mapped operator port> \
 *   --mapping-evidence <run>/operator-port-forward.json
 *
 * DEV12_OPERATOR_PASSWORD must contain the disposable operator credential.
 * A different browser URL needs a retained local forwarding receipt. Do not
 * put credentials in command arguments, screenshots or this program's output.
 */
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const {execFileSync} = require("node:child_process");
const {URL} = require("node:url");

const SOURCE = __filename;
const SOURCE_RELATIVE = path.relative(path.resolve(__dirname, "../.."), SOURCE);
const sha = data => crypto.createHash("sha256").update(data).digest("hex");
const assert = (condition, message) => { if (!condition) throw Error(message); };
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

function options(argv) {
  const result = {};
  for (let i = 0; i < argv.length; i += 2) {
    assert(argv[i]?.startsWith("--") && argv[i + 1] &&
      !result[argv[i].slice(2)], "expected unique --name value arguments");
    result[argv[i].slice(2)] = argv[i + 1];
  }
  assert(["t64", "t65"].includes(result.mode), "--mode must be t64 or t65");
  assert(result.root && result["debug-port"], "--root and --debug-port required");
  assert(/^\d+$/.test(result["debug-port"]), "invalid Chrome debug port");
  return result;
}

function retainedRoot(input) {
  const root = fs.realpathSync(input);
  const approved = fs.realpathSync("/Users/larrymitchell/Mach33/Duranki-artifacts");
  assert(root.startsWith(approved + path.sep) && fs.statSync(root).isDirectory(),
    "capture root must be a dedicated Duranki-artifacts directory");
  return root;
}

function requested(root, mode) {
  const journal = fs.readFileSync(path.join(root, "case-journal.jsonl"), "utf8")
    .trim().split("\n").filter(Boolean).map(line => JSON.parse(line));
  const filename = mode === "t64" ? "operator-browser-evidence.json" :
    "preview-browser-evidence.json";
  const matches = journal.map((row,index) => ({row,index})).filter(item =>
    item.row.kind === "browser_capture_requested" &&
    typeof item.row.expected_evidence_path === "string" &&
    path.isAbsolute(item.row.expected_evidence_path) &&
    path.basename(item.row.expected_evidence_path) === filename);
  assert(matches.length > 0, `pending ${mode} capture request absent`);
  const {row:request,index} = matches.at(-1);
  const hostEvidencePath = path.join(root, filename);
  assert(!fs.existsSync(hostEvidencePath), "one-use browser evidence exists");
  assert(!journal.slice(index + 1).some(row => row.kind === "case_end" &&
    row.case_id === request.case_id),
    "browser case already completed");
  return {...request,host_evidence_path:hostEvidencePath};
}

function releasedFingerprint(root, request) {
  // A continued campaign has one immutable receipt per source tree. The
  // original receipt describes the original build, not the current browser
  // target. Require the matching release as independent mounted identity.
  const receipts = fs.readdirSync(root).filter(name =>
    /^preflight-receipt(?:-continuation\d+)?\.json$/.test(name))
    .map(name => {
      const file = path.join(root, name);
      assert(fs.statSync(file).isFile() && !fs.lstatSync(file).isSymbolicLink(),
        "unsafe preflight receipt");
      return JSON.parse(fs.readFileSync(file, "utf8"));
    }).filter(value => value.source_tree === request.source_tree);
  assert(receipts.length === 1, "exact current-source preflight receipt absent");
  const receipt = receipts[0];
  const releases = fs.readFileSync(path.join(root, "release-identity.jsonl"), "utf8")
    .trim().split("\n").filter(Boolean).map(line => JSON.parse(line))
    .filter(value => value.plan_sha256 === receipt.plan_sha256 &&
      value.source_tree === request.source_tree &&
      value.mounted_source?.sha256 === receipt.mounted_source_identity?.sha256);
  assert(releases.length === 1, "current-source release identity absent");
  return receipt.mounted_source_identity.sha256;
}

function fileIdentity(filename) {
  if (!fs.existsSync(filename)) return {present:false, bytes:0, sha256:null};
  const stat = fs.lstatSync(filename);
  assert(stat.isFile() && !stat.isSymbolicLink(), `unsafe ledger file: ${filename}`);
  const bytes = fs.readFileSync(filename);
  return {present:true, bytes:bytes.length, sha256:sha(bytes)};
}

function ledger(root, campaignId) {
  const db = path.join(root, "campaign.sqlite");
  const dbStat = fs.lstatSync(db);
  assert(dbStat.isFile() && !dbStat.isSymbolicLink(),
    "campaign SQLite file unavailable or linked");
  const sql = query => execFileSync("sqlite3", ["-readonly", db, query],
    {encoding:"utf8", maxBuffer:1_000_000}).trim();
  const count = table => {
    const value = sql(`SELECT COUNT(*) FROM ${table};`);
    assert(/^\d+$/.test(value), `invalid ${table} count`);
    return Number(value);
  };
  const records = sql("SELECT record FROM dev12_campaigns;").split("\n")
    .filter(Boolean).map(line => JSON.parse(line));
  const campaign = records.find(row => row.campaign_id === campaignId);
  assert(campaign && Number.isInteger(campaign.attempt_count) &&
    Number.isInteger(campaign.possible_send_count),
    "current campaign counters unavailable");
  const receiver = path.join(root, "receiver.jsonl");
  const receiverArrivals = fs.existsSync(receiver) ?
    fs.readFileSync(receiver, "utf8").split("\n").filter(Boolean).length : 0;
  return {submissions:count("dev12_submissions"),
    usage_revisions:count("dev12_usage_revisions"),
    receiver_arrivals:receiverArrivals,
    attempt_count:campaign.attempt_count,
    possible_send_count:campaign.possible_send_count,
    files:Object.fromEntries(["receiver.jsonl", "guard.jsonl",
      "send-events.jsonl", "receiver-receipts.jsonl"].map(name =>
      [name, fileIdentity(path.join(root, name))]))};
}

function localUrl(value) {
  const url = new URL(value);
  assert(url.protocol === "http:" && url.hostname === "127.0.0.1" &&
    url.port && url.pathname === "/" && !url.search && !url.hash,
    "browser URL must be exact local operator origin");
  return url.origin;
}

async function cdp(debugPort) {
  const listing = await fetch(`http://127.0.0.1:${debugPort}/json/list`);
  assert(listing.ok, "owned Chrome target list unavailable");
  const targets = await listing.json();
  const target = targets.find(row => row.type === "page" && row.url === "about:blank");
  assert(target?.webSocketDebuggerUrl, "owned blank Chrome page absent");
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, {once:true});
    socket.addEventListener("error", reject, {once:true});
  });
  let next = 0;
  const pending = new Map();
  const events = [];
  socket.addEventListener("message", event => {
    const packet = JSON.parse(event.data);
    if (!packet.id) {events.push(packet); return;}
    const item = pending.get(packet.id);
    if (!item) return;
    pending.delete(packet.id);
    packet.error ? item.reject(Error(packet.error.message)) : item.resolve(packet.result);
  });
  function call(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = ++next;
      pending.set(id, {resolve, reject});
      socket.send(JSON.stringify({id, method, params}));
    });
  }
  async function evalJs(expression) {
    const answer = await call("Runtime.evaluate", {expression,
      returnByValue:true, awaitPromise:true});
    if (answer.exceptionDetails) throw Error("browser expression failed: " +
      (answer.exceptionDetails.text || "unknown"));
    return answer.result.value;
  }
  async function until(expression, label) {
    for (let i = 0; i < 100; ++i) {
      if (await evalJs(expression)) return;
      await delay(100);
    }
    throw Error(`browser condition timed out: ${label}`);
  }
  return {call, evalJs, until, events, close:() => socket.close()};
}

function requestsSince(events, browserUrl) {
  return events.filter(row => row.method === "Network.requestWillBeSent")
    .map(row => ({method:row.params.request.method,
      url:row.params.request.url})).filter(row => row.url.startsWith(browserUrl));
}

async function probe(browser, expectedFingerprint) {
  const result = await browser.evalJs("(async()=>{const [build,response]=await Promise.all(["+
    "fetch('/operator/v1/build',{credentials:'same-origin',cache:'no-store',redirect:'error'}),"+
    "fetch('/operator/v1/dev12-usage',{credentials:'same-origin',cache:'no-store',redirect:'error'})]);"+
    "if(!build.ok||!response.ok)throw Error('authenticated probe failed');"+
    "return {build:await build.json(),report:await response.json()}})()");
  assert(result.build.build.fingerprint === expectedFingerprint,
    "browser target build fingerprint differs from mounted target");
  const attempts = result.report.attempts;
  assert(Array.isArray(attempts) && attempts.length > 0,
    "populated authenticated target report required");
  const ids = attempts.map(row => row.attempt_id);
  assert(new Set(ids).size === ids.length, "browser report has duplicate attempt IDs");
  return {build_fingerprint:result.build.build.fingerprint,
    report_attempt_ids_sha256:sha(ids.sort().join("\n")),
    report_total:result.report.total};
}

async function screenshot(browser, root, mode, suffix, shots) {
  const name = `${mode}-${process.pid}-${CAPTURE_ID}-${suffix}.png`;
  const target = path.join(root, "screenshots", name);
  fs.mkdirSync(path.dirname(target), {recursive:true});
  assert(!fs.existsSync(target), `one-use screenshot exists: ${name}`);
  const response = await browser.call("Page.captureScreenshot",
    {format:"png", captureBeyondViewport:false});
  const bytes = Buffer.from(response.data, "base64");
  assert(bytes.length > 1000 && bytes.length < 8_000_000,
    "screenshot size outside retained bound");
  fs.writeFileSync(target, bytes, {flag:"wx", mode:0o600});
  shots.push({path:path.relative(root, target), sha256:sha(bytes)});
}

const CAPTURE_ID = crypto.randomUUID();

async function openUsage(browser, password, browserUrl) {
  await browser.call("Page.enable");
  await browser.call("Runtime.enable");
  await browser.call("Network.enable");
  await browser.call("Emulation.setDeviceMetricsOverride",
    {width:1440, height:900, deviceScaleFactor:1, mobile:false});
  await browser.call("Page.navigate", {url:browserUrl + "/#/usage"});
  await browser.until("document.readyState==='complete'&&!!document.getElementById('password')",
    "login form");
  await browser.evalJs("(()=>{document.getElementById('password').value="+
    JSON.stringify(password)+";document.getElementById('login-form').requestSubmit();return true})()");
  await browser.until("document.getElementById('workspace')?.hidden===false ||"+
    "!!document.getElementById('login-error')?.textContent", "authenticated workspace");
  assert(await browser.evalJs("document.getElementById('workspace').hidden===false"),
    "disposable operator login failed");
  assert(await browser.evalJs("document.getElementById('password').value===''"),
    "credential remains in the browser input");
  await browser.until("document.querySelector('.dev12-report .cards')!==null&&"+
    "document.getElementById('view-message').textContent===''", "synthetic report");
  assert(await browser.evalJs("document.querySelector('.dev12-report')?.textContent"+
    ".includes('Fictional USD only')"), "controlled report label absent");
}

async function captureT64(browser, root, shots, password) {
  const desktop = await browser.evalJs("({inner_width:innerWidth,"+
    "scroll_width:document.documentElement.scrollWidth})");
  assert(desktop.scroll_width <= desktop.inner_width + 2,
    "desktop document clips report controls");
  await screenshot(browser, root, "t64", "report-desktop", shots);
  const selected = await browser.evalJs("(()=>{const button=document.querySelector("+
    "'.dev12-report .dev12-row button');if(!button)return null;button.focus();"+
    "return {tag:document.activeElement.tagName,text:button.textContent}})()");
  assert(selected?.tag === "BUTTON", "keyboard detail button absent");
  for (const [type, extra] of [["rawKeyDown",{}],["char",{text:"\r"}],
    ["keyUp",{}]]) await browser.call("Input.dispatchKeyEvent",
      {type,key:"Enter",code:"Enter",windowsVirtualKeyCode:13,
        nativeVirtualKeyCode:13,...extra});
  await browser.until("!!document.querySelector('.dev12-report .panel h2')?.textContent"+
    ".includes('Synthetic operation detail')", "selected operation detail");
  const activated = await browser.evalJs("!!document.querySelector("+
    "'.dev12-report .panel h2')?.textContent.includes('Synthetic operation detail')");
  await screenshot(browser, root, "t64", "keyboard-detail", shots);
  await browser.call("Emulation.setDeviceMetricsOverride",
    {width:860,height:900,deviceScaleFactor:1,mobile:false});
  await delay(150);
  const narrow = await browser.evalJs("({inner_width:innerWidth,"+
    "scroll_width:document.documentElement.scrollWidth})");
  assert(narrow.inner_width < desktop.inner_width &&
    narrow.scroll_width <= narrow.inner_width + 2,
    "narrow document clips report controls");
  await screenshot(browser, root, "t64", "report-narrow", shots);
  // Exercise the normal report error path using an invalid *read* filter.
  await browser.evalJs("(()=>{const input=[...document.querySelectorAll("+
    "'.dev12-report .cost-filters label')].find(x=>x.textContent.startsWith("+
    "'Usage revision cutoff'))?.querySelector('input');if(!input)throw Error("+
    "'cutoff filter absent');input.value='invalid-cutoff';"+
    "[...document.querySelectorAll('.dev12-report button')].find(x=>"+
    "x.textContent==='Apply synthetic filters').click();return true})()");
  await browser.until("document.getElementById('view-message')?.textContent"+
    ".includes('Current data unavailable')", "visible report error");
  const errorReason = await browser.evalJs("document.getElementById('view-message').textContent");
  assert(errorReason.length > 5, "concrete report error reason absent");
  // Restore the normal report with a read-only render. The management result
  // is taken only from visible UI evidence; no synthetic registry edit here.
  await browser.evalJs("(()=>{dev12Ui.filters={};render();return true})()");
  await browser.until("document.querySelector('.dev12-report .cards')!==null&&"+
    "document.getElementById('view-message').textContent===''", "restored report");
  const management = await browser.evalJs("(()=>{const area=document.querySelector("+
    "'.dev12-report');const visible=area?.innerText||'';const reason="+
    "visible.match(/(?:management|edit)[^\\n]{0,120}(?:disabled|read.only|unavailable)[^\\n]{0,120}/i)"+
    "||visible.match(/(?:disabled|read.only|unavailable)[^\\n]{0,120}(?:management|edit)[^\\n]{0,120}/i);"+
    "return {worked:false,disabled:!!reason,reason:reason?.[0]||null}})()");
  const secretVisible = await browser.evalJs("document.body.innerText.includes("+
    JSON.stringify(password)+")");
  assert(!secretVisible, "credential visible in browser text");
  return {desktop,narrow,keyboard:{focused_tag:selected.tag,
    activated_detail:activated},management,error_reason:errorReason,
    secret_text_visible:secretVisible};
}

async function captureT65(browser, root, shots, password) {
  await browser.evalJs("(()=>{const button=[...document.querySelectorAll("+
    "'#view-content button')].find(x=>x.textContent==='Open demo workspace');"+
    "if(!button)throw Error('preview entry absent');button.click();return true})()");
  await browser.until("demoUi.data?.identity==='dev09-team-scripted-cost-demo-v2'"+
    "&&!!document.querySelector('.demo-viz svg')", "isolated team preview");
  assert(await browser.evalJs("document.querySelector('.demo-banner')?.textContent"+
    ".includes('DEMO')"), "scripted preview label absent");
  const end = await browser.evalJs("Number(document.querySelector("+
    "'.demo-controls input[type=range]').max)");
  assert(Number.isFinite(end) && end > 1, "preview time domain absent");
  const seek = {};
  for (const [name,time] of [["start",0],["midpoint",Math.floor(end/2)],
    ["end",end]]) {
    const shown = await browser.evalJs("(()=>{const slider=document.querySelector("+
      "'.demo-controls input[type=range]');slider.value="+time+";"+
      "slider.dispatchEvent(new Event('input',{bubbles:true}));"+
      "return demoUi.time})()");
    assert(shown === time, `preview ${name} seek differs`);
    seek[name] = shown;
    await screenshot(browser, root, "t65", name, shots);
  }
  await browser.evalJs("(()=>{const button=[...document.querySelectorAll("+
    "'.demo-controls button')].find(x=>x.textContent==='Replay');"+
    "if(!button)throw Error('Replay absent');button.click();return true})()");
  await browser.until("demoUi.playing&&demoUi.time>0", "preview replay");
  await browser.evalJs("(()=>{const button=[...document.querySelectorAll("+
    "'.demo-controls button')].find(x=>x.textContent==='Pause');"+
    "if(!button)throw Error('Pause absent');button.click();return true})()");
  const replayed = await browser.evalJs("!demoUi.playing&&demoUi.time>0&&"+
    "demoUi.time<demoUi.data.end");
  assert(replayed, "preview replay did not advance and pause");
  const secretVisible = await browser.evalJs("document.body.innerText.includes("+
    JSON.stringify(password)+")");
  assert(!secretVisible, "credential visible in preview");
  return {seek,replayed,secret_text_visible:secretVisible};
}

async function main() {
  const input = options(process.argv.slice(2));
  const root = retainedRoot(input.root);
  const request = requested(root, input.mode);
  const password = process.env.DEV12_OPERATOR_PASSWORD;
  assert(typeof password === "string" && password.length >= 32,
    "DEV12_OPERATOR_PASSWORD must be the disposable credential");
  const browserUrl = localUrl(input["browser-url"] || request.operator_url);
  let portForward = null;
  if (browserUrl !== request.operator_url) {
    const supplied = input["mapping-evidence"];
    assert(supplied, "different browser port needs retained mapping evidence");
    const filename = fs.realpathSync(supplied);
    assert(filename.startsWith(root + path.sep), "mapping evidence must be in run root");
    const bytes = fs.readFileSync(filename);
    assert(bytes.length > 0 && bytes.length < 10_000,
      "mapping evidence size outside bound");
    const mapping = JSON.parse(bytes.toString("utf8"));
    assert(mapping && mapping.from === request.operator_url &&
      mapping.to === browserUrl && mapping.method === "local_port_forward" &&
      typeof mapping.observation === "string" && mapping.observation.length > 5,
      "retained mapping receipt does not identify the observed local forward");
    portForward = {from:request.operator_url,to:browserUrl,
      method:"local_port_forward",evidence_path:path.relative(root, filename),
      sha256:sha(bytes)};
  } else assert(!input["mapping-evidence"], "unneeded mapping evidence supplied");
  const beforeLedger = ledger(root, request.campaign_id);
  const browser = await cdp(input["debug-port"]);
  try {
    await openUsage(browser, password, browserUrl);
    const targetProbe = await probe(browser, releasedFingerprint(root, request));
    const screenshots = [];
    const result = input.mode === "t64" ?
      await captureT64(browser, root, screenshots, password) :
      await captureT65(browser, root, screenshots, password);
    const again = await probe(browser, targetProbe.build_fingerprint);
    assert(JSON.stringify(again) === JSON.stringify(targetProbe),
      "browser reads changed authenticated report or build");
    const afterLedger = ledger(root, request.campaign_id);
    assert(JSON.stringify(beforeLedger) === JSON.stringify(afterLedger),
      "browser activity changed target sender or receiver ledger files");
    const requests = requestsSince(browser.events, browserUrl);
    assert(requests.length > 0, "browser local requests absent");
    assert(requests.every(row => row.method === "GET" ||
      (row.method === "POST" && row.url === browserUrl + "/operator/v1/login")),
      "browser sent an unexpected mutation request");
    const getCount = requests.filter(row => row.method === "GET").length;
    assert(getCount > 0, "local read traffic absent");
    const localRequests = Object.entries(requests.reduce((counts,row) => {
      const url = new URL(row.url);
      const key = row.method + " " + url.pathname + url.search;
      counts[key] = (counts[key] || 0) + 1;
      return counts;
    }, {})).sort(([a],[b]) => a.localeCompare(b)).map(([route,count]) =>
      ({route,count}));
    const evidence = {kind:"dev12_controlled_browser_observation_v1",
      campaign_id:request.campaign_id,source_tree:request.source_tree,
      operator_url:request.operator_url,browser_url:browserUrl,
      port_forward:portForward,target_probe:targetProbe,
      capture_source:SOURCE_RELATIVE,capture_source_sha256:sha(fs.readFileSync(SOURCE)),
      screenshots,browser:{...result,local_requests:localRequests},ledger_before:beforeLedger,
      ledger_after:afterLedger,local_get_count:getCount};
    fs.writeFileSync(request.host_evidence_path,
      JSON.stringify(evidence,null,2)+"\n", {flag:"wx",mode:0o600});
    process.stdout.write(JSON.stringify({status:"CAPTURED_AWAITING_TARGET_VERIFICATION",mode:input.mode,
      evidence_path:request.host_evidence_path,
      sha256:sha(fs.readFileSync(request.host_evidence_path)),
      local_get_count:getCount,screenshots})+"\n");
  } finally {browser.close();}
}

main().catch(error => {process.stderr.write(error.stack+"\n");process.exitCode=1;});
