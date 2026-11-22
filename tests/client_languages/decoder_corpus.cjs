"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const sdk = process.env.EZLLMROUTER_JS_CONSUMER;
const {strictDecode} = require(sdk ? path.join(path.dirname(require.resolve("@cognitivedynamics/ezllmrouter-client", {paths: [sdk]})), "successor.cjs") : "../../clients/js/successor.cjs");
const policy = JSON.parse(fs.readFileSync(path.join(__dirname, "../fixtures/contracts/transport-security/decoder_cases.json"), "utf8"));
function canonical(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  const order = (a, b) => {
    const left = [...a].map(c => c.codePointAt(0)), right = [...b].map(c => c.codePointAt(0));
    for (let i = 0; i < Math.min(left.length, right.length); i++) if (left[i] !== right[i]) return left[i] - right[i];
    return left.length - right.length;
  };
  return "{" + Object.keys(value).sort(order).map(key => JSON.stringify(key) + ":" + canonical(value[key])).join(",") + "}";
}
for (const row of policy.cases) {
  let result = null;
  try {
    const value = strictDecode(Buffer.from(row.raw_hex, "hex"), 262144);
    if (value && typeof value === "object" && !Array.isArray(value)) result = canonical(value);
  } catch {}
  assert.equal(result, row.canonical, row.id);
}
console.log(`JavaScript: ${policy.cases.length} independent decoder cases passed.`);
