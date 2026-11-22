"use strict";
const assert = require("node:assert/strict"), test = require("node:test");
const vm = require("node:vm"), path = require("node:path");
const fs = require("node:fs"), os = require("node:os"), {Worker} = require("node:worker_threads");
const {runScript, files} = require("../../tools/javascript_vm_coverage.cjs");

test("workers sharing a pid retain separate VM coverage artifacts", async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "ezllmrouter-vm-"));
  try {
    const workerSource = `
      const {workerData}=require("node:worker_threads"),vm=require("node:vm");
      const {runScript}=require(workerData.helper);
      runScript("function sample(){return 1;} sample();",vm.createContext({}),{filename:workerData.filename});`;
    await Promise.all(["first.js","second.js"].map(filename => new Promise((resolve,reject) => {
      const worker = new Worker(workerSource, {eval:true,workerData:{helper:require.resolve("../../tools/javascript_vm_coverage.cjs"),filename:path.join(directory,filename)},
        env:{...process.env,EZLLMROUTER_JS_COVERAGE:directory,NODE_V8_COVERAGE:""}});
      worker.once("error",reject);worker.once("exit",code=>code?reject(Error("worker failed")):resolve());
    })));
    const artifacts=fs.readdirSync(directory).filter(name=>name.startsWith("vm-coverage-"));
    assert.equal(artifacts.length,2);
    const names=artifacts.flatMap(name=>Object.keys(JSON.parse(fs.readFileSync(path.join(directory,name),"utf8")).files));
    assert.deepEqual(names.sort(),["first.js","second.js"].map(name=>path.join(directory,name)));
  } finally {fs.rmSync(directory,{recursive:true,force:true});}
});

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
