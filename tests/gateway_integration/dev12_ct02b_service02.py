"""Disposable supp02 service: start ready, await one durable pair release."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import socket
import ssl
import sys
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dev12_completion_preflight import mounted_source_identity
from dev12_completion_runner import CompletionRuntime, append_durable
from dev12_ct02b_supp02 import (
    CAMPAIGN,
    CASE,
    EXPIRY,
    digest,
    durable_json,
    original_snapshot,
    run_single_target,
    supplemental_limits,
    utc,
    now,
    verify_started_limits,
)


def main(plan_path, target_root, original_root, capacity_path):
    plan = json.loads(plan_path.read_bytes())
    start_path = target_root / "TARGET-START.json"
    started = json.loads(start_path.read_bytes())
    finite = {"resource_started_at": started["resource_started_at"], "original_expiry": EXPIRY}
    supplemental_limits(plan, finite)
    if mounted_source_identity() != plan["mounted_source_identity"]:
        raise AssertionError("mounted source differs from frozen host receipt")
    if digest(plan_path.read_bytes()) != started["plan_sha256"]:
        raise AssertionError("target plan differs from single-use release")
    with __import__("sqlite3").connect(f"file:{capacity_path}?mode=ro", uri=True) as db:
        rows = {
            row[0]: json.loads(row[1])
            for row in db.execute("SELECT allocation_key,record FROM allocations")
        }
    allocation = rows.get(CAMPAIGN + "|single-use-release")
    if (
        allocation is None
        or allocation["plan_sha256"] != started["plan_sha256"]
        or allocation["source_tree"] != plan["source_tree"]
        or allocation["adopted_instruction_sha256"] != plan["adopted_instruction_sha256"]
    ):
        raise AssertionError("committed single-use allocation differs")
    before = original_snapshot(original_root)
    if before["file_sha256"] != plan["original_file_sha256"]:
        raise AssertionError("original paused campaign changed before target")
    if (target_root / "campaign.sqlite").exists() or (target_root / "case-journal.jsonl").exists():
        raise AssertionError("target campaign or journal already exists")
    for name in ("receiver.jsonl", "receiver-receipts.jsonl", "guard.jsonl"):
        (target_root / name).touch(exist_ok=False)
    runtime = CompletionRuntime(plan, target_root, {})
    error = None
    result = None
    try:
        runtime.start(finite_scope=finite)
        campaign = verify_started_limits(runtime.allowance.inspect(), finite)
        if (
            runtime.store.work_owner(
                {
                    "principal_id": "user.demo",
                    "task_id": "task.demo",
                    "step_id": "step.completion02.ct02.first_owner.supp02",
                    "step_revision": 1,
                    "execution_generation": "gen.ct02b.supp02",
                }
            )
            is not None
        ):
            raise AssertionError("work owner exists before pair release")
        tls = ssl.create_default_context(cafile=str(target_root / "cert.pem"))
        with socket.create_connection(("127.0.0.1", runtime.receiver_port), timeout=3) as raw:
            with tls.wrap_socket(raw, server_hostname="synthetic.invalid") as verified:
                peer = sha256(verified.getpeercert(binary_form=True)).hexdigest()
        durable_json(
            target_root / "SERVICE-READY.json",
            {
                "kind": "ct02b_supp02_service_ready_v1",
                "case_id": CASE,
                "plan_sha256": started["plan_sha256"],
                "campaign": campaign,
                "receiver_tls_peer_der_sha256": peer,
                "service_port": runtime.service_port,
                "receiver_port": runtime.receiver_port,
                "worker_socket": "/link/dev12-worker.sock",
                "no_submission_issued": True,
                "at_ns": time.time_ns(),
            },
        )
        while not (target_root / "PAIR-RELEASE.json").exists():
            if now() >= min(
                utc(EXPIRY),
                utc(campaign["expires_at"]),
                utc(started["resource_started_at"]) + __import__("datetime").timedelta(minutes=15),
            ):
                raise TimeoutError("pair release window ended before dispatch")
            time.sleep(0.1)
        release = json.loads((target_root / "PAIR-RELEASE.json").read_bytes())
        if (
            release
            != {
                "kind": "ct02b_supp02_pair_release_v1",
                "case_id": CASE,
                "plan_sha256": started["plan_sha256"],
                "ready_sha256": digest((target_root / "SERVICE-READY.json").read_bytes()),
            }
            or (target_root / "REQUEST-ISSUED-SKY.json").exists()
            or (target_root / "REQUEST-ISSUED-RIVER.json").exists()
        ):
            raise AssertionError("pair release marker or prior request differs")
        result = run_single_target(runtime, plan, finite)
    except BaseException as exc:
        error = {
            "type": type(exc).__name__,
            "message": str(exc)[:1000],
            "traceback": traceback.format_exc(limit=12)[-6000:],
        }
        try:
            append_durable(
                runtime.journal,
                {"kind": "ct02b_case_failure", "at_ns": time.time_ns(), "error": error},
            )
        except BaseException:
            pass
    finally:
        try:
            runtime.close()
        except BaseException as exc:
            error = error or {
                "type": type(exc).__name__,
                "message": "runtime close: " + str(exc)[:1000],
            }
    after = original_snapshot(original_root)
    unchanged = (
        before["file_sha256"] == after["file_sha256"]
        and before["campaign"] == after["campaign"]
        and before["counts"] == after["counts"]
    )
    final = {
        "kind": "ct02b_supplemental_service_final_v1",
        "status": "PASS" if error is None and unchanged and result is not None else "FAIL",
        "case_id": plan["case_id"],
        "campaign_id": CAMPAIGN,
        "original_unchanged": unchanged,
        "original_file_sha256": after["file_sha256"],
        "observed_case": result is not None,
        "error": error,
        "real_provider_calls": 0,
        "real_spend": 0,
    }
    raw = json.dumps(final, sort_keys=True, indent=2).encode() + b"\n"
    with (target_root / "SERVICE-FINAL.json").open("xb") as stream:
        stream.write(raw)
        stream.flush()
        __import__("os").fsync(stream.fileno())
    print(json.dumps(final, sort_keys=True), flush=True)
    return 0 if final["status"] == "PASS" else 1


if __name__ == "__main__":
    if len(sys.argv) != 5:
        raise SystemExit("plan, target root, original read-only root, capacity DB required")
    raise SystemExit(main(*(Path(value) for value in sys.argv[1:])))
