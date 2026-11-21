"use strict";
// Parse canonical sources without evaluating them. Offsets use V8's UTF-16 units.
const fs = require("node:fs"), path = require("node:path"), crypto = require("node:crypto");
const directory = path.resolve(__dirname, "../tests/playwright/node_modules/typescript");
if (require(path.join(directory, "package.json")).version !== "5.9.3") {
  throw Error("Static function coverage requires locked TypeScript 5.9.3");
}
const ts = require(directory);

function inventory(filename) {
  const source = fs.readFileSync(filename, "utf8");
  const parsed = ts.createSourceFile(filename, source, ts.ScriptTarget.ESNext, true, ts.ScriptKind.JS);
  if (parsed.parseDiagnostics.length) throw Error("Static coverage input is not valid JavaScript: " + filename);
  const functions = [];
  function visit(node) {
    if (ts.isFunctionLike(node) && node.body) {
      const start = node.getStart(parsed);
      functions.push({
        start, end: node.end, body_start: node.body.getStart(parsed),
        kind: ts.SyntaxKind[node.kind], line: parsed.getLineAndCharacterOfPosition(start).line + 1,
      });
    }
    ts.forEachChild(node, visit);
  }
  visit(parsed);
  return { sha256: crypto.createHash("sha256").update(source).digest("hex"), utf16_length: source.length, functions };
}

if (require.main === module) {
  const filenames = JSON.parse(fs.readFileSync(0, "utf8"));
  process.stdout.write(JSON.stringify(Object.fromEntries(filenames.map(filename => [filename, inventory(filename)]))));
}
module.exports = { inventory };
