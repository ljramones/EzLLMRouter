#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
root=$(cd "$(dirname "$0")/../.." && pwd -P)
run_name=${1:?usage: ./tests/tool_cycle/run.sh run-YYYYMMDD-NN}
[[ "$run_name" =~ ^run-[0-9]{8}-[0-9]{2}$ ]] || { echo 'invalid run name' >&2; exit 2; }
run_dir="/private/tmp/ezllmrouter-dev-03/$run_name"
result_dir="$root/.artifacts/tool-cycle"
project="ezllmrouter-dev03-${run_name#run-}"
python_tool=/opt/homebrew/bin/python3.12
python_image=docker.io/library/python@sha256:739ba32ae445e8d58f3d90feb85f83bebc8346f8dd280fa1eb5848f4ff1ed163
node_image=docker.io/library/node@sha256:be8204d4bd327363357f532187b752ff62759c31bedf98e9e18fc08c9cbd605c
export EZLLMROUTER_RECEIVER_IMAGE="ezllmrouter-dev03-receiver:$run_name"
export EZLLMROUTER_SERVICE_IMAGE="ezllmrouter-dev03-service:$run_name"
export EZLLMROUTER_PYTHON_CLIENT_IMAGE="ezllmrouter-dev03-pyclient:$run_name"
export EZLLMROUTER_JS_CLIENT_IMAGE="ezllmrouter-dev03-jsclient:$run_name"
compose_file="$root/tests/tool_cycle/compose.yaml"
started=0
mutation_started=0
built_images=()

logrun() {
  local name=$1; shift
  printf '%q ' "$@" > "$run_dir/$name.argv"; printf '\n' >> "$run_dir/$name.argv"
  set +e
  "$@" > "$run_dir/$name.stdout" 2> "$run_dir/$name.stderr"
  local rc=$?
  set -e
  printf '%s\n' "$rc" > "$run_dir/$name.exit"
  cat "$run_dir/$name.stdout"
  cat "$run_dir/$name.stderr" >&2
  return "$rc"
}
compose() { docker --context desktop-linux compose -f "$compose_file" -p "$project" "$@"; }

capture() {
  "$python_tool" -I -B - "$run_dir" "$result_dir" <<'PY'
import hashlib,json,sys,zipfile
from pathlib import Path
run,out=map(Path,sys.argv[1:]);dest=out/('DEV-03-RUNTIME-'+run.name+'.zip')
if dest.exists() or dest.is_symlink():raise SystemExit('runtime packet collision')
secrets=[(run/name).read_bytes() for name in ('token',) if (run/name).is_file()]
rows=[]
with zipfile.ZipFile(dest,'x',zipfile.ZIP_DEFLATED) as z:
 for path in sorted(run.rglob('*')):
  if path.is_file() and not path.is_symlink() and 'build' not in path.relative_to(run).parts and path.name not in {'token','capture.stdout','capture.stderr'}:
   raw=path.read_bytes();redacted=False
   for secret in secrets:
    if secret and secret in raw:raw=raw.replace(secret,b'[REDACTED-TOKEN]');redacted=True
   name=str(path.relative_to(run));z.writestr(name,raw)
   rows.append({'path':name,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
                'token_redacted':redacted})
 z.writestr('EVIDENCE-MANIFEST.json',json.dumps({'files':rows,'self_excluded':True},indent=2))
print(json.dumps({'path':str(dest),'sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'payloads':len(rows)}))
PY
}

finish() {
  local rc=$?
  trap - EXIT
  set +e
  printf '%s\n' "$rc" > "$run_dir/work.exit"
  if [[ $started == 1 ]]; then
    compose ps > "$run_dir/compose-ps.stdout" 2> "$run_dir/compose-ps.stderr"
    compose logs --no-color > "$run_dir/compose-logs.stdout" 2> "$run_dir/compose-logs.stderr"
    compose exec -T receiver cat /data/arrivals.jsonl > "$run_dir/final-receiver.stdout" 2> "$run_dir/final-receiver.stderr"
    printf '%s\n' "$?" > "$run_dir/final-receiver.exit"
    compose exec -T service python -c \
      'import sqlite3,json;d=sqlite3.connect("/data/store.sqlite");print(json.dumps({"submissions":d.execute("select count(*) from submissions").fetchone()[0],"intents":d.execute("select count(*) from intents").fetchone()[0],"usage_revisions":d.execute("select count(*) from usage_revisions").fetchone()[0]}))' \
      > "$run_dir/final-service.stdout" 2> "$run_dir/final-service.stderr"
    printf '%s\n' "$?" > "$run_dir/final-service.exit"
    if [[ $mutation_started == 1 ]]; then
      compose exec -T service_mutation python -c \
        'import sqlite3,json;d=sqlite3.connect("/data/store.sqlite");print(json.dumps({"submissions":d.execute("select count(*) from submissions").fetchone()[0],"intents":d.execute("select count(*) from intents").fetchone()[0],"usage_revisions":d.execute("select count(*) from usage_revisions").fetchone()[0]}))' \
        > "$run_dir/final-mutation-service.stdout" 2> "$run_dir/final-mutation-service.stderr"
      printf '%s\n' "$?" > "$run_dir/final-mutation-service.exit"
    fi
    compose down --remove-orphans --volumes > "$run_dir/cleanup.stdout" 2> "$run_dir/cleanup.stderr"
    local cleanup_rc=$?
    printf '%s\n' "$cleanup_rc" > "$run_dir/cleanup.exit"
    if [[ $rc == 0 && $cleanup_rc != 0 ]]; then rc=$cleanup_rc; fi
  fi
  if (( ${#built_images[@]} )); then
    docker --context desktop-linux image rm "${built_images[@]}" > "$run_dir/image-cleanup.stdout" 2> "$run_dir/image-cleanup.stderr"
    local image_rc=$?
    printf '%s\n' "$image_rc" > "$run_dir/image-cleanup.exit"
    if [[ $rc == 0 && $image_rc != 0 ]]; then rc=$image_rc; fi
  fi
  printf '%s\n' "$rc" > "$run_dir/run.exit"
  capture > "$run_dir/capture.stdout" 2> "$run_dir/capture.stderr"
  local capture_rc=$?
  if [[ $capture_rc != 0 ]]; then cat "$run_dir/capture.stderr" >&2; exit "$capture_rc"; fi
  cat "$run_dir/capture.stdout"
  exit "$rc"
}

[[ ! -e "$run_dir" && ! -L "$run_dir" ]] || { echo "run collision: $run_dir" >&2; exit 2; }
[[ ! -e "$result_dir/DEV-03-RUNTIME-$run_name.zip" ]] || { echo 'runtime packet collision' >&2; exit 2; }
mkdir -p -m 700 "$run_dir/build/python" "$run_dir/build/js" "$run_dir/build/service" "$run_dir/build/receiver"
trap finish EXIT
"$python_tool" -I -B -c 'import secrets,sys;open(sys.argv[1],"x").write(secrets.token_urlsafe(48))' "$run_dir/token"
chmod 0600 "$run_dir/token"
export EZLLMROUTER_DEV_TOKEN
EZLLMROUTER_DEV_TOKEN=$(cat "$run_dir/token")
logrun stage "$python_tool" -I -B "$root/tests/tool_cycle/stage.py" prepare "$root" "$run_dir"
logrun core-regression env TMPDIR="$run_dir" "$python_tool" -I -B "$root/tests/development_slice/test_core.py" -v
logrun tool-core-component env EZLLMROUTER_TEST_SCRATCH="$run_dir" "$python_tool" -I -B "$root/tests/tool_cycle/test_core.py" -v
logrun receiver-component "$python_tool" -I -B "$root/tests/tool_cycle/test_receiver.py" -v
logrun base-image-inspect docker --context desktop-linux image inspect "$python_image" "$node_image"
logrun base-image-verify "$python_tool" -I -B "$root/tests/tool_cycle/stage.py" verify-images "$run_dir/base-image-inspect.stdout"
logrun image-tag-list docker --context desktop-linux image ls --format '{{.Repository}}:{{.Tag}}'
logrun image-tag-collision-check "$python_tool" -I -B -c 'import sys;tags=set(open(sys.argv[1]).read().splitlines());wanted=sys.argv[2:];assert not tags.intersection(wanted),"run image tag collision";print("run image tags clear")' \
  "$run_dir/image-tag-list.stdout" "$EZLLMROUTER_RECEIVER_IMAGE" "$EZLLMROUTER_SERVICE_IMAGE" "$EZLLMROUTER_PYTHON_CLIENT_IMAGE" "$EZLLMROUTER_JS_CLIENT_IMAGE"
source_hash=$(shasum -a 256 "$run_dir/source-build-manifest.json" | awk '{print $1}')
logrun receiver-build docker --context desktop-linux build --pull=false --network none --platform linux/arm64 --build-arg "PYTHON_IMAGE=$python_image" \
  --label "org.ezllmrouter.dev03.source-manifest-sha256=$source_hash" \
  -f "$root/tests/development_slice/Dockerfile.receiver" -t "$EZLLMROUTER_RECEIVER_IMAGE" "$run_dir/build/receiver"
built_images+=("$EZLLMROUTER_RECEIVER_IMAGE")
logrun service-build docker --context desktop-linux build --pull=false --network none --platform linux/arm64 --build-arg "PYTHON_IMAGE=$python_image" \
  --label "org.ezllmrouter.dev03.source-manifest-sha256=$source_hash" \
  -f "$root/tests/development_slice/Dockerfile.service" -t "$EZLLMROUTER_SERVICE_IMAGE" "$run_dir/build/service"
built_images+=("$EZLLMROUTER_SERVICE_IMAGE")
logrun python-client-build docker --context desktop-linux build --pull=false --network none --platform linux/arm64 --build-arg "PYTHON_IMAGE=$python_image" \
  --label "org.ezllmrouter.dev03.source-manifest-sha256=$source_hash" \
  -f "$root/tests/tool_cycle/Dockerfile.python-consumer" -t "$EZLLMROUTER_PYTHON_CLIENT_IMAGE" "$run_dir/build/python"
built_images+=("$EZLLMROUTER_PYTHON_CLIENT_IMAGE")
logrun js-client-build docker --context desktop-linux build --pull=false --network none --platform linux/arm64 --build-arg "NODE_IMAGE=$node_image" \
  --label "org.ezllmrouter.dev03.source-manifest-sha256=$source_hash" \
  -f "$root/tests/tool_cycle/Dockerfile.js-consumer" -t "$EZLLMROUTER_JS_CLIENT_IMAGE" "$run_dir/build/js"
built_images+=("$EZLLMROUTER_JS_CLIENT_IMAGE")
logrun built-image-inspect docker --context desktop-linux image inspect "${built_images[@]}"
logrun crypto-proof docker --context desktop-linux run --rm --pull=never --platform linux/arm64 --network none --read-only --cap-drop ALL \
  "$EZLLMROUTER_SERVICE_IMAGE" python /app/tests/test_crypto.py
logrun tool-core-target docker --context desktop-linux run --rm --pull=never --platform linux/arm64 --network none --read-only --cap-drop ALL \
  --tmpfs /tmp:rw,nosuid,nodev,size=8m "$EZLLMROUTER_SERVICE_IMAGE" python /app/tests/tool_cycle/test_core.py -v
logrun http-boundary docker --context desktop-linux run --rm --pull=never --platform linux/arm64 --network none --read-only --cap-drop ALL \
  --tmpfs /tmp:rw,nosuid,nodev,size=8m "$EZLLMROUTER_SERVICE_IMAGE" python /app/tests/test_http.py -v
logrun native-adapter docker --context desktop-linux run --rm --pull=never --platform linux/arm64 --network none --read-only --cap-drop ALL \
  --tmpfs /tmp:rw,nosuid,nodev,size=8m "$EZLLMROUTER_SERVICE_IMAGE" python /app/tests/test_native_adapter.py -v
started=1
logrun compose-up compose up -d receiver service
ready=0
for _ in {1..20}; do
  if compose exec -T service python -c 'import socket;socket.create_connection(("127.0.0.1",8765),1).close()' >/dev/null 2>&1; then ready=1; break; fi
  sleep 1
done
[[ "$ready" == 1 ]] || { echo 'service readiness failed' >&2; exit 1; }
logrun python-installed-identity compose run -T --rm --no-deps python_consumer python -c \
  'import ezllmrouter_client,importlib.metadata,importlib.util,json,hashlib,pathlib;d=importlib.metadata.distribution("cognitivedynamics-ezllmrouter-client");assert importlib.util.find_spec("ezllmrouter_server") is None;p=pathlib.Path(ezllmrouter_client.__file__);print(json.dumps({"module":str(p),"module_sha256":hashlib.sha256(p.read_bytes()).hexdigest(),"version":d.version,"requires":d.requires}))'
logrun python-pip-check compose run -T --rm --no-deps python_consumer python -m pip check
logrun python-tool-client-unit compose run -T --rm --no-deps python_consumer python test_python_client.py -v
logrun js-installed-identity compose run -T --rm --no-deps js_consumer node -e \
  'const fs=require("node:fs"),crypto=require("node:crypto");let n=0;globalThis.fetch=()=>{n++;throw Error("import invoked fetch")};const p=require("@cognitivedynamics/ezllmrouter-client"),file=require.resolve("@cognitivedynamics/ezllmrouter-client");console.log(JSON.stringify({module:file,module_sha256:crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex"),exports:Object.keys(p),fetch_calls:n}))'
logrun js-tool-client-unit compose run -T --rm --no-deps js_consumer node test_js_client.cjs
logrun python-cycle compose run -T --rm --no-deps python_consumer python python_actor.py cycle
python_first=$("$python_tool" -I -B -c 'import json,sys;print(json.load(open(sys.argv[1]))["first_submission_id"])' "$run_dir/python-cycle.stdout")
logrun js-cross-read compose run -T --rm --no-deps js_consumer node js_actor.cjs status "$python_first"
logrun js-cycle compose run -T --rm --no-deps js_consumer node js_actor.cjs cycle
js_first=$("$python_tool" -I -B -c 'import json,sys;print(json.load(open(sys.argv[1]))["first_submission_id"])' "$run_dir/js-cycle.stdout")
logrun python-cross-read compose run -T --rm --no-deps python_consumer python python_actor.py status "$js_first"
logrun python-alt-cycle compose run -T --rm --no-deps python_consumer python python_actor.py cycle_alt
logrun js-alt-cycle compose run -T --rm --no-deps js_consumer node js_actor.cjs cycle_alt
logrun receiver-observation compose exec -T receiver cat /data/arrivals.jsonl
logrun receiver-check "$python_tool" -I -B -c 'import json,sys;rows=[json.loads(x) for x in open(sys.argv[1])];rounds=[x.get("tool_observation",{}).get("round") for x in rows];assert len(rows)==8 and rounds==["call","result"]*4;assert all(rows[i]["tool_observation"].get("value")=="synthetic" for i in (1,3,5,7));print(json.dumps({"model_posts":len(rows),"tool_rounds":rounds}))' "$run_dir/receiver-observation.stdout"
logrun text-regression compose run -T --rm --no-deps python_consumer python python_actor.py text
logrun service-observation compose exec -T service python -c \
  'import sqlite3,json;d=sqlite3.connect("/data/store.sqlite");print(json.dumps({"submissions":d.execute("select count(*) from submissions").fetchone()[0],"intents":d.execute("select count(*) from intents").fetchone()[0],"usage_revisions":d.execute("select count(*) from usage_revisions").fetchone()[0]}))'
logrun service-check "$python_tool" -I -B -c 'import json,sys;row=json.load(open(sys.argv[1]));assert row=={"submissions":9,"intents":9,"usage_revisions":9};print(json.dumps(row))' "$run_dir/service-observation.stdout"
logrun no-store-cycle compose run -T --rm --no-deps python_consumer python python_actor.py no_store
logrun no-store-receiver-observation compose exec -T receiver cat /data/arrivals.jsonl
logrun no-store-receiver-check "$python_tool" -I -B -c 'import json,sys;rows=[json.loads(x) for x in open(sys.argv[1])];assert len(rows)==11;assert [r["tool_observation"]["round"] for r in rows[-2:]]==["call","result"];assert rows[-1]["tool_observation"]["value"]=="synthetic";print(json.dumps({"model_posts":len(rows),"no_store_rounds":["call","result"]}))' "$run_dir/no-store-receiver-observation.stdout"
logrun no-store-service-observation compose exec -T service python -c \
  'import sqlite3,json;d=sqlite3.connect("/data/store.sqlite");print(json.dumps({"submissions":d.execute("select count(*) from submissions").fetchone()[0],"intents":d.execute("select count(*) from intents").fetchone()[0],"usage_revisions":d.execute("select count(*) from usage_revisions").fetchone()[0]}))'
logrun no-store-service-check "$python_tool" -I -B -c 'import json,sys;row=json.load(open(sys.argv[1]));assert row=={"submissions":11,"intents":11,"usage_revisions":11};print(json.dumps(row))' "$run_dir/no-store-service-observation.stdout"
no_store_first=$("$python_tool" -I -B -c 'import json,sys;print(json.load(open(sys.argv[1]))["first_submission_id"])' "$run_dir/no-store-cycle.stdout")
no_store_second=$("$python_tool" -I -B -c 'import json,sys;print(json.load(open(sys.argv[1]))["second_submission_id"])' "$run_dir/no-store-cycle.stdout")
logrun no-store-db-check compose exec -T service python -c \
  'import json,sqlite3,sys;db=sqlite3.connect("/data/store.sqlite");rows=[json.loads(db.execute("select record from submissions where submission_id=?",(sid,)).fetchone()[0]) for sid in sys.argv[1:]];assert len(rows)==2 and all(r["candidate"] is None and r["candidate_access"]=="not_retained" and r["delivery_state"]=="candidate_delivered" for r in rows);assert len(rows[0].get("live_source_tags",[]))==1 and rows[1].get("live_source_tags",[])==[];assert all("call.lookup.1" not in json.dumps(r) and "Lookup: synthetic" not in json.dumps(r) for r in rows);print(json.dumps({"no_store_submissions":2,"plaintext_candidate_retained":False,"live_source_tags":[len(r.get("live_source_tags",[])) for r in rows]}))' \
  "$no_store_first" "$no_store_second"
logrun js-no-store-cycle compose run -T --rm --no-deps js_consumer node js_actor.cjs no_store
js_no_store_first=$("$python_tool" -I -B -c 'import json,sys;print(json.load(open(sys.argv[1]))["first_submission_id"])' "$run_dir/js-no-store-cycle.stdout")
js_no_store_second=$("$python_tool" -I -B -c 'import json,sys;print(json.load(open(sys.argv[1]))["second_submission_id"])' "$run_dir/js-no-store-cycle.stdout")
logrun js-no-store-db-check compose exec -T service python -c \
  'import json,sqlite3,sys;db=sqlite3.connect("/data/store.sqlite");rows=[json.loads(db.execute("select record from submissions where submission_id=?",(sid,)).fetchone()[0]) for sid in sys.argv[1:]];assert len(rows)==2 and all(r["candidate"] is None and r["candidate_access"]=="not_retained" and r["delivery_state"]=="candidate_delivered" for r in rows);assert len(rows[0].get("live_source_tags",[]))==1 and rows[1].get("live_source_tags",[])==[];assert all("call.lookup.1" not in json.dumps(r) and "Lookup: synthetic" not in json.dumps(r) for r in rows);print(json.dumps({"no_store_submissions":2,"plaintext_candidate_retained":False,"live_source_tags":[len(r.get("live_source_tags",[])) for r in rows]}))' \
  "$js_no_store_first" "$js_no_store_second"
logrun wait-no-store compose run -T --rm --no-deps python_consumer python python_actor.py wait_no_store
wait_sid=$("$python_tool" -I -B -c 'import json,sys;print(json.load(open(sys.argv[1]))["submission_id"])' "$run_dir/wait-no-store.stdout")
logrun wait-no-store-db-check compose exec -T service python -c \
  'import json,sqlite3,sys;d=sqlite3.connect("/data/store.sqlite");r=json.loads(d.execute("select record from submissions where submission_id=?",(sys.argv[1],)).fetchone()[0]);assert r["wait_expired_no_store"] and r["candidate"] is None and r["candidate_access"]=="not_retained" and not r.get("live_source_tags");assert r["result_unavailable_reason"]=="wait_expired_no_store";print(json.dumps({"wait_expired_no_store":True,"plaintext_candidate_retained":False,"live_source_tags":0}))' "$wait_sid"
logrun malformed-provider compose run -T --rm --no-deps python_consumer python python_actor.py malformed
logrun ordered-multi-call compose run -T --rm --no-deps python_consumer python python_actor.py multi
logrun composed-receiver-observation compose exec -T receiver cat /data/arrivals.jsonl
logrun composed-receiver-check "$python_tool" -I -B -c 'import json,sys;rows=[json.loads(x) for x in open(sys.argv[1])];assert len(rows)==17;rounds=[r.get("tool_observation",{}).get("round") for r in rows];assert rounds[:8]==["call","result"]*4 and rounds[8] is None and rounds[9:13]==["call","result"]*2 and rounds[13:]==["call","call","call","result_multi"];assert rows[-1]["tool_observation"]["call_ids"]==["call.lookup.1","call.lookup.2"];print(json.dumps({"model_posts":17,"tail_rounds":rounds[9:]}))' "$run_dir/composed-receiver-observation.stdout"
logrun composed-service-observation compose exec -T service python -c \
  'import sqlite3,json;d=sqlite3.connect("/data/store.sqlite");print(json.dumps({"submissions":d.execute("select count(*) from submissions").fetchone()[0],"intents":d.execute("select count(*) from intents").fetchone()[0],"usage_revisions":d.execute("select count(*) from usage_revisions").fetchone()[0]}))'
logrun composed-service-check "$python_tool" -I -B -c 'import json,sys;row=json.load(open(sys.argv[1]));assert row=={"submissions":17,"intents":17,"usage_revisions":16};print(json.dumps(row))' "$run_dir/composed-service-observation.stdout"
logrun mutation-compose-up compose up -d service_mutation
mutation_started=1
mutation_ready=0
for _ in {1..20}; do
  if compose exec -T service_mutation python -c 'import socket;socket.create_connection(("127.0.0.1",8765),1).close()' >/dev/null 2>&1; then mutation_ready=1; break; fi
  sleep 1
done
[[ "$mutation_ready" == 1 ]] || { echo 'mutation service readiness failed' >&2; exit 1; }
logrun tool-mutation-no-send compose run -T --rm --no-deps -e EZLLMROUTER_SERVICE_URL=http://service_mutation:8765 python_consumer python python_actor.py mutation
logrun mutation-service-observation compose exec -T service_mutation python -c \
  'import sqlite3,json;d=sqlite3.connect("/data/store.sqlite");print(json.dumps({"submissions":d.execute("select count(*) from submissions").fetchone()[0],"intents":d.execute("select count(*) from intents").fetchone()[0],"usage_revisions":d.execute("select count(*) from usage_revisions").fetchone()[0]}))'
logrun mutation-service-check "$python_tool" -I -B -c 'import json,sys;row=json.load(open(sys.argv[1]));assert row=={"submissions":1,"intents":0,"usage_revisions":0};print(json.dumps(row))' "$run_dir/mutation-service-observation.stdout"
