#!/usr/bin/env bash
# Sourced by run.sh after its frozen build, namespace, component and actor gates.

run_boundaries() {
  local mode index=0
  logrun d04-4-positive-p0 compose exec -T python_consumer python /app/actors/python_boundary.py positive p0
  for mode in 422 503 close; do
    logrun "d04-4-$mode" compose exec -T python_consumer python /app/actors/python_boundary.py "$mode"
    logrun "d04-4-$mode-selected-drain" compose exec -T service python -c \
      'import json,sqlite3; d=sqlite3.connect("/data/store.sqlite"); r=json.loads(d.execute("select record from submissions order by rowid desc limit 1").fetchone()[0]); o=[json.loads(x) for x in open("/data/sdk-retry-observations.jsonl")][-1]; assert r["attempt_id"]==o["attempt_id"] and o["effective_max_retries"]==0 and o["selected_pool_requests_at_send_end"]==0 and r["submission_state"] in ("failed_after_transmit","outcome_unknown"); print(json.dumps({"attempt_id":r["attempt_id"],"submission_state":r["submission_state"],"sdk_retry":o["effective_max_retries"],"pool_requests_at_send_end":o["selected_pool_requests_at_send_end"]}))'
    logrun "d04-4-$mode-before-horizon" compose exec -T receiver cat /data/arrivals.jsonl
    logrun "d04-4-$mode-horizon" "$python_tool" -I -B -c \
      'import time; start=time.monotonic(); time.sleep(5.2); print(round((time.monotonic()-start)*1000))'
    logrun "d04-4-$mode-after-horizon" compose exec -T receiver cat /data/arrivals.jsonl
    logrun "d04-4-$mode-no-late-send" cmp "$run_dir/d04-4-$mode-before-horizon.stdout" "$run_dir/d04-4-$mode-after-horizon.stdout"
    index=$((index + 1))
    logrun "d04-4-positive-p$index" compose exec -T python_consumer python /app/actors/python_boundary.py positive "p$index"
  done
  logrun d04-4-receiver compose exec -T receiver cat /data/arrivals.jsonl
  logrun d04-4-events compose exec -T service cat /data/guard-events.jsonl
  logrun d04-4-sdk compose exec -T service cat /data/sdk-retry-observations.jsonl
  logrun d04-4-receipts compose exec -T service python -c \
    'import json,sqlite3; d=sqlite3.connect("/data/store.sqlite"); [print(json.dumps({"attempt_id":a,"submission_id":s,"receipt":json.loads(r)})) for a,s,r in d.execute("select attempt_id,submission_id,receipt from guard_dispatches order by rowid")]'
  logrun d04-4-store compose exec -T service python -c \
    'import json,sqlite3; d=sqlite3.connect("/data/store.sqlite"); [print(json.dumps({"attempt_id":r["attempt_id"],"step_id":r["work_key"]["step_id"],"submission_state":r["submission_state"],"terminal_code":(r.get("terminal_failure") or {}).get("code")})) for (v,) in d.execute("select record from submissions order by rowid") for r in [json.loads(v)]]; print(json.dumps({"usage_revisions":d.execute("select count(*) from usage_revisions").fetchone()[0]}))'
  logrun d04-4-verify "$python_tool" -I -B "$root/tests/gateway_integration/verify_boundary.py" errors "$run_dir"
  logrun forced-second-transport-control compose exec -T service python -B /app/gateway/test_guard.py GuardTests.test_valid_final_request_commits_before_one_lower_send -q

  # D04-5: a held receiver response occupies the selected real HTTPX/httpcore pool.
  logrun d04-5-service-up compose up -d service_wait
  wait_started=1
  logrun d04-5-readiness compose exec -T python_consumer python -c \
    'import os,time,urllib.request,urllib.error
u=urllib.request.Request("http://127.0.0.1:8771/v1/capabilities",headers={"Duranki-Contract-Version":"0.2","Authorization":"Bearer "+os.environ["DURANKI_DEV_TOKEN"]})
for i in range(60):
 try:
  with urllib.request.urlopen(u,timeout=1) as response:
   assert response.status==200
   assert response.headers.get("Duranki-Contract-Version")=="0.2"
   print(response.status)
  break
 except urllib.error.HTTPError:
  raise
 except (urllib.error.URLError,TimeoutError,ConnectionError):
  if i==59: raise
  time.sleep(.1)'
  logrun d04-5-positive-before compose exec -T -e DURANKI_SERVICE_URL=http://127.0.0.1:8771 \
    python_consumer python /app/actors/python_boundary.py positive wait_before
  logrun d04-5-hold-stale compose exec -T -e DURANKI_SERVICE_URL=http://127.0.0.1:8771 \
    python_consumer python /app/actors/python_wait.py hold hold_stale
  logrun d04-5-hold-stale-sid "$python_tool" -I -B -c \
    'import json,sys; print(json.load(open(sys.argv[1]))["submission_id"])' "$run_dir/d04-5-hold-stale.stdout"
  logrun d04-5-hold-entered compose exec -T receiver python -c \
    'import json,pathlib,time; p=pathlib.Path("/data/controls.jsonl");
for i in range(100):
 r=[json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []
 if sum(x["event"]=="hold_entered_after_receiver_arrival" for x in r)>=1: print(json.dumps(r[-1])); break
 time.sleep(.05)
else: raise AssertionError("receiver hold not entered")'
  logrun d04-5-queued-stale compose exec -T -e DURANKI_SERVICE_URL=http://127.0.0.1:8771 \
    python_consumer python /app/actors/python_wait.py queued queued_stale
  logrun d04-5-queued-stale-sid "$python_tool" -I -B -c \
    'import json,sys; print(json.load(open(sys.argv[1]))["submission_id"])' "$run_dir/d04-5-queued-stale.stdout"
  local queued_sid
  queued_sid=$(<"$run_dir/d04-5-queued-stale-sid.stdout")
  logrun d04-5-real-pool-queued compose exec -T service_wait python -c \
    'import json,pathlib,sqlite3,sys,time; d=sqlite3.connect("/data/store.sqlite"); row=d.execute("select record from submissions where submission_id=?",(sys.argv[1],)).fetchone(); assert row; aid=json.loads(row[0])["attempt_id"]; p=pathlib.Path("/data/pool-observations.jsonl");
for i in range(200):
 r=[json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []
 if any(x["attempt_id"]==aid and x["event"]=="queued_in_selected_httpcore_pool" for x in r): print(json.dumps({"attempt_id":aid,"pool_queued":True})); break
 time.sleep(.02)
else: raise AssertionError("selected request never queued in httpcore pool")' "$queued_sid"
  logrun d04-5-authority-revoked compose exec -T service_wait python -c \
    'import json,pathlib,time; pathlib.Path("/data/authority-state").write_text("revoked"); row={"event":"authority_revoked_after_pool_queue","monotonic_ns":time.monotonic_ns()}; p=pathlib.Path("/data/authority-events.jsonl"); p.write_text(json.dumps(row)+"\n"); print(json.dumps(row))'
  logrun d04-5-release-stale compose exec -T netns python -c \
    'import urllib.request; print(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8766/control/release",data=b"",method="POST"),timeout=3).status)'
  local hold_sid
  hold_sid=$(<"$run_dir/d04-5-hold-stale-sid.stdout")
  logrun d04-5-hold-status compose exec -T -e DURANKI_SERVICE_URL=http://127.0.0.1:8771 \
    python_consumer python /app/actors/python_wait.py status "$hold_sid"
  logrun d04-5-queued-status compose exec -T -e DURANKI_SERVICE_URL=http://127.0.0.1:8771 \
    python_consumer python /app/actors/python_wait.py status "$queued_sid"
  logrun d04-5-stale-before-horizon compose exec -T receiver cat /data/arrivals.jsonl
  logrun d04-5-stale-horizon "$python_tool" -I -B -c \
    'import time; start=time.monotonic(); time.sleep(5.2); print(round((time.monotonic()-start)*1000))'
  logrun d04-5-stale-after-horizon compose exec -T receiver cat /data/arrivals.jsonl
  logrun d04-5-stale-no-late-send cmp "$run_dir/d04-5-stale-before-horizon.stdout" "$run_dir/d04-5-stale-after-horizon.stdout"
  logrun d04-5-authority-active compose exec -T service_wait python -c \
    'import json,pathlib,time; pathlib.Path("/data/authority-state").write_text("active"); row={"event":"authority_restored","monotonic_ns":time.monotonic_ns()}; p=pathlib.Path("/data/authority-events.jsonl"); p.write_text(p.read_text()+json.dumps(row)+"\n"); print(json.dumps(row))'
  logrun d04-5-positive-after-stale compose exec -T -e DURANKI_SERVICE_URL=http://127.0.0.1:8771 \
    python_consumer python /app/actors/python_boundary.py positive wait_after_stale

  # Actual ContextVar swap while a distinct authenticated context is in flight.
  logrun d04-5-hold-swap compose exec -T -e DURANKI_SERVICE_URL=http://127.0.0.1:8771 \
    python_consumer python /app/actors/python_wait.py hold hold_swap
  logrun d04-5-hold-swap-sid "$python_tool" -I -B -c \
    'import json,sys; print(json.load(open(sys.argv[1]))["submission_id"])' "$run_dir/d04-5-hold-swap.stdout"
  logrun d04-5-second-hold-entered compose exec -T receiver python -c \
    'import json,pathlib,time; p=pathlib.Path("/data/controls.jsonl");
for i in range(100):
 r=[json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []
 if sum(x["event"]=="hold_entered_after_receiver_arrival" for x in r)>=2: print(json.dumps(r[-1])); break
 time.sleep(.05)
else: raise AssertionError("second receiver hold not entered")'
  logrun d04-5-swapped-context compose exec -T -e DURANKI_SERVICE_URL=http://127.0.0.1:8771 \
    python_consumer python /app/actors/python_wait.py swapped
  logrun d04-5-release-swap compose exec -T netns python -c \
    'import urllib.request; print(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8766/control/release",data=b"",method="POST"),timeout=3).status)'
  local swap_hold_sid
  swap_hold_sid=$(<"$run_dir/d04-5-hold-swap-sid.stdout")
  logrun d04-5-swap-hold-status compose exec -T -e DURANKI_SERVICE_URL=http://127.0.0.1:8771 \
    python_consumer python /app/actors/python_wait.py status "$swap_hold_sid"
  logrun d04-5-swap-before-horizon compose exec -T receiver cat /data/arrivals.jsonl
  logrun d04-5-swap-horizon "$python_tool" -I -B -c \
    'import time; start=time.monotonic(); time.sleep(5.2); print(round((time.monotonic()-start)*1000))'
  logrun d04-5-swap-after-horizon compose exec -T receiver cat /data/arrivals.jsonl
  logrun d04-5-swap-no-late-send cmp "$run_dir/d04-5-swap-before-horizon.stdout" "$run_dir/d04-5-swap-after-horizon.stdout"
  logrun d04-5-positive-after-swap compose exec -T -e DURANKI_SERVICE_URL=http://127.0.0.1:8771 \
    python_consumer python /app/actors/python_boundary.py positive wait_after_swap
  logrun d04-5-overlap-contexts compose exec -T -e DURANKI_SERVICE_URL=http://127.0.0.1:8771 \
    python_consumer python /app/actors/python_wait.py overlap
  logrun d04-5-receiver compose exec -T receiver cat /data/arrivals.jsonl
  logrun d04-5-events compose exec -T service_wait cat /data/guard-events.jsonl
  logrun d04-5-pool compose exec -T service_wait cat /data/pool-observations.jsonl
  logrun d04-5-lower-trace compose exec -T service_wait cat /data/lower-trace.jsonl
  logrun d04-5-sdk compose exec -T service_wait cat /data/sdk-retry-observations.jsonl
  logrun d04-5-authority-events compose exec -T service_wait cat /data/authority-events.jsonl
  logrun d04-5-receipts compose exec -T service_wait python -c \
    'import json,sqlite3; d=sqlite3.connect("/data/store.sqlite"); [print(json.dumps({"attempt_id":a,"submission_id":s,"receipt":json.loads(r)})) for a,s,r in d.execute("select attempt_id,submission_id,receipt from guard_dispatches order by rowid")]; [print(json.dumps({"attempt_id":r["attempt_id"],"context_id":r["context_id"],"step_id":r["work_key"]["step_id"],"submission_state":r["submission_state"]})) for (v,) in d.execute("select record from submissions order by rowid") for r in [json.loads(v)]]'
  logrun d04-5-verify "$python_tool" -I -B "$root/tests/gateway_integration/verify_boundary.py" wait "$run_dir"

  # D04-6: compare actual handler restrictions with an explicitly labelled raw client.
  logrun d04-6-positive-before compose exec -T python_consumer python /app/actors/python_boundary.py positive bypass_before
  logrun d04-6-alt-handler-startup compose exec -T service python -B /app/gateway/test_alt_handler.py
  logrun d04-6-service-up compose up -d service_probe
  probe_started=1
  logrun d04-6-readiness compose exec -T python_consumer python -c \
    'import os,time,urllib.request,urllib.error
u=urllib.request.Request("http://127.0.0.1:8772/v1/capabilities",headers={"Duranki-Contract-Version":"0.2","Authorization":"Bearer "+os.environ["DURANKI_DEV_TOKEN"]})
for i in range(60):
 try:
  with urllib.request.urlopen(u,timeout=1) as response:
   assert response.status==200
   assert response.headers.get("Duranki-Contract-Version")=="0.2"
   print(response.status)
  break
 except urllib.error.HTTPError:
  raise
 except (urllib.error.URLError,TimeoutError,ConnectionError):
  if i==59: raise
  time.sleep(.1)'
  logrun d04-6-probes compose exec -T service_probe cat /data/bypass-probes.json
  logrun d04-6-before-horizon compose exec -T receiver cat /data/arrivals.jsonl
  logrun d04-6-horizon "$python_tool" -I -B -c \
    'import time; start=time.monotonic(); time.sleep(5.2); print(round((time.monotonic()-start)*1000))'
  logrun d04-6-after-horizon compose exec -T receiver cat /data/arrivals.jsonl
  logrun d04-6-no-late-send cmp "$run_dir/d04-6-before-horizon.stdout" "$run_dir/d04-6-after-horizon.stdout"
  logrun d04-6-positive-after compose exec -T python_consumer python /app/actors/python_boundary.py positive bypass_after
  logrun d04-6-receiver compose exec -T receiver cat /data/arrivals.jsonl
  logrun d04-6-verify "$python_tool" -I -B "$root/tests/gateway_integration/verify_boundary.py" bypass "$run_dir"
}
