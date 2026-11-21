"""Portable, self-auditing CT02-02b one-case review packet."""

from __future__ import annotations

if not __package__:
    import sys
    from pathlib import Path

    for _parent in Path(__file__).resolve().parents:
        if (_parent / "tools/gateway/__init__.py").is_file():
            sys.path.insert(0, str(_parent))
            break
        if (_parent / "server/tools/gateway/__init__.py").is_file():
            sys.path.insert(0, str(_parent / "server"))
            break


from decimal import Decimal, ROUND_HALF_EVEN
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

from tools.gateway.evidence.dev12_ct02b_supplement import (
    ADJUDICATION_SHA,
    ALLOC,
    BUDGET,
    CAMPAIGN,
    CASE,
    EXPIRY,
    OWNER,
    PREDECESSOR_PACKET_SHA,
    ROOT_BASENAME,
    digest,
    durable_json,
)


def document(path):
    return json.loads(path.read_bytes())


def git(*args):
    return subprocess.check_output(("git", *args), text=True).strip()


def capture_failure(review, target, original):
    """Read-only live closeout after the consumed release failed before HTTP."""
    if (review / "FAILURE-CENSUS.json").exists():
        raise ValueError("failure census already captured")
    host = document(review / "HOST-FINAL.json")
    if host["status"] != "FAIL" or host["service_exit"] is not None:
        raise AssertionError("this closeout is only for the retained pre-service stop")
    from tools.gateway.evidence.dev12_ct02b_supplement import original_snapshot

    snapshot = original_snapshot(original)
    with sqlite3.connect(f"file:{review / 'capacity.sqlite'}?mode=ro", uri=True) as db:
        allocations = {
            key: json.loads(raw)
            for key, raw in db.execute("SELECT allocation_key,record FROM allocations")
        }
    if len(allocations) != 2:
        raise AssertionError("expected legacy booking and consumed sole release")
    durable_json(review / "ALLOCATION-RECORDS.json", allocations)
    inventory = {
        path.name: {"bytes": path.stat().st_size, "sha256": digest(path.read_bytes())}
        for path in target.iterdir()
        if path.is_file() and not path.is_symlink()
    }
    if (
        (target / "campaign.sqlite").exists()
        or (target / "RAW-HTTP.jsonl").exists()
        or (target / "case-journal.jsonl").exists()
        or snapshot["file_sha256"] != document(review / "PLAN.json")["original_file_sha256"]
    ):
        raise AssertionError("unexpected admission, HTTP request or original target change")
    containers = subprocess.run(
        (
            "docker",
            "ps",
            "-a",
            "--filter",
            "name=ezllmrouter-dev12-ct02b-supp01-",
            "--format",
            "{{.Names}}",
        ),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    volume = subprocess.run(
        (
            "docker",
            "volume",
            "ls",
            "--filter",
            "name=^ezllmrouter-dev12-ct02b-supp01-link$",
            "--format",
            "{{.Name}}",
        ),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    if containers or volume:
        raise AssertionError("owned failed target resources still live")
    checked = {
        "kind": "ct02b_retained_failed_release_census_v1",
        "status": "FAIL_BEFORE_HTTP_RETAINED",
        "target_files": inventory,
        "original_file_sha256": snapshot["file_sha256"],
        "original_mixed_admissions": 124,
        "original_possible_send_upper": 109,
        "supplemental_admissions": 0,
        "supplemental_possible_sends": 0,
        "supplemental_receiver_arrivals": 0,
        "legacy_native_cost": None,
        "historical_conservative_consumption_decimal": "0.044000030",
        "consumed_supplemental_allocation_decimal": "0.010000000",
        "combined_conservative_allocation_decimal": "0.054000030",
        "original_campaign_unchanged": True,
        "owner_profile_unchanged": host["running_owner_profile_containers_before"]
        == host["running_owner_profile_containers_after"],
        "owned_container_names_after": containers,
        "owned_volume_names_after": volume,
        "real_provider_calls": 0,
        "real_spend": 0,
    }
    durable_json(review / "FAILURE-CENSUS.json", checked)
    return checked


def audit_failed(root, plan, host, started, listed):
    target = root / "target"
    census = document(root / "FAILURE-CENSUS.json")
    allocations = document(root / "ALLOCATION-RECORDS.json")
    commands = document(target / "HOST-COMMANDS.json")
    stderr = (target / "worker.stderr").read_text()
    expected_target = {"TARGET-START.json", "HOST-COMMANDS.json", "worker.stdout", "worker.stderr"}
    if (
        host["status"] != "FAIL"
        or host["service_exit"] is not None
        or host["error"] != {"type": "TimeoutError", "message": "isolated worker socket absent"}
        or not host["original_unchanged"]
        or host["running_owner_profile_containers_before"]
        != host["running_owner_profile_containers_after"]
        or set(census["target_files"]) != expected_target
        or census["original_file_sha256"] != plan["original_file_sha256"]
        or not census["original_campaign_unchanged"]
        or not census["owner_profile_unchanged"]
        or census["owned_container_names_after"]
        or census["owned_volume_names_after"]
        or len(allocations) != 2
        or CAMPAIGN + "|single-use-release" not in allocations
        or allocations[CAMPAIGN + "|single-use-release"]
        != document(root / "SUPPLEMENTAL-ALLOCATION.json")
        or allocations[document(root / "LEGACY-BOOKING.json")["record"]["key"]]
        != document(root / "LEGACY-BOOKING.json")["record"]
        or "ModuleNotFoundError: No module named 'choice_b_wire'" not in stderr
        or started["plan_sha256"] != digest((root / "PLAN.json").read_bytes())
    ):
        raise AssertionError("retained failed release evidence differs")
    for name, spec in census["target_files"].items():
        path = target / name
        if path.stat().st_size != spec["bytes"] or digest(path.read_bytes()) != spec["sha256"]:
            raise AssertionError("failed target file identity differs: " + name)
    if (
        any(path.name not in expected_target for path in target.iterdir())
        or any(
            path.name in {"campaign.sqlite", "RAW-HTTP.jsonl", "BOUNDARY.jsonl"}
            for path in target.iterdir()
        )
        or len(
            [
                row
                for row in commands
                if row["argv"][:2] == ["docker", "run"] and "dev12_ct02b_service.py" in row["argv"]
            ]
        )
        != 0
        or len(
            [
                row
                for row in commands
                if row["argv"][:2] == ["docker", "run"]
                and "dev12_worker.py" in " ".join(row["argv"])
            ]
        )
        != 1
    ):
        raise AssertionError("service/HTTP path unexpectedly started")
    worker_cmd = next(row["argv"] for row in commands if "dev12_worker.py" in " ".join(row["argv"]))
    if worker_cmd[-4:] != ["python", "-I", "-B", "tools/gateway/evidence/dev12_worker.py"]:
        raise AssertionError("failed worker startup command differs")
    if (
        Decimal(census["historical_conservative_consumption_decimal"])
        + Decimal(census["consumed_supplemental_allocation_decimal"])
        != Decimal(census["combined_conservative_allocation_decimal"])
        or census["supplemental_admissions"] != 0
        or census["supplemental_possible_sends"] != 0
        or census["supplemental_receiver_arrivals"] != 0
    ):
        raise AssertionError("failed release capacity/zero-send arithmetic differs")
    fix = document(root / "POSTMORTEM-IDENTITY.json")
    if (
        digest((root / "postmortem-source.tar").read_bytes()) != fix["source_tar_sha256"]
        or digest((root / "focused-tested-to-postmortem.diff").read_bytes())
        != fix["focused_diff_sha256"]
        or fix["tested_commit"] != plan["source_commit"]
        or fix["postmortem_commit"] == fix["tested_commit"]
        or fix["target_reexecuted"] is not False
    ):
        raise AssertionError("postmortem source was confused with tested bytes")
    with tarfile.open(
        fileobj=BytesIO((root / "postmortem-source.tar").read_bytes()), mode="r:"
    ) as tar:
        corrected = tar.extractfile("postmortem/tools/gateway/evidence/dev12_ct02b_host.py").read()
    if (
        b'SERVICE_IMAGE, "python", "-B",' not in corrected
        or b"import choice_b_wire; print(choice_b_wire.__file__)" not in corrected
    ):
        raise AssertionError("postmortem worker startup correction absent")
    return {
        "status": "FAILED_BEFORE_HTTP_RETAINED",
        "tested_source_commit": plan["source_commit"],
        "postmortem_source_commit": fix["postmortem_commit"],
        "payloads_manifested": listed,
        "original_mixed_admissions": 124,
        "original_possible_send_upper": 109,
        "supplemental_admissions": 0,
        "supplemental_possible_sends": 0,
        "supplemental_receiver_arrivals": 0,
        "legacy_native_cost": None,
        "historical_conservative_consumption_decimal": "0.044000030",
        "consumed_supplemental_allocation_decimal": "0.010000000",
        "combined_conservative_allocation_decimal": "0.054000030",
        "original_unchanged": True,
        "owner_profile_unchanged": True,
        "real_provider_calls": 0,
        "real_spend": 0,
    }


def lines(path):
    return [json.loads(value) for value in path.read_text().splitlines()]


def verify_manifest(root):
    manifest = root / "MANIFEST.sha256"
    if not manifest.is_file():
        return None
    listed = {}
    for line in manifest.read_text().splitlines():
        expected, name = line.split("  ", 1)
        if name in listed or name.startswith("/") or ".." in Path(name).parts:
            raise AssertionError("invalid portable manifest entry")
        path = root / name
        if not path.is_file() or path.is_symlink() or digest(path.read_bytes()) != expected:
            raise AssertionError("portable payload hash differs: " + name)
        listed[name] = expected
    actual = {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() and path != manifest and "source" not in path.relative_to(root).parts
    }
    if set(listed) != actual:
        raise AssertionError("portable packet member set differs")
    return len(listed)


def audit(root):
    files, listed, plan = _audit_packet_source_custody(root)
    booking = document(root / "LEGACY-BOOKING.json")
    allocation = document(root / "SUPPLEMENTAL-ALLOCATION.json")
    gate = document(root / "NO-SEND-GATE.json")
    if (
        booking["record"]["observed_native_cost_decimal"] is not None
        or Decimal(booking["record"]["successor_cumulative_reservations_decimal"])
        + Decimal(booking["record"]["amount_decimal"])
        != Decimal("0.044000030")
        or allocation["kind"] != "ct02b_single_use_release_allocation_v1"
        or allocation["campaign_id"] != CAMPAIGN
        or allocation["max_admissions"] != 1
        or allocation["max_possible_sends"] != 1
        or Decimal(allocation["max_reservation_decimal"]) != ALLOC
        or Decimal(booking["record"]["historical_conservative_consumption_decimal"]) + ALLOC
        != Decimal(allocation["combined_max_conservative_consumption_decimal"])
        or allocation["combined_max_admissions"] != 125
        or allocation["combined_max_possible_send_slots"] != 110
        or allocation["plan_sha256"] != digest((root / "PLAN.json").read_bytes())
        or allocation["source_commit"] != plan["source_commit"]
        or allocation["adopted_instruction_sha256"] != plan["adopted_instruction_sha256"]
        or gate["status"] != "PASS"
        or gate["original_file_sha256"] != plan["original_file_sha256"]
    ):
        raise AssertionError("append-once legacy/supplemental capacity arithmetic differs")
    target = root / "target"
    host = document(root / "HOST-FINAL.json")
    started = document(target / "TARGET-START.json")
    if host["status"] == "FAIL":
        return audit_failed(root, plan, host, started, listed)
    service = document(target / "SERVICE-FINAL.json")
    observation = document(target / "TARGET-OBSERVATION.json")
    exact = document(target / "CASE-PREFLIGHT.json")
    if (
        host["status"] != "PASS"
        or service["status"] != "PASS"
        or observation["status"] != "PASS"
        or not host["original_unchanged"]
        or not service["original_unchanged"]
        or host["running_owner_profile_containers_before"]
        != host["running_owner_profile_containers_after"]
        or started["plan_sha256"] != digest((root / "PLAN.json").read_bytes())
        or observation["case_id"] != CASE
        or exact["case_id"] != CASE
    ):
        raise AssertionError("sole target did not pass its own durable outcome")
    pair = exact["requests"]
    if (
        len(pair) != 2
        or pair[0]["body_utf8"] == pair[1]["body_utf8"]
        or pair[0]["work_digest"] == pair[1]["work_digest"]
        or [document_bytes(row["body_utf8"].encode())["input"]["items"][0]["text"] for row in pair]
        != ["Sky", "River"]
    ):
        raise AssertionError("predeclared two-body WorkKey conflict differs")
    for row in pair:
        if digest(row["body_utf8"].encode()) != row["body_sha256"]:
            raise AssertionError("request bytes differ")
    replies = observation["responses"]
    raw = lines(target / "RAW-HTTP.jsonl")
    if (
        len(replies) != 2
        or len(raw) != 2
        or sorted(row["request_sha256"] for row in replies)
        != sorted(row["body_sha256"] for row in pair)
    ):
        raise AssertionError("one and only one HTTP pair differs")
    winner = [row for row in replies if row["reply"].get("handle")]
    loser = [row for row in replies if row["http_status"] == 409]
    if (
        len(winner) != 1
        or len(loser) != 1
        or winner[0]["http_status"] != 200
        or loser[0]["reply"].get("code") != "WORK_CONFLICT"
        or loser[0]["reply"].get("retry_guidance") != "never"
        or loser[0]["response_headers"].get("EzLLMRouter-Contract-Version") != "0.3"
        or observation["owner"]["submission_id"] != winner[0]["reply"]["handle"]["submission_id"]
    ):
        raise AssertionError("selected-wire winner/conflict differs")
    boundary = observation["boundary"]
    barrier = lines(target / "BOUNDARY.jsonl")
    transactions = lines(target / "TRANSACTIONS.jsonl")
    if (
        len(boundary["arrivals"]) != 2
        or len({row["thread_id"] for row in boundary["arrivals"]}) != 2
        or not boundary["owner_absent_when_both_arrived"]
        or len([row for row in barrier if row["kind"] == "ct02b_barrier_arrival"]) != 2
        or barrier[-1]["kind"] != "ct02b_barrier_release"
        or len([row for row in transactions if row["kind"] == "ct02b_product_claim_entry"]) != 2
        or any(row["at_ns"] >= boundary["release_at_ns"] for row in boundary["arrivals"])
        or any(
            row["at_ns"] < boundary["release_at_ns"] for row in observation["transaction_entries"]
        )
    ):
        raise AssertionError("first-owner barrier did not precede both product claims")
    ledger = document(target / "ledger.json")
    rows = {name: item["rows"] for name, item in ledger.items()}
    if (
        len(rows["dev12_campaigns"]) != 1
        or len(rows["dev12_submissions"]) != 1
        or len(rows["dev12_campaign_attempts"]) != 1
        or len(rows["work_key_owners"]) != 1
        or len(rows["dev12_send_ownership"]) > 1
        or observation["after"]["submissions"] != 1
        or observation["after"]["campaign"]["attempt_count"] != 1
        or observation["after"]["campaign"]["possible_send_count"] > 1
        or observation["after"]["receiver_arrivals"] > 1
    ):
        raise AssertionError("supplemental unique-attempt census differs")
    admitted = json.loads(rows["dev12_submissions"][0]["record"])
    campaign = json.loads(rows["dev12_campaigns"][0]["record"])
    attempt = admitted["attempt_id"]
    if (
        admitted["submission_id"] != observation["owner"]["submission_id"]
        or admitted["work_key"] != exact["work_key"]
        or admitted["work_digest"] not in {row["work_digest"] for row in pair}
        or campaign["max_attempts"] != 1
        or campaign["max_concurrent"] != 1
        or campaign["ceiling_decimal"] != "0.010000000"
        or campaign["expires_at"] > EXPIRY
        or Decimal(campaign["cumulative_reserved_decimal"]) > ALLOC
    ):
        raise AssertionError("winning durable record or fixed campaign limits differ")
    for name in ("dev12_send_ownership", "dev12_usage_revisions"):
        if any(row["attempt_id"] != attempt for row in rows[name]):
            raise AssertionError("foreign attempt in supplemental " + name)
    arrivals = lines(target / "receiver.jsonl")
    receipts = lines(target / "receiver-receipts.jsonl")
    guard = lines(target / "guard.jsonl")
    if (
        len(arrivals) > 1
        or len(receipts) > 1
        or any(row["attempt_id"] != attempt for row in arrivals + receipts)
        or any(row.get("attempt_id") not in (None, attempt) for row in guard)
        or len(arrivals) != observation["after"]["receiver_arrivals"]
        or len(rows["dev12_send_ownership"])
        != observation["after"]["campaign"]["possible_send_count"]
    ):
        raise AssertionError("receiver/guard ownership correlation differs")
    tariff = document_bytes(files["tests/fixtures/contracts/dev12-successor-01/tariffs.json"])
    rate = Decimal(tariff["embedding_document"]["per_item_usd"])
    known = Decimal(0)
    latest = max(rows["dev12_usage_revisions"], key=lambda row: row["revision"], default=None)
    for item in [latest] if latest is not None else []:
        usage = json.loads(item["usage"])
        if usage["cost_status"] in ("calculated", "over_bound"):
            quantity = sum(
                Decimal(component["quantity"])
                for component in usage["components"]
                if component.get("presence") == "known"
            )
            amount = (quantity * rate).quantize(Decimal("0.000000001"), rounding=ROUND_HALF_EVEN)
            if amount != Decimal(usage["amount_decimal"]):
                raise AssertionError("independent native-unit cost differs")
            known += amount
    return {
        "status": "PASS",
        "source_commit": plan["source_commit"],
        "source_tree": plan["source_tree"],
        "payloads_manifested": listed,
        "original_mixed_admissions": 124,
        "supplemental_admissions": 1,
        "combined_admissions": 125,
        "original_possible_send_upper": 109,
        "supplemental_possible_sends": len(rows["dev12_send_ownership"]),
        "combined_possible_send_upper": 109 + len(rows["dev12_send_ownership"]),
        "historical_conservative_consumption_decimal": "0.044000030",
        "combined_allocated_ceiling_decimal": "0.054000030",
        "supplemental_known_native_usd": format(known, ".9f"),
        "receiver_arrivals": len(arrivals),
        "read_only_status_gets": observation["read_only_status_gets"],
        "real_provider_calls": 0,
        "real_spend": 0,
    }


def document_bytes(raw):
    return json.loads(raw)


def copy_file(source, target):
    if not source.is_file() or source.is_symlink():
        raise AssertionError("missing or linked packet evidence: " + str(source))
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def build(review, target, predecessor_zip, stage, output):
    if stage.exists() or output.exists():
        raise ValueError("fresh packet stage and ZIP required")
    stage.mkdir(parents=True)
    root_files = (
        "PLAN.json",
        "SOURCE-FILES.json",
        "source.tar",
        "ADOPTED-INSTRUCTION.md",
        "OWNER-START.txt",
        "LEGACY-ALLOCATION-ADJUDICATION-01.json",
        "PREPARE.json",
        "LEGACY-BOOKING.json",
        "NO-SEND-GATE.json",
        "SUPPLEMENTAL-ALLOCATION.json",
        "HOST-FINAL.json",
    )
    for name in root_files:
        copy_file(review / name, stage / name)
    for path in (review / "packages").iterdir():
        copy_file(path, stage / "packages" / path.name)
    copy_file(predecessor_zip, stage / "history/continue03.zip")
    failed = document(review / "HOST-FINAL.json")["status"] == "FAIL"
    if failed:
        target_files = ("TARGET-START.json", "HOST-COMMANDS.json", "worker.stdout", "worker.stderr")
        for name in ("FAILURE-CENSUS.json", "ALLOCATION-RECORDS.json"):
            copy_file(review / name, stage / name)
        current = git("rev-parse", "HEAD")
        tested = document(review / "PLAN.json")["source_commit"]
        if current == tested or git("status", "--porcelain", "--untracked-files=no"):
            raise AssertionError("postmortem source must be a distinct clean commit")
        tar = subprocess.check_output(
            ("git", "archive", "--format=tar", "--prefix=postmortem/", "HEAD")
        )
        (stage / "postmortem-source.tar").write_bytes(tar)
        diff = subprocess.check_output(
            (
                "git",
                "diff",
                "--binary",
                tested,
                current,
                "--",
                "tools/gateway/evidence/dev12_ct02b_host.py",
                "tools/gateway/evidence/dev12_ct02b_packet.py",
                "docs/development/dev-12/RESULT.md",
                "docs/development/dev-12/REVIEW-HANDOFF.md",
                "docs/development/dev-12/A2-A4-VALIDATION.json",
            )
        )
        (stage / "focused-tested-to-postmortem.diff").write_bytes(diff)
        durable_json(
            stage / "POSTMORTEM-IDENTITY.json",
            {
                "tested_commit": tested,
                "postmortem_commit": current,
                "postmortem_tree": git("rev-parse", "HEAD^{tree}"),
                "source_tar_sha256": digest(tar),
                "focused_diff_sha256": digest(diff),
                "target_reexecuted": False,
            },
        )
    else:
        target_files = (
            "TARGET-START.json",
            "CASE-PREFLIGHT.json",
            "RAW-HTTP.jsonl",
            "BOUNDARY.jsonl",
            "TRANSACTIONS.jsonl",
            "TARGET-OBSERVATION.json",
            "SERVICE-FINAL.json",
            "HOST-COMMANDS.json",
            "receiver.jsonl",
            "receiver-receipts.jsonl",
            "guard.jsonl",
            "case-journal.jsonl",
            "release-identity.jsonl",
            "service.stdout",
            "service.stderr",
            "worker.stdout",
            "worker.stderr",
        )
    for name in target_files:
        copy_file(target / name, stage / "target" / name)
    if not failed:
        from tools.gateway.evidence.dev12_completion_export import logical_tables

        ledger = logical_tables(target / "campaign.sqlite")
        durable_json(stage / "target/ledger.json", ledger)
    copy_file(Path(__file__), stage / "verifier/dev12_ct02b_packet.py")
    copy_file(
        Path(__file__).with_name("dev12_ct02b_supplement.py"),
        stage / "verifier/dev12_ct02b_supplement.py",
    )
    result = audit(stage)
    durable_json(stage / "AUDIT-RESULT.json", result)
    description = (
        "The single authorized release failed during worker startup, before the "
        "service listener, HTTP contenders, admission or send. Its allocation "
        "was consumed. The corrected postmortem source was not target tested. "
        if failed
        else "The one-case target contains its HTTP pair, durable public rows and "
        "read-only status. "
    )
    (stage / "README.md").write_text(
        "# DEV-12 CT02-02b one-case supplemental review\n\n"
        "Fictional USD and synthetic controlled receiver only. The original "
        "campaign stayed paused. This packet nests the exact Continue03 packet "
        "once and contains this exception's tested source and conservative "
        "allocation. "
        + description
        + "It excludes raw databases, bearer credentials, private signing/TLS "
        "keys and the owner profile.\n\n"
        "Offline replay after extraction: `python3 -I -B "
        "verifier/dev12_ct02b_packet.py .`\n"
    )
    included = [
        path
        for path in sorted(stage.rglob("*"))
        if path.is_file()
        and path != stage / "MANIFEST.sha256"
        and "source" not in path.relative_to(stage).parts
    ]
    manifest = [
        digest(path.read_bytes()) + "  " + str(path.relative_to(stage)) for path in included
    ]
    (stage / "MANIFEST.sha256").write_text("\n".join(manifest) + "\n")
    with ZipFile(output, "x", ZIP_DEFLATED, compresslevel=6) as z:
        for path in included:
            z.write(path, str(path.relative_to(stage)))
        z.write(stage / "MANIFEST.sha256", "MANIFEST.sha256")
    with ZipFile(output) as z:
        if set(z.namelist()) != {str(path.relative_to(stage)) for path in included} | {
            "MANIFEST.sha256"
        }:
            raise AssertionError("portable ZIP membership differs")
    return {
        "status": "PASS",
        "bytes": output.stat().st_size,
        "sha256": digest(output.read_bytes()),
        "payloads": len(included),
        "audit": result,
    }


if __name__ == "__main__":
    if len(sys.argv) == 2:
        print(json.dumps(audit(Path(sys.argv[1])), sort_keys=True, indent=2))
    elif len(sys.argv) == 5 and sys.argv[1] == "capture-failure":
        print(
            json.dumps(
                capture_failure(*(Path(value) for value in sys.argv[2:])), sort_keys=True, indent=2
            )
        )
    elif len(sys.argv) == 6:
        print(json.dumps(build(*(Path(value) for value in sys.argv[1:])), sort_keys=True, indent=2))
    else:
        raise SystemExit(
            "audit ROOT, capture-failure REVIEW TARGET ORIGINAL, "
            "or build REVIEW TARGET PREDECESSOR_ZIP STAGE OUTPUT"
        )


def _audit_packet_source_custody(root):
    listed = verify_manifest(root)
    plan = document(root / "PLAN.json")
    source = document(root / "SOURCE-FILES.json")
    if (
        plan["kind"] != "ct02b_one_case_plan_v1"
        or plan["case_id"] != CASE
        or plan["target_root_basename"] != ROOT_BASENAME
        or plan["envelope"]["campaign_id"] != CAMPAIGN
        or plan["envelope"]["budget_account_id"] != BUDGET
        or plan["envelope"]["financial_owner_id"] != OWNER
        or plan["envelope"]["max_admissions"] != 1
        or plan["envelope"]["max_possible_sends"] != 1
        or plan["envelope"]["max_inflight"] != 1
        or plan["envelope"]["ceiling_decimal"] != "0.010000000"
        or plan["original_expiry"] != EXPIRY
        or digest((root / "ADOPTED-INSTRUCTION.md").read_bytes())
        != plan["adopted_instruction_sha256"]
        or digest((root / "OWNER-START.txt").read_bytes()) != plan["owner_forwarding_sha256"]
        or digest((root / "LEGACY-ALLOCATION-ADJUDICATION-01.json").read_bytes())
        != ADJUDICATION_SHA
    ):
        raise AssertionError("adopted one-case plan differs")
    if (
        digest((root / "history/continue03.zip").read_bytes()) != PREDECESSOR_PACKET_SHA
        or document(root / "PREPARE.json")["status"] != "PASS"
    ):
        raise AssertionError("predecessor or no-target preparation differs")
    with ZipFile(root / "history/continue03.zip") as z:
        if (
            document_bytes(z.read("AUDIT-RESULT.json"))["status"] != "PASS"
            or document_bytes(z.read("IDENTITY.json"))["commit"]
            != "a49926e5b7ae107f35b5a045812fb15dfcc706cc"
        ):
            raise AssertionError("nested reviewed predecessor differs")
    if digest((root / "source.tar").read_bytes()) != source["source_tar_sha256"]:
        raise AssertionError("exact source TAR differs")
    with tarfile.open(fileobj=BytesIO((root / "source.tar").read_bytes()), mode="r:") as tar:
        files = {}
        for item in tar:
            if item.isfile():
                if item.name.startswith("/") or ".." in Path(item.name).parts:
                    raise AssertionError("unsafe source TAR member")
                files[item.name.removeprefix("source/")] = tar.extractfile(item).read()
    value = sha256()
    for row in source["files"]:
        raw = files[row["path"]]
        if len(raw) != row["bytes"] or digest(raw) != row["sha256"]:
            raise AssertionError("frozen mounted source member differs")
        name = row["path"].encode()
        value.update(len(name).to_bytes(4, "big") + name)
        value.update(len(raw).to_bytes(8, "big") + raw)
    if (
        len(source["files"]) != source["mounted_source_identity"]["file_count"]
        or value.hexdigest() != source["mounted_source_identity"]["sha256"]
        or plan["mounted_source_identity"] != source["mounted_source_identity"]
        or source["source_commit"] != plan["source_commit"]
        or source["source_tree"] != plan["source_tree"]
    ):
        raise AssertionError("mounted source aggregate differs")
    for artifact in plan["artifacts"]:
        path = root / "packages" / Path(artifact["path"]).name
        if digest(path.read_bytes()) != artifact["sha256"]:
            raise AssertionError("exact corrected client archive differs")
    return files, listed, plan
