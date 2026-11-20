"""Host custody, no-send gate, and one-use release for CT02-02b only."""

from __future__ import annotations

from datetime import timedelta
from hashlib import sha256
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dev12_completion_preflight import mounted_source_identity
from dev12_completion_source_custody import source_files
from dev12_ct02b_supplement import (
    ADJUDICATION_SHA,
    ALLOC,
    BUDGET,
    CAMPAIGN,
    CASE,
    EXPIRY,
    GENERATION,
    ORIGINAL,
    OWNER,
    PREDECESSOR_PACKET_SHA,
    ROOT_BASENAME,
    STEP,
    book_legacy,
    digest,
    durable_json,
    now,
    original_snapshot,
    release_allocation,
    utc,
    verify_legacy,
)

REPO = Path(__file__).resolve().parents[2]
SERVICE_IMAGE = "sha256:9a4e020902e2b1b60433036d655e7361e800a9dbc34008123d2ab3208f324e33"
NODE_IMAGE = "sha256:517e1b65b0e7e17377720978f1e7756318d17f57df8dce51d79e717c10cbf1cf"
WHEEL_SHA = "955b15582de0739377a1f1206a686283ba3b8d4b39212ef36d3f02baf63210c0"
TARBALL_SHA = "cfe563b1c50a597e6d65876432436b9cf9cb6d9bfeb22dee80520b90a69ac52d"
PACKAGE_SHA = "880eb1c3ea47440682719d4550d5cf673ada129758097927f7582ea3a307df6c"
WORKER = "ezllmrouter-dev12-ct02b-supp01-worker"
SERVICE = "ezllmrouter-dev12-ct02b-supp01-service"
VOLUME = "ezllmrouter-dev12-ct02b-supp01-link"


def call(*args, check=True, timeout=30):
    return subprocess.run(
        args, cwd=REPO, capture_output=True, text=True, check=check, timeout=timeout
    )


def git(*args):
    return call("git", *args).stdout.strip()


def read_plan(review):
    path = review / "PLAN.json"
    plan = json.loads(path.read_bytes())
    if (
        plan["kind"] != "ct02b_one_case_plan_v1"
        or plan["target_root_basename"] != ROOT_BASENAME
        or plan["case_id"] != CASE
        or plan["source_commit"] != git("rev-parse", "HEAD")
        or plan["source_tree"] != git("rev-parse", "HEAD^{tree}")
        or plan["mounted_source_identity"] != mounted_source_identity()
        or plan["original_expiry"] != EXPIRY
    ):
        raise AssertionError("frozen one-case plan/source differs")
    return plan


def prepare(review, original, predecessor, supplied_package, owner_start, corrected):
    if (
        review.exists()
        or (review.parent / ROOT_BASENAME).exists()
        or review.parent.name != "dev12-a2-a4-completion02-20261026-01"
    ):
        raise ValueError("fresh approved review root and unused fixed target required")
    if (
        git("rev-parse", "--abbrev-ref", "HEAD") != "dev12/operation-contract"
        or git("remote", "get-url", "origin") != "git@github.com:33fg/ezllmrouter.git"
        or git("status", "--porcelain", "--untracked-files=no")
    ):
        raise AssertionError("committed approved feature source required")
    if digest(supplied_package.read_bytes()) != PACKAGE_SHA:
        raise AssertionError("owner review package differs")
    if (
        digest(owner_start.read_bytes())
        != "35d4bae67d51536b71f05f5c1376bad64f5abdb5be7538441be1653c369331e3"
    ):
        raise AssertionError("owner forwarding START differs")
    predecessor_zip = (
        predecessor.parent / "dev12-completion02-continue03-review-a49926e-20261027.zip"
    )
    if digest(predecessor_zip.read_bytes()) != PREDECESSOR_PACKET_SHA:
        raise AssertionError("exact predecessor packet differs")
    adjudication = REPO / "docs/development/dev-12/LEGACY-ALLOCATION-ADJUDICATION-01.json"
    snapshot = verify_legacy(adjudication, predecessor, original)
    with ZipFile(supplied_package) as z:
        instruction = z.read("EZLLMROUTER-DEV12-COMPLETION-02-CONTINUE-04.md")
        if (
            z.read("EZLLMROUTER-DEV12-COMPLETION-02-CONTINUE-04-START.txt")
            != owner_start.read_bytes()
            or z.read("LEGACY-ALLOCATION-ADJUDICATION-01.json") != adjudication.read_bytes()
        ):
            raise AssertionError("owner adoption and adjudication package bytes differ")
    if now() >= utc(EXPIRY) - timedelta(minutes=25):
        raise PermissionError("insufficient original deadline before source preparation")
    packages = {
        "python_wheel": (
            corrected / "cognitivedynamics_ezllmrouter_client-0.3.0-py3-none-any.whl",
            WHEEL_SHA,
        ),
        "js_tarball": (corrected / "cognitivedynamics-ezllmrouter-client-0.3.0.tgz", TARBALL_SHA),
    }
    for name, (path, expected) in packages.items():
        if not path.is_file() or path.is_symlink() or digest(path.read_bytes()) != expected:
            raise AssertionError("corrected installed artifact differs: " + name)
    review.mkdir()
    (review / "packages").mkdir()
    for path, _expected in packages.values():
        shutil.copyfile(path, review / "packages" / path.name)
    shutil.copyfile(adjudication, review / adjudication.name)
    (review / "ADOPTED-INSTRUCTION.md").write_bytes(instruction)
    (review / "OWNER-START.txt").write_bytes(owner_start.read_bytes())
    archive = subprocess.check_output(
        ("git", "archive", "--format=tar", "--prefix=source/", "HEAD"), cwd=REPO
    )
    (review / "source.tar").write_bytes(archive)
    selected, source_identity, rows = source_files(REPO, git("rev-parse", "HEAD"))
    if source_identity != mounted_source_identity():
        raise AssertionError("exact Git source differs from mounted source")
    durable_json(
        review / "SOURCE-FILES.json",
        {
            "kind": "ct02b_exact_mounted_source_v1",
            "source_commit": git("rev-parse", "HEAD"),
            "source_tree": git("rev-parse", "HEAD^{tree}"),
            "mounted_source_identity": source_identity,
            "files": rows,
            "source_tar_sha256": digest(archive),
        },
    )
    plan = {
        "kind": "ct02b_one_case_plan_v1",
        "case_id": CASE,
        "target_root_basename": ROOT_BASENAME,
        "source_commit": git("rev-parse", "HEAD"),
        "source_tree": git("rev-parse", "HEAD^{tree}"),
        "mounted_source_identity": source_identity,
        "adopted_instruction_sha256": digest(instruction),
        "owner_forwarding_sha256": digest(owner_start.read_bytes()),
        "review_package_sha256": PACKAGE_SHA,
        "predecessor_packet_sha256": PREDECESSOR_PACKET_SHA,
        "adjudication_sha256": ADJUDICATION_SHA,
        "original_expiry": EXPIRY,
        "original_file_sha256": snapshot["file_sha256"],
        "work_selector": {
            "task_id": "task.demo",
            "step_id": STEP,
            "step_revision": 1,
            "execution_generation": GENERATION,
        },
        "contenders": [{"text": "Sky"}, {"text": "River"}],
        "envelope": {
            "campaign_id": CAMPAIGN,
            "budget_account_id": BUDGET,
            "financial_owner_id": OWNER,
            "currency": "USD",
            "max_admissions": 1,
            "max_possible_sends": 1,
            "max_inflight": 1,
            "ceiling_decimal": "0.010000000",
            "absolute_expiry": EXPIRY,
            "service_network_mode": "bridge",
            "real_provider_calls": 0,
        },
        "artifacts": [
            {"kind": name, "path": "/review/packages/" + path.name, "sha256": expected}
            for name, (path, expected) in packages.items()
        ],
        "frozen_images": {"service": SERVICE_IMAGE, "node": NODE_IMAGE},
    }
    plan_sha = durable_json(review / "PLAN.json", plan)
    booked = book_legacy(
        review / "capacity.sqlite", review / adjudication.name, predecessor, original
    )
    durable_json(review / "LEGACY-BOOKING.json", booked)
    durable_json(
        review / "PREPARE.json",
        {
            "status": "PASS",
            "kind": "ct02b_no_target_prepare_v1",
            "source_commit": plan["source_commit"],
            "source_tree": plan["source_tree"],
            "plan_sha256": plan_sha,
            "adopted_instruction_sha256": plan["adopted_instruction_sha256"],
            "legacy_booking_decision": booked["decision"],
            "historical_conservative_consumption_decimal": "0.044000030",
            "original_mixed_admissions": 124,
            "original_mixed_possible_send_slots": 109,
            "new_admissions_or_sends": 0,
            "real_provider_calls": 0,
        },
    )
    return {
        "status": "PASS",
        "plan_sha256": plan_sha,
        "source_commit": plan["source_commit"],
        "mounted_source_identity": source_identity,
        "legacy_booking": booked["decision"],
    }


def no_send_gate(review, original, predecessor):
    plan = read_plan(review)
    if (review.parent / ROOT_BASENAME).exists():
        raise PermissionError("fixed supplemental target root already exists")
    if (
        digest((review / "source.tar").read_bytes())
        != json.loads((review / "SOURCE-FILES.json").read_bytes())["source_tar_sha256"]
    ):
        raise AssertionError("frozen source snapshot differs")
    snapshot = verify_legacy(
        review / "LEGACY-ALLOCATION-ADJUDICATION-01.json", predecessor, original
    )
    if snapshot["file_sha256"] != plan["original_file_sha256"]:
        raise AssertionError("original paused target changed")
    if now() >= utc(EXPIRY) - timedelta(minutes=20):
        raise PermissionError("insufficient original absolute release window")
    with __import__("sqlite3").connect(
        f"file:{review / 'capacity.sqlite'}?mode=ro", uri=True
    ) as db:
        rows = {
            row[0]: json.loads(row[1])
            for row in db.execute("SELECT allocation_key,record FROM allocations")
        }
    legacy = next(
        (row for row in rows.values() if row["kind"] == "historical_conservative_capacity_v1"), None
    )
    if (
        len(rows) != 1
        or legacy is None
        or legacy["historical_conservative_consumption_decimal"] != "0.044000030"
    ):
        raise AssertionError("single historical booking differs or release already consumed")
    for name, expected in (("service", SERVICE_IMAGE), ("node", NODE_IMAGE)):
        inspected = call(
            "docker", "image", "inspect", expected, "--format", "{{.Id}}"
        ).stdout.strip()
        if inspected != expected:
            raise AssertionError("frozen " + name + " image differs")
    worker_import = call(
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "-v",
        str(REPO) + ":/workspace:ro",
        "-w",
        "/workspace",
        SERVICE_IMAGE,
        "python",
        "-B",
        "-c",
        "import choice_b_wire; print(choice_b_wire.__file__)",
    )
    if worker_import.stdout.strip() != "/app/gateway/choice_b_wire.py":
        raise AssertionError("frozen worker wire import differs")
    for name in (WORKER, SERVICE):
        if call(
            "docker", "ps", "-a", "--filter", "name=^/" + name + "$", "--format", "{{.Names}}"
        ).stdout.strip():
            raise AssertionError("fixed Docker container namespace already used")
    if call(
        "docker", "volume", "ls", "--filter", "name=^" + VOLUME + "$", "--format", "{{.Name}}"
    ).stdout.strip():
        raise AssertionError("fixed Docker volume namespace already used")
    if snapshot["campaign"]["pause_reasons"] != ["authority"]:
        raise AssertionError("original terminal pause differs")
    owner_profile = call(
        "docker",
        "ps",
        "--filter",
        "name=ezllmrouter-dev06-local-",
        "--format",
        "{{.ID}} {{.Names}} {{.Image}}",
    ).stdout.splitlines()
    return {
        "status": "PASS",
        "kind": "ct02b_no_send_gate_v1",
        "checked_at": now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_commit": plan["source_commit"],
        "source_tree": plan["source_tree"],
        "mounted_source_identity": plan["mounted_source_identity"],
        "plan_sha256": digest((review / "PLAN.json").read_bytes()),
        "original_file_sha256": snapshot["file_sha256"],
        "historical_conservative_consumption_decimal": "0.044000030",
        "prospective_supplemental_allocation_decimal": "0.010000000",
        "combined_max_conservative_consumption_decimal": "0.054000030",
        "mixed_admissions_before": 124,
        "mixed_possible_send_slots_before": 109,
        "campaign_paused": True,
        "running_owner_profile_containers": owner_profile,
        "new_admissions_or_sends": 0,
    }


def release(review, original, predecessor):
    gate = no_send_gate(review, original, predecessor)
    durable_json(review / "NO-SEND-GATE.json", gate)
    plan = read_plan(review)
    allocation = release_allocation(
        review / "capacity.sqlite",
        review / "LEGACY-ALLOCATION-ADJUDICATION-01.json",
        predecessor,
        original,
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
            "kind": "ct02b_single_use_target_start_v1",
            "resource_started_at": started_at,
            "original_expiry": EXPIRY,
            "plan_sha256": gate["plan_sha256"],
            "allocation_sha256": digest((review / "SUPPLEMENTAL-ALLOCATION.json").read_bytes()),
            "worker_container": WORKER,
            "service_container": SERVICE,
            "worker_volume": VOLUME,
        },
    )
    commands = []

    def execute(*args, timeout=30):
        row = {"argv": list(args), "started_at": now().strftime("%Y-%m-%dT%H:%M:%SZ")}
        commands.append(row)
        try:
            result = call(*args, timeout=timeout)
            row["exit"] = result.returncode
            row["stdout"] = result.stdout[-2000:]
            row["stderr"] = result.stderr[-2000:]
            return result
        except BaseException as exc:
            row["error"] = type(exc).__name__ + ": " + str(exc)[:500]
            raise

    result = None
    error = None
    try:
        execute("docker", "volume", "create", VOLUME)
        execute(
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
        execute(
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
            ready = call(
                "docker",
                "exec",
                WORKER,
                "test",
                "-S",
                "/link/dev12-worker.sock",
                check=False,
                timeout=5,
            )
            if ready.returncode == 0:
                break
            if time.monotonic() >= deadline_mono - 120:
                raise TimeoutError("worker readiness consumed target window")
            time.sleep(0.1)
        else:
            raise TimeoutError("isolated worker socket absent")
        command = (
            "docker",
            "run",
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
            "tests/gateway_integration/dev12_ct02b_service.py",
            "/review/PLAN.json",
            "/target",
            "/original",
            "/review/capacity.sqlite",
        )
        remaining = max(1, int(deadline_mono - time.monotonic()))
        result = execute(*command, timeout=remaining)
        (target / "service.stdout").write_text(result.stdout)
        (target / "service.stderr").write_text(result.stderr)
    except BaseException as exc:
        error = {"type": type(exc).__name__, "message": str(exc)[:1000]}
    finally:
        for name in (SERVICE, WORKER):
            stopped = call("docker", "stop", "--time", "3", name, check=False, timeout=10)
            commands.append(
                {
                    "argv": ["docker", "stop", name],
                    "exit": stopped.returncode,
                    "stderr": stopped.stderr[-1000:],
                }
            )
        worker_log = call("docker", "logs", WORKER, check=False, timeout=10)
        (target / "worker.stdout").write_text(worker_log.stdout)
        (target / "worker.stderr").write_text(worker_log.stderr)
        for name in (SERVICE, WORKER):
            call("docker", "rm", name, check=False, timeout=10)
        call("docker", "volume", "rm", VOLUME, check=False, timeout=10)
        durable_json(target / "HOST-COMMANDS.json", commands)
    after = original_snapshot(original)
    same_original = after["file_sha256"] == plan["original_file_sha256"]
    owner_profile_after = call(
        "docker",
        "ps",
        "--filter",
        "name=ezllmrouter-dev06-local-",
        "--format",
        "{{.ID}} {{.Names}} {{.Image}}",
    ).stdout.splitlines()
    final = {
        "kind": "ct02b_host_one_use_release_v1",
        "status": "PASS"
        if result is not None
        and result.returncode == 0
        and error is None
        and same_original
        and owner_profile_after == gate["running_owner_profile_containers"]
        else "FAIL",
        "case_id": CASE,
        "source_commit": plan["source_commit"],
        "service_exit": result.returncode if result is not None else None,
        "error": error,
        "original_unchanged": same_original,
        "running_owner_profile_containers_before": gate["running_owner_profile_containers"],
        "running_owner_profile_containers_after": owner_profile_after,
        "target_root": str(target),
        "started_at": started_at,
        "finished_at": now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "new_target_releases_permitted": 0,
        "real_provider_calls": 0,
        "real_spend": 0,
    }
    durable_json(review / "HOST-FINAL.json", final)
    return final


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "preflight", "release"))
    parser.add_argument("review", type=Path)
    parser.add_argument("original", type=Path)
    parser.add_argument("predecessor", type=Path)
    parser.add_argument("--package", type=Path)
    parser.add_argument("--start", type=Path)
    parser.add_argument("--corrected", type=Path)
    args = parser.parse_args()
    if args.mode == "prepare":
        if any(value is None for value in (args.package, args.start, args.corrected)):
            parser.error("prepare requires exact package, START and corrected artifacts")
        value = prepare(
            args.review, args.original, args.predecessor, args.package, args.start, args.corrected
        )
    elif args.mode == "preflight":
        value = no_send_gate(args.review, args.original, args.predecessor)
    else:
        value = release(args.review, args.original, args.predecessor)
    print(json.dumps(value, sort_keys=True, indent=2))
    if value["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
