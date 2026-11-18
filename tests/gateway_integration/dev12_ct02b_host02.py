"""Host custody and no-send gate for the fixed CT02-02b supp02 scope."""
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
from dev12_ct02b_supp02 import (
    ADJUDICATION_SHA, ALLOC, BUDGET, CAMPAIGN, CASE, EXPIRY, GENERATION,
    ORIGINAL, OWNER, PREDECESSOR_PACKET_SHA, ROOT_BASENAME, STEP,
    digest, durable_json, now, original_snapshot,
    release_allocation, utc, verify_legacy,
)

REPO = Path(__file__).resolve().parents[2]
SERVICE_IMAGE = "sha256:9a4e020902e2b1b60433036d655e7361e800a9dbc34008123d2ab3208f324e33"
NODE_IMAGE = "sha256:517e1b65b0e7e17377720978f1e7756318d17f57df8dce51d79e717c10cbf1cf"
WHEEL_SHA = "955b15582de0739377a1f1206a686283ba3b8d4b39212ef36d3f02baf63210c0"
TARBALL_SHA = "cfe563b1c50a597e6d65876432436b9cf9cb6d9bfeb22dee80520b90a69ac52d"
PACKAGE_SHA = "5b96826e21909648384e21fe49508161fd6f4094c070bd1e2d7073ed73815954"
START_SHA = "c89a65a920f7b4383b880793153aba031fe226735c7b80bcc869cba993b67da0"
PRIOR_ZIP = "dev12-completion02-continue04-failed-b0661be-20261027.zip"
WORKER = "duranki-dev12-ct02b-supp02-worker"
SERVICE = "duranki-dev12-ct02b-supp02-service"
VOLUME = "duranki-dev12-ct02b-supp02-link"


def call(*args, check=True, timeout=30):
    return subprocess.run(args, cwd=REPO, capture_output=True, text=True,
                          check=check, timeout=timeout)


def git(*args):
    return call("git", *args).stdout.strip()


def read_plan(review):
    path = review / "PLAN.json"
    plan = json.loads(path.read_bytes())
    if (plan["kind"] != "ct02b_one_case_plan_v1" or
            plan["target_root_basename"] != ROOT_BASENAME or
            plan["case_id"] != CASE or
            plan["source_commit"] != git("rev-parse", "HEAD") or
            plan["source_tree"] != git("rev-parse", "HEAD^{tree}") or
            plan["mounted_source_identity"] != mounted_source_identity() or
            plan["original_expiry"] != EXPIRY):
        raise AssertionError("frozen one-case plan/source differs")
    return plan


def prepare(review, original, predecessor, supplied_package, owner_start, corrected):
    if (review.exists() or (review.parent / ROOT_BASENAME).exists() or
            review.parent.name != "dev12-a2-a4-completion02-20261026-01"):
        raise ValueError("fresh approved review root and unused fixed target required")
    if git("rev-parse", "--abbrev-ref", "HEAD") != "dev12/operation-contract" or \
            git("remote", "get-url", "origin") != "git@github.com:33fg/duranki.git" or \
            git("status", "--porcelain", "--untracked-files=no"):
        raise AssertionError("committed approved feature source required")
    if digest(supplied_package.read_bytes()) != PACKAGE_SHA:
        raise AssertionError("owner review package differs")
    if digest(owner_start.read_bytes()) != START_SHA:
        raise AssertionError("owner forwarding START differs")
    prior_review = review.parent / "continue04-review"
    predecessor_zip = prior_review / PRIOR_ZIP
    if digest(predecessor_zip.read_bytes()) != PREDECESSOR_PACKET_SHA:
        raise AssertionError("exact predecessor packet differs")
    prior_records = json.loads((prior_review / "ALLOCATION-RECORDS.json").read_bytes())
    with __import__("sqlite3").connect(
            f"file:{prior_review / 'capacity.sqlite'}?mode=ro", uri=True) as db:
        actual = {key: json.loads(raw) for key, raw in db.execute(
            "SELECT allocation_key,record FROM allocations")}
    if prior_records != actual or len(actual) != 2:
        raise AssertionError("previous append-once allocations differ")
    census = json.loads((prior_review / "FAILURE-CENSUS.json").read_bytes())
    if (census["status"] != "FAIL_BEFORE_HTTP_RETAINED" or
            any(census[key] for key in ("supplemental_admissions",
                                      "supplemental_possible_sends",
                                      "supplemental_receiver_arrivals"))):
        raise AssertionError("previous zero result differs")
    adjudication = REPO / "docs/development/dev-12/LEGACY-ALLOCATION-ADJUDICATION-01.json"
    snapshot = verify_legacy(adjudication, predecessor, original)
    with ZipFile(supplied_package) as z:
        instruction = z.read("DURANKI-DEV12-COMPLETION-02-CONTINUE-05.md")
        if z.read("DURANKI-DEV12-COMPLETION-02-CONTINUE-05-START.txt") != owner_start.read_bytes() or \
                z.read("governing/LEGACY-ALLOCATION-ADJUDICATION-01.json") != adjudication.read_bytes() or \
                z.read("input/" + PRIOR_ZIP) != predecessor_zip.read_bytes():
            raise AssertionError("owner adoption and adjudication package bytes differ")
    if now() >= utc(EXPIRY) - timedelta(minutes=25):
        raise PermissionError("insufficient original deadline before source preparation")
    packages = {
        "python_wheel": (corrected / "mach33_duranki_client-0.0.4-py3-none-any.whl", WHEEL_SHA),
        "js_tarball": (corrected / "mach33-duranki-client-0.0.3.tgz", TARBALL_SHA),
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
    archive = subprocess.check_output(("git", "archive", "--format=tar",
        "--prefix=source/", "HEAD"), cwd=REPO)
    (review / "source.tar").write_bytes(archive)
    selected, source_identity, rows = source_files(REPO, git("rev-parse", "HEAD"))
    if source_identity != mounted_source_identity():
        raise AssertionError("exact Git source differs from mounted source")
    durable_json(review / "SOURCE-FILES.json", {"kind": "ct02b_exact_mounted_source_v1",
        "source_commit": git("rev-parse", "HEAD"),
        "source_tree": git("rev-parse", "HEAD^{tree}"),
        "mounted_source_identity": source_identity,
        "files": rows, "source_tar_sha256": digest(archive)})
    plan = {"kind": "ct02b_one_case_plan_v1", "case_id": CASE,
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
        "work_selector": {"task_id": "task.demo", "step_id": STEP,
                          "step_revision": 1, "execution_generation": GENERATION},
        "contenders": [{"text": "Sky"}, {"text": "River"}],
        "envelope": {"campaign_id": CAMPAIGN, "budget_account_id": BUDGET,
            "financial_owner_id": OWNER, "currency": "USD", "max_admissions": 1,
            "max_possible_sends": 1, "max_inflight": 1,
            "ceiling_decimal": "0.010000000", "absolute_expiry": EXPIRY,
            "service_network_mode": "bridge", "real_provider_calls": 0},
        "artifacts": [{"kind": name, "path": "/review/packages/" + path.name,
                       "sha256": expected} for name, (path, expected) in packages.items()],
        "frozen_images": {"service": SERVICE_IMAGE, "node": NODE_IMAGE}}
    plan_sha = durable_json(review / "PLAN.json", plan)
    durable_json(review / "PRIOR-ALLOCATION-RECORDS.json", prior_records)
    durable_json(review / "PRIOR-ZERO-CENSUS.json", census)
    durable_json(review / "PREPARE.json", {
        "status": "PASS", "kind": "ct02b_no_target_prepare_v1",
        "source_commit": plan["source_commit"], "source_tree": plan["source_tree"],
        "plan_sha256": plan_sha, "adopted_instruction_sha256":
            plan["adopted_instruction_sha256"],
        "prior_allocations": len(prior_records),
        "historical_conservative_consumption_decimal": "0.054000030",
        "original_mixed_admissions": 124, "original_mixed_possible_send_slots": 109,
        "new_admissions_or_sends": 0, "real_provider_calls": 0})
    return {"status": "PASS", "plan_sha256": plan_sha,
            "source_commit": plan["source_commit"],
            "mounted_source_identity": source_identity,
            "prior_allocations": len(prior_records)}


def no_send_gate(review, original, predecessor):
    plan = read_plan(review)
    if (review.parent / ROOT_BASENAME).exists():
        raise PermissionError("fixed supplemental target root already exists")
    if digest((review / "source.tar").read_bytes()) != \
            json.loads((review / "SOURCE-FILES.json").read_bytes())["source_tar_sha256"]:
        raise AssertionError("frozen source snapshot differs")
    snapshot = verify_legacy(review / "LEGACY-ALLOCATION-ADJUDICATION-01.json",
                             predecessor, original)
    if snapshot["file_sha256"] != plan["original_file_sha256"]:
        raise AssertionError("original paused target changed")
    if now() >= utc(EXPIRY) - timedelta(minutes=20):
        raise PermissionError("insufficient original absolute release window")
    prior_review = review.parent / "continue04-review"
    with __import__("sqlite3").connect(
            f"file:{prior_review / 'capacity.sqlite'}?mode=ro", uri=True) as db:
        rows = {row[0]: json.loads(row[1]) for row in db.execute(
            "SELECT allocation_key,record FROM allocations")}
    if rows != json.loads((review / "PRIOR-ALLOCATION-RECORDS.json").read_bytes()) or len(rows) != 2:
        raise AssertionError("prior allocations differ or supp02 already consumed")
    for name, expected in (("service", SERVICE_IMAGE), ("node", NODE_IMAGE)):
        inspected = call("docker", "image", "inspect", expected,
                         "--format", "{{.Id}}").stdout.strip()
        if inspected != expected:
            raise AssertionError("frozen " + name + " image differs")
    worker_import = call("docker", "run", "--rm", "--network", "none",
        "-v", str(REPO) + ":/workspace:ro", "-w", "/workspace",
        SERVICE_IMAGE, "python", "-B", "-c",
        "import choice_b_wire; print(choice_b_wire.__file__)")
    if worker_import.stdout.strip() != "/app/gateway/choice_b_wire.py":
        raise AssertionError("frozen worker wire import differs")
    for name in (WORKER, SERVICE):
        if call("docker", "ps", "-a", "--filter", "name=^/" + name + "$",
                "--format", "{{.Names}}").stdout.strip():
            raise AssertionError("fixed Docker container namespace already used")
    if call("docker", "volume", "ls", "--filter", "name=^" + VOLUME + "$",
            "--format", "{{.Name}}").stdout.strip():
        raise AssertionError("fixed Docker volume namespace already used")
    if snapshot["campaign"]["pause_reasons"] != ["authority"]:
        raise AssertionError("original terminal pause differs")
    owner_profile = call("docker", "ps", "--filter", "name=duranki-dev06-local-",
        "--format", "{{.ID}} {{.Names}} {{.Image}}").stdout.splitlines()
    return {"status": "PASS", "kind": "ct02b_no_send_gate_v1",
        "checked_at": now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_commit": plan["source_commit"],
        "source_tree": plan["source_tree"],
        "mounted_source_identity": plan["mounted_source_identity"],
        "plan_sha256": digest((review / "PLAN.json").read_bytes()),
        "original_file_sha256": snapshot["file_sha256"],
        "historical_conservative_consumption_decimal": "0.054000030",
        "prospective_supplemental_allocation_decimal": "0.010000000",
        "combined_max_conservative_consumption_decimal": "0.064000030",
        "mixed_admissions_before": 124, "mixed_possible_send_slots_before": 109,
        "campaign_paused": True, "running_owner_profile_containers": owner_profile,
        "new_admissions_or_sends": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "preflight"))
    parser.add_argument("review", type=Path)
    parser.add_argument("original", type=Path)
    parser.add_argument("predecessor", type=Path)
    parser.add_argument("--package", type=Path)
    parser.add_argument("--start", type=Path)
    parser.add_argument("--corrected", type=Path)
    args = parser.parse_args()
    if args.mode == "prepare":
        if any(value is None for value in (args.package, args.start, args.corrected)):
            parser.error("prepare needs package, start and corrected package directory")
        result = prepare(args.review, args.original, args.predecessor,
                         args.package, args.start, args.corrected)
    else:
        result = no_send_gate(args.review, args.original, args.predecessor)
    print(json.dumps(result, sort_keys=True))
