"use strict";
// Extract the exact private tarball in a disposable networkless container.
const fs=require("node:fs");
const os=require("node:os");
const path=require("node:path");
const {execFileSync}=require("node:child_process");
const artifact=process.env.DEV12_JS_CLIENT_TARBALL;
if(!artifact||!fs.statSync(artifact).isFile())throw Error("private CommonJS tarball absent");
const directory=fs.mkdtempSync(path.join(os.tmpdir(),"dev12-installed-sdk-"));
execFileSync("tar",["-xzf",artifact,"-C",directory]);
process.env.DEV12_JS_CLIENT_DIR=path.join(directory,"package");
require(path.resolve(__dirname, "../../../tests/development_slice/test_retrieval_client.cjs"));
