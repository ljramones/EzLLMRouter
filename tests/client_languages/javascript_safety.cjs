"use strict";
const assert = require("node:assert/strict");
const {createRequire} = require("node:module");
const path = require("node:path");
const {test} = require("node:test");

const root = path.resolve(__dirname, "../..");
const consumer = process.env.EZLLMROUTER_JS_CONSUMER;
const load = consumer ? createRequire(path.join(consumer, "package.json")) : require;
const {EzLLMRouterClient, EzLLMRouterError, IntegrationClient, IntegrationClientError} = consumer ?
  load("@cognitivedynamics/ezllmrouter-client") : require("../../clients/js");
const legacy = require(path.join(root,
  "tests/fixtures/contracts/wp-a-03-c01/EZLLMROUTER-WP-A-VECTORS-v0.3-CORRECTION-01.json")).examples;
const vectors = require(path.join(root, "tests/fixtures/contracts/dev12-successor-01/vectors.json"));
const example = id => structuredClone(vectors.examples.find(row => row.id === id).request);
const fixture = id => structuredClone(vectors.protocol_fixtures.find(row => row.id === id).value);
const clone = value => structuredClone(value);
const methods = ["wire", "successor", "attribution", "integration"];
const limitFor = kind => ["wire", "attribution"].includes(kind) ? 1024 * 1024 : 16 * 1024 * 1024;

function streamed(chunks, kind = "wire", extraHeaders = {}) {
  const state = {reads: 0, cancelled: 0, released: 0, calls: []};
  const reader = {
    async read() {
      const index = state.reads++;
      if (index >= chunks.length) return {done: true};
      if (chunks[index] instanceof Error) throw chunks[index];
      return {done: false, value: chunks[index]};
    },
    async cancel() { state.cancelled++; },
    releaseLock() { state.released++; },
  };
  const response = {
    status: 200, ok: true,
    headers: new Headers({"EzLLMRouter-Contract-Version": kind === "successor" ? "0.3" : "0.2",
      "EzLLMRouter-Integration-Version": "1", ...extraHeaders}),
    body: {getReader: () => reader},
    json: async () => { throw Error("unbounded JSON reader used"); },
    arrayBuffer: async () => { throw Error("buffered reader used instead of stream"); },
  };
  const fetchImpl = async (url, options) => { state.calls.push({url, options}); return response; };
  return {state, reader, response, fetchImpl};
}

function operation(kind, fetchImpl, timeoutMs) {
  const settings = {baseUrl: "http://synthetic.invalid", token: "synthetic", fetchImpl, timeoutMs};
  if (kind === "integration") {
    return () => new IntegrationClient(settings.baseUrl, settings.token, {fetchImpl, timeoutMs}).report("dataset.synthetic");
  }
  const client = new EzLLMRouterClient(settings);
  return {wire: () => client.submit(clone(legacy.submit_text)),
    successor: () => client.submit_rerank(example("DELEGATED_RERANK")),
    attribution: () => client.getRun("run.synthetic")}[kind];
}

async function unknown(action, kind, status = 200) {
  await assert.rejects(action, error => {
    assert(error instanceof (kind === "integration" ? IntegrationClientError : EzLLMRouterError));
    assert.equal(error.code, "TRANSPORT_OUTCOME_UNKNOWN");
    assert.equal(kind === "integration" ? error.httpStatus : error.http_status, status);
    assert.equal(kind === "integration" ? error.retryGuidance : error.retry_guidance, "query_first");
    return true;
  });
}

for (const kind of methods) {
  test(`${kind}: compression is rejected without reading or retrying`, async () => {
    const stream = streamed([Buffer.from("unused")], kind, {"Content-Encoding": "gzip"});
    await unknown(operation(kind, stream.fetchImpl), kind);
    assert.equal(stream.state.reads, 0);
    assert.equal(stream.state.cancelled, 1);
    assert.equal(stream.state.released, 1);
    assert.equal(stream.state.calls.length, 1);
    assert.equal(stream.state.calls[0].options.headers["Accept-Encoding"], "identity");
  });

  test(`${kind}: declared oversize is rejected before reading`, async () => {
    const stream = streamed([Buffer.from("unused")], kind, {"Content-Length": String(limitFor(kind) + 1)});
    await unknown(operation(kind, stream.fetchImpl), kind);
    assert.equal(stream.state.reads, 0);
    assert.equal(stream.state.cancelled, 1);
    assert.equal(stream.state.released, 1);
    assert.equal(stream.state.calls.length, 1);
  });

  test(`${kind}: unknown-length stream stops at its protocol cap`, async () => {
    const chunk = Buffer.alloc(65536, "x");
    const reads = limitFor(kind) / chunk.length + 1;
    const stream = streamed(Array(reads + 20).fill(chunk), kind);
    await unknown(operation(kind, stream.fetchImpl), kind);
    assert.equal(stream.state.reads, reads);
    assert.equal(stream.state.cancelled, 1);
    assert.equal(stream.state.released, 1);
    assert.equal(stream.state.calls.length, 1);
  });

  test(`${kind}: body failure preserves the HTTP status and releases the reader`, async () => {
    const stream = streamed([Buffer.from("{"), new Error("synthetic body interruption")], kind);
    await unknown(operation(kind, stream.fetchImpl), kind);
    assert.equal(stream.state.cancelled, 1);
    assert.equal(stream.state.released, 1);
    assert.equal(stream.state.calls.length, 1);
  });
}

test("wire: valid chunk boundaries, UTF-8 and declared length are preserved", async () => {
  const reply = clone(legacy.reply_delivered);
  reply.candidate.output_blocks[0].text = "Multiline:\n\tα 🔐\r\n";
  const raw = Buffer.from(JSON.stringify(reply));
  const chunks = Array.from({length: Math.ceil(raw.length / 3)}, (_, i) => raw.subarray(i * 3, i * 3 + 3));
  const stream = streamed(chunks, "wire", {"Content-Length": String(raw.length)});
  const result = await operation("wire", stream.fetchImpl)();
  assert.equal(result.candidate.output_blocks[0].text, reply.candidate.output_blocks[0].text);
  assert.equal(stream.state.cancelled, 0);
  assert.equal(stream.state.released, 1);
});

test("wire: length mismatch and invalid declarations never reach JSON validation", async () => {
  const raw = Buffer.from(JSON.stringify(legacy.reply_delivered));
  for (const length of [String(raw.length - 1), String(raw.length + 1), "-1", "1.5", "invalid"]) {
    const stream = streamed([raw], "wire", {"Content-Length": length});
    await unknown(operation("wire", stream.fetchImpl), "wire");
    assert.equal(stream.state.cancelled, 1);
    assert.equal(stream.state.released, 1);
  }
});

test("wire: cancellation failure cannot hide the original read failure", async () => {
  const stream = streamed([new Error("body failure")]);
  stream.reader.cancel = async () => { throw Error("cancellation failure"); };
  await unknown(operation("wire", stream.fetchImpl), "wire");
  assert.equal(stream.state.released, 1);
});

for (const kind of ["wire", "successor"]) {
  test(`${kind}: a valid response at the exact byte cap is accepted`, async () => {
    const value = kind === "wire" ? legacy.reply_delivered : fixture("COMPLETED");
    const body = Buffer.from(JSON.stringify(value));
    const limit = limitFor(kind);
    const raw = Buffer.concat([body, Buffer.alloc(limit - body.length, " ")], limit);
    const chunks = Array.from({length: Math.ceil(raw.length / 65536)},
      (_, index) => raw.subarray(index * 65536, (index + 1) * 65536));
    const stream = streamed(chunks, kind, {"Content-Length": String(limit)});
    assert.equal((await operation(kind, stream.fetchImpl)()).state, kind === "wire" ? "delivered" : "completed");
    assert.equal(stream.state.cancelled, 0);
    assert.equal(stream.state.released, 1);
  });
}

test("all protocols: strict JSON rejects duplicate keys, unsafe integers, bad scalars and excess nesting", async () => {
  for (const kind of methods) {
    for (const raw of [Buffer.from('{"duplicate":1,"duplicate":2}'),
      Buffer.from('{"number":9007199254740992}'), Buffer.from('{"number":1.5}'),
      Buffer.from('{"text":"\\ud800"}'), Buffer.from('{"text":"\\u0000"}'),
      Buffer.from("[".repeat(40) + "0" + "]".repeat(40)), Buffer.from([0xff]),
      Buffer.concat([Buffer.from([0xef, 0xbb, 0xbf]), Buffer.from("{}")])]) {
      const stream = streamed([raw], kind);
      await unknown(operation(kind, stream.fetchImpl), kind);
      assert.equal(stream.state.released, 1);
      assert.equal(stream.state.calls.length, 1);
    }
  }
});

test("wire: buffered injected transports remain bounded; JSON-only transports are rejected", async () => {
  const raw = Buffer.from(JSON.stringify(legacy.capabilities));
  let buffers = 0, json = 0;
  const response = {status: 200, ok: true, headers: new Headers({"EzLLMRouter-Contract-Version": "0.2"}),
    async arrayBuffer() { buffers++; return Uint8Array.from(raw).buffer; },
    async json() { json++; return legacy.capabilities; }};
  const client = new EzLLMRouterClient({baseUrl: "http://synthetic.invalid", token: "synthetic",
    fetchImpl: async () => response});
  assert.equal((await client.getCapabilities()).contract_version, "0.2");
  assert.equal(buffers, 1);
  assert.equal(json, 0);
  delete response.arrayBuffer;
  await unknown(() => client.getCapabilities(), "wire");
  assert.equal(json, 0);
});

function wireClient(reply, wire, status = 200) {
  return new EzLLMRouterClient({baseUrl: "http://synthetic.invalid", token: "synthetic",
    fetchImpl: async () => new Response(JSON.stringify(reply), {status,
      headers: {"EzLLMRouter-Contract-Version": wire}})});
}

for (const wire of ["0.2", "0.3"]) {
  const action = (client, kind, selector) => kind === "submit" ?
    (wire === "0.2" ? client.submit(clone(legacy.submit_text)) : client.submit_rerank(example("DELEGATED_RERANK"))) :
    client.getStatus(selector, {contractVersion: wire});
  for (const kind of ["submit", "status"]) {
    test(`${wire} ${kind}: malformed and foreign recovery handles are discarded`, async () => {
      const original = wire === "0.2" ? clone(kind === "submit" ? legacy.reply_delivered : legacy.status_present) :
        fixture(kind === "submit" ? "COMPLETED" : "STATUS_VALID_UNKNOWN_COST");
      for (const malformed of [false, true]) {
        const reply = clone(original);
        if (malformed) reply.handle = ["not a handle"];
        else if (kind === "submit") reply.handle.work_key.task_id = "task.foreign";
        else reply.handle.submission_id = "submission.foreign";
        await assert.rejects(action(wireClient(reply, wire), kind,
          {submission_id: original.handle.submission_id}), error => {
          assert.equal(error.code, "PROTOCOL_INVALID");
          assert.equal(error.retry_guidance, "query_first");
          assert.equal(error.handle, undefined);
          assert.equal(error.work_key, undefined);
          return true;
        });
      }
    });
  }
  test(`${wire}: a matching handle survives a verified failure`, async () => {
    const reply = wire === "0.2" ? clone(legacy.reply_failed_fdc) : fixture("FAILED_BEFORE_SEND");
    await assert.rejects(action(wireClient(reply, wire, 409), "submit"), error => {
      assert.equal(error.code, "FDC_REJECTED");
      assert.deepEqual(error.handle, reply.handle);
      assert.deepEqual(error.work_key, reply.handle.work_key);
      assert.notEqual(error.handle, reply.handle);
      return true;
    });
  });
  test(`${wire}: unsupported versions never supply a recovery handle`, async () => {
    const reply = wire === "0.2" ? clone(legacy.reply_delivered) : fixture("COMPLETED");
    reply.contract_version = "9.9";
    await assert.rejects(action(wireClient(reply, wire), "submit"), error => {
      assert.equal(error.code, "UNSUPPORTED_VERSION");
      assert.equal(error.handle, undefined);
      assert.equal(error.work_key, undefined);
      return true;
    });
  });
}

test("wire: a trailing newline cannot turn a foreign submission ID into a recovery handle", async () => {
  const reply = clone(legacy.status_present);
  reply.handle.submission_id += "\n";
  await assert.rejects(wireClient(reply, "0.2").getStatus({submission_id: "submission.demo"}), error => {
    assert.equal(error.code, "PROTOCOL_INVALID");
    assert.equal(error.handle, undefined);
    return true;
  });
});

function largeEmbedding() {
  const request = example("DIRECT_DOCUMENT");
  request.requested_configuration_ref = "cfg.newly.registered.embedding";
  request.input.profile = {...request.input.profile, profile_id: "space.new", model_ref: "model.new", dimensions: 2048};
  request.input.items = Array.from({length: 25}, (_, i) => ({item_id: "item." + i, text: "synthetic"}));
  const reply = fixture("COMPLETED");
  Object.assign(reply.handle.work_key, request.work_selector);
  reply.result = clone(vectors.result_examples.find(row => row.id === "EMBEDDING_RESULT").value);
  Object.assign(reply.result, {attempt_id: reply.attempt_id, profile_id: "space.new", model_ref: "model.new", dimensions: 2048});
  reply.result.vectors = request.input.items.map((item, input_index) => ({item_id: item.item_id, input_index,
    values: Array(2048).fill("0.1234567890123456")}));
  return {request, reply};
}

test("successor: a large embedding from a newly registered configuration is submitted and recovered", async () => {
  const {request, reply} = largeEmbedding();
  const raw = Buffer.from(JSON.stringify(reply));
  assert(raw.length > 65536);
  const stream = streamed(Array.from({length: Math.ceil(raw.length / 65536)},
    (_, i) => raw.subarray(i * 65536, (i + 1) * 65536)), "successor");
  const client = new EzLLMRouterClient({baseUrl: "http://synthetic.invalid", token: "synthetic", fetchImpl: stream.fetchImpl});
  assert.equal((await client.submit_embedding(request)).result.vectors.length, 25);
  assert.equal(stream.state.released, 1);
  assert.equal(stream.state.calls.length, 1);
  const status = fixture("STATUS_VALID_UNKNOWN_COST");
  status.handle = reply.handle;
  status.attempts[0].attempt_id = reply.attempt_id;
  status.attempts[0].result = reply.result;
  const recovered = await wireClient(status, "0.3").getSuccessorStatus({submission_id: status.handle.submission_id});
  assert.equal(recovered.attempts[0].result.vectors.length, 25);
});

test("successor: embedding profile, model, dimensions and item correspondence still reject mismatches", async () => {
  const {request, reply} = largeEmbedding();
  for (const [key, value] of [["profile_id", "space.foreign"], ["model_ref", "model.foreign"], ["dimensions", 3]]) {
    const bad = clone(reply);
    bad.result[key] = value;
    await assert.rejects(wireClient(bad, "0.3").submit_embedding(request), error => {
      assert.equal(error.code, "PROTOCOL_INVALID");
      assert.deepEqual(error.handle, reply.handle);
      return true;
    });
  }
  const bad = clone(reply);
  bad.result.vectors[0].item_id = "item.foreign";
  await assert.rejects(wireClient(bad, "0.3").submit_embedding(request), error => error.code === "PROTOCOL_INVALID");
});

test("successor: new rerank profiles match the request without a synthetic configuration allowlist", async () => {
  const request = example("DELEGATED_RERANK");
  request.requested_configuration_ref = "cfg.newly.registered.rerank";
  request.input.ranking_profile_id = "rank.new";
  const reply = fixture("COMPLETED");
  reply.result.ranking_profile_id = "rank.new";
  assert.equal((await wireClient(reply, "0.3").submit_rerank(request)).result.ranking_profile_id, "rank.new");
  reply.result.ranking_profile_id = "rank.foreign";
  await assert.rejects(wireClient(reply, "0.3").submit_rerank(request), error => error.code === "PROTOCOL_INVALID");
});

for (const kind of methods) {
  test(`${kind}: one total deadline bounds a fetch that never resolves`, async () => {
    let calls=0, signal;
    const started=performance.now();
    await unknown(operation(kind,async (_url,options)=>{calls++;signal=options.signal;return new Promise(()=>{});},25),kind,null);
    assert.equal(calls,1);assert.equal(signal.aborted,true);
    assert(performance.now()-started<1000);
  });
  test(`${kind}: deadline includes a stalled response body and cancels its reader`, async () => {
    const stream=streamed([],kind);
    stream.reader.read=()=>new Promise(()=>{});
    await unknown(operation(kind,stream.fetchImpl,25),kind,200);
    assert.equal(stream.state.calls.length,1);
    assert.equal(stream.state.cancelled,1);
    assert.equal(stream.state.released,1);
  });
  test(`${kind}: slow body chunks cannot restart the total deadline`, async () => {
    const stream=streamed(Array(20).fill(Buffer.from(" ")),kind);
    const read=stream.reader.read;
    stream.reader.read=async()=>{await new Promise(resolve=>setTimeout(resolve,8));return read();};
    await unknown(operation(kind,stream.fetchImpl,25),kind,200);
    await new Promise(resolve=>setTimeout(resolve,15));
    assert(stream.state.reads<20);
    assert.equal(stream.state.calls.length,1);
    assert.equal(stream.state.cancelled,1);
    assert.equal(stream.state.released,1);
  });
}

test("local circular, BigInt, float and null request values never reach fetch",async()=>{
  let calls=0;
  const client=new EzLLMRouterClient({baseUrl:"http://synthetic.invalid",token:"synthetic",fetchImpl:async()=>{calls++;throw Error("unexpected send");}});
  const circular={};circular.self=circular;
  for(const value of [circular,1n,1.25,null]){
    const request=clone(legacy.submit_text);request.extra=value;
    await assert.rejects(client.submit(request),error=>error instanceof EzLLMRouterError&&error.code==="SCHEMA_INVALID"&&error.retry_guidance==="never");
  }
  const integration=new IntegrationClient("http://synthetic.invalid","synthetic",{fetchImpl:async()=>{calls++;throw Error("unexpected send");}});
  for(const value of [circular,1n])await assert.rejects(integration.submitObservation({extra:value}),error=>error instanceof IntegrationClientError&&error.code==="SCHEMA_INVALID"&&error.retry_guidance==="never");
  assert.equal(calls,0);
});

test("credentials stay private in both client diagnostic representations",()=>{
  const {inspect}=require("node:util"),token="synthetic-private-credential-canary";
  for(const client of [new EzLLMRouterClient({baseUrl:"http://synthetic.invalid",token}),new IntegrationClient("http://synthetic.invalid",token)]){
    assert.equal(client.token,undefined);
    assert(!inspect(client,{showHidden:true}).includes(token));
    assert(!JSON.stringify(client).includes(token));
  }
  const error=new IntegrationClientError("SYNTHETIC",503,"query_first");
  assert.equal(error.http_status,error.httpStatus);
  assert.equal(error.retry_guidance,error.retryGuidance);
});

test("timeout configuration and header credentials are validated before fetch",()=>{
  for(const timeoutMs of [0,-1,1.5,Infinity,NaN,2147483648]){
    assert.throws(()=>new EzLLMRouterClient({baseUrl:"http://synthetic.invalid",token:"synthetic",timeoutMs}),TypeError);
    assert.throws(()=>new IntegrationClient("http://synthetic.invalid","synthetic",{timeoutMs}),TypeError);
  }
  for(const token of ["with space","bad\r\nheader","nonascii-\u00e9"]){
    assert.throws(()=>new EzLLMRouterClient({baseUrl:"http://synthetic.invalid",token}),TypeError);
    assert.throws(()=>new IntegrationClient("http://synthetic.invalid",token),TypeError);
  }
});

test("late fetch responses are cleaned up after the caller deadline",async()=>{
  const stream=streamed([],"wire");let resolve;
  await unknown(operation("wire",()=>new Promise(done=>{resolve=done;}),20),"wire",null);
  resolve(stream.response);
  await new Promise(done=>setImmediate(done));
  assert.equal(stream.state.cancelled,1);assert.equal(stream.state.released,1);
});

test("completed exchanges clear their deadline timer",async()=>{
  const row=require("./cases.json").find(row=>row.name==="capabilities");
  let signal;
  const client=new EzLLMRouterClient({baseUrl:"http://synthetic.invalid",token:"synthetic",timeoutMs:20,
    fetchImpl:async(_url,options)=>{signal=options.signal;return new Response(JSON.stringify(row.response),{headers:{"EzLLMRouter-Contract-Version":"0.2"}});}});
  await client.getCapabilities();
  await new Promise(done=>setTimeout(done,30));
  assert.equal(signal.aborted,false);
});
