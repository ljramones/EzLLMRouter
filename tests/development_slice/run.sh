#!/usr/bin/env bash
set -Eeuo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd -P)
mode=${1:-}
run_name=${2:-run-20261018-02}
[[ "$run_name" =~ ^run-[0-9]{8}-[0-9]{2}$ ]] || { echo 'invalid run name' >&2; exit 2; }
run_dir="/private/tmp/duranki-dev-01/$run_name"
project="duranki-dev01-${run_name#run-}"
compose_file="$root/tests/development_slice/compose.yaml"
result_dir="$root/docs/development/dev-01"
python_tool=/opt/homebrew/bin/python3.12
node_tag=docker.io/library/node@sha256:be8204d4bd327363357f532187b752ff62759c31bedf98e9e18fc08c9cbd605c
python_digest=docker.io/library/python@sha256:739ba32ae445e8d58f3d90feb85f83bebc8346f8dd280fa1eb5848f4ff1ed163
mkdir -p "$result_dir"

logrun() {
  local label=$1; shift
  printf '%q ' "$@" >> "$run_dir/commands.log"; printf '\n' >> "$run_dir/commands.log"
  set +e
  "$@" > "$run_dir/$label.stdout" 2> "$run_dir/$label.stderr"
  local rc=$?
  set -e
  printf '%s\n' "$rc" > "$run_dir/$label.exit"
  cat "$run_dir/$label.stdout"
  cat "$run_dir/$label.stderr" >&2
  return "$rc"
}

new_run() {
  [[ ! -e "$run_dir" && ! -L "$run_dir" ]] || { echo "run collision: $run_dir" >&2; exit 2; }
  mkdir -m 0700 -p "$run_dir"
  chmod 0700 "$run_dir"
  "$python_tool" -I -B -c 'import secrets,sys;open(sys.argv[1],"w").write(secrets.token_urlsafe(48))' "$run_dir/token"
  chmod 0600 "$run_dir/token"
}

load_run() {
  [[ -d "$run_dir" && ! -L "$run_dir" ]] || { echo "missing run: $run_dir" >&2; exit 2; }
  export DURANKI_DEV_TOKEN
  DURANKI_DEV_TOKEN=$(cat "$run_dir/token")
  export DURANKI_SERVICE_IMAGE="duranki-dev01-service:$run_name"
  export DURANKI_RECEIVER_IMAGE="duranki-dev01-receiver:$run_name"
  export DURANKI_DRIVER_IMAGE="duranki-dev01-driver:$run_name"
}

compose() { docker compose -f "$compose_file" -p "$project" "$@"; }

prepare() {
  load_run
  mkdir -p "$run_dir/wheels"
  logrun domain-tests env PYTHONDONTWRITEBYTECODE=1 "$python_tool" -I -B "$root/tests/development_slice/test_core.py" -v
  # The lock was compiled from two direct roots under the frozen run-41 constraints.
  local args=(--platform manylinux2014_aarch64 --platform manylinux_2_17_aarch64)
  for n in {18..36}; do args+=(--platform "manylinux_2_${n}_aarch64"); done
  logrun wheel-download env -u PIP_EXTRA_INDEX_URL -u PIP_FIND_LINKS -u PIP_TRUSTED_HOST \
    -u PIP_CERT -u PIP_CLIENT_CERT -u PIP_NO_BINARY -u PIP_ONLY_BINARY -u PIP_REQUIRE_VIRTUALENV \
    -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
    PIP_CONFIG_FILE=/dev/null PIP_DISABLE_PIP_VERSION_CHECK=1 \
    "$python_tool" -m pip download --index-url https://pypi.org/simple --no-cache-dir \
    --require-hashes --only-binary=:all: --no-deps \
    --implementation cp --python-version 3.12 --abi cp312 "${args[@]}" \
    --dest "$run_dir/wheels" -r "$root/tests/development_slice/requirements.lock"
  "$python_tool" -I -B - "$run_dir/wheels" > "$run_dir/wheel-manifest.json" <<'PY'
import hashlib,json,sys
from pathlib import Path
p=Path(sys.argv[1]); files=sorted(p.glob('*.whl'))
assert len(files)==10, f'expected 10 wheels, got {len(files)}'
print(json.dumps([{'filename':x.name,'bytes':x.stat().st_size,'sha256':hashlib.sha256(x.read_bytes()).hexdigest()} for x in files],indent=2))
PY
  "$python_tool" -I -B - "$run_dir/wheels" > "$run_dir/wheel-license-manifest.json" <<'PY'
import email,hashlib,json,sys,zipfile
from pathlib import Path
result=[]
for wheel in sorted(Path(sys.argv[1]).glob('*.whl')):
 with zipfile.ZipFile(wheel) as z:
  names=z.namelist(); metas=[n for n in names if n.endswith('.dist-info/METADATA')]
  if len(metas)!=1 or len(names)!=len(set(names)): raise SystemExit('invalid wheel metadata census: '+wheel.name)
  raw=z.read(metas[0]);meta=email.message_from_bytes(raw)
  licenses=[]
  for n in names:
   base=n.rsplit('/',1)[-1].lower()
   if '.dist-info/licenses/' in n or base.startswith(('license','licence','copying','notice')):
    b=z.read(n);licenses.append({'path':n,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()})
  result.append({'wheel':wheel.name,'name':meta.get('Name'),'version':meta.get('Version'),
    'license_expression':meta.get('License-Expression'),
    'license_field':meta.get('License'),
    'license_classifiers':[x for x in meta.get_all('Classifier',[]) if x.startswith('License ::')],
    'license_files':licenses,'metadata_sha256':hashlib.sha256(raw).hexdigest()})
print(json.dumps(result,indent=2,sort_keys=True))
PY
}

reuse_inputs() {
  load_run
  local predecessor=${3:-run-20261018-02}
  [[ "$predecessor" =~ ^run-[0-9]{8}-[0-9]{2}$ && "$predecessor" != "$run_name" ]] || {
    echo 'invalid predecessor run' >&2; exit 2;
  }
  local old="/private/tmp/duranki-dev-01/$predecessor"
  [[ -d "$old" && ! -L "$old" ]] || { echo "missing predecessor: $old" >&2; exit 2; }
  logrun domain-tests env PYTHONDONTWRITEBYTECODE=1 "$python_tool" -I -B "$root/tests/development_slice/test_core.py" -v
  "$python_tool" -I -B - "$old" "$run_dir" "$root/tests/development_slice/requirements.lock" > "$run_dir/reuse-inputs.json" <<'PY'
import hashlib,json,shutil,sys
from pathlib import Path
old,new,lock=map(Path,sys.argv[1:]); expected=json.loads((old/'wheel-manifest.json').read_text())
assert len(expected)==10 and (old/'wheels').is_dir()
assert hashlib.sha256(lock.read_bytes()).hexdigest()=='d0c2d0665ecdf21754caaef060b5300ddf0d47b0bbfb08456c72e700203a5fad'
listed={x['filename'] for x in expected}; actual={x.name for x in (old/'wheels').iterdir()}
assert listed==actual, 'predecessor wheel set changed'
target=new/'wheels';target.mkdir()
lock_text=lock.read_text()
for item in expected:
 p=old/'wheels'/item['filename']
 assert p.is_file() and not p.is_symlink()
 assert p.stat().st_size==item['bytes']
 assert hashlib.sha256(p.read_bytes()).hexdigest()==item['sha256']
 assert item['sha256'] in lock_text, 'wheel digest absent from frozen lock'
 shutil.copy2(p,target/p.name)
 assert hashlib.sha256((target/p.name).read_bytes()).hexdigest()==item['sha256']
for name in ['node-image.txt','python-inspect.stdout','node-inspect.stdout']:
 p=old/name
 assert p.is_file() and not p.is_symlink()
 shutil.copy2(p,new/name)
node=(new/'node-image.txt').read_text().strip()
assert node.startswith('docker.io/library/node@sha256:') and len(node.split(':')[-1])==64
print(json.dumps({'predecessor':old.name,'wheel_count':len(expected),'wheel_hashes':expected,
                  'lock_sha256':hashlib.sha256(lock.read_bytes()).hexdigest(),
                  'node_child_image':node},indent=2))
PY
  cp "$old/wheel-manifest.json" "$run_dir/wheel-manifest.json"
  cp "$old/wheel-license-manifest.json" "$run_dir/wheel-license-manifest.json"
  logrun python-inspect-reused docker image inspect "$python_digest"
  logrun node-inspect-reused docker image inspect "$(cat "$run_dir/node-image.txt")"
  "$python_tool" -I -B - "$run_dir/python-inspect-reused.stdout" "$run_dir/node-inspect-reused.stdout" <<'PY'
import json,sys
for path in sys.argv[1:]:
 image=json.load(open(path))[0]
 assert image['Os']=='linux' and image['Architecture']=='arm64', path
PY
}

images() {
  load_run
  logrun python-pull docker pull --platform linux/arm64 "$python_digest"
  logrun python-inspect docker image inspect "$python_digest"
  logrun node-index docker buildx imagetools inspect --raw "$node_tag"
  local node_child
  node_child=$("$python_tool" -I -B - "$run_dir/node-index.stdout" <<'PY'
import json,sys
x=json.load(open(sys.argv[1])); hits=[m['digest'] for m in x['manifests'] if m.get('platform',{}).get('os')=='linux' and m.get('platform',{}).get('architecture')=='arm64']
if len(hits)!=1 or not hits[0].startswith('sha256:'): raise SystemExit('no unique Linux ARM64 Node child')
print(hits[0])
PY
)
  printf '%s\n' "docker.io/library/node@$node_child" > "$run_dir/node-image.txt"
  logrun node-pull docker pull --platform linux/arm64 "docker.io/library/node@$node_child"
  logrun node-inspect docker image inspect "docker.io/library/node@$node_child"
  "$python_tool" -I -B - "$run_dir/python-inspect.stdout" "$run_dir/node-inspect.stdout" <<'PY'
import json,sys
for p in sys.argv[1:]:
 x=json.load(open(p))[0]
 if x['Os']!='linux' or x['Architecture']!='arm64': raise SystemExit('wrong image architecture: '+p)
PY
}

build() {
  load_run
  [[ -s "$run_dir/node-image.txt" && -s "$run_dir/wheel-manifest.json" ]] || { echo 'prepare/images first' >&2; exit 2; }
  mkdir -p "$run_dir/build/service/wheels" "$run_dir/build/service/tests" "$run_dir/build/receiver" "$run_dir/build/driver"
  cp -R "$root/server/src" "$run_dir/build/service/server"
  "$python_tool" -I -B - "$run_dir/build/service/server" <<'PY'
from pathlib import Path
import sys
for path in Path(sys.argv[1]).rglob('.DS_Store'):
 if not path.is_file() or path.is_symlink(): raise SystemExit('unexpected build-context metadata entry: '+str(path))
 path.unlink()
PY
  cp "$root/tests/development_slice/"{service_main.py,native_adapter.py,recipe.py,fixture.json,request.json,test_crypto.py,test_http.py,test_native_adapter.py} "$run_dir/build/service/tests/"
  cp "$root/tests/development_slice/requirements.lock" "$run_dir/build/service/"
  cp "$run_dir/wheels/"*.whl "$run_dir/build/service/wheels/"
  cp "$root/tests/development_slice/receiver.py" "$run_dir/build/receiver/"
  cp "$root/clients/js/index.cjs" "$run_dir/build/driver/"
  cp "$root/tests/development_slice/"{driver.cjs,test_client.cjs,request.json,expected_request.txt} "$run_dir/build/driver/"
  cp "$root/docs/contracts/wp-a-03-c01/DURANKI-WP-A-VECTORS-v0.3-CORRECTION-01.json" "$run_dir/build/driver/vectors.json"
  "$python_tool" -I -B - "$run_dir/build" "$root" > "$run_dir/source-build-manifest.json" <<'PY'
import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1]);repo=Path(sys.argv[2]);rows=[]
for path in sorted(root.rglob('*')):
 if path.is_symlink(): raise SystemExit('build context link rejected: '+str(path))
 if path.is_dir(): continue
 if not path.is_file(): raise SystemExit('build context special file rejected: '+str(path))
 raw=path.read_bytes()
 rows.append({'path':path.relative_to(root).as_posix(),'bytes':len(raw),
              'sha256':hashlib.sha256(raw).hexdigest()})
recipes=[]
for name in ['Dockerfile.service','Dockerfile.receiver','Dockerfile.driver','compose.yaml','run.sh']:
 path=repo/'tests/development_slice'/name
 assert path.is_file() and not path.is_symlink()
 raw=path.read_bytes()
 recipes.append({'path':path.relative_to(repo).as_posix(),'bytes':len(raw),
                 'sha256':hashlib.sha256(raw).hexdigest()})
print(json.dumps({'build_context_files':rows,'recipe_files':recipes},indent=2))
PY
  local source_hash
  source_hash=$(shasum -a 256 "$run_dir/source-build-manifest.json" | awk '{print $1}')
  logrun service-build docker build --pull=false --build-arg "PYTHON_IMAGE=$python_digest" \
    --label "org.duranki.dev01.source-manifest-sha256=$source_hash" \
    -f "$root/tests/development_slice/Dockerfile.service" -t "$DURANKI_SERVICE_IMAGE" "$run_dir/build/service"
  logrun receiver-build docker build --pull=false --build-arg "PYTHON_IMAGE=$python_digest" \
    --label "org.duranki.dev01.source-manifest-sha256=$source_hash" \
    -f "$root/tests/development_slice/Dockerfile.receiver" -t "$DURANKI_RECEIVER_IMAGE" "$run_dir/build/receiver"
  logrun driver-build docker build --pull=false --build-arg "NODE_IMAGE=$(cat "$run_dir/node-image.txt")" \
    --label "org.duranki.dev01.source-manifest-sha256=$source_hash" \
    -f "$root/tests/development_slice/Dockerfile.driver" -t "$DURANKI_DRIVER_IMAGE" "$run_dir/build/driver"
  logrun built-image-inspect docker image inspect "$DURANKI_SERVICE_IMAGE" "$DURANKI_RECEIVER_IMAGE" "$DURANKI_DRIVER_IMAGE"
}

run_tests() {
  load_run
  logrun crypto-proof docker run --rm --network none --read-only --cap-drop ALL \
    "$DURANKI_SERVICE_IMAGE" python /app/tests/test_crypto.py
  logrun http-boundary docker run --rm --network none --read-only --cap-drop ALL \
    --tmpfs /tmp:rw,nosuid,nodev,size=8m "$DURANKI_SERVICE_IMAGE" python /app/tests/test_http.py -v
  logrun native-adapter docker run --rm --network none --read-only --cap-drop ALL \
    --tmpfs /tmp:rw,nosuid,nodev,size=8m "$DURANKI_SERVICE_IMAGE" python /app/tests/test_native_adapter.py -v
  logrun compose-up compose up -d receiver service service_mutant service_failstore
  local ready=0
  for actor in service service_mutant service_failstore; do
    ready=0
    for _ in {1..20}; do
      if compose exec -T "$actor" python -c 'import socket;socket.create_connection(("127.0.0.1",8765),1).close()' >/dev/null 2>&1; then ready=1; break; fi
      sleep 1
    done
    [[ $ready == 1 ]] || { echo "$actor readiness failed" >&2; return 1; }
  done
  logrun python-runtime compose exec -T service python --version
  logrun installed-packages compose exec -T service python -m pip list --format=json
  logrun node-runtime compose run --rm driver node --version
  logrun sdk-validation compose run --rm driver node test_client.cjs
  logrun roundtrip compose run --rm driver node driver.cjs submit
  logrun unauthorized compose run --rm driver node driver.cjs unauthorized
  logrun mutation compose run --rm driver node driver.cjs mutation
  logrun intent-failure compose run --rm driver node driver.cjs intent-failure
  local sid
  sid=$("$python_tool" -I -B - "$run_dir/roundtrip.stdout" <<'PY'
import json,sys
lines=[x for x in open(sys.argv[1]).read().splitlines() if x.startswith('{')]
items=[json.loads(x) for x in lines]
match=[x['submission_id'] for x in items if x.get('test')=='js_python_receiver_roundtrip']
if len(match)!=1: raise SystemExit('roundtrip receipt missing')
print(match[0])
PY
)
  export DURANKI_SUBMISSION_ID="$sid"
  logrun service-restart compose restart service
  ready=0
  for _ in {1..20}; do
    if compose exec -T service python -c 'import socket;socket.create_connection(("127.0.0.1",8765),1).close()' >/dev/null 2>&1; then ready=1; break; fi
    sleep 1
  done
  [[ $ready == 1 ]] || { echo 'service restart readiness failed' >&2; return 1; }
  logrun restart-status compose run --rm driver node driver.cjs status
  logrun receiver-log compose exec -T receiver cat /data/arrivals.jsonl
  logrun store-observation compose exec -T service python -c \
    'import sqlite3,json;d=sqlite3.connect("/data/store.sqlite");print(json.dumps({"submissions":d.execute("select count(*) from submissions").fetchone()[0],"intents":d.execute("select count(*) from intents").fetchone()[0],"usage_revisions":d.execute("select count(*) from usage_revisions").fetchone()[0]}))'
}

capture() {
  load_run
  logrun compose-ps compose ps || true
  logrun compose-logs compose logs --no-color || true
  "$python_tool" -I -B - "$run_dir" "$result_dir" <<'PY'
import hashlib,json,sys,zipfile
from pathlib import Path
run,out=map(Path,sys.argv[1:]);name=run.name;dest=out/('DEV-01-RUNTIME-'+name+'.zip')
if dest.exists():raise SystemExit('runtime evidence collision')
files=[p for p in run.iterdir() if p.is_file() and p.name != 'token']
rows=[]
with zipfile.ZipFile(dest,'x',zipfile.ZIP_DEFLATED) as z:
 for p in sorted(files):
  data=p.read_bytes();z.writestr(p.name,data);rows.append({'path':p.name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
 manifest=json.dumps({'files':rows,'self_excluded':True},indent=2).encode();z.writestr('EVIDENCE-MANIFEST.json',manifest)
print(json.dumps({'path':str(dest),'sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'files':len(rows)}))
PY
}

case "$mode" in
  all)
    new_run
    trap 'rc=$?; if [[ $rc != 0 ]]; then capture || true; fi; exit "$rc"' EXIT
    prepare; images; build; run_tests; capture
    trap - EXIT
    ;;
  all-reuse)
    new_run
    trap 'rc=$?; if [[ $rc != 0 ]]; then capture || true; fi; exit "$rc"' EXIT
    reuse_inputs "$@"; build; run_tests; capture
    trap - EXIT
    ;;
  prepare) new_run; prepare ;;
  images) images ;;
  build) build ;;
  test) run_tests ;;
  evidence) capture ;;
  cleanup) load_run; compose down --remove-orphans --volumes ;;
  *) echo 'usage: run.sh all|prepare|images|build|test|evidence|cleanup [run-YYYYMMDD-NN]; all-reuse [new-run] [predecessor-run]' >&2; exit 2 ;;
esac
