#!/usr/bin/env bash
set -Eeuo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd -P)
run_name=${1:-run-20261019-04}
[[ "$run_name" =~ ^run-[0-9]{8}-[0-9]{2}$ ]] || { echo 'invalid run name' >&2; exit 2; }
run_dir="/private/tmp/duranki-dev-02/$run_name"
result_dir="$root/.artifacts/client-parity"
project="duranki-dev02-${run_name#run-}"
python_tool=/opt/homebrew/bin/python3.12
python_image=docker.io/library/python@sha256:739ba32ae445e8d58f3d90feb85f83bebc8346f8dd280fa1eb5848f4ff1ed163
node_image=docker.io/library/node@sha256:be8204d4bd327363357f532187b752ff62759c31bedf98e9e18fc08c9cbd605c
export DURANKI_SERVICE_IMAGE="duranki-dev02-service:$run_name"
export DURANKI_RECEIVER_IMAGE=duranki-dev01-receiver:run-20261018-04
export DURANKI_PYTHON_CLIENT_IMAGE="duranki-dev02-pyclient:$run_name"
export DURANKI_JS_CLIENT_IMAGE="duranki-dev02-jsclient:$run_name"
compose_file="$root/tests/client_parity/compose.yaml"

logrun() {
  local label=$1; shift
  printf '%q ' "$@" > "$run_dir/$label.argv"; printf '\n' >> "$run_dir/$label.argv"
  set +e
  "$@" > "$run_dir/$label.stdout" 2> "$run_dir/$label.stderr"
  local rc=$?
  set -e
  printf '%s\n' "$rc" > "$run_dir/$label.exit"
  cat "$run_dir/$label.stdout"
  cat "$run_dir/$label.stderr" >&2
  return "$rc"
}
compose() { docker --context desktop-linux compose -f "$compose_file" -p "$project" "$@"; }

capture() {
  "$python_tool" -I -B - "$run_dir" "$result_dir" <<'PY'
import hashlib,json,sys,zipfile
from pathlib import Path
run,out=map(Path,sys.argv[1:]);dest=out/('DEV-02-RUNTIME-'+run.name+'.zip')
if dest.exists() or dest.is_symlink():raise SystemExit('runtime packet collision')
secrets=[(run/name).read_bytes() for name in ('token','token-secondary') if (run/name).is_file()]
rows=[]
with zipfile.ZipFile(dest,'x',zipfile.ZIP_DEFLATED) as z:
 for path in sorted(run.iterdir()):
  if path.is_file() and not path.is_symlink() and path.name not in {'token','token-secondary'}:
   raw=path.read_bytes();redacted=False
   for secret in secrets:
    if secret and secret in raw:
     raw=raw.replace(secret,b'[REDACTED-TOKEN]');redacted=True
   z.writestr(path.name,raw)
   rows.append({'path':path.name,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
                'token_redacted':redacted})
 z.writestr('EVIDENCE-MANIFEST.json',json.dumps({'files':rows,'self_excluded':True},indent=2))
print(json.dumps({'path':str(dest),'bytes':dest.stat().st_size,
                  'sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'payloads':len(rows)}))
PY
}

finish() {
  local rc=$?
  trap - EXIT
  set +e
  printf '%s\n' "$rc" > "$run_dir/work.exit"
  if [[ -s "$run_dir/token" ]]; then
    compose ps > "$run_dir/compose-ps.stdout" 2> "$run_dir/compose-ps.stderr"
    compose logs --no-color > "$run_dir/compose-logs.stdout" 2> "$run_dir/compose-logs.stderr"
    for actor in receiver receiver_delay receiver_fail; do
      compose exec -T "$actor" cat /data/arrivals.jsonl > "$run_dir/final-$actor.stdout" 2> "$run_dir/final-$actor.stderr"
      printf '%s\n' "$?" > "$run_dir/final-$actor.exit"
    done
    compose exec -T service python -c \
      'import sqlite3,json;d=sqlite3.connect("/data/store.sqlite");print(json.dumps({"submissions":d.execute("select count(*) from submissions").fetchone()[0],"intents":d.execute("select count(*) from intents").fetchone()[0],"usage_revisions":d.execute("select count(*) from usage_revisions").fetchone()[0]}))' \
      > "$run_dir/final-service.stdout" 2> "$run_dir/final-service.stderr"
    printf '%s\n' "$?" > "$run_dir/final-service.exit"
  fi
  compose down --remove-orphans --volumes > "$run_dir/cleanup.stdout" 2> "$run_dir/cleanup.stderr"
  local cleanup_rc=$?
  printf '%s\n' "$cleanup_rc" > "$run_dir/cleanup.exit"
  docker --context desktop-linux image rm "$DURANKI_SERVICE_IMAGE" "$DURANKI_PYTHON_CLIENT_IMAGE" "$DURANKI_JS_CLIENT_IMAGE" > "$run_dir/image-cleanup.stdout" 2> "$run_dir/image-cleanup.stderr"
  local image_cleanup_rc=$?
  printf '%s\n' "$image_cleanup_rc" > "$run_dir/image-cleanup.exit"
  if [[ $rc == 0 && $cleanup_rc != 0 ]]; then rc=$cleanup_rc; fi
  if [[ $rc == 0 && $image_cleanup_rc != 0 ]]; then rc=$image_cleanup_rc; fi
  printf '%s\n' "$rc" > "$run_dir/run.exit"
  capture > "$run_dir/capture.stdout" 2> "$run_dir/capture.stderr"
  local capture_rc=$?
  if [[ $capture_rc != 0 ]]; then cat "$run_dir/capture.stderr" >&2; exit "$capture_rc"; fi
  cat "$run_dir/capture.stdout"
  exit "$rc"
}

[[ ! -e "$run_dir" && ! -L "$run_dir" ]] || { echo "run collision: $run_dir" >&2; exit 2; }
[[ ! -e "$result_dir/DEV-02-RUNTIME-$run_name.zip" ]] || { echo 'runtime packet collision' >&2; exit 2; }
mkdir -m 0700 -p "$run_dir"
mkdir -p "$run_dir/build/python" "$run_dir/build/js" "$run_dir/image-artifacts"
trap finish EXIT
"$python_tool" -I -B -c 'import secrets,sys;open(sys.argv[1],"x").write(secrets.token_urlsafe(48))' "$run_dir/token"
chmod 0600 "$run_dir/token"
"$python_tool" -I -B -c 'import secrets,sys;open(sys.argv[1],"x").write(secrets.token_urlsafe(48))' "$run_dir/token-secondary"
chmod 0600 "$run_dir/token-secondary"
export DURANKI_DEV_TOKEN
DURANKI_DEV_TOKEN=$(cat "$run_dir/token")
export DURANKI_DEV_TOKEN_SECONDARY
DURANKI_DEV_TOKEN_SECONDARY=$(cat "$run_dir/token-secondary")
logrun stage "$python_tool" -I -B "$root/tests/client_parity/stage.py" prepare "$root" "$run_dir"
logrun image-inspect docker --context desktop-linux image inspect duranki-dev01-service:run-20261018-04 "$DURANKI_RECEIVER_IMAGE" \
  duranki-dev01-driver:run-20261018-04 "$python_image" "$node_image"
logrun image-identity "$python_tool" -I -B "$root/tests/client_parity/stage.py" verify-images "$root" "$run_dir/image-inspect.stdout"
logrun npm-pack-image docker --context desktop-linux run --rm --pull=never --platform linux/arm64 --network none --read-only --cap-drop ALL \
  --tmpfs /tmp:rw,nosuid,nodev,size=16m,mode=1777 --user "$(id -u):$(id -g)" \
  --env HOME=/tmp --env npm_config_cache=/tmp/npm-cache \
  --mount "type=bind,src=$root/clients/js,dst=/src,readonly" \
  --mount "type=bind,src=$run_dir/image-artifacts,dst=/out" \
  "$node_image" sh -c 'cd /src && npm pack /src --ignore-scripts --offline --no-audit --no-fund --pack-destination /out --json'
logrun stage-image-js "$python_tool" -I -B - "$root" "$run_dir" <<'PY'
import hashlib,json,shutil,sys,tarfile
from pathlib import Path
root,run=map(Path,sys.argv[1:]);src=run/'image-artifacts/mach33-duranki-client-0.0.1.tgz'
if not src.is_file() or src.is_symlink():raise SystemExit('image npm artifact missing')
with tarfile.open(src,'r:gz') as t:
 members=t.getmembers();names=[m.name for m in members]
 if len(names)!=len(set(names)) or set(names)!={'package/index.cjs','package/package.json'} or not all(m.isfile() for m in members):
  raise SystemExit('unexpected npm package members')
 for m in members:
  raw=t.extractfile(m).read();origin=root/('clients/js/index.cjs' if m.name.endswith('index.cjs') else 'clients/js/package.json')
  if hashlib.sha256(raw).hexdigest()!=hashlib.sha256(origin.read_bytes()).hexdigest():raise SystemExit('npm content mismatch')
dst=run/'build/js'/src.name
if dst.exists() or dst.is_symlink():raise SystemExit('npm stage collision')
shutil.copy2(src,dst)
print(json.dumps({'name':src.name,'bytes':src.stat().st_size,'sha256':hashlib.sha256(src.read_bytes()).hexdigest()}))
PY
source_hash=$(shasum -a 256 "$run_dir/source-build-manifest.json" | awk '{print $1}')
logrun service-build docker --context desktop-linux build --pull=false --build-arg "PYTHON_IMAGE=$python_image" \
  --label "org.duranki.dev02.source-manifest-sha256=$source_hash" \
  -f "$root/tests/development_slice/Dockerfile.service" -t "$DURANKI_SERVICE_IMAGE" "$run_dir/build/service"
logrun python-client-build docker --context desktop-linux build --pull=false --build-arg "PYTHON_IMAGE=$python_image" \
  --label "org.duranki.dev02.source-manifest-sha256=$source_hash" \
  -f "$root/tests/client_parity/Dockerfile.python-consumer" -t "$DURANKI_PYTHON_CLIENT_IMAGE" "$run_dir/build/python"
logrun js-client-build docker --context desktop-linux build --pull=false --build-arg "NODE_IMAGE=$node_image" \
  --label "org.duranki.dev02.source-manifest-sha256=$source_hash" \
  -f "$root/tests/client_parity/Dockerfile.js-consumer" -t "$DURANKI_JS_CLIENT_IMAGE" "$run_dir/build/js"
logrun built-image-inspect docker --context desktop-linux image inspect "$DURANKI_SERVICE_IMAGE" "$DURANKI_PYTHON_CLIENT_IMAGE" "$DURANKI_JS_CLIENT_IMAGE"
logrun crypto-proof docker --context desktop-linux run --rm --pull=never --platform linux/arm64 --network none --read-only --cap-drop ALL \
  "$DURANKI_SERVICE_IMAGE" python /app/tests/test_crypto.py
logrun http-boundary docker --context desktop-linux run --rm --pull=never --platform linux/arm64 --network none --read-only --cap-drop ALL \
  --tmpfs /tmp:rw,nosuid,nodev,size=8m "$DURANKI_SERVICE_IMAGE" python /app/tests/test_http.py -v
logrun native-adapter docker --context desktop-linux run --rm --pull=never --platform linux/arm64 --network none --read-only --cap-drop ALL \
  --tmpfs /tmp:rw,nosuid,nodev,size=8m "$DURANKI_SERVICE_IMAGE" python /app/tests/test_native_adapter.py -v
logrun compose-up compose up -d receiver service
ready=0
for _ in {1..20}; do
  if compose exec -T service python -c 'import socket;socket.create_connection(("127.0.0.1",8765),1).close()' >/dev/null 2>&1; then ready=1; break; fi
  sleep 1
done
[[ "$ready" == 1 ]] || { echo 'service readiness failed' >&2; exit 1; }
logrun python-installed-unit compose run -T --rm --no-deps python_consumer python test_python_client.py -v
logrun js-installed-unit compose run -T --rm --no-deps js_consumer node test_client.cjs
logrun python-actor-logic compose run -T --rm --no-deps python_consumer python test_actor_logic.py -v
logrun js-actor-logic compose run -T --rm --no-deps js_consumer node test_actor_logic.cjs
logrun python-installed-identity compose run -T --rm --no-deps python_consumer python -c \
 'import duranki_client,importlib.metadata,importlib.util,json,hashlib,pathlib;d=importlib.metadata.distribution("mach33-duranki-client");assert importlib.util.find_spec("duranki_server") is None;p=pathlib.Path(duranki_client.__file__);print(json.dumps({"module":str(p),"module_sha256":hashlib.sha256(p.read_bytes()).hexdigest(),"version":d.version,"requires":d.requires}))'
logrun python-pip-check compose run -T --rm --no-deps python_consumer python -m pip check
logrun python-installed-set compose run -T --rm --no-deps python_consumer python -m pip list --format=json
logrun js-installed-identity compose run -T --rm --no-deps js_consumer node -e \
 'const fs=require("node:fs"),crypto=require("node:crypto");let n=0;globalThis.fetch=()=>{n++;throw Error("import invoked fetch")};const p=require("@mach33/duranki-client"),file=require.resolve("@mach33/duranki-client");console.log(JSON.stringify({module:file,module_sha256:crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex"),exports:Object.keys(p),fetch_calls:n}))'
logrun python-capabilities compose run -T --rm --no-deps python_consumer python integration_python.py capabilities
logrun js-capabilities compose run -T --rm --no-deps js_consumer node integration_js.cjs capabilities
logrun js-submit-a compose run -T --rm --no-deps js_consumer node integration_js.cjs submit installed_js_a
js_sid=$("$python_tool" -I -B - "$run_dir/js-submit-a.stdout" <<'PY'
import json,sys
items=[json.loads(x) for x in open(sys.argv[1]).read().splitlines() if x.startswith('{')]
match=[x['submission_id'] for x in items if x.get('actor')=='js' and x.get('case')=='installed_js_a']
if len(match)!=1:raise SystemExit('JS submission receipt missing')
print(match[0])
PY
)
logrun python-reads-a compose run -T --rm --no-deps python_consumer python integration_python.py status installed_js_a "$js_sid"
logrun python-submit-b compose run -T --rm --no-deps python_consumer python integration_python.py submit installed_python_b
py_sid=$("$python_tool" -I -B - "$run_dir/python-submit-b.stdout" <<'PY'
import json,sys
items=[json.loads(x) for x in open(sys.argv[1]).read().splitlines() if x.startswith('{')]
match=[x['submission_id'] for x in items if x.get('actor')=='python' and x.get('case')=='installed_python_b']
if len(match)!=1:raise SystemExit('Python submission receipt missing')
print(match[0])
PY
)
logrun js-reads-b compose run -T --rm --no-deps js_consumer node integration_js.cjs status installed_python_b "$py_sid"
logrun python-auth-negative compose run -T --rm --no-deps python_consumer python integration_python.py auth
logrun js-auth-negative compose run -T --rm --no-deps js_consumer node integration_js.cjs auth
logrun principal-isolation compose run -T --rm --no-deps python_consumer python integration_python.py forbidden_status "$js_sid"
logrun extra-services-up compose up -d receiver_delay receiver_fail service_delay service_nostore_delay service_nostore_live \
  service_mutant service_failstore service_remote_fail service_serial_a service_serial_b
for service_name in service_delay service_nostore_delay service_nostore_live service_mutant service_failstore service_remote_fail service_serial_a service_serial_b; do
  ready=0
  for _ in {1..20}; do
    if compose exec -T "$service_name" python -c 'import socket;socket.create_connection(("127.0.0.1",8765),1).close()' >/dev/null 2>&1; then ready=1; break; fi
    sleep 1
  done
  [[ "$ready" == 1 ]] || { echo "service readiness failed: $service_name" >&2; exit 1; }
done
logrun retained-pending compose run -T --rm --no-deps \
  -e DURANKI_SERVICE_URL=http://service_delay:8765 -e DURANKI_RECEIVER_URL=http://receiver_delay:8766 \
  python_consumer python integration_python.py submit retained_pending
pending_sid=$($python_tool -I -B - "$run_dir/retained-pending.stdout" <<'PY'
import json,sys
rows=[json.loads(x) for x in open(sys.argv[1]) if x.startswith('{')]
assert len(rows)==1 and rows[0]['state']=='pending'
print(rows[0]['submission_id'])
PY
)
logrun retained-status compose run -T --rm --no-deps \
  -e DURANKI_SERVICE_URL=http://service_delay:8765 -e DURANKI_RECEIVER_URL=http://receiver_delay:8766 \
  python_consumer python integration_python.py status retained_pending "$pending_sid"
logrun no-store-expiry compose run -T --rm --no-deps \
  -e DURANKI_SERVICE_URL=http://service_nostore_delay:8765 -e DURANKI_RECEIVER_URL=http://receiver_delay:8766 \
  python_consumer python integration_python.py submit no_store_expiry
nostore_sid=$($python_tool -I -B - "$run_dir/no-store-expiry.stdout" <<'PY'
import json,sys
rows=[json.loads(x) for x in open(sys.argv[1]) if x.startswith('{')]
assert len(rows)==1 and rows[0]['state']=='pending'
print(rows[0]['submission_id'])
PY
)
logrun no-store-metadata compose run -T --rm --no-deps \
  -e DURANKI_SERVICE_URL=http://service_nostore_delay:8765 -e DURANKI_RECEIVER_URL=http://receiver_delay:8766 \
  python_consumer python integration_python.py status_metadata no_store_expiry "$nostore_sid"
logrun no-store-live compose run -T --rm --no-deps \
  -e DURANKI_SERVICE_URL=http://service_nostore_live:8765 \
  python_consumer python integration_python.py submit no_store_live
logrun retained-pending-js compose run -T --rm --no-deps \
  -e DURANKI_SERVICE_URL=http://service_delay:8765 -e DURANKI_RECEIVER_URL=http://receiver_delay:8766 \
  js_consumer node integration_js.cjs submit retained_pending_js
pending_js_sid=$($python_tool -I -B - "$run_dir/retained-pending-js.stdout" <<'PY'
import json,sys
rows=[json.loads(x) for x in open(sys.argv[1]) if x.startswith('{')]
assert len(rows)==1 and rows[0]['state']=='pending'
print(rows[0]['submission_id'])
PY
)
logrun retained-status-js compose run -T --rm --no-deps \
  -e DURANKI_SERVICE_URL=http://service_delay:8765 -e DURANKI_RECEIVER_URL=http://receiver_delay:8766 \
  js_consumer node integration_js.cjs status retained_pending_js "$pending_js_sid"
logrun no-store-expiry-js compose run -T --rm --no-deps \
  -e DURANKI_SERVICE_URL=http://service_nostore_delay:8765 -e DURANKI_RECEIVER_URL=http://receiver_delay:8766 \
  js_consumer node integration_js.cjs submit no_store_expiry_js
nostore_js_sid=$($python_tool -I -B - "$run_dir/no-store-expiry-js.stdout" <<'PY'
import json,sys
rows=[json.loads(x) for x in open(sys.argv[1]) if x.startswith('{')]
assert len(rows)==1 and rows[0]['state']=='pending'
print(rows[0]['submission_id'])
PY
)
logrun no-store-metadata-js compose run -T --rm --no-deps \
  -e DURANKI_SERVICE_URL=http://service_nostore_delay:8765 -e DURANKI_RECEIVER_URL=http://receiver_delay:8766 \
  js_consumer node integration_js.cjs status_metadata no_store_expiry_js "$nostore_js_sid"
logrun no-store-live-js compose run -T --rm --no-deps \
  -e DURANKI_SERVICE_URL=http://service_nostore_live:8765 \
  js_consumer node integration_js.cjs submit no_store_live_js
logrun fdc-python compose run -T --rm --no-deps \
  -e DURANKI_SERVICE_URL=http://service_mutant:8765 \
  python_consumer python integration_python.py failure fdc_python
logrun fdc-js compose run -T --rm --no-deps \
  -e DURANKI_SERVICE_URL=http://service_mutant:8765 \
  js_consumer node integration_js.cjs failure fdc_js
logrun intent-python compose run -T --rm --no-deps \
  -e DURANKI_SERVICE_URL=http://service_failstore:8765 \
  python_consumer python integration_python.py failure intent_python
logrun intent-js compose run -T --rm --no-deps \
  -e DURANKI_SERVICE_URL=http://service_failstore:8765 \
  js_consumer node integration_js.cjs failure intent_js
logrun remote-python compose run -T --rm --no-deps \
  -e DURANKI_SERVICE_URL=http://service_remote_fail:8765 -e DURANKI_RECEIVER_URL=http://receiver_fail:8766 \
  python_consumer python integration_python.py failure known_remote_failure
logrun remote-js compose run -T --rm --no-deps \
  -e DURANKI_SERVICE_URL=http://service_remote_fail:8765 -e DURANKI_RECEIVER_URL=http://receiver_fail:8766 \
  js_consumer node integration_js.cjs failure remote_js
logrun serial-js compose run -T --rm --no-deps \
  -e DURANKI_SERVICE_URL=http://service_serial_a:8765 \
  js_consumer node integration_js.cjs submit serialization_equal
logrun serial-python-reordered compose run -T --rm --no-deps \
  -e DURANKI_SERVICE_URL=http://service_serial_b:8765 \
  python_consumer python integration_python.py submit_reordered serialization_equal
logrun serial-digest-a compose exec -T service_serial_a python -c \
  'import sqlite3,json;d=sqlite3.connect("/data/store.sqlite");print(json.dumps(d.execute("select work_digest from submissions").fetchall()))'
logrun serial-digest-b compose exec -T service_serial_b python -c \
  'import sqlite3,json;d=sqlite3.connect("/data/store.sqlite");print(json.dumps(d.execute("select work_digest from submissions").fetchall()))'
$python_tool -I -B - "$run_dir/serial-digest-a.stdout" "$run_dir/serial-digest-b.stdout" <<'PY'
import json,sys
a,b=[json.load(open(p)) for p in sys.argv[1:]]
assert len(a)==len(b)==1 and a[0][0]==b[0][0]
print(json.dumps({'serialization_parity':'PASS','work_digest':a[0][0]}))
PY
logrun receiver-observation compose exec -T receiver cat /data/arrivals.jsonl
logrun delay-receiver-observation compose exec -T receiver_delay cat /data/arrivals.jsonl
logrun fail-receiver-observation compose exec -T receiver_fail cat /data/arrivals.jsonl
logrun store-observation compose exec -T service python -c \
 'import sqlite3,json;d=sqlite3.connect("/data/store.sqlite");print(json.dumps({"submissions":d.execute("select count(*) from submissions").fetchone()[0],"intents":d.execute("select count(*) from intents").fetchone()[0],"usage_revisions":d.execute("select count(*) from usage_revisions").fetchone()[0]}))'
"$python_tool" -I -B - "$run_dir/receiver-observation.stdout" "$run_dir/delay-receiver-observation.stdout" \
  "$run_dir/fail-receiver-observation.stdout" "$run_dir/store-observation.stdout" <<'PY'
import json,sys
arrivals=[json.loads(x) for x in open(sys.argv[1]) if x.strip()]
delayed=[json.loads(x) for x in open(sys.argv[2]) if x.strip()]
failed=[json.loads(x) for x in open(sys.argv[3]) if x.strip()]
store=json.load(open(sys.argv[4]))
assert len(arrivals)==6 and [x['sequence'] for x in arrivals]==list(range(1,7))
assert len(delayed)==4 and len(failed)==2
assert store=={'submissions':2,'intents':2,'usage_revisions':2}
print(json.dumps({'installed_cross_client_checkpoint':'PASS','receiver_arrivals':len(arrivals),
                  'delay_arrivals':len(delayed),'failure_arrivals':len(failed),'store':store}))
PY
