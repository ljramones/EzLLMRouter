"use strict";
// One bounded stdin batch; no sockets, provider clients or artifact downloads.
const fs = require("node:fs"), {strictDecode} = require("../../clients/js/successor.cjs");
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
if (!Array.isArray(cases) || cases.length > 10000) throw Error("case budget");
process.stdout.write(JSON.stringify(cases.map(raw => {
  try { return {accepted: true, value: strictDecode(Buffer.from(raw, "base64"), 262144)}; }
  catch { return {accepted: false}; }
})));
