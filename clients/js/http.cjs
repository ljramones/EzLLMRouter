"use strict";

const WIRE_RESPONSE_LIMIT = 1024 * 1024;
const SUCCESSOR_RESPONSE_LIMIT = 16 * 1024 * 1024;
const INTEGRATION_RESPONSE_LIMIT = 16 * 1024 * 1024;

async function readResponse(response, limit) {
  let reader;
  let complete = false;
  try {
    if (response.body && typeof response.body.getReader === "function") {
      reader = response.body.getReader();
    }
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
        const part = await reader.read();
        if (part.done) break;
        append(part.value);
      }
    } else {
      // Injected, buffered transports own their allocation. Native fetch uses
      // the streaming path above; never fall back to an unbounded json() call.
      append(new Uint8Array(await response.arrayBuffer()));
    }
    if (declared !== null && declared !== undefined && size !== Number(declared)) {
      throw new Error("response length mismatch");
    }
    complete = true;
    return Buffer.concat(chunks, size);
  } finally {
    if (reader) {
      try {
        if (!complete) await reader.cancel();
      } catch {
        // A failed cancellation must not replace the original read failure.
      } finally {
        reader.releaseLock();
      }
    }
  }
}

module.exports = Object.freeze({readResponse, WIRE_RESPONSE_LIMIT,
  SUCCESSOR_RESPONSE_LIMIT, INTEGRATION_RESPONSE_LIMIT});
