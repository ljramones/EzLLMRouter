"""Disposable service entry point for the one approved CT02-02b HTTP pair."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dev12_completion_preflight import mounted_source_identity
from dev12_completion_runner import CompletionRuntime, append_durable
from dev12_ct02b_supplement import (
    CAMPAIGN, EXPIRY, ROOT_FILES, digest, original_snapshot,
    run_single_target, supplemental_limits,
)


def main(plan_path, target_root, original_root, capacity_path):
    plan = json.loads(plan_path.read_bytes())
    start_path = target_root / "TARGET-START.json"
    started = json.loads(start_path.read_bytes())
    finite = {"resource_started_at": started["resource_started_at"],
              "original_expiry": EXPIRY}
    supplemental_limits(plan, finite)
    if mounted_source_identity() != plan["mounted_source_identity"]:
        raise AssertionError("mounted source differs from frozen host receipt")
    if digest(plan_path.read_bytes()) != started["plan_sha256"]:
        raise AssertionError("target plan differs from single-use release")
    with __import__("sqlite3").connect(f"file:{capacity_path}?mode=ro", uri=True) as db:
        rows = {row[0]: json.loads(row[1]) for row in db.execute(
            "SELECT allocation_key,record FROM allocations")}
    allocation = rows.get(CAMPAIGN + "|single-use-release")
    if (allocation is None or allocation["plan_sha256"] != started["plan_sha256"] or
            allocation["source_tree"] != plan["source_tree"] or
            allocation["adopted_instruction_sha256"] !=
                plan["adopted_instruction_sha256"]):
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
        result = run_single_target(runtime, plan, finite)
    except BaseException as exc:
        error = {"type": type(exc).__name__, "message": str(exc)[:1000],
                 "traceback": traceback.format_exc(limit=12)[-6000:]}
        try:
            append_durable(runtime.journal, {"kind": "ct02b_case_failure",
                "at_ns": time.time_ns(), "error": error})
        except BaseException:
            pass
    finally:
        try:
            runtime.close()
        except BaseException as exc:
            error = error or {"type": type(exc).__name__,
                              "message": "runtime close: " + str(exc)[:1000]}
    after = original_snapshot(original_root)
    unchanged = before["file_sha256"] == after["file_sha256"] and \
        before["campaign"] == after["campaign"] and before["counts"] == after["counts"]
    final = {"kind": "ct02b_supplemental_service_final_v1",
        "status": "PASS" if error is None and unchanged and result is not None else "FAIL",
        "case_id": plan["case_id"], "campaign_id": CAMPAIGN,
        "original_unchanged": unchanged,
        "original_file_sha256": after["file_sha256"],
        "observed_case": result is not None,
        "error": error, "real_provider_calls": 0, "real_spend": 0}
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
