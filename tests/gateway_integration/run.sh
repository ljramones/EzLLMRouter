#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

root=$(cd "$(dirname "$0")/../.." && pwd -P)
run_name=${1:?usage: ./tests/gateway_integration/run.sh run-YYYYMMDD-NN}
[[ "$run_name" =~ ^run-[0-9]{8}-[0-9]{2}$ ]] || { echo 'invalid run ID' >&2; exit 2; }
phase=${2:-checkpoint}
[[ "$phase" == checkpoint || "$phase" == boundaries || "$phase" == choice_b || "$phase" == dev05 ]] || { echo 'invalid phase' >&2; exit 2; }
if [[ "$phase" == choice_b ]]; then
  source "$root/tests/gateway_integration/choice_b_steps.sh"
elif [[ "$phase" == dev05 ]]; then
  source "$root/tests/gateway_integration/dev05_steps.sh"
fi
packet_prefix=DEV-04
run_dir="/private/tmp/ezllmrouter-dev-04/$run_name"
result_dir="$root/.artifacts/gateway/dev-04"
if [[ "$phase" == dev05 ]]; then
  packet_prefix=DEV-05
  run_dir="/private/tmp/ezllmrouter-dev-05/$run_name"
  result_dir="$root/.artifacts/gateway/dev-05"
fi
frozen_dir="$root/.artifacts/gateway/dev-04"
wheel_dir="$root/gateway-inputs/dev04/wheels"
compose_file="$root/tests/gateway_integration/compose.yaml"
project="ezllmrouter-dev04-${run_name#run-}"
if [[ "$phase" == dev05 ]]; then project="ezllmrouter-dev05-${run_name#run-}"; fi
python_tool=/usr/local/bin/python3
node24_tool=/Users/larrymitchell/.nvm/versions/node/v24.22.1/bin/node
if [[ "$phase" == dev05 ]]; then python_tool=/usr/local/bin/python3.12; fi
python_image=docker.io/library/python@sha256:739ba32ae445e8d58f3d90feb85f83bebc8346f8dd280fa1eb5848f4ff1ed163
node_image=docker.io/library/node@sha256:be8204d4bd327363357f532187b752ff62759c31bedf98e9e18fc08c9cbd605c
export EZLLMROUTER_DEV04_PYTHON_BASE="$python_image"
export EZLLMROUTER_DEV04_SERVICE_IMAGE="ezllmrouter-dev04-service:$run_name"
export EZLLMROUTER_DEV04_RECEIVER_IMAGE="ezllmrouter-dev04-receiver:$run_name"
export EZLLMROUTER_DEV04_PYCLIENT_IMAGE="ezllmrouter-dev04-pyclient:$run_name"
export EZLLMROUTER_DEV04_JSCLIENT_IMAGE="ezllmrouter-dev04-jsclient:$run_name"
export EZLLMROUTER_DEV04_WORKER_IMAGE="ezllmrouter-dev04-worker:$run_name"
if [[ "$phase" == dev05 ]]; then
  export EZLLMROUTER_DEV05_TEST_TOOL_MUTATION=1
  export EZLLMROUTER_DEV04_SERVICE_IMAGE="ezllmrouter-dev05-service:$run_name"
  export EZLLMROUTER_DEV04_RECEIVER_IMAGE="ezllmrouter-dev05-receiver:$run_name"
  export EZLLMROUTER_DEV04_PYCLIENT_IMAGE="ezllmrouter-dev05-pyclient:$run_name"
  export EZLLMROUTER_DEV04_JSCLIENT_IMAGE="ezllmrouter-dev05-jsclient:$run_name"
  export EZLLMROUTER_DEV04_WORKER_IMAGE="ezllmrouter-dev05-worker:$run_name"
fi
started=0
fault_started=0
tool_mutation_started=0
destination_mutation_started=0
wait_started=0
probe_started=0
built_images=()

logrun() {
  local name=$1; shift
  printf '%q ' "$@" > "$run_dir/$name.argv"; printf '\n' >> "$run_dir/$name.argv"
  set +e
  "$@" > "$run_dir/$name.stdout" 2> "$run_dir/$name.stderr"
  local rc=$?
  set -e
  printf '%s\n' "$rc" > "$run_dir/$name.exit"
  printf '%s exit=%s\n' "$name" "$rc"
  if (( rc != 0 )); then
    "$python_tool" -I -B - "$run_dir/$name.stderr" "$run_dir/token" \
      "$run_dir/provider-key" "$run_dir/$name.diagnostic-tail.txt" "$name" <<'PY'
from pathlib import Path
import sys

source, token_file, key_file, target = map(Path, sys.argv[1:5])
name = sys.argv[5]
raw = source.read_bytes()
for path in (token_file, key_file):
    if path.is_file():
        secret = path.read_bytes().strip()
        if secret:
            raw = raw.replace(secret, b"[REDACTED-SYNTHETIC-CREDENTIAL]")
lines = raw.decode("utf-8", errors="replace").splitlines()
header, tail = lines[:3], lines[-16:]
message = "failure diagnostic " + name + " (redacted stderr header):\n"
message += "\n".join(line[:300] for line in header) + "\n"
message += "last 16 stderr lines:\n" + "\n".join(line[:300] for line in tail) + "\n"
target.write_text(message)
print(message, end="")
PY
  fi
  return "$rc"
}

compose() { docker --context desktop-linux compose -f "$compose_file" -p "$project" "$@"; }

capture() {
  "$python_tool" -I -B "$root/tests/gateway_integration/capture_runtime.py" \
    "$run_dir" "$result_dir" "$packet_prefix"
}

finish() {
  local rc=$?
  trap - EXIT
  set +e
  printf '%s\n' "$rc" > "$run_dir/work.exit"
  if [[ "$phase" == dev05 ]]; then
    finish_dev05 "$rc"
  fi
  if [[ "$phase" == choice_b ]]; then
    finish_choice_b "$rc"
  fi
  if [[ $started == 1 ]]; then
    compose ps > "$run_dir/compose-ps.stdout" 2> "$run_dir/compose-ps.stderr"
    printf '%s\n' "$?" > "$run_dir/compose-ps.exit"
    compose logs --no-color > "$run_dir/compose-logs.stdout" 2> "$run_dir/compose-logs.stderr"
    printf '%s\n' "$?" > "$run_dir/compose-logs.exit"
    compose exec -T receiver cat /data/arrivals.jsonl > "$run_dir/final-receiver.stdout" 2> "$run_dir/final-receiver.stderr"
    printf '%s\n' "$?" > "$run_dir/final-receiver.exit"
    compose exec -T receiver cat /data/controls.jsonl > "$run_dir/final-receiver-controls.stdout" 2> "$run_dir/final-receiver-controls.stderr"
    printf '%s\n' "$?" > "$run_dir/final-receiver-controls.exit"
    compose exec -T service cat /data/module-identities.json > "$run_dir/final-modules.stdout" 2> "$run_dir/final-modules.stderr"
    printf '%s\n' "$?" > "$run_dir/final-modules.exit"
    compose exec -T service cat /data/guard-events.jsonl > "$run_dir/final-main-guard-events.stdout" 2> "$run_dir/final-main-guard-events.stderr"
    printf '%s\n' "$?" > "$run_dir/final-main-guard-events.exit"
    compose exec -T service python -c \
      'import json,sqlite3; d=sqlite3.connect("/data/store.sqlite"); [print(json.dumps({"attempt_id":a,"submission_id":s,"receipt":json.loads(r)})) for a,s,r in d.execute("select attempt_id,submission_id,receipt from guard_dispatches order by rowid")]' \
      > "$run_dir/final-main-guard-receipts.stdout" 2> "$run_dir/final-main-guard-receipts.stderr"
    printf '%s\n' "$?" > "$run_dir/final-main-guard-receipts.exit"
    compose exec -T service python -c \
      'import json,sqlite3; d=sqlite3.connect("/data/store.sqlite"); print(json.dumps({"submissions":d.execute("select count(*) from submissions").fetchone()[0],"preparatory_intents":d.execute("select count(*) from intents").fetchone()[0],"guard_dispatches":d.execute("select count(*) from guard_dispatches").fetchone()[0],"usage_revisions":d.execute("select count(*) from usage_revisions").fetchone()[0]}))' \
      > "$run_dir/final-service.stdout" 2> "$run_dir/final-service.stderr"
    printf '%s\n' "$?" > "$run_dir/final-service.exit"
    compose exec -T service cat /data/sdk-retry-observations.jsonl > "$run_dir/final-main-sdk-retry.stdout" 2> "$run_dir/final-main-sdk-retry.stderr"
    printf '%s\n' "$?" > "$run_dir/final-main-sdk-retry.exit"
    if [[ $fault_started == 1 ]]; then
      compose exec -T service_fault python -c \
        'import json,sqlite3; d=sqlite3.connect("/data/store.sqlite"); print(json.dumps({"submissions":d.execute("select count(*) from submissions").fetchone()[0],"preparatory_intents":d.execute("select count(*) from intents").fetchone()[0],"guard_dispatches":d.execute("select count(*) from guard_dispatches").fetchone()[0]}))' \
        > "$run_dir/final-fault-service.stdout" 2> "$run_dir/final-fault-service.stderr"
      printf '%s\n' "$?" > "$run_dir/final-fault-service.exit"
      compose exec -T service_fault cat /data/guard-events.jsonl > "$run_dir/final-fault-guard-events.stdout" 2> "$run_dir/final-fault-guard-events.stderr"
      printf '%s\n' "$?" > "$run_dir/final-fault-guard-events.exit"
      compose exec -T service_fault cat /data/sdk-retry-observations.jsonl > "$run_dir/final-fault-sdk-retry.stdout" 2> "$run_dir/final-fault-sdk-retry.stderr"
      printf '%s\n' "$?" > "$run_dir/final-fault-sdk-retry.exit"
      compose exec -T service_fault python -c \
        'import json,sqlite3; d=sqlite3.connect("/data/store.sqlite"); row=d.execute("select record from submissions order by rowid desc limit 1").fetchone(); record=json.loads(row[0]) if row else {}; failure=record.get("terminal_failure") or {}; print(json.dumps({"attempt_id":record.get("attempt_id"),"submission_state":record.get("submission_state"),"terminal_code":failure.get("code"),"guard_dispatches":d.execute("select count(*) from guard_dispatches").fetchone()[0]}))' \
        > "$run_dir/final-fault-terminal.stdout" 2> "$run_dir/final-fault-terminal.stderr"
      printf '%s\n' "$?" > "$run_dir/final-fault-terminal.exit"
    else
      printf 'NOT_STARTED\n' > "$run_dir/final-fault-service.status"
      printf 'NOT_STARTED\n' > "$run_dir/final-fault-guard-events.status"
      printf 'NOT_STARTED\n' > "$run_dir/final-fault-sdk-retry.status"
      printf 'NOT_STARTED\n' > "$run_dir/final-fault-terminal.status"
    fi
    if [[ $tool_mutation_started == 1 ]]; then
      compose exec -T service_tool_mutation cat /data/guard-events.jsonl > "$run_dir/final-service_tool_mutation-guard.stdout" 2> "$run_dir/final-service_tool_mutation-guard.stderr"
      printf '%s\n' "$?" > "$run_dir/final-service_tool_mutation-guard.exit"
      compose exec -T service_tool_mutation cat /data/sdk-retry-observations.jsonl > "$run_dir/final-service_tool_mutation-sdk-retry.stdout" 2> "$run_dir/final-service_tool_mutation-sdk-retry.stderr"
      printf '%s\n' "$?" > "$run_dir/final-service_tool_mutation-sdk-retry.exit"
    else
      printf 'NOT_STARTED\n' > "$run_dir/final-service_tool_mutation-guard.status"
      printf 'NOT_STARTED\n' > "$run_dir/final-service_tool_mutation-sdk-retry.status"
    fi
    if [[ $destination_mutation_started == 1 ]]; then
      compose exec -T service_destination_mutation cat /data/guard-events.jsonl > "$run_dir/final-service_destination_mutation-guard.stdout" 2> "$run_dir/final-service_destination_mutation-guard.stderr"
      printf '%s\n' "$?" > "$run_dir/final-service_destination_mutation-guard.exit"
      compose exec -T service_destination_mutation cat /data/sdk-retry-observations.jsonl > "$run_dir/final-service_destination_mutation-sdk-retry.stdout" 2> "$run_dir/final-service_destination_mutation-sdk-retry.stderr"
      printf '%s\n' "$?" > "$run_dir/final-service_destination_mutation-sdk-retry.exit"
    else
      printf 'NOT_STARTED\n' > "$run_dir/final-service_destination_mutation-guard.status"
      printf 'NOT_STARTED\n' > "$run_dir/final-service_destination_mutation-sdk-retry.status"
    fi
    if [[ $wait_started == 1 ]]; then
      for item in guard-events.jsonl sdk-retry-observations.jsonl pool-observations.jsonl lower-trace.jsonl; do
        stem=${item%.jsonl}
        compose exec -T service_wait cat "/data/$item" > "$run_dir/final-service_wait-$stem.stdout" 2> "$run_dir/final-service_wait-$stem.stderr"
        printf '%s\n' "$?" > "$run_dir/final-service_wait-$stem.exit"
      done
      compose exec -T service_wait python -c \
        'import json,sqlite3; d=sqlite3.connect("/data/store.sqlite"); [print(json.dumps({"attempt_id":a,"submission_id":s,"receipt":json.loads(r)})) for a,s,r in d.execute("select attempt_id,submission_id,receipt from guard_dispatches order by rowid")]' \
        > "$run_dir/final-service_wait-receipts.stdout" 2> "$run_dir/final-service_wait-receipts.stderr"
      printf '%s\n' "$?" > "$run_dir/final-service_wait-receipts.exit"
    else
      printf 'NOT_STARTED\n' > "$run_dir/final-service_wait.status"
    fi
    if [[ $probe_started == 1 ]]; then
      compose exec -T service_probe cat /data/bypass-probes.json > "$run_dir/final-service_probe-bypass.stdout" 2> "$run_dir/final-service_probe-bypass.stderr"
      printf '%s\n' "$?" > "$run_dir/final-service_probe-bypass.exit"
      compose exec -T service_probe cat /data/guard-events.jsonl > "$run_dir/final-service_probe-guard.stdout" 2> "$run_dir/final-service_probe-guard.stderr"
      printf '%s\n' "$?" > "$run_dir/final-service_probe-guard.exit"
    else
      printf 'NOT_STARTED\n' > "$run_dir/final-service_probe.status"
    fi
    if [[ -f "$run_dir/final-receiver.stdout" && -f "$run_dir/final-main-guard-receipts.stdout" ]]; then
      correlation_args=()
      receipt_file="$run_dir/final-main-guard-receipts.stdout"
      if [[ "$phase" == boundaries ]]; then
        correlation_args+=(--report-unmatched)
        receipt_file="$run_dir/boundary-all-guard-receipts.jsonl"
        cat "$run_dir/final-main-guard-receipts.stdout" > "$receipt_file"
        if [[ -f "$run_dir/final-service_wait-receipts.stdout" ]]; then
          cat "$run_dir/final-service_wait-receipts.stdout" >> "$receipt_file"
        fi
      fi
      "$python_tool" -I -B "$root/tests/gateway_integration/correlate_partial.py" \
        "$run_dir/final-receiver.stdout" "$receipt_file" "${correlation_args[@]}" \
        > "$run_dir/final-main-attempt-correlation.stdout" 2> "$run_dir/final-main-attempt-correlation.stderr"
      local correlation_rc=$?
      printf '%s\n' "$correlation_rc" > "$run_dir/final-main-attempt-correlation.exit"
      if [[ $rc == 0 && $correlation_rc != 0 ]]; then rc=$correlation_rc; fi
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
[[ ! -e "$result_dir/$packet_prefix-RUNTIME-$run_name.zip" && ! -e "$result_dir/$packet_prefix-SOURCE-$run_name.zip" ]] ||
  { echo 'review packet collision' >&2; exit 2; }
mkdir -p -m 700 "$run_dir"
printf '%s\n' "mkdir -p -m 700 $run_dir" > "$run_dir/bootstrap.argv"
printf '0\n' > "$run_dir/bootstrap.exit"
trap finish EXIT

logrun physical-root "$python_tool" -I -B -c \
  'import pathlib,sys; p=pathlib.Path(sys.argv[1]).resolve(); assert p.is_dir(); print(p)' "$root"
logrun core-regression "$python_tool" -I -B "$root/tests/development_slice/test_core.py" -q
logrun tool-regression "$python_tool" -I -B "$root/tests/tool_cycle/test_core.py" -q
logrun bridge-component "$python_tool" -I -B "$root/tests/gateway_integration/test_core_bridge.py" -q
logrun inventory "$python_tool" -I -B "$root/tests/gateway_integration/receipts.py" inventory "$wheel_dir" "$run_dir"
logrun inventory-match cmp "$run_dir/WHEEL-INVENTORY.json" "$frozen_dir/WHEEL-INVENTORY.json"
logrun lock-match cmp "$run_dir/requirements.gateway.lock" "$frozen_dir/requirements.gateway.lock"
logrun source-correspondence "$python_tool" -I -B "$root/tests/gateway_integration/source_correspondence.py" \
  "$root/docs/gateway/review-evidence-02/litellm-1.105.1.tar.gz" \
  "$wheel_dir/litellm-1.105.1-cp310-abi3-manylinux_2_28_aarch64.whl" \
  "$run_dir/SOURCE-CORRESPONDENCE.json"
logrun source-match cmp "$run_dir/SOURCE-CORRESPONDENCE.json" "$frozen_dir/SOURCE-CORRESPONDENCE.json"
# Run-01 already captured dated publisher records for this unchanged frozen set.
logrun pypi-advisories cp "$frozen_dir/PYPI-ADVISORIES.json" "$run_dir/PYPI-ADVISORIES.json"
logrun publisher-advisories cp "$frozen_dir/GITHUB-ADVISORIES.json" "$run_dir/GITHUB-ADVISORIES.json"
logrun artifact-review "$python_tool" -I -B "$root/tests/gateway_integration/review_gate.py" "$root" "$run_dir"
if [[ "$phase" == dev05 ]]; then
  logrun stage "$python_tool" -I -B "$root/tests/gateway_integration/stage.py" "$root" "$run_dir" "$result_dir" DEV-05
else
  logrun stage "$python_tool" -I -B "$root/tests/gateway_integration/stage.py" "$root" "$run_dir"
fi
logrun model-identity-regression "$python_tool" -I -B "$root/tests/gateway_integration/test_model_identity.py" -q
logrun boundary-readiness-regression "$python_tool" -I -B "$root/tests/gateway_integration/test_readiness.py" -q
if [[ "$phase" == choice_b || "$phase" == dev05 ]]; then
  logrun choice-b-component "$python_tool" -I -B "$root/tests/gateway_integration/test_choice_b.py" -q
  logrun choice-b-owned-sender-component "$python_tool" -I -B "$root/tests/gateway_integration/test_owned_sender_transport.py" -q
  logrun choice-b-run10-timeout-regression "$python_tool" -I -B \
    "$root/tests/gateway_integration/test_run10_held_timeout.py" \
    --repo "$root" --runtime /private/tmp/ezllmrouter-dev-04/run-20261020-10 \
    --timeout-source "$root/tests/gateway_integration/inputs/litellm_completion_timeout_1_105_1.py"
fi
if [[ "$phase" == dev05 ]]; then
  # Replay the existing pure retry suite on the exact staged bytes before Docker.
  # Keep its later pinned-container execution as an additional target check.
  logrun dev05-retry-regression "$python_tool" -I -B \
    "$run_dir/build/service/gateway/test_retry_cause.py" \
    --source-root "$run_dir/build/service" -q
  logrun dev05-work-identity-regression "$python_tool" -I -B \
    "$run_dir/build/service/gateway/test_work_identity.py" \
    --source-root "$run_dir/build/service" -q
  logrun dev05-component "$python_tool" -I -B "$root/tests/gateway_integration/test_dev05.py" -q
  logrun dev05-capture-regression "$python_tool" -I -B \
    "$root/tests/gateway_integration/test_dev05_capture.py" -q
  logrun dev05-worker-readiness-regression "$python_tool" -I -B \
    "$root/tests/gateway_integration/test_worker_ready.py" -q
  logrun dev05-python-actor-modes "$python_tool" -I -B \
    "$root/tests/gateway_integration/test_dev05_python_actor.py" -q
  logrun dev05-js-actor-modes "$node24_tool" \
    "$root/tests/gateway_integration/test_dev05_js_actor.cjs"
fi
if [[ "$phase" == dev05 && ${EZLLMROUTER_DEV05_PREFLIGHT_ONLY:-0} == 1 ]]; then
  printf 'PRE_DOCKER_COMPONENTS_ONLY\n' > "$run_dir/preflight-only.status"
  exit 0
fi
logrun generate-credentials "$python_tool" -I -B -c \
  'import json,pathlib,secrets,sys
run=pathlib.Path(sys.argv[1]); state=run/"credential-generation-state.json"; expected=[]
for name, value in (("token",lambda: secrets.token_urlsafe(48)),
                    ("provider-key",lambda: "sk-"+secrets.token_urlsafe(48))):
 expected.append(name); state.write_text(json.dumps({"expected":expected}))
 (run/name).write_text(value())' "$run_dir"
export EZLLMROUTER_DEV_TOKEN EZLLMROUTER_DEV04_PROVIDER_KEY
EZLLMROUTER_DEV_TOKEN=$(<"$run_dir/token")
EZLLMROUTER_DEV04_PROVIDER_KEY=$(<"$run_dir/provider-key")
logrun base-inspect docker --context desktop-linux image inspect "$python_image" "$node_image"

roles=(service receiver python js)
if [[ "$phase" == choice_b || "$phase" == dev05 ]]; then roles+=(worker); fi
for role in "${roles[@]}"; do
  case "$role" in
    service) tag=$EZLLMROUTER_DEV04_SERVICE_IMAGE; base=$python_image; arg=PYTHON_IMAGE ;;
    receiver) tag=$EZLLMROUTER_DEV04_RECEIVER_IMAGE; base=$python_image; arg=PYTHON_IMAGE ;;
    python) tag=$EZLLMROUTER_DEV04_PYCLIENT_IMAGE; base=$python_image; arg=PYTHON_IMAGE ;;
    js) tag=$EZLLMROUTER_DEV04_JSCLIENT_IMAGE; base=$node_image; arg=NODE_IMAGE ;;
    worker) tag=$EZLLMROUTER_DEV04_WORKER_IMAGE; base=$python_image; arg=PYTHON_IMAGE ;;
  esac
  logrun "build-$role" docker --context desktop-linux build --pull=false --network=none \
    --platform linux/arm64 --build-arg "$arg=$base" -t "$tag" "$run_dir/build/$role"
  built_images+=("$tag")
done
logrun built-inspect docker --context desktop-linux image inspect "${built_images[@]}"
if [[ "$phase" == choice_b ]]; then
  run_choice_b
  exit 0
fi
if [[ "$phase" == dev05 ]]; then
  run_dev05
  exit 0
fi
logrun compose-config compose config --quiet
logrun namespace-up compose up -d netns
started=1
logrun namespace-check compose exec -T netns python -c \
  'import json,pathlib,socket; routes=pathlib.Path("/proc/net/route").read_text(); assert not any(line.split()[1]=="00000000" for line in routes.splitlines()[1:] if len(line.split())>1); sock=socket.socket(); sock.settimeout(0.5); denied=False
try: sock.connect(("1.1.1.1",443))
except OSError: denied=True
finally: sock.close()
assert denied; print(json.dumps({"default_route":False,"off_loopback_denied":True,"routes":routes,"listeners":pathlib.Path("/proc/net/tcp").read_text()}))'
logrun receiver-up compose up -d receiver
logrun service-up compose up -d service python_consumer js_consumer
logrun readiness compose exec -T netns python -c \
  'import time,urllib.request,urllib.error; urls=["http://127.0.0.1:8766/health","http://127.0.0.1:8765/v1/capabilities"]
for url in urls:
 for attempt in range(60):
  try:
   with urllib.request.urlopen(url,timeout=1) as response: print(url,response.status); break
  except urllib.error.HTTPError as error: print(url,error.code); break
  except Exception:
   if attempt==59: raise
   time.sleep(0.5)'
logrun installed-identities compose exec -T service cat /data/module-identities.json
logrun guard-component compose exec -T service python -B /app/gateway/test_guard.py -q
logrun retry-cause-regression compose exec -T service python -B /app/gateway/test_retry_cause.py --source-root /app -q
logrun actor-output-regression compose exec -T js_consumer node \
  /app/consumer/actor_output_regression.cjs /app/consumer/js_text.cjs \
  /app/consumer/node_modules/@cognitivedynamics/ezllmrouter-client/index.cjs /app/consumer/request.json
logrun actor-output-consumer "$python_tool" -I -B \
  "$root/tests/gateway_integration/verify_actor_output.py" \
  "$run_dir/actor-output-regression.stdout"
if [[ "$phase" == boundaries ]]; then
  source "$root/tests/gateway_integration/boundary_steps.sh"
  run_boundaries
  exit 0
fi

# D04-1: two installed clients, one independent receiver, cross-language status.
logrun js-first compose exec -T js_consumer node /app/consumer/js_text.cjs first
logrun first-sdk-retry compose exec -T service python -c \
  'import json; r=[json.loads(x) for x in open("/data/sdk-retry-observations.jsonl")]; assert len(r)==1 and r[0]["matched_sdk_clients"]>=1 and type(r[0]["effective_max_retries"]) is int and r[0]["effective_max_retries"]==0; print(json.dumps(r))'
logrun first-submission "$python_tool" -I -B -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["submission_id"])' "$run_dir/js-first.stdout"
first_sid=$(<"$run_dir/first-submission.stdout")
logrun python-cross-and-text compose exec -T python_consumer python /app/actors/python_text.py cross_and_submit "$first_sid"

# D04-2: one caller-owned lookup cycle through the same proxy/adapter/SDK path.
logrun python-tool-cycle compose exec -T python_consumer python /app/actors/python_actor.py cycle
logrun tool-mutation-service-up compose up -d service_tool_mutation
tool_mutation_started=1
logrun tool-mutation-readiness compose exec -T netns python -c \
  'import time,urllib.request,urllib.error; url="http://127.0.0.1:8769/v1/capabilities"
for attempt in range(60):
 try:
  with urllib.request.urlopen(url,timeout=1) as response: print(response.status); break
 except urllib.error.HTTPError as error: print(error.code); break
 except Exception:
  if attempt==59: raise
  time.sleep(0.5)'
logrun receiver-before-tool-negative compose exec -T receiver cat /data/arrivals.jsonl
logrun python-tool-mutation compose exec -T -e EZLLMROUTER_SERVICE_URL=http://127.0.0.1:8769 \
  python_consumer python /app/actors/python_negative.py tool
logrun tool-sdk-retry compose exec -T service_tool_mutation python -c \
  'import json; r=[json.loads(x) for x in open("/data/sdk-retry-observations.jsonl")]; assert len(r)==1 and r[0]["matched_sdk_clients"]>=1 and type(r[0]["effective_max_retries"]) is int and r[0]["effective_max_retries"]==0; print(json.dumps(r))'
logrun tool-guard-reached compose exec -T service_tool_mutation python -c \
  'import json,sqlite3; e=[json.loads(x) for x in open("/data/guard-events.jsonl")]; d=sqlite3.connect("/data/store.sqlite"); assert len(e)==2 and [x["stage"] for x in e]==["entered","blocked"] and e[1]["code"]=="FDC_REJECTED" and e[0]["attempt_id"]==e[1]["attempt_id"]; assert d.execute("select count(*) from guard_dispatches").fetchone()[0]==0; print(json.dumps({"guard_events":e,"guard_dispatches":0}))'
logrun tool-negative-horizon "$python_tool" -I -B -c 'import time; start=time.monotonic(); time.sleep(5.2); print(round((time.monotonic()-start)*1000))'
logrun tool-one-guard-after-horizon compose exec -T service_tool_mutation python -c \
  'import json; e=[json.loads(x) for x in open("/data/guard-events.jsonl")]; assert len(e)==2 and [x["stage"] for x in e]==["entered","blocked"]; print(json.dumps({"guard_events":len(e),"blocked_code":e[1]["code"]}))'
logrun receiver-after-tool-negative compose exec -T receiver cat /data/arrivals.jsonl
logrun tool-no-extra-send cmp "$run_dir/receiver-before-tool-negative.stdout" "$run_dir/receiver-after-tool-negative.stdout"
logrun js-after-tool compose exec -T js_consumer node /app/consumer/js_text.cjs after_tool

logrun destination-mutation-service-up compose up -d service_destination_mutation
destination_mutation_started=1
logrun destination-mutation-readiness compose exec -T netns python -c \
  'import time,urllib.request,urllib.error; url="http://127.0.0.1:8770/v1/capabilities"
for attempt in range(60):
 try:
  with urllib.request.urlopen(url,timeout=1) as response: print(response.status); break
 except urllib.error.HTTPError as error: print(error.code); break
 except Exception:
  if attempt==59: raise
  time.sleep(0.5)'
logrun receiver-before-destination-negative compose exec -T receiver cat /data/arrivals.jsonl
logrun python-destination-mutation compose exec -T -e EZLLMROUTER_SERVICE_URL=http://127.0.0.1:8770 \
  python_consumer python /app/actors/python_negative.py destination
logrun destination-sdk-retry compose exec -T service_destination_mutation python -c \
  'import json; r=[json.loads(x) for x in open("/data/sdk-retry-observations.jsonl")]; assert len(r)==1 and r[0]["matched_sdk_clients"]>=1 and type(r[0]["effective_max_retries"]) is int and r[0]["effective_max_retries"]==0; print(json.dumps(r))'
logrun destination-guard-reached compose exec -T service_destination_mutation python -c \
  'import json,sqlite3; e=[json.loads(x) for x in open("/data/guard-events.jsonl")]; d=sqlite3.connect("/data/store.sqlite"); assert len(e)==2 and [x["stage"] for x in e]==["entered","blocked"] and e[1]["code"]=="FDC_REJECTED" and e[0]["attempt_id"]==e[1]["attempt_id"]; assert d.execute("select count(*) from guard_dispatches").fetchone()[0]==0; print(json.dumps({"guard_events":e,"guard_dispatches":0}))'
logrun destination-negative-horizon "$python_tool" -I -B -c 'import time; start=time.monotonic(); time.sleep(5.2); print(round((time.monotonic()-start)*1000))'
logrun destination-one-guard-after-horizon compose exec -T service_destination_mutation python -c \
  'import json; e=[json.loads(x) for x in open("/data/guard-events.jsonl")]; assert len(e)==2 and [x["stage"] for x in e]==["entered","blocked"]; print(json.dumps({"guard_events":len(e),"blocked_code":e[1]["code"]}))'
logrun receiver-after-destination-negative compose exec -T receiver cat /data/arrivals.jsonl
logrun destination-no-extra-send cmp "$run_dir/receiver-before-destination-negative.stdout" "$run_dir/receiver-after-destination-negative.stdout"
logrun js-after-destination compose exec -T js_consumer node /app/consumer/js_text.cjs after_destination

# D04-3: fault the actual final guard commit; the original service remains live.
logrun fault-service-up compose up -d service_fault
fault_started=1
logrun fault-readiness compose exec -T netns python -c \
  'import time,urllib.request,urllib.error; url="http://127.0.0.1:8768/v1/capabilities"
for attempt in range(60):
 try:
  with urllib.request.urlopen(url,timeout=1) as response: print(response.status); break
 except urllib.error.HTTPError as error: print(error.code); break
 except Exception:
  if attempt==59: raise
  time.sleep(0.5)'
logrun receiver-before-fault compose exec -T receiver cat /data/arrivals.jsonl
logrun python-guard-failure compose exec -T -e EZLLMROUTER_SERVICE_URL=http://127.0.0.1:8768 \
  python_consumer python /app/actors/python_text.py guard_failure
logrun fault-sdk-retry compose exec -T service_fault python -c \
  'import json; r=[json.loads(x) for x in open("/data/sdk-retry-observations.jsonl")]; assert len(r)==1 and r[0]["matched_sdk_clients"]>=1 and type(r[0]["effective_max_retries"]) is int and r[0]["effective_max_retries"]==0; print(json.dumps(r))'
logrun fault-store compose exec -T service_fault python -c \
  'import json,sqlite3; d=sqlite3.connect("/data/store.sqlite"); record=json.loads(d.execute("select record from submissions").fetchone()[0]); row={"submissions":d.execute("select count(*) from submissions").fetchone()[0],"preparatory_intents":d.execute("select count(*) from intents").fetchone()[0],"guard_dispatches":d.execute("select count(*) from guard_dispatches").fetchone()[0],"submission_state":record["submission_state"],"failure_code":record["terminal_failure"]["code"]}; assert row=={"submissions":1,"preparatory_intents":1,"guard_dispatches":0,"submission_state":"failed_before_transmit","failure_code":"INTENT_PERSIST_FAILED"}; print(json.dumps(row))'
logrun bounded-horizon "$python_tool" -I -B -c 'import time; start=time.monotonic(); time.sleep(5.2); print(round((time.monotonic()-start)*1000))'
logrun fault-one-guard-after-horizon compose exec -T service_fault python -c \
  'import json,sqlite3; e=[json.loads(x) for x in open("/data/guard-events.jsonl")]; d=sqlite3.connect("/data/store.sqlite"); assert len(e)==2 and [x["stage"] for x in e]==["entered","blocked"] and e[1]["code"]=="INTENT_PERSIST_FAILED" and e[0]["attempt_id"]==e[1]["attempt_id"]; assert d.execute("select count(*) from guard_dispatches").fetchone()[0]==0; print(json.dumps({"guard_events":e,"guard_dispatches":0}))'
logrun receiver-after-fault compose exec -T receiver cat /data/arrivals.jsonl
logrun fault-no-extra-send cmp "$run_dir/receiver-before-fault.stdout" "$run_dir/receiver-after-fault.stdout"
logrun js-after-guard compose exec -T js_consumer node /app/consumer/js_text.cjs after_guard
logrun final-receiver-control compose exec -T receiver python -c \
  'import json; r=[json.loads(x) for x in open("/data/arrivals.jsonl")]; assert len(r)==7 and len({x["attempt_id"] for x in r})==7 and all(x["attempt_id"] for x in r); print(json.dumps({"arrivals":len(r),"attempt_ids":[x["attempt_id"] for x in r]}))'
logrun final-store-control compose exec -T service python -c \
  'import json,sqlite3; d=sqlite3.connect("/data/store.sqlite"); row={"submissions":d.execute("select count(*) from submissions").fetchone()[0],"preparatory_intents":d.execute("select count(*) from intents").fetchone()[0],"guard_dispatches":d.execute("select count(*) from guard_dispatches").fetchone()[0],"usage_revisions":d.execute("select count(*) from usage_revisions").fetchone()[0]}; assert row=={"submissions":7,"preparatory_intents":7,"guard_dispatches":7,"usage_revisions":7}; print(json.dumps(row))'
logrun final-guard-records compose exec -T service python -c \
  'import sqlite3; d=sqlite3.connect("/data/store.sqlite"); [print(row[0]) for row in d.execute("select receipt from guard_dispatches order by rowid")]'
logrun final-arrivals compose exec -T receiver cat /data/arrivals.jsonl
logrun receiver-guard-correlation "$python_tool" -I -B "$root/tests/gateway_integration/verify_runtime.py" \
  "$run_dir/final-arrivals.stdout" "$run_dir/final-guard-records.stdout"
