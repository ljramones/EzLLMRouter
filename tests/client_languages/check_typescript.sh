#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
mkdir -p "$repo_root/.artifacts"
consumer="$(mktemp -d "$repo_root/.artifacts/typescript-client-XXXXXX")"
export npm_config_cache="${npm_config_cache:-$repo_root/.cache/npm}"
archive="$(npm pack "$repo_root/clients/js" --offline --ignore-scripts --pack-destination "$consumer" --json | node -e 'let s="";process.stdin.on("data",c=>s+=c).on("end",()=>process.stdout.write(JSON.parse(s)[0].filename));')"
printf '%s\n' '{"private":true,"type":"module"}' > "$consumer/package.json"
npm install --prefix "$consumer" --offline --ignore-scripts --no-audit --no-fund "$consumer/$archive"
cp "$repo_root/tests/client_languages/typescript/consumer.mts" "$repo_root/tests/client_languages/typescript/consumer.cts" "$consumer/"
if [[ "${1:-}" != "--package-only" ]]; then
  "${TSC_BINARY:-tsc}" --strict --noEmit --target ES2022 --lib ES2022 --module NodeNext --moduleResolution NodeNext \
    "$consumer/consumer.mts" "$consumer/consumer.cts"
  "${TSC_BINARY:-tsc}" --strict --noEmit --target ES2022 --lib ES2022 --module commonjs --moduleResolution node \
    "$consumer/consumer.cts"
fi
node -e 'const c=require(process.argv[1]);if(c.DurankiClient!==c.EzLLMRouterClient||c.contractVersion!=="0.2")process.exit(1)' \
  "$consumer/node_modules/@cognitivedynamics/ezllmrouter-client"
node --input-type=module -e 'import {pathToFileURL} from "node:url";const c=await import(pathToFileURL(process.argv[1]));if(c.EzLLMRouterClient!==c.default.EzLLMRouterClient||c.contractVersion!=="0.2")process.exit(1)' \
  "$consumer/node_modules/@cognitivedynamics/ezllmrouter-client/index.mjs"
node --input-type=module -e 'import{readFileSync}from"node:fs";import{stripTypeScriptTypes}from"node:module";for(const f of ["index.d.cts","index.d.mts","contracts.d.cts"])stripTypeScriptTypes(readFileSync(process.argv[1]+"/"+f,"utf8"),{mode:"transform"});console.log("Packaged exports and TypeScript declaration syntax passed.")' \
  "$consumer/node_modules/@cognitivedynamics/ezllmrouter-client"
