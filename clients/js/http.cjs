"use strict";

const WIRE_RESPONSE_LIMIT = 1024 * 1024;
const SUCCESSOR_RESPONSE_LIMIT = 16 * 1024 * 1024;
const INTEGRATION_RESPONSE_LIMIT = 16 * 1024 * 1024;

const DEFAULT_TIMEOUT_MS = 35000;
function timeoutMs(value = DEFAULT_TIMEOUT_MS) {
  if (value !== null && (!Number.isSafeInteger(value) || value < 1 || value > 2147483647))
    throw new TypeError("timeoutMs must be a positive integer or null");
  return value;
}

function serializeBody(body, ErrorType, {allowNull = true, details = {}} = {}) {
  if (body === undefined) return undefined;
  const active = new Set();
  function check(value, depth = 0) {
    if (depth > 32) throw new TypeError("request nesting limit");
    if (value === null) { if (!allowNull) throw new TypeError("null request value"); return value; }
    if (typeof value === "string") {
      if (!value.isWellFormed() || value.includes("\0")) throw new TypeError("invalid request text");
      return value;
    }
    if (typeof value === "boolean") return value;
    if (typeof value === "number" && Number.isSafeInteger(value)) return value;
    if (typeof value !== "object" || active.has(value) ||
        !Array.isArray(value) && ![Object.prototype, null].includes(Object.getPrototypeOf(value)))
      throw new TypeError("invalid JSON request value");
    active.add(value);
    try {
      if (Array.isArray(value)) {
        return value.map(item => check(item, depth + 1));
      }
      return Object.fromEntries(Object.entries(value).map(([key, item]) =>
        [check(key, depth + 1), check(item, depth + 1)]));
    } finally { active.delete(value); }
  }
  try { return JSON.stringify(check(body)); }
  catch { throw new ErrorType("SCHEMA_INVALID", null, "never", null, details); }
}

function retryGuidance(value, status) {
  return ["never", "query_first", "orchestrator_decision"].includes(value) ? value :
    status >= 500 ? "query_first" : "never";
}

async function exchange(fetchImpl, url, options, limit, budget) {
  const controller = new AbortController();
  let timer, response;
  const expired = new Promise((_, reject) => {
    if (budget !== null) timer = setTimeout(() => {
      const error = new Error("request deadline exceeded");
      controller.abort(error);
      reject(error);
    }, budget);
  });
  try {
    return await Promise.race([expired, (async () => {
      response = await fetchImpl(url, {...options, signal: controller.signal});
      const raw = await readResponse(response, limit, controller.signal);
      return {response, raw};
    })()]);
  } catch (cause) {
    const error = new Error("HTTP exchange failed", {cause});
    error.httpStatus = response?.status ?? null;
    throw error;
  } finally { clearTimeout(timer); }
}

async function untilAbort(operation, signal) {
  if (!signal) return operation;
  if (signal.aborted) throw signal.reason;
  let abort;
  const interrupted = new Promise((_, reject) => {
    abort = () => reject(signal.reason);
    signal.addEventListener("abort", abort, {once: true});
  });
  try { return await Promise.race([operation, interrupted]); }
  finally { signal.removeEventListener("abort", abort); }
}

async function readResponse(response, limit, signal) {
  let reader;
  let complete = false, cancellation;
  function cancel() {
    if (reader && cancellation === undefined) {
      try { cancellation = Promise.resolve(reader.cancel()).catch(() => {}); }
      catch { cancellation = Promise.resolve(); }
    }
    return cancellation;
  }
  const abort = () => { cancel(); };
  signal?.addEventListener("abort", abort, {once: true});
  const check = () => { if (signal?.aborted) throw signal.reason; };
  try {
    if (response.body && typeof response.body.getReader === "function") {
      reader = response.body.getReader();
    }
    check();
    const encoding = response.headers.get("Content-Encoding");
    if (encoding !== null && encoding !== undefined && encoding.trim().toLowerCase() !== "identity") {
      throw new Error("encoded responses are not supported");
    }
    const declared = response.headers.get("Content-Length");
    if (declared !== null && declared !== undefined &&
        (/^[0-9]+$/.exec(declared)?.[0] !== declared || Number(declared) > limit)) {
      throw new Error("invalid or excessive content length");
    }
    const chunks = [];
    let size = 0;
    function append(chunk) {
      if (!(chunk instanceof Uint8Array) || chunk.byteLength > limit - size) {
        throw new Error("response exceeds its byte limit");
      }
      size += chunk.byteLength;
      chunks.push(Buffer.from(chunk));
    }
    if (reader) {
      while (true) {
        check();
        const part = await untilAbort(reader.read(), signal);
        check();
        if (part.done) break;
        append(part.value);
      }
    } else {
      // Injected, buffered transports own their allocation. Native fetch uses
      // the streaming path above; never fall back to an unbounded json() call.
      append(new Uint8Array(await untilAbort(response.arrayBuffer(), signal)));
    }
    check();
    if (declared !== null && declared !== undefined && size !== Number(declared)) {
      throw new Error("response length mismatch");
    }
    complete = true;
    return Buffer.concat(chunks, size);
  } finally {
    try {
      if (reader) {
        try {
          if (!complete) cancel();
          if (cancellation && !signal?.aborted) await untilAbort(cancellation, signal);
        } finally {
          try { reader.releaseLock(); } catch { /* Preserve the original failure. */ }
        }
      }
    } finally { signal?.removeEventListener("abort", abort); }
  }
}

module.exports = Object.freeze({readResponse, exchange, serializeBody, retryGuidance, timeoutMs, DEFAULT_TIMEOUT_MS, WIRE_RESPONSE_LIMIT,
  SUCCESSOR_RESPONSE_LIMIT, INTEGRATION_RESPONSE_LIMIT});
