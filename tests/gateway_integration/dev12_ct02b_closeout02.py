"""Read-only supp02 failed-setup reconciliation; writes one safe receipt."""
from __future__ import annotations

from datetime import timedelta
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dev12_ct02b_host02 import SERVICE_IMAGE, WORKER, SERVICE, ROOT_BASENAME
from dev12_ct02b_host02_run import zero_primary
from dev12_ct02b_supp02 import CAMPAIGN, EXPIRY, digest, durable_json, now, original_snapshot, utc


def read(path):
    return json.loads(path.read_bytes())


def main(review, original):
    target = review.parent / ROOT_BASENAME
    plan = read(review / "PLAN.json")
    started = read(target / "TARGET-START.json")
    ready = read(target / "SERVICE-READY.json")
    setup = read(review / "SETUP-RESULT.json")
    if (setup["status"] != "FAIL" or setup["pair_released"] or
            (review / "SETUP-RESTART-USED.json").exists() or
            (review / "RESTART-READY.json").exists() or
            (target / "SERVICE-READY-RESTART.json").exists()):
        raise AssertionError("failed setup or unused restart differs")
    census = zero_primary(target)
    expiry = utc(census["campaign"]["expires_at"])
    if (expiry > now() or census["campaign"] != ready["campaign"] or
            expiry > utc(started["resource_started_at"]) + timedelta(minutes=15) or
            expiry > utc(EXPIRY)):
        raise AssertionError("finite allowance has not expired within fixed bounds")
    snapshot = original_snapshot(original)
    if snapshot["file_sha256"] != plan["original_file_sha256"]:
        raise AssertionError("original paused campaign changed")
    prior = read(review / "PRIOR-ALLOCATION-RECORDS.json")
    with sqlite3.connect(f"file:{review.parent / 'continue04-review' / 'capacity.sqlite'}?mode=ro",
                         uri=True) as db:
        rows = {key: json.loads(raw) for key, raw in db.execute(
            "SELECT allocation_key,record FROM allocations")}
    new = rows.get(CAMPAIGN + "|single-use-release")
    if (len(rows) != 3 or {key: rows[key] for key in prior} != prior or
            new != read(review / "SUPPLEMENTAL-ALLOCATION.json") or
            new["combined_max_conservative_consumption_decimal"] != "0.064000030" or
            new["max_reservation_decimal"] != "0.010000000"):
        raise AssertionError("append-once aggregate allocation differs")
    processes = {}
    for name in (WORKER, SERVICE):
        item = json.loads(subprocess.check_output(("docker", "inspect", name), text=True))[0]
        if item["Image"] != SERVICE_IMAGE or item["State"]["Running"] or \
                item["State"]["Pid"] != 0:
            raise AssertionError("owned setup process remains running")
        processes[name] = {"container_id": item["Id"], "running": False,
                           "pid": 0, "exit_code": item["State"]["ExitCode"]}
    owner = subprocess.check_output(("docker", "ps", "--filter",
        "name=ezllmrouter-dev06-local-", "--format", "{{.ID}} {{.Names}} {{.Image}}"),
        text=True).splitlines()
    gate = read(review / "NO-SEND-GATE.json")
    if owner != gate["running_owner_profile_containers"]:
        raise AssertionError("owner profile containers changed")
    safe_names = ("TARGET-START.json", "SERVICE-READY.json", "SETUP-COMMANDS.json",
                  "case-journal.jsonl", "release-identity.jsonl", "receiver.jsonl",
                  "receiver-receipts.jsonl", "guard.jsonl", "receiver.stderr")
    files = {name: {"bytes": (target / name).stat().st_size,
                    "sha256": digest((target / name).read_bytes())}
             for name in safe_names}
    result = {"kind": "ct02b_supp02_expired_no_pair_closeout_v1",
        "status": "OPEN_SETUP_FAILED_FINITE_ALLOWANCE_EXPIRED",
        "tested_source_commit": plan["source_commit"],
        "tested_source_tree": plan["source_tree"],
        "mounted_source_identity": plan["mounted_source_identity"],
        "first_resource_started_at": started["resource_started_at"],
        "finite_campaign_expires_at": census["campaign"]["expires_at"],
        "original_absolute_expiry": EXPIRY,
        "setup_failure": setup["error"],
        "service_reached_ready": True, "worker_ipc_and_receiver_tls_reached_ready": True,
        "setup_restarts_used": 0, "pair_release_committed": False,
        "request_issued_markers": 0,
        "supplemental_admissions": 0, "supplemental_possible_sends": 0,
        "supplemental_receiver_arrivals": 0,
        "primary_counts": census["counts"],
        "capacity_allocation_keys": sorted(rows),
        "combined_conservative_allocation_decimal": "0.064000030",
        "legacy_native_cost": None,
        "original_file_sha256": snapshot["file_sha256"],
        "original_campaign_pause_reasons": snapshot["campaign"]["pause_reasons"],
        "original_held_reservations": 3,
        "owner_profile_containers": owner,
        "owned_stopped_processes": processes,
        "safe_target_file_hashes": files,
        "real_provider_calls": 0, "real_spend": 0,
        "observed_at": now().strftime("%Y-%m-%dT%H:%M:%SZ")}
    durable_json(review / "CLOSEOUT.json", result)
    return result


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("review and original root required")
    print(json.dumps(main(*(Path(value) for value in sys.argv[1:])), sort_keys=True))
