#!/usr/bin/env bash
# Sourced by run.sh only for the bounded Choice B discriminator.

run_choice_b() {
  logrun choice-b-compose-config compose config --quiet
  started=1
  logrun choice-b-up compose up -d netns receiver worker_choice_b service_choice_b python_choice_b
  logrun choice-b-worker-ready compose exec -T service_choice_b python -c \
    'import pathlib,stat,time; p=pathlib.Path("/link/worker.sock");
for i in range(100):
 if p.exists() and stat.S_ISSOCK(p.stat().st_mode): print("worker Unix socket ready"); break
 if i==99: raise AssertionError("worker socket absent")
 time.sleep(.2)'
  logrun choice-b-worker-identities compose exec -T worker_choice_b python -c \
    'import json,socket; from choice_b_wire import receive,send; s=socket.socket(socket.AF_UNIX); s.settimeout(5); s.connect("/link/worker.sock"); send(s,{"kind":"module_identity"}); print(json.dumps(receive(s))); s.close()'
  logrun choice-b-worker-isolation compose exec -T worker_choice_b python -c \
    'import json,os,pathlib,socket; routes=pathlib.Path("/proc/net/route").read_text().splitlines(); assert not any(len(x.split())>1 and x.split()[1]=="00000000" for x in routes[1:]); assert "DURANKI_DEV_TOKEN" not in os.environ and "DURANKI_DEV04_PROVIDER_KEY" not in os.environ; assert not any(pathlib.Path(x).exists() for x in ("/app/server","/app/dev_slice","/app/gateway")); s=socket.socket(); s.settimeout(.5); rc=s.connect_ex(("127.0.0.1",8766)); s.close(); assert rc != 0; print(json.dumps({"network_mode":"none","default_route":False,"direct_receiver_connect_errno":rc,"trusted_code_mounted":False,"trusted_credentials_in_environment":False}))'
  logrun choice-b-readiness compose exec -T python_choice_b python -c \
    'import os,time,urllib.request,urllib.error; u=urllib.request.Request("http://127.0.0.1:8773/v1/capabilities",headers={"Duranki-Contract-Version":"0.2","Authorization":"Bearer "+os.environ["DURANKI_DEV_TOKEN"]});
for i in range(60):
 try:
  with urllib.request.urlopen(u,timeout=1) as response:
   assert response.status==200 and response.headers.get("Duranki-Contract-Version")=="0.2"
   print(response.status)
  break
 except urllib.error.HTTPError: raise
 except (urllib.error.URLError,TimeoutError,ConnectionError):
  if i==59: raise
  time.sleep(.2)'
  logrun choice-b-positive-before compose exec -T python_choice_b python /app/actors/python_boundary.py positive choice_b_before
  logrun choice-b-receiver-before compose exec -T receiver cat /data/arrivals.jsonl
  logrun choice-b-raw-probe compose exec -T worker_choice_b python -c \
    'import json,socket; from choice_b_wire import receive,send; s=socket.socket(socket.AF_UNIX); s.settimeout(5); s.connect("/link/worker.sock"); send(s,{"kind":"raw_egress_probe"}); r=receive(s); s.close(); assert r.get("probe")=="raw_worker_direct_provider" and r.get("error_type") in ("ConnectError","ConnectTimeout"); print(json.dumps(r))'
  logrun choice-b-forged-attempt compose exec -T worker_choice_b python -c \
    'import json,socket; from choice_b_wire import receive,send; s=socket.socket(socket.AF_UNIX); s.settimeout(5); s.connect("/link/sender.sock"); send(s,{"kind":"final_request","attempt_id":"attempt.forged.choice-b","method":"POST","url":"http://127.0.0.1:8766/v1/chat/completions","headers":[["authorization","Bearer sk-dev04-worker-placeholder-not-provider-000000"]],"body_b64":"e30=","timeout":{"connect":1,"read":1,"write":1,"pool":1}}); r=receive(s); s.close(); assert r=={"error_type":"ValueError"}; print(json.dumps({"probe":"forged_sender_attempt","rejected":True,"error_type":r["error_type"]}))'
  logrun choice-b-receiver-after-negatives compose exec -T receiver cat /data/arrivals.jsonl
  logrun choice-b-no-negative-arrival cmp "$run_dir/choice-b-receiver-before.stdout" "$run_dir/choice-b-receiver-after-negatives.stdout"
  logrun choice-b-horizon "$python_tool" -I -B -c \
    'import time; s=time.monotonic(); time.sleep(5.2); print(round((time.monotonic()-s)*1000))'
  logrun choice-b-receiver-after-horizon compose exec -T receiver cat /data/arrivals.jsonl
  logrun choice-b-no-late-arrival cmp "$run_dir/choice-b-receiver-before.stdout" "$run_dir/choice-b-receiver-after-horizon.stdout"
  logrun choice-b-positive-after compose exec -T python_choice_b python /app/actors/python_boundary.py positive choice_b_after
  logrun choice-b-receiver compose exec -T receiver cat /data/arrivals.jsonl
  logrun choice-b-guard-events compose exec -T service_choice_b cat /data/guard-events.jsonl
  logrun choice-b-receipts compose exec -T service_choice_b python -c \
    'import json,sqlite3; d=sqlite3.connect("/data/store.sqlite"); [print(json.dumps({"attempt_id":a,"submission_id":s,"receipt":json.loads(r)})) for a,s,r in d.execute("select attempt_id,submission_id,receipt from guard_dispatches order by rowid")]'
  logrun choice-b-store compose exec -T service_choice_b python -c \
    'import json,sqlite3; d=sqlite3.connect("/data/store.sqlite"); print(json.dumps({"submissions":d.execute("select count(*) from submissions").fetchone()[0],"preparatory_intents":d.execute("select count(*) from intents").fetchone()[0],"guard_dispatches":d.execute("select count(*) from guard_dispatches").fetchone()[0],"usage_revisions":d.execute("select count(*) from usage_revisions").fetchone()[0]}))'
  logrun choice-b-modules compose exec -T service_choice_b cat /data/module-identities.json
  logrun choice-b-verify "$python_tool" -I -B "$root/tests/gateway_integration/verify_choice_b.py" "$run_dir"
  run_choice_b_freshness
}

run_choice_b_freshness() {
  logrun choice-b-freshness-hold compose exec -T python_choice_b \
    python /app/actors/python_wait.py hold choice_b_owned_hold
  logrun choice-b-freshness-hold-sid "$python_tool" -I -B -c \
    'import json,sys; print(json.load(open(sys.argv[1]))["submission_id"])' \
    "$run_dir/choice-b-freshness-hold.stdout"
  logrun choice-b-freshness-hold-entered compose exec -T receiver python -c \
    'import json,pathlib,time; p=pathlib.Path("/data/controls.jsonl");
for i in range(100):
 r=[json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []
 if any(x["event"]=="hold_entered_after_receiver_arrival" for x in r): print(json.dumps(r[-1])); break
 time.sleep(.05)
else: raise AssertionError("receiver hold not entered")'
  logrun choice-b-freshness-queued compose exec -T python_choice_b \
    python /app/actors/python_wait.py queued choice_b_owned_queued
  logrun choice-b-freshness-queued-sid "$python_tool" -I -B -c \
    'import json,sys; print(json.load(open(sys.argv[1]))["submission_id"])' \
    "$run_dir/choice-b-freshness-queued.stdout"
  local queued_sid hold_sid
  queued_sid=$(<"$run_dir/choice-b-freshness-queued-sid.stdout")
  hold_sid=$(<"$run_dir/choice-b-freshness-hold-sid.stdout")
  logrun choice-b-freshness-real-pool-queued compose exec -T service_choice_b python -c \
    'import json,pathlib,sqlite3,sys,time; d=sqlite3.connect("/data/store.sqlite"); row=d.execute("select record from submissions where submission_id=?",(sys.argv[1],)).fetchone(); assert row; aid=json.loads(row[0])["attempt_id"]; p=pathlib.Path("/data/pool-observations.jsonl");
for i in range(200):
 r=[json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []
 if any(x["attempt_id"]==aid and x["event"]=="queued_in_owned_httpcore_pool" for x in r): print(json.dumps({"attempt_id":aid,"pool_queued":True})); break
 time.sleep(.02)
else: raise AssertionError("second request never queued in owned httpcore pool")' "$queued_sid"
  logrun choice-b-freshness-authority-revoked compose exec -T service_choice_b python -c \
    'import json,socket; s=socket.socket(socket.AF_UNIX); s.settimeout(3); s.connect("/data/authority.sock"); s.sendall(b"revoke\n"); r=json.loads(s.makefile().readline()); s.close(); assert r["authority_state"]=="revoked"; print(json.dumps(r))'
  logrun choice-b-freshness-release compose exec -T netns python -c \
    'import urllib.request; print(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8766/control/release",data=b"",method="POST"),timeout=3).status)'
  logrun choice-b-freshness-hold-status compose exec -T python_choice_b \
    python /app/actors/python_wait.py status "$hold_sid"
  logrun choice-b-freshness-queued-status compose exec -T python_choice_b \
    python /app/actors/python_wait.py status "$queued_sid"
  logrun choice-b-freshness-receiver-before-horizon compose exec -T receiver cat /data/arrivals.jsonl
  logrun choice-b-freshness-horizon "$python_tool" -I -B -c \
    'import time; start=time.monotonic(); time.sleep(5.2); print(round((time.monotonic()-start)*1000))'
  logrun choice-b-freshness-receiver-after-horizon compose exec -T receiver cat /data/arrivals.jsonl
  logrun choice-b-freshness-no-late-send cmp \
    "$run_dir/choice-b-freshness-receiver-before-horizon.stdout" \
    "$run_dir/choice-b-freshness-receiver-after-horizon.stdout"
  logrun choice-b-freshness-authority-restored compose exec -T service_choice_b python -c \
    'import json,socket; s=socket.socket(socket.AF_UNIX); s.settimeout(3); s.connect("/data/authority.sock"); s.sendall(b"restore\n"); r=json.loads(s.makefile().readline()); s.close(); assert r["authority_state"]=="active"; print(json.dumps(r))'
  logrun choice-b-freshness-positive-after compose exec -T python_choice_b \
    python /app/actors/python_boundary.py positive choice_b_owned_after
  logrun choice-b-freshness-receiver-final compose exec -T receiver cat /data/arrivals.jsonl
  logrun choice-b-freshness-receiver-controls compose exec -T receiver cat /data/controls.jsonl
  logrun choice-b-freshness-pool-observations compose exec -T service_choice_b cat /data/pool-observations.jsonl
  logrun choice-b-freshness-send-events compose exec -T service_choice_b cat /data/send-events.jsonl
  logrun choice-b-freshness-guard-events compose exec -T service_choice_b cat /data/guard-events.jsonl
  logrun choice-b-freshness-receipts compose exec -T service_choice_b python -c \
    'import json,sqlite3; d=sqlite3.connect("/data/store.sqlite"); [print(json.dumps({"attempt_id":a,"submission_id":s,"receipt":json.loads(r)})) for a,s,r in d.execute("select attempt_id,submission_id,receipt from guard_dispatches order by rowid")]'
  logrun choice-b-freshness-store compose exec -T service_choice_b python -c \
    'import json,sqlite3; d=sqlite3.connect("/data/store.sqlite"); print(json.dumps({"submissions":d.execute("select count(*) from submissions").fetchone()[0],"preparatory_intents":d.execute("select count(*) from intents").fetchone()[0],"guard_dispatches":d.execute("select count(*) from guard_dispatches").fetchone()[0],"usage_revisions":d.execute("select count(*) from usage_revisions").fetchone()[0]}))'
  logrun choice-b-freshness-verify "$python_tool" -I -B \
    "$root/tests/gateway_integration/verify_choice_b_freshness.py" "$run_dir"
}

finish_choice_b() {
  local rc=$1
  if [[ $started == 1 ]]; then
    compose ps > "$run_dir/compose-ps.stdout" 2> "$run_dir/compose-ps.stderr"
    printf '%s\n' "$?" > "$run_dir/compose-ps.exit"
    compose logs --no-color > "$run_dir/compose-logs.stdout" 2> "$run_dir/compose-logs.stderr"
    printf '%s\n' "$?" > "$run_dir/compose-logs.exit"
    compose exec -T receiver cat /data/arrivals.jsonl > "$run_dir/final-receiver.stdout" 2> "$run_dir/final-receiver.stderr"
    printf '%s\n' "$?" > "$run_dir/final-receiver.exit"
    compose exec -T receiver cat /data/controls.jsonl > "$run_dir/final-receiver-controls.stdout" 2> "$run_dir/final-receiver-controls.stderr"
    printf '%s\n' "$?" > "$run_dir/final-receiver-controls.exit"
    compose exec -T service_choice_b cat /data/guard-events.jsonl > "$run_dir/final-choice-b-guard.stdout" 2> "$run_dir/final-choice-b-guard.stderr"
    printf '%s\n' "$?" > "$run_dir/final-choice-b-guard.exit"
    for item in pool-observations send-events; do
      compose exec -T service_choice_b cat "/data/$item.jsonl" > "$run_dir/final-choice-b-$item.stdout" 2> "$run_dir/final-choice-b-$item.stderr"
      printf '%s\n' "$?" > "$run_dir/final-choice-b-$item.exit"
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
  if [[ $capture_rc != 0 ]]; then cat "$run_dir/capture.stderr" >&2; exit "$capture_rc"; fi
  cat "$run_dir/capture.stdout"
  exit "$rc"
}
