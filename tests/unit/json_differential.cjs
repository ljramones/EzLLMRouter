"use strict";
// One bounded stdin batch; no sockets, provider clients or artifact downloads.
const fs = require("node:fs"), {strictDecode} = require("../../clients/js/successor.cjs");
function observe(value) {
  if (value === null) return ["null"];
  if (typeof value === "boolean") return ["boolean", value ? "true" : "false"];
  if (typeof value === "number") {
    if (Number.isInteger(value) && !Object.is(value, -0)) return ["integer", String(value)];
    const bits = Buffer.alloc(8); bits.writeDoubleBE(value); return ["float", bits.toString("hex")];
  }
  if (typeof value === "string") return ["string", value];
  if (Array.isArray(value)) return ["array", value.map(observe)];
  return ["object", Object.keys(value).sort().map(key => [key, observe(value[key])])];
}
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
if (!Array.isArray(cases) || cases.length > 10000) throw Error("case budget");
process.stdout.write(JSON.stringify(cases.map(raw => {
  try { return {accepted: true, observation: observe(strictDecode(Buffer.from(raw, "base64"), 262144))}; }
  catch { return {accepted: false}; }
})));
