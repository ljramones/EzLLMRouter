"""One supp02 setup and one durable pair release; no automatic target retry."""

from __future__ import annotations

from datetime import timedelta
import argparse
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dev12_ct02b_host02 import (
    REPO,
    SERVICE_IMAGE,
    NODE_IMAGE,
    WORKER,
    SERVICE,
    VOLUME,
    ROOT_BASENAME,
    call,
    no_send_gate,
    read_plan,
)
from dev12_ct02b_supp02 import (
    CAMPAIGN,
    CASE,
    EXPIRY,
    digest,
    durable_json,
    now,
    original_snapshot,
    release_allocation,
    utc,
)

IPC_PROBE = (
    "import socket; from choice_b_wire import send,receive; "
    "s=socket.socket(socket.AF_UNIX); s.settimeout(3); "
    "s.connect('/link/dev12-worker.sock'); "
    "send(s,{'kind':'prepare','request':{},'recipe':{}}); "
    "print(receive(s)); s.close()"
)


def record(commands, *argv, timeout=30, check=True):
    row = {"argv": list(argv), "at_ns": time.time_ns()}
    commands.append(row)
    try:
        result = call(*argv, timeout=timeout, check=False)
        row.update(
            exit=result.returncode, stdout=result.stdout[-4000:], stderr=result.stderr[-4000:]
        )
        if check and result.returncode:
            raise RuntimeError("command failed: " + " ".join(argv[:4]))
        return result
    except BaseException as exc:
        row["error"] = type(exc).__name__ + ": " + str(exc)[:500]
        if isinstance(exc, subprocess.TimeoutExpired):
            for field, raw in (("stdout", exc.stdout), ("stderr", exc.stderr)):
                row[field] = (
                    raw.decode(errors="replace") if isinstance(raw, bytes) else raw or ""
                )[-4000:]
        raise


def alive(name):
    result = call(
        "docker", "inspect", "--format", "{{.State.Running}} {{.Image}}", name, check=False
    )
    return result.returncode == 0 and result.stdout.strip() == "true " + SERVICE_IMAGE


def normalized_bind(raw):
    # Docker Desktop can expose the same host bind through /host_mnt and omit rw.
    if raw.startswith("/host_mnt/"):
        raw = raw[len("/host_mnt") :]
    if raw.count(":") == 1:
        raw += ":rw"
    return raw


def inspect_launch(name, target, review, original):
    item = json.loads(call("docker", "inspect", name).stdout)[0]
    worker = name == WORKER
    expected = (
        ["python", "-B", "tests/gateway_integration/dev12_worker.py"]
        if worker
        else [
            "python",
            "-I",
            "-B",
            "tests/gateway_integration/dev12_ct02b_service02.py",
            "/review/PLAN.json",
            "/target",
            "/original",
            "/capacity.sqlite",
        ]
    )
    mounts = {entry["Destination"]: entry for entry in item["Mounts"]}
    required = {"/workspace": str(REPO) + ":/workspace:ro", "/link": VOLUME + ":/link:rw"}
    if not worker:
        required.update(
            {
                "/target": str(target) + ":/target:rw",
                "/review": str(review) + ":/review:ro",
                "/original": str(original) + ":/original:ro",
                "/capacity.sqlite": str(review.parent / "continue04-review" / "capacity.sqlite")
                + ":/capacity.sqlite:ro",
            }
        )
    for destination in required:
        if destination not in mounts:
            raise AssertionError("actual Docker mount differs: " + destination)
    config = item["Config"]
    if (
        item["Image"] != SERVICE_IMAGE
        or config["Cmd"] != expected
        or config["WorkingDir"] != "/workspace"
        or config["User"] != "10001:10001"
        or item["HostConfig"]["NetworkMode"] != ("none" if worker else "bridge")
        or {normalized_bind(value) for value in item["HostConfig"]["Binds"]}
        != {normalized_bind(value) for value in required.values()}
        or item["State"]["Running"] is not True
    ):
        raise AssertionError("actual Docker launcher or running state differs")
    return {
        "container_id": item["Id"],
        "image": item["Image"],
        "command": config["Cmd"],
        "cwd": config["WorkingDir"],
        "uid": config["User"],
        "network": item["HostConfig"]["NetworkMode"],
        "mounts": {key: required[key] for key in sorted(required)},
    }


def zero_primary(target):
    for name in (
        "REQUEST-ISSUED-SKY.json",
        "REQUEST-ISSUED-RIVER.json",
        "PAIR-RELEASE.json",
        "RAW-HTTP.jsonl",
        "BOUNDARY.jsonl",
        "TRANSACTIONS.jsonl",
        "TARGET-OBSERVATION.json",
    ):
        if (target / name).exists():
            raise AssertionError("pair or HTTP evidence already exists: " + name)
    with sqlite3.connect(f"file:{target / 'campaign.sqlite'}?mode=ro", uri=True) as db:
        counts = {
            name: db.execute("SELECT COUNT(*) FROM " + name).fetchone()[0]
            for name in (
                "dev12_submissions",
                "dev12_campaign_attempts",
                "dev12_send_ownership",
                "dev12_usage_revisions",
                "work_key_owners",
            )
        }
        row = db.execute(
            "SELECT record FROM dev12_campaigns WHERE campaign_id=?", (CAMPAIGN,)
        ).fetchone()
    if row is None or any(counts.values()):
        raise AssertionError("setup created primary work")
    campaign = json.loads(row[0])
    if (
        campaign["attempt_count"] != 0
        or campaign["possible_send_count"] != 0
        or campaign["inflight_count"] != 0
        or campaign["paused"]
        or campaign["max_attempts"] != 1
        or campaign["max_concurrent"] != 1
        or campaign["ceiling_decimal"] != "0.010000000"
    ):
        raise AssertionError("durable finite setup differs")
    for name in ("receiver.jsonl", "receiver-receipts.jsonl", "guard.jsonl"):
        if (target / name).read_bytes():
            raise AssertionError("setup performed receiver or guard work")
    return {
        "counts": counts,
        "campaign": campaign,
        "receiver_bytes": 0,
        "guard_bytes": 0,
        "request_markers": 0,
    }


def setup(review, original, predecessor):
    gate = no_send_gate(review, original, predecessor)
    durable_json(review / "NO-SEND-GATE.json", gate)
    plan = read_plan(review)
    prior_review = review.parent / "continue04-review"
    prior = json.loads((review / "PRIOR-ALLOCATION-RECORDS.json").read_bytes())
    allocation = release_allocation(
        prior_review / "capacity.sqlite",
        prior,
        plan["original_file_sha256"],
        plan["source_commit"],
        plan["source_tree"],
        gate["plan_sha256"],
        plan["adopted_instruction_sha256"],
    )
    durable_json(review / "SUPPLEMENTAL-ALLOCATION.json", allocation)
    target = review.parent / ROOT_BASENAME
    target.mkdir()
    started_at = now().strftime("%Y-%m-%dT%H:%M:%SZ")
    deadline_mono = time.monotonic() + 900
    durable_json(
        target / "TARGET-START.json",
        {
            "kind": "ct02b_supp02_resource_start_v1",
            "resource_started_at": started_at,
            "monotonic_deadline": deadline_mono,
            "original_expiry": EXPIRY,
            "plan_sha256": gate["plan_sha256"],
            "allocation_sha256": digest((review / "SUPPLEMENTAL-ALLOCATION.json").read_bytes()),
            "worker_container": WORKER,
            "service_container": SERVICE,
            "worker_volume": VOLUME,
            "max_setup_restarts": 1,
        },
    )
    commands = []
    error = None
    ready = None
    try:
        record(commands, "docker", "volume", "create", VOLUME)
        record(
            commands,
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "-v",
            VOLUME + ":/link",
            SERVICE_IMAGE,
            "chown",
            "10001:10001",
            "/link",
        )
        record(
            commands,
            "docker",
            "run",
            "-d",
            "--name",
            WORKER,
            "--network",
            "none",
            "--user",
            "10001:10001",
            "-v",
            VOLUME + ":/link",
            "-v",
            str(REPO) + ":/workspace:ro",
            "-w",
            "/workspace",
            SERVICE_IMAGE,
            "python",
            "-B",
            "tests/gateway_integration/dev12_worker.py",
        )
        for _ in range(80):
            if (
                alive(WORKER)
                and call(
                    "docker", "exec", WORKER, "test", "-S", "/link/dev12-worker.sock", check=False
                ).returncode
                == 0
            ):
                break
            time.sleep(0.1)
        else:
            raise TimeoutError("worker socket/process absent")
        probe = record(
            commands,
            "docker",
            "exec",
            "--user",
            "10001:10001",
            WORKER,
            "python",
            "-B",
            "-c",
            IPC_PROBE,
        )
        if probe.stdout.strip() != "{'error_type': 'ValueError'}":
            raise AssertionError("non-sending worker IPC response differs")
        service_command = (
            "docker",
            "run",
            "-d",
            "--name",
            SERVICE,
            "--network",
            "bridge",
            "-v",
            str(REPO) + ":/workspace:ro",
            "-v",
            str(target) + ":/target",
            "-v",
            str(review) + ":/review:ro",
            "-v",
            str(original) + ":/original:ro",
            "-v",
            str(prior_review / "capacity.sqlite") + ":/capacity.sqlite:ro",
            "-v",
            VOLUME + ":/link",
            "-w",
            "/workspace",
            "-e",
            "DEV12_SERVICE_NETWORK_MODE=bridge",
            "-e",
            "DEV12_SERVICE_IMAGE_ID=" + SERVICE_IMAGE,
            "-e",
            "DEV12_NODE_IMAGE_ID=" + NODE_IMAGE,
            SERVICE_IMAGE,
            "python",
            "-I",
            "-B",
            "tests/gateway_integration/dev12_ct02b_service02.py",
            "/review/PLAN.json",
            "/target",
            "/original",
            "/capacity.sqlite",
        )
        record(commands, *service_command)
        for _ in range(150):
            if (target / "SERVICE-READY.json").is_file() and alive(SERVICE):
                break
            if not alive(SERVICE):
                raise RuntimeError("service exited before ready")
            time.sleep(0.1)
        else:
            raise TimeoutError("service did not reach held ready state")
        ready = json.loads((target / "SERVICE-READY.json").read_bytes())
        worker_launch = inspect_launch(WORKER, target, review, original)
        service_launch = inspect_launch(SERVICE, target, review, original)
        if (
            ready["plan_sha256"] != gate["plan_sha256"]
            or ready["campaign"]["campaign_id"] != CAMPAIGN
            or not ready["no_submission_issued"]
            or not alive(WORKER)
            or now() >= utc(started_at) + timedelta(minutes=15)
            or time.monotonic() >= deadline_mono
        ):
            raise AssertionError("ready identities or deadline differ")
        census = zero_primary(target)
        if original_snapshot(original)["file_sha256"] != plan["original_file_sha256"]:
            raise AssertionError("original changed during setup")
        durable_json(
            target / "SETUP-LAUNCH-IDENTITY.json",
            {
                "worker": worker_launch,
                "service": service_launch,
                "service_ready_sha256": digest((target / "SERVICE-READY.json").read_bytes()),
            },
        )
        durable_json(target / "SETUP-READY-CENSUS.json", census)
    except BaseException as exc:
        error = {"type": type(exc).__name__, "message": str(exc)[:1000]}
        for name in (SERVICE, WORKER):
            record(commands, "docker", "logs", name, check=False)
            record(commands, "docker", "stop", "--time", "3", name, check=False)
        # Keep the first setup and durable state for a separately checked restart.
    finally:
        durable_json(target / "SETUP-COMMANDS.json", commands)
        durable_json(
            review / "SETUP-RESULT.json",
            {
                "status": "READY" if error is None else "FAIL",
                "error": error,
                "service_ready": ready is not None,
                "pair_released": False,
                "at_ns": time.time_ns(),
            },
        )
    return {"status": "READY" if error is None else "FAIL", "error": error, "target": str(target)}


def release_pair(review, original):
    target = review.parent / ROOT_BASENAME
    plan = read_plan(review)
    started = json.loads((target / "TARGET-START.json").read_bytes())
    ready = json.loads((target / "SERVICE-READY.json").read_bytes())
    launch = json.loads((target / "SETUP-LAUNCH-IDENTITY.json").read_bytes())
    current_worker = inspect_launch(WORKER, target, review, original)
    current_service = inspect_launch(SERVICE, target, review, original)
    if (
        json.loads((review / "SETUP-RESULT.json").read_bytes())["status"] != "READY"
        or launch["worker"] != current_worker
        or launch["service"] != current_service
        or not alive(WORKER)
        or not alive(SERVICE)
        or now()
        >= min(
            utc(EXPIRY),
            utc(ready["campaign"]["expires_at"]),
            utc(started["resource_started_at"]) + timedelta(minutes=15),
        )
        or time.monotonic() >= started["monotonic_deadline"]
        or ready["plan_sha256"] != digest((review / "PLAN.json").read_bytes())
        or original_snapshot(original)["file_sha256"] != plan["original_file_sha256"]
    ):
        raise PermissionError("supp02 setup no longer eligible for pair release")
    before = zero_primary(target)
    durable_json(
        target / "PAIR-RELEASE.json",
        {
            "kind": "ct02b_supp02_pair_release_v1",
            "case_id": CASE,
            "plan_sha256": ready["plan_sha256"],
            "ready_sha256": digest((target / "SERVICE-READY.json").read_bytes()),
        },
    )
    commands = []
    error = None
    try:
        remaining = max(1, min(120, int(started["monotonic_deadline"] - time.monotonic())))
        outcome = record(commands, "docker", "wait", SERVICE, timeout=remaining, check=False)
        if outcome.returncode or outcome.stdout.strip() != "0":
            raise RuntimeError("service pair exited nonzero or timed out")
    except BaseException as exc:
        error = {"type": type(exc).__name__, "message": str(exc)[:1000]}
    finally:
        for name in (SERVICE, WORKER):
            row = record(commands, "docker", "logs", name, check=False)
            # Logs are retained with fixed distinct names.
            (target / ("service.stdout" if name == SERVICE else "worker.stdout")).write_text(
                row.stdout
            )
            (target / ("service.stderr" if name == SERVICE else "worker.stderr")).write_text(
                row.stderr
            )
            record(commands, "docker", "stop", "--time", "3", name, check=False)
            record(commands, "docker", "rm", name, check=False)
        record(commands, "docker", "volume", "rm", VOLUME, check=False)
        durable_json(target / "PAIR-HOST-COMMANDS.json", commands)
    after = original_snapshot(original)
    final = {
        "kind": "ct02b_supp02_host_final_v1",
        "status": "PASS"
        if error is None
        and (target / "TARGET-OBSERVATION.json").exists()
        and after["file_sha256"] == plan["original_file_sha256"]
        else "FAIL",
        "error": error,
        "before": before,
        "original_unchanged": after["file_sha256"] == plan["original_file_sha256"],
        "pair_release_committed": True,
        "new_pair_releases_permitted": 0,
        "at_ns": time.time_ns(),
        "real_provider_calls": 0,
        "real_spend": 0,
    }
    durable_json(review / "HOST-FINAL.json", final)
    return final


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("setup", "pair"))
    parser.add_argument("review", type=Path)
    parser.add_argument("original", type=Path)
    parser.add_argument("--predecessor", type=Path)
    args = parser.parse_args()
    if args.mode == "setup":
        if args.predecessor is None:
            parser.error("setup requires predecessor")
        result = setup(args.review, args.original, args.predecessor)
    else:
        result = release_pair(args.review, args.original)
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if result["status"] in ("READY", "PASS") else 1)
