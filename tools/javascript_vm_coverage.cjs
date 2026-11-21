"use strict";
// The pinned Node VM mis-resolves an early `typeof` after a later lexical declaration
// under native precise coverage. Keep that profiler off for VM components and insert
// counters with the already-pinned TypeScript parser; normal component runs stay raw.
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm"), crypto = require("node:crypto");
const root = path.resolve(__dirname, "..");
const files = new Map(), cache = new Map();
let compiler;
function typescript() {
  if (!compiler) {
    const directory = path.join(root, "tests/playwright/node_modules/typescript");
    if (require(path.join(directory, "package.json")).version !== "5.9.3") throw Error("VM coverage requires locked TypeScript 5.9.3");
    compiler = require(directory);
  }
  return compiler;
}
function instrument(source, filename) {
  const ts = typescript(), key = path.resolve(filename), hash = crypto.createHash("sha256").update(source).digest("hex");
  if (cache.has(key + hash)) return cache.get(key + hash);
  const parsed = ts.createSourceFile(key, source, ts.ScriptTarget.ESNext, true, ts.ScriptKind.JS);
  if (parsed.parseDiagnostics.length) throw Error("VM coverage input is not valid JavaScript");
  const entry = { sha256: hash, counters: {} }; files.set(key, entry);
  function counter(node, kind) {
    const start = node.getStart(parsed), id = kind + ":" + start + ":" + node.end;
    entry.counters[id] ??= { kind, line: parsed.getLineAndCharacterOfPosition(start).line + 1, count: 0 };
    return ts.factory.createExpressionStatement(ts.factory.createCallExpression(
      ts.factory.createPropertyAccessExpression(ts.factory.createIdentifier("__EZLLMROUTER_VM_COVERAGE"), "hit"), undefined,
      [ts.factory.createStringLiteral(key), ts.factory.createStringLiteral(id)]));
  }
  const directive = node => ts.isExpressionStatement(node) && ts.isStringLiteral(node.expression);
  function statements(nodes) {
    const result = []; let prologue = true;
    for (const node of nodes) {
      if (prologue && directive(node)) { result.push(node); continue; }
      prologue = false;
      if (node.pos >= 0) result.push(counter(node, "statement"));
      result.push(node);
    }
    return ts.factory.createNodeArray(result);
  }
  const transformed = ts.transform(parsed, [context => {
    function wrap(node) { return ts.isBlock(node) ? node : ts.factory.createBlock([counter(node, "statement"), node], true); }
    function visit(node) {
      const updated = ts.visitEachChild(node, visit, context);
      if (ts.isSourceFile(updated) || ts.isBlock(updated) || ts.isCaseClause(updated) || ts.isDefaultClause(updated)) updated.statements = statements(updated.statements);
      if (ts.isIfStatement(updated)) {
        updated.thenStatement = wrap(updated.thenStatement);
        if (updated.elseStatement) updated.elseStatement = wrap(updated.elseStatement);
      }
      if (ts.isForStatement(updated) || ts.isForInStatement(updated) || ts.isForOfStatement(updated) || ts.isWhileStatement(updated) || ts.isDoStatement(updated)) updated.statement = wrap(updated.statement);
      if (ts.isFunctionLike(updated) && updated.body) {
        let body = updated.body;
        if (!ts.isBlock(body)) body = ts.factory.createBlock([ts.factory.createReturnStatement(body)], true);
        const list = [...body.statements]; let index = 0;
        while (index < list.length && directive(list[index])) index++;
        list.splice(index, 0, counter(node, "function"));
        updated.body = ts.factory.updateBlock(body, list);
      }
      return updated;
    }
    return node => ts.visitNode(node, visit);
  }]);
  try {
    const result = ts.createPrinter().printFile(transformed.transformed[0]);
    cache.set(key + hash, result); return result;
  } finally { transformed.dispose(); }
}
const recorder = { hit(filename, id) { files.get(filename).counters[id].count++; } };
function runScript(source, context, options = {}) {
  if (!process.env.EZLLMROUTER_JS_COVERAGE) return vm.runInContext(source, context, options);
  if (process.env.NODE_V8_COVERAGE) throw Error("Native V8 coverage must be disabled for late-lexical VM components");
  if (!options.filename) throw Error("VM coverage requires a canonical source filename");
  const filename = path.isAbsolute(options.filename) ? options.filename : path.join(root, "web", options.filename);
  if (context.__EZLLMROUTER_VM_COVERAGE && context.__EZLLMROUTER_VM_COVERAGE !== recorder) throw Error("VM coverage namespace collision");
  context.__EZLLMROUTER_VM_COVERAGE = recorder;
  return vm.runInContext(instrument(source, filename), context, options);
}
process.once("exit", () => {
  const directory = process.env.EZLLMROUTER_JS_COVERAGE;
  if (directory && files.size) {
    fs.mkdirSync(directory, { recursive: true });
    fs.writeFileSync(path.join(directory, "vm-coverage-" + process.pid + ".json"), JSON.stringify({ scope: "TypeScript 5.9.3 AST statement/function counters; no branch percentage", files: Object.fromEntries(files) }));
  }
});
module.exports = { runScript, instrument, recorder, files };
