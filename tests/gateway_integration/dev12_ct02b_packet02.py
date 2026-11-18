"""Portable supp02 failed-setup packet and independent offline replay audit."""
from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tarfile
from zipfile import ZipFile, ZIP_DEFLATED

PRIOR_SHA = "52ace93e04e48be13451f61158cd10efe25f0dd36b12a25c2b8273863a02bf85"
TESTED = "3481d7326823ac1a8000e0e568e611c62d1f00c2"
CAMPAIGN = "campaign.dev12.c02.ct02b.supp02"
CASE = "case.ct02.first_owner.supp02"
ROOT_NAME = "dev12-ct02b-supplement02-20261027"
EXPIRY = "2026-10-27T21:54:14Z"


def digest(raw):
    return sha256(raw).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as output:
        output.write(json.dumps(value, sort_keys=True, indent=2).encode() + b"\n")


def copy(source, destination):
    if not source.is_file() or source.is_symlink():
        raise AssertionError("missing or linked packet input: " + str(source))
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def manifest(root):
    path = root / "MANIFEST.sha256"
    if not path.exists():
        return None
    listed = {}
    for line in path.read_text().splitlines():
        expected, name = line.split("  ", 1)
        parts = Path(name).parts
        if (name in listed or name.startswith("/") or ".." in parts or
                len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected)):
            raise AssertionError("invalid manifest member")
        member = root / name
        if not member.is_file() or member.is_symlink() or digest(member.read_bytes()) != expected:
            raise AssertionError("packet payload differs: " + name)
        listed[name] = expected
    actual = {str(item.relative_to(root)) for item in root.rglob("*")
              if item.is_file() and item != path}
    if set(listed) != actual:
        raise AssertionError("packet membership differs")
    return len(listed)


def source_audit(root, plan):
    selected = read(root / "SOURCE-FILES.json")
    if (selected["source_commit"] != TESTED or
            selected["source_tree"] != plan["source_tree"] or
            selected["mounted_source_identity"] != plan["mounted_source_identity"] or
            selected["source_tar_sha256"] != digest((root / "source.tar").read_bytes())):
        raise AssertionError("tested source identity differs")
    with tarfile.open(fileobj=BytesIO((root / "source.tar").read_bytes()), mode="r:") as tar:
        files = {item.name.removeprefix("source/"): tar.extractfile(item).read()
                 for item in tar if item.isfile()}
    value = sha256()
    for row in selected["files"]:
        name = row["path"]
        raw = files[name]
        if len(raw) != row["bytes"] or digest(raw) != row["sha256"]:
            raise AssertionError("tested mounted file differs: " + name)
        label = name.encode()
        value.update(len(label).to_bytes(4, "big") + label +
                     len(raw).to_bytes(8, "big") + raw)
    if (len(selected["files"]) != 246 or
            value.hexdigest() != "806a654fd9e416ebd6d975234f8f293a74f993d50c48a043eec75707621e425d"):
        raise AssertionError("tested mounted source aggregate differs")
    return files


def audit(root):
    listed = manifest(root)
    plan = read(root / "PLAN.json")
    close = read(root / "CLOSEOUT.json")
    started = read(root / "target/TARGET-START.json")
    ready = read(root / "target/SERVICE-READY.json")
    setup = read(root / "SETUP-RESULT.json")
    if (plan["source_commit"] != TESTED or plan["case_id"] != CASE or
            plan["target_root_basename"] != ROOT_NAME or
            plan["envelope"]["campaign_id"] != CAMPAIGN or
            plan["envelope"]["max_admissions"] != 1 or
            plan["envelope"]["max_possible_sends"] != 1 or
            plan["envelope"]["max_inflight"] != 1 or
            plan["envelope"]["ceiling_decimal"] != "0.010000000" or
            plan["original_expiry"] != EXPIRY or
            plan["predecessor_packet_sha256"] != PRIOR_SHA or
            digest((root / "ADOPTED-INSTRUCTION.md").read_bytes()) !=
                plan["adopted_instruction_sha256"] or
            digest((root / "OWNER-START.txt").read_bytes()) !=
                plan["owner_forwarding_sha256"] or
            digest((root / "history/continue04.zip").read_bytes()) != PRIOR_SHA or
            started["plan_sha256"] != digest((root / "PLAN.json").read_bytes())):
        raise AssertionError("fixed adopted supp02 plan differs")
    with ZipFile(root / "history/continue04.zip") as z:
        if (z.testzip() is not None or
                json.loads(z.read("AUDIT-RESULT.json"))["status"] !=
                    "FAILED_BEFORE_HTTP_RETAINED" or
                json.loads(z.read("POSTMORTEM-IDENTITY.json"))["postmortem_commit"] !=
                    "b0661becb3412acab8794b3ed28d5b930685e64a"):
            raise AssertionError("nested Continue04 predecessor differs")
    source_audit(root, plan)
    for artifact in plan["artifacts"]:
        item = root / "packages" / Path(artifact["path"]).name
        if digest(item.read_bytes()) != artifact["sha256"]:
            raise AssertionError("exact installed client archive differs")
    prior = read(root / "PRIOR-ALLOCATION-RECORDS.json")
    allocation = read(root / "SUPPLEMENTAL-ALLOCATION.json")
    prior_zero = read(root / "PRIOR-ZERO-CENSUS.json")
    if (len(prior) != 2 or len(close["capacity_allocation_keys"]) != 3 or
            prior_zero["status"] != "FAIL_BEFORE_HTTP_RETAINED" or
            prior_zero["supplemental_admissions"] != 0 or
            allocation["campaign_id"] != CAMPAIGN or
            allocation["combined_max_conservative_consumption_decimal"] != "0.064000030" or
            Decimal("0.034000030") + Decimal("0.010000000") * 3 !=
                Decimal(allocation["combined_max_conservative_consumption_decimal"])):
        raise AssertionError("aggregate allocation arithmetic differs")
    if (close["status"] != "OPEN_SETUP_FAILED_FINITE_ALLOWANCE_EXPIRED" or
            close["tested_source_commit"] != TESTED or
            close["original_file_sha256"] != plan["original_file_sha256"] or
            close["setup_restarts_used"] != 0 or close["pair_release_committed"] or
            close["request_issued_markers"] != 0 or
            any(close[key] for key in ("supplemental_admissions",
                                      "supplemental_possible_sends",
                                      "supplemental_receiver_arrivals")) or
            any(close["primary_counts"].values()) or
            close["finite_campaign_expires_at"] != ready["campaign"]["expires_at"] or
            close["first_resource_started_at"] != started["resource_started_at"] or
            close["combined_conservative_allocation_decimal"] != "0.064000030" or
            close["legacy_native_cost"] is not None or
            setup["status"] != "FAIL" or setup["pair_released"] or
            setup["error"]["message"] != "actual Docker launcher or running state differs"):
        raise AssertionError("retained failed setup/zero census differs")
    for name, identity in close["safe_target_file_hashes"].items():
        item = root / "target" / name
        if (item.stat().st_size != identity["bytes"] or
                digest(item.read_bytes()) != identity["sha256"]):
            raise AssertionError("safe target file differs: " + name)
    commands = read(root / "target/SETUP-COMMANDS.json")
    worker = [row for row in commands if row["argv"][:2] == ["docker", "run"] and
              "tests/gateway_integration/dev12_worker.py" in row["argv"]]
    service = [row for row in commands if row["argv"][:2] == ["docker", "run"] and
               "tests/gateway_integration/dev12_ct02b_service02.py" in row["argv"]]
    if (len(worker) != 1 or len(service) != 1 or
            worker[0]["argv"][-3:] != ["python", "-B",
                "tests/gateway_integration/dev12_worker.py"] or
            service[0]["argv"][-8:] != ["python", "-I", "-B",
                "tests/gateway_integration/dev12_ct02b_service02.py",
                "/review/PLAN.json", "/target", "/original", "/capacity.sqlite"] or
            len([row for row in commands if row["argv"][:2] == ["docker", "stop"]]) != 2 or
            not ready["no_submission_issued"] or
            ready["campaign"]["attempt_count"] != 0 or
            ready["campaign"]["possible_send_count"] != 0):
        raise AssertionError("held startup and stop command record differs")
    ledger = read(root / "target/PRIMARY-LEDGER.json")
    if (ledger["campaign"] != ready["campaign"] or
            any(ledger["tables"][name] for name in ledger["tables"])):
        raise AssertionError("portable primary ledger is not zero")
    post = read(root / "POSTMORTEM-IDENTITY.json")
    if (post["tested_commit"] != TESTED or post["postmortem_commit"] == TESTED or
            post["target_reexecuted"] is not False or
            digest((root / "postmortem-source.tar").read_bytes()) !=
                post["source_tar_sha256"] or
            digest((root / "tested-to-postmortem.diff").read_bytes()) !=
                post["focused_diff_sha256"]):
        raise AssertionError("postmortem source conflated with tested source")
    with tarfile.open(fileobj=BytesIO((root / "postmortem-source.tar").read_bytes()),
                      mode="r:") as tar:
        corrected = tar.extractfile("postmortem/tests/gateway_integration/"
                                    "dev12_ct02b_host02_run.py").read()
    if b"def normalized_bind(raw):" not in corrected or \
            b'utc(ready["campaign"]["expires_at"])' not in corrected:
        raise AssertionError("postmortem bind/deadline corrections absent")
    return {"status": "OPEN_SETUP_FAILED_FINITE_ALLOWANCE_EXPIRED",
        "payloads_manifested": listed, "tested_source_commit": TESTED,
        "postmortem_source_commit": post["postmortem_commit"],
        "first_resource_started_at": started["resource_started_at"],
        "finite_campaign_expires_at": close["finite_campaign_expires_at"],
        "setup_restarts_used": 0, "pair_release_committed": False,
        "request_issued_markers": 0,
        "supplemental_admissions": 0, "supplemental_possible_sends": 0,
        "supplemental_receiver_arrivals": 0,
        "mixed_admissions": 124, "mixed_possible_send_upper": 109,
        "combined_conservative_allocation_decimal": "0.064000030",
        "legacy_native_cost": None,
        "original_unchanged": True, "owner_profile_unchanged": True,
        "real_provider_calls": 0, "real_spend": 0}


def build(review, target, predecessor, stage, output):
    if stage.exists() or output.exists():
        raise ValueError("fresh packet stage and ZIP required")
    stage.mkdir(parents=True)
    names = ("PLAN.json", "SOURCE-FILES.json", "source.tar", "ADOPTED-INSTRUCTION.md",
             "OWNER-START.txt", "LEGACY-ALLOCATION-ADJUDICATION-01.json",
             "PREPARE.json", "PRIOR-ALLOCATION-RECORDS.json", "PRIOR-ZERO-CENSUS.json",
             "NO-SEND-GATE.json", "SUPPLEMENTAL-ALLOCATION.json", "SETUP-RESULT.json",
             "CLOSEOUT.json")
    for name in names:
        copy(review / name, stage / name)
    for name in ("RESTART-SERVICE.py", "RESTART-HOST.py"):
        copy(review / name, stage / "unexecuted" / name)
    for item in (review / "packages").iterdir():
        copy(item, stage / "packages" / item.name)
    copy(predecessor, stage / "history/continue04.zip")
    for name in read(review / "CLOSEOUT.json")["safe_target_file_hashes"]:
        copy(target / name, stage / "target" / name)
    with sqlite3.connect(f"file:{target / 'campaign.sqlite'}?mode=ro", uri=True) as db:
        campaign = json.loads(db.execute("SELECT record FROM dev12_campaigns WHERE campaign_id=?",
                                         (CAMPAIGN,)).fetchone()[0])
        tables = {name: db.execute("SELECT * FROM " + name).fetchall()
                  for name in ("dev12_submissions", "dev12_campaign_attempts",
                               "dev12_send_ownership", "dev12_usage_revisions",
                               "work_key_owners")}
    write(stage / "target/PRIMARY-LEDGER.json", {"campaign": campaign, "tables": tables})
    copy(Path(__file__), stage / "verifier/dev12_ct02b_packet02.py")
    current = subprocess.check_output(("git", "rev-parse", "HEAD"), text=True).strip()
    if current == TESTED or subprocess.check_output(("git", "status", "--porcelain",
                                                      "--untracked-files=no")):
        raise AssertionError("postmortem source must be a distinct clean commit")
    tar = subprocess.check_output(("git", "archive", "--format=tar",
                                   "--prefix=postmortem/", "HEAD"))
    (stage / "postmortem-source.tar").write_bytes(tar)
    diff = subprocess.check_output(("git", "diff", "--binary", TESTED, current,
        "--", "tests/gateway_integration", "docs/development/dev-12/RESULT.md",
        "docs/development/dev-12/REVIEW-HANDOFF.md",
        "docs/development/dev-12/A2-A4-VALIDATION.json"))
    (stage / "tested-to-postmortem.diff").write_bytes(diff)
    write(stage / "POSTMORTEM-IDENTITY.json", {"tested_commit": TESTED,
        "postmortem_commit": current,
        "postmortem_tree": subprocess.check_output(("git", "rev-parse", "HEAD^{tree}"),
                                                     text=True).strip(),
        "source_tar_sha256": digest(tar), "focused_diff_sha256": digest(diff),
        "target_reexecuted": False})
    write(stage / "AUDIT-RESULT.json", audit(stage))
    (stage / "README.md").write_text(
        "# DEV-12 CT02-02b supp02 review\n\n"
        "OPEN: the held setup reached worker IPC, receiver TLS and service ready, "
        "then its host bind verifier failed. No pair release or HTTP request was "
        "issued. The finite campaign expired; no setup restart was used. The "
        "unexecuted/ scripts were prepared but never run. All USD amounts are "
        "fictional conservative allocation, not observed spend. Raw databases, "
        "keys and credentials are excluded.\n\n"
        "Offline replay: `python3 -I -S -B verifier/dev12_ct02b_packet02.py audit .`\n")
    included = [item for item in sorted(stage.rglob("*")) if item.is_file() and
                item != stage / "MANIFEST.sha256"]
    (stage / "MANIFEST.sha256").write_text("".join(
        digest(item.read_bytes()) + "  " + str(item.relative_to(stage)) + "\n"
        for item in included))
    with ZipFile(output, "x", ZIP_DEFLATED, compresslevel=6) as z:
        for item in included:
            z.write(item, str(item.relative_to(stage)))
        z.write(stage / "MANIFEST.sha256", "MANIFEST.sha256")
    with ZipFile(output) as z:
        if z.testzip() is not None or len(z.namelist()) != len(included) + 1:
            raise AssertionError("portable ZIP differs")
    return {"status": "PACKET_BUILT", "bytes": output.stat().st_size,
        "sha256": digest(output.read_bytes()), "payloads": len(included)}


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "audit":
        print(json.dumps(audit(Path(sys.argv[2])), sort_keys=True, indent=2))
    elif len(sys.argv) == 7 and sys.argv[1] == "build":
        print(json.dumps(build(*(Path(value) for value in sys.argv[2:])),
                         sort_keys=True, indent=2))
    else:
        raise SystemExit("audit ROOT or build REVIEW TARGET CONTINUE04_ZIP STAGE OUTPUT")
