#!/usr/bin/env bash
# Sourced by run.sh for the bounded installed-client Choice B matrix.

dev05_sid() {
  "$python_tool" -I -B -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' \
    "$run_dir/$1.stdout" "$2"
}

dev05_cross() {
  local name=$1 actor=$2 submission=$3 kind=${4:-tool_call}
  if [[ "$actor" == js ]]; then
    logrun "$name" compose exec -T js_choice_b node /app/consumer/js_actor.cjs status "$submission" "$kind"
  else
    logrun "$name" compose exec -T python_choice_b python /app/actors/python_actor.py status "$submission" "$kind"
  fi
}

run_dev05() {
  logrun d05-compose-config compose config --quiet
  started=1
  logrun d05-up compose up -d netns receiver worker_choice_b service_choice_b python_choice_b js_choice_b
  logrun d05-readiness compose exec -T python_choice_b python -c \
    'import os,time,urllib.request,urllib.error; u=urllib.request.Request("http://127.0.0.1:8773/v1/capabilities",headers={"EzLLMRouter-Contract-Version":"0.2","Authorization":"Bearer "+os.environ["EZLLMROUTER_DEV_TOKEN"]});
for i in range(60):
 try:
  with urllib.request.urlopen(u,timeout=1) as response:
   assert response.status==200 and response.headers.get("EzLLMRouter-Contract-Version")=="0.2"
   print(response.status)
  break
 except urllib.error.HTTPError: raise
 except (urllib.error.URLError,TimeoutError,ConnectionError):
  if i==59: raise
  time.sleep(.2)'
  logrun d05-python-package compose exec -T python_choice_b python -c \
    'import importlib.metadata as m,ezllmrouter_client,json; print(json.dumps({"version":m.version("cognitivedynamics-ezllmrouter-client"),"path":ezllmrouter_client.__file__}))'
  logrun d05-js-package compose exec -T js_choice_b node -e \
    'const p=require.resolve("@cognitivedynamics/ezllmrouter-client");const m=require("/app/consumer/node_modules/@cognitivedynamics/ezllmrouter-client/package.json");console.log(JSON.stringify({version:m.version,path:p}))'
  logrun d05-worker-identities compose exec -T service_choice_b \
    python -B /app/gateway/worker_ready.py
  logrun d05-worker-isolation compose exec -T worker_choice_b python -c \
    'import json,os,pathlib,socket; routes=pathlib.Path("/proc/net/route").read_text().splitlines(); assert not any(len(x.split())>1 and x.split()[1]=="00000000" for x in routes[1:]); assert "EZLLMROUTER_DEV_TOKEN" not in os.environ and "EZLLMROUTER_DEV04_PROVIDER_KEY" not in os.environ; assert not any(pathlib.Path(x).exists() for x in ("/app/server","/app/dev_slice","/app/gateway")); s=socket.socket(); s.settimeout(.5); rc=s.connect_ex(("127.0.0.1",8766)); s.close(); assert rc != 0; print(json.dumps({"network_mode":"none","default_route":False,"direct_receiver_connect_errno":rc,"trusted_code_mounted":False,"trusted_credentials_in_environment":False}))'
  logrun d05-guard-component compose exec -T service_choice_b python -B /app/gateway/test_guard.py -q
  logrun d05-retry-component compose exec -T service_choice_b python -B /app/gateway/test_retry_cause.py --source-root /app -q
  logrun d05-work-identity-component compose exec -T service_choice_b \
    python -B /app/gateway/test_work_identity.py --source-root /app -q
  logrun d05-python-client-validation compose exec -T python_choice_b \
    python -B /app/actors/test_python_client.py -q
  logrun d05-js-client-validation compose exec -T js_choice_b \
    node /app/consumer/test_js_client.cjs
  logrun d05-js-actor-output-regression compose exec -T js_choice_b node \
    /app/consumer/actor_output_regression.cjs /app/consumer/js_text.cjs \
    /app/consumer/node_modules/@cognitivedynamics/ezllmrouter-client/index.cjs /app/consumer/request.json
  logrun d05-js-actor-output-consumer "$python_tool" -I -B \
    "$root/tests/gateway_integration/verify_actor_output.py" \
    "$run_dir/d05-js-actor-output-regression.stdout"

  # D05-01: exactly two retained text sends, followed by both cross reads.
  logrun d05-js-text compose exec -T js_choice_b node /app/consumer/js_text.cjs first
  local js_text_sid
  js_text_sid=$(dev05_sid d05-js-text submission_id)
  logrun d05-python-cross-text compose exec -T python_choice_b \
    python /app/actors/python_text.py cross_and_submit "$js_text_sid"
  local python_text_sid
  python_text_sid=$(dev05_sid d05-python-cross-text submission_id)
  dev05_cross d05-js-cross-text js "$python_text_sid" assistant_text
  logrun d05-python-by-work-js-text compose exec -T python_choice_b \
    python /app/actors/python_actor.py by_work step.dev04.js.text gen.1 assistant_text
  logrun d05-js-by-work-python-text compose exec -T js_choice_b \
    node /app/consumer/js_actor.cjs by_work step.dev04.python.text gen.1 assistant_text

  # D05-02: each installed caller performs exactly one explicit lookup.
  logrun d05-python-cycle compose exec -T python_choice_b python /app/actors/python_actor.py cycle
  local py_tool_sid
  py_tool_sid=$(dev05_sid d05-python-cycle first_submission_id)
  dev05_cross d05-js-cross-python-tool js "$py_tool_sid"
  logrun d05-js-cycle compose exec -T js_choice_b node /app/consumer/js_actor.cjs cycle
  local js_tool_sid
  js_tool_sid=$(dev05_sid d05-js-cycle first_submission_id)
  dev05_cross d05-python-cross-js-tool python "$js_tool_sid"
  logrun d05-python-by-work-js-tool compose exec -T python_choice_b \
    python /app/actors/python_actor.py by_work step.dev03.js gen.1 tool_call
  logrun d05-js-by-work-python-tool compose exec -T js_choice_b \
    node /app/consumer/js_actor.cjs by_work step.dev03.python gen.1 tool_call
  logrun d05-checkpoint-receiver compose exec -T receiver cat /data/arrivals.jsonl
  logrun d05-checkpoint-receipts compose exec -T service_choice_b python -c \
    'import json,sqlite3; d=sqlite3.connect("/data/store.sqlite"); [print(json.dumps({"attempt_id":a,"submission_id":s,"receipt":json.loads(r)})) for a,s,r in d.execute("select attempt_id,submission_id,receipt from guard_dispatches order by rowid")]'
  logrun d05-checkpoint-verify "$python_tool" -I -B "$root/tests/gateway_integration/verify_dev05.py" checkpoint "$run_dir"

  # D05-03: live no-store candidates; each forged source precedes its legitimate second round.
  logrun d05-python-no-store compose exec -T python_choice_b python /app/actors/python_actor.py no_store
  logrun d05-js-no-store compose exec -T js_choice_b node /app/consumer/js_actor.cjs no_store

  # D05-04: controlled provider error and ambiguous close, no replay.
  local mode sid expected
  for mode in 503 close; do
    logrun "d05-$mode" compose exec -T python_choice_b python /app/actors/python_boundary.py "$mode"
    sid=$(dev05_sid "d05-$mode" submission_id)
    expected=failed_after_transmit
    if [[ "$mode" == close ]]; then expected=outcome_unknown; fi
    logrun "d05-js-cross-$mode" compose exec -T js_choice_b \
      node /app/consumer/js_actor.cjs failure_status "$sid" "$expected"
    logrun "d05-$mode-drain" compose exec -T service_choice_b python -c \
      'import json,sqlite3,sys; d=sqlite3.connect("/data/store.sqlite"); r=json.loads(d.execute("select record from submissions where submission_id=?",(sys.argv[1],)).fetchone()[0]); assert r["submission_state"]==sys.argv[2]; print(json.dumps({"attempt_id":r["attempt_id"],"submission_state":r["submission_state"],"selected_pool_requests":None}))' "$sid" "$expected"
    logrun "d05-$mode-before-horizon" compose exec -T receiver cat /data/arrivals.jsonl
    logrun "d05-$mode-horizon" "$python_tool" -I -B -c \
      'import time; s=time.monotonic(); time.sleep(5.2); print(round((time.monotonic()-s)*1000))'
    logrun "d05-$mode-after-horizon" compose exec -T receiver cat /data/arrivals.jsonl
    logrun "d05-$mode-no-late-send" cmp "$run_dir/d05-$mode-before-horizon.stdout" "$run_dir/d05-$mode-after-horizon.stdout"
  done

  # D05-05: a post-binding tool-field mutation reaches the trusted final guard.
  logrun d05-mutation-before compose exec -T receiver cat /data/arrivals.jsonl
  logrun d05-tool-mutation compose exec -T python_choice_b python /app/actors/python_actor.py mutation
  logrun d05-mutation-after compose exec -T receiver cat /data/arrivals.jsonl
  logrun d05-mutation-no-send cmp "$run_dir/d05-mutation-before.stdout" "$run_dir/d05-mutation-after.stdout"
  logrun d05-probes-before compose exec -T receiver cat /data/arrivals.jsonl
  logrun d05-raw-probe compose exec -T worker_choice_b python -c \
    'import json,socket; from choice_b_wire import receive,send; s=socket.socket(socket.AF_UNIX); s.settimeout(5); s.connect("/link/worker.sock"); send(s,{"kind":"raw_egress_probe"}); r=receive(s); s.close(); assert r.get("probe")=="raw_worker_direct_provider" and r.get("error_type") in ("ConnectError","ConnectTimeout"); print(json.dumps(r))'
  logrun d05-forged-attempt compose exec -T worker_choice_b python -c \
    'import json,socket; from choice_b_wire import receive,send; s=socket.socket(socket.AF_UNIX); s.settimeout(5); s.connect("/link/sender.sock"); send(s,{"kind":"final_request","attempt_id":"attempt.forged.dev05","method":"POST","url":"http://127.0.0.1:8766/v1/chat/completions","headers":[["authorization","Bearer sk-dev04-worker-placeholder-not-provider-000000"]],"body_b64":"e30=","timeout":{"connect":1,"read":1,"write":1,"pool":1}}); r=receive(s); s.close(); assert r=={"error_type":"ValueError"}; print(json.dumps({"probe":"forged_sender_attempt","rejected":True,"error_type":r["error_type"]}))'
  logrun d05-probes-horizon "$python_tool" -I -B -c \
    'import time; s=time.monotonic(); time.sleep(5.2); print(round((time.monotonic()-s)*1000))'
  logrun d05-receiver compose exec -T receiver cat /data/arrivals.jsonl
  logrun d05-probes-no-send cmp "$run_dir/d05-probes-before.stdout" "$run_dir/d05-receiver.stdout"
  logrun d05-probes-health compose exec -T python_choice_b python -c \
    'import os,urllib.request; a=urllib.request.urlopen("http://127.0.0.1:8766/health",timeout=2); b=urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8773/v1/capabilities",headers={"EzLLMRouter-Contract-Version":"0.2","Authorization":"Bearer "+os.environ["EZLLMROUTER_DEV_TOKEN"]}),timeout=2); assert a.status==b.status==200; print("200")'
  logrun d05-controls compose exec -T receiver python -c \
    'from pathlib import Path; p=Path("/data/controls.jsonl"); print(p.read_text() if p.exists() else "",end="")'
  logrun d05-guard-events compose exec -T service_choice_b cat /data/guard-events.jsonl
  logrun d05-send-events compose exec -T service_choice_b cat /data/send-events.jsonl
  logrun d05-worker-attempts compose exec -T worker_choice_b python -c \
    'import json,socket; from choice_b_wire import receive,send; s=socket.socket(socket.AF_UNIX); s.settimeout(5); s.connect("/link/worker.sock"); send(s,{"kind":"module_identity"}); r=receive(s); s.close(); print(json.dumps({"relay_attempt_counts":r["relay_attempt_counts"]}))'
  logrun d05-tool-mutation-events compose exec -T service_choice_b cat /data/tool-mutation-events.jsonl
  logrun d05-receipts compose exec -T service_choice_b python -c \
    'import json,sqlite3; d=sqlite3.connect("/data/store.sqlite"); [print(json.dumps({"attempt_id":a,"submission_id":s,"receipt":json.loads(r)})) for a,s,r in d.execute("select attempt_id,submission_id,receipt from guard_dispatches order by rowid")]'
  logrun d05-authority-chain compose exec -T service_choice_b python -c \
    'import json,sqlite3; d=sqlite3.connect("/data/store.sqlite");
for (raw,) in d.execute("select record from submissions order by rowid"):
 r=json.loads(raw); sid=r["submission_id"]; aid=r["attempt_id"]; i=d.execute("select intent from intents where attempt_id=?",(aid,)).fetchone(); g=d.execute("select receipt from guard_dispatches where attempt_id=?",(aid,)).fetchone(); intent=json.loads(i[0]) if i else None; receipt=json.loads(g[0]) if g else None; usage=d.execute("select count(*) from usage_revisions where attempt_id=?",(aid,)).fetchone()[0]; print(json.dumps({"submission_id":sid,"attempt_id":aid,"work_digest":r["work_digest"],"step_id":r["work_key"]["step_id"],"execution_generation":r["work_key"]["execution_generation"],"intent":intent,"receipt_plan_id":receipt["plan_id"] if receipt else None,"receipt_work_digest":receipt["work_digest"] if receipt else None,"usage_revisions":usage,"submission_state":r["submission_state"]}))'
  logrun d05-store-metadata compose exec -T service_choice_b python -c \
    'import json,sqlite3; d=sqlite3.connect("/data/store.sqlite"); [print(json.dumps({"submission_id":r["submission_id"],"attempt_id":r["attempt_id"],"step_id":r["work_key"]["step_id"],"submission_state":r["submission_state"],"candidate_access":r["candidate_access"],"content_store_allowed":r["content_store_allowed"],"usage_state":"available" if d.execute("select 1 from usage_revisions where attempt_id=?",(r["attempt_id"],)).fetchone() else "not_recorded","candidate_present":r.get("candidate") is not None})) for (v,) in d.execute("select record from submissions order by rowid") for r in [json.loads(v)]]'
  logrun d05-no-store-storage compose exec -T service_choice_b python -c \
    'import json,sqlite3; d=sqlite3.connect("/data/store.sqlite"); ids=[r["submission_id"] for (v,) in d.execute("select record from submissions") for r in [json.loads(v)] if r["work_key"]["step_id"] in ("step.dev03.no_store","step.dev03.js.no_store")]; assert len(ids)==4; bad=("Use lookup for synthetic.","Lookup: synthetic","\"arguments\":{\"key\":\"synthetic\"}"); counts={};
for table,column in (("submissions","record"),("intents","intent"),("guard_dispatches","receipt"),("usage_revisions","usage")):
 rows=[text for sid in ids for (text,) in d.execute(f"select {column} from {table} where submission_id=?",(sid,))]; assert all(not any(marker in text for marker in bad) for text in rows),table; counts[table]=len(rows)
print(json.dumps({"no_store_submissions":len(ids),"checked_rows":counts,"candidate_or_prompt_literals_present":False}))'
  logrun d05-log-scan "$python_tool" -I -B \
    "$root/tests/gateway_integration/scan_dev05_logs.py" "$compose_file" "$project"
  logrun d05-verify "$python_tool" -I -B "$root/tests/gateway_integration/verify_dev05.py" full "$run_dir"
}

finish_dev05() {
  local rc=$1
  if [[ $started == 1 ]]; then
    if [[ -f "$run_dir/d05-worker-identities.exit" ]] &&
       [[ $(<"$run_dir/d05-worker-identities.exit") != 0 ]] &&
       [[ ! -f "$run_dir/d05-js-text.argv" ]]; then
      compose logs --no-color worker_choice_b > "$run_dir/worker-startup-logs.stdout" \
        2> "$run_dir/worker-startup-logs.stderr"
      printf '%s\n' "$?" > "$run_dir/worker-startup-logs.exit"
    fi
    compose ps > "$run_dir/compose-ps.stdout" 2> "$run_dir/compose-ps.stderr"
    printf '%s\n' "$?" > "$run_dir/compose-ps.exit"
    "$python_tool" -I -B "$root/tests/gateway_integration/scan_dev05_logs.py" "$compose_file" "$project" \
      > "$run_dir/final-log-scan.stdout" 2> "$run_dir/final-log-scan.stderr"
    printf '%s\n' "$?" > "$run_dir/final-log-scan.exit"
    for item in 'receiver arrivals.jsonl' 'receiver controls.jsonl' 'service_choice_b guard-events.jsonl' 'service_choice_b send-events.jsonl'; do
      local service=${item%% *} file=${item#* }
      compose exec -T "$service" cat "/data/$file" > "$run_dir/final-${service}-${file%.jsonl}.stdout" 2> "$run_dir/final-${service}-${file%.jsonl}.stderr"
      printf '%s\n' "$?" > "$run_dir/final-${service}-${file%.jsonl}.exit"
    done
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
  printf '%s\n' "$capture_rc" > "$run_dir/capture.exit"
  if [[ $capture_rc != 0 ]]; then
    cat "$run_dir/capture.stderr" >&2
    if [[ $rc == 0 ]]; then exit "$capture_rc"; fi
    exit "$rc"
  fi
  cat "$run_dir/capture.stdout"
  exit "$rc"
}
