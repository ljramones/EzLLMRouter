"use strict";
const assert = require("node:assert/strict"), test = require("node:test");
const vm = require("node:vm"), path = require("node:path");
const {runScript, files} = require("../../tools/javascript_vm_coverage.cjs");

test("VM measurement preserves late lexical bindings, strict directives and arrow this", () => {
  const context = vm.createContext({});
  const filename = path.resolve(__dirname, "measurement-synthetic.js");
  runScript('"use strict"; function clear(){if(typeof state!=="undefined")state.x=false;} clear();', context, {filename});
  runScript('const state={x:true};', context, {filename: filename + "-state"});
  vm.runInContext("clear()", context);
  assert.equal(vm.runInContext("state.x", context), false);
  runScript('"use strict"; function strict(){return this;} const obj={x:4, arrow(){return ()=>this.x;}};', context, {filename: filename + "-strict"});
  assert.equal(vm.runInContext("strict()", context), undefined);
  assert.equal(vm.runInContext("obj.arrow()()", context), 4);
});

if (process.env.EZLLMROUTER_JS_COVERAGE) {
  test("VM counters distinguish untaken statements/functions and preserve control flow", () => {
    const context = vm.createContext({}), filename = path.resolve(__dirname, "measurement-control.js");
    runScript('function unused(){return 99;} function run(){let n=0; for(let i=0;i<4;i++) if(i===2) continue; else n++; try {throw Error("synthetic");} catch(e){n++;} finally {n++;} return n;} run();', context, {filename});
    assert.equal(vm.runInContext("run()", context), 5);
    const rows = Object.values(files.get(filename).counters);
    assert.ok(rows.some(row => row.kind === "function" && row.count === 0));
    assert.ok(rows.some(row => row.kind === "function" && row.count === 2));
    assert.ok(rows.some(row => row.kind === "statement" && row.count === 0));
    assert.ok(rows.some(row => row.kind === "statement" && row.count >= 4));
  });
}
