"""No-send gate and bounded continuation of the retained DEV-12 campaign.

The original 80-case plan and its journal stay immutable.  This inventory
adds only independently reviewed missing/affected cases to the same campaign.
Build and preflight run on the host without starting a listener or sender;
release runs in the pinned isolated service image with the original worker.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from dev12_completion_catalog import (
    REQUIRED_PAIRS,
    SUPPLEMENT_LIMITS,
    SUPPLEMENT_PREDICATES,
    SUPPLEMENT_REQUIRED_PAIRS,
)
from dev12_completion_preflight import mounted_source_identity, verify_case_result
from dev12_completion_runner import (
    CompletionRuntime,
    _clean_relevant_source,
    _journal_rows,
    _json_bytes,
    _tree,
    append_durable,
    snapshot,
)
from dev12_completion_supplement_handlers import supplement

EXPECTED_CAMPAIGN = "campaign.dev12.c02.20261026.continue01"
EXPECTED_BUDGET = "budget.dev12.c02.20261026.continue01"
EXPECTED_OWNER = "team.dev12.c02.20261026.continue01"
EXPECTED_START = "2026-10-26T21:54:14Z"
EXPECTED_EXPIRY = "2026-10-27T21:54:14Z"
EXPECTED_FAILURES = frozenset(
    (
        "case.t24_b.partial_write",
        "case.t24_b.partial_write.continuation1",
        "case.t47_a.composed",
        "case.t49_d.composed",
        "case.t60.composed",
        "case.t62_b.composed",
    )
)
ORDER = (
    ("ct02_reporting", "csv_overbound"),
    ("ct02_revision33", "accepted_history"),
    ("ct02_historical_auth", "read_write_resume"),
    ("ct02_workkey", "wire02_first"),
    ("ct02_workkey", "wire03_first"),
    ("ct02_workkey", "http_contention"),
    ("ct02_recovery", "wheel"),
    ("ct02_recovery", "tarball"),
    ("ct02_realized_guard", "method_host_route"),
    ("ct02_realized_guard", "headers_body"),
    ("ct02_realized_guard", "timeout_matrix"),
    ("ct02_failed_unknown", "failed_then_corrected"),
    ("ct02_transport", "would_block_revoke"),
    ("ct02_transport", "partial_unknown"),
    ("ct02_authority_atomic", "rollback_stall_unpublished_restart"),
    ("ct02_authority_wait", "activation_pause_expiry"),
)
assert set(ORDER) == SUPPLEMENT_REQUIRED_PAIRS


def _sha(path):
    value = sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            value.update(chunk)
    return value.hexdigest()


def _root(path):
    root = Path(path).resolve(strict=True)
    approved = Path("/Users/larrymitchell/Mach33/EzLLMRouter-artifacts").resolve(strict=True)
    if approved not in root.parents or root.is_symlink() or not root.is_dir():
        raise RuntimeError("dedicated existing EzLLMRouter-artifacts root required")
    return root


def _durable(root):
    database = root / "campaign.sqlite"
    if not database.is_file() or database.is_symlink():
        raise RuntimeError("original durable campaign unavailable")
    # A stopped WAL may contain accepted history; never use immutable=1 then.
    wal = Path(str(database) + "-wal")
    shm = Path(str(database) + "-shm")
    if wal.exists() != shm.exists() or any(p.is_symlink() for p in (wal, shm)):
        raise RuntimeError("unsafe or incomplete stopped SQLite sidecars")
    mode = "mode=ro" if wal.exists() else "immutable=1"
    with sqlite3.connect("file:" + str(database) + "?" + mode, uri=True) as db:
        row = db.execute(
            "SELECT record FROM dev12_campaigns WHERE campaign_id=?", (EXPECTED_CAMPAIGN,)
        ).fetchone()
        if row is None:
            raise RuntimeError("retained campaign row absent")
        campaign = json.loads(row[0])
        counts = {
            name: db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
            for name, table in (
                ("submissions", "dev12_submissions"),
                ("ownership", "dev12_send_ownership"),
                ("usage_revisions", "dev12_usage_revisions"),
            )
        }
        states = dict(
            db.execute(
                "SELECT json_extract(record,'$.submission_state'), "
                "COUNT(*) FROM dev12_submissions GROUP BY 1"
            ).fetchall()
        )
    counts["receiver_arrivals"] = len((root / "receiver.jsonl").read_bytes().splitlines())
    return campaign, counts, states


def _legacy_durable(root):
    """Read the other wire's durable admissions before any new release."""
    database = root / "campaign.sqlite"
    wal = Path(str(database) + "-wal")
    mode = "mode=ro" if wal.exists() else "immutable=1"
    with sqlite3.connect("file:" + str(database) + "?" + mode, uri=True) as db:
        counts = {
            name: db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
            for name, table in (
                ("admissions", "submissions"),
                ("intents", "intents"),
                ("guard_dispatches", "guard_dispatches"),
                ("usage_revisions", "usage_revisions"),
            )
        }
        owners = db.execute(
            "SELECT COUNT(*) FROM work_key_owners WHERE contract_version='0.2'"
        ).fetchone()[0]
        possible_attempts = {
            row[0]
            for table in ("intents", "guard_dispatches")
            for row in db.execute("SELECT attempt_id FROM " + table)
        }
    if owners != counts["admissions"] or counts["intents"] > counts["admissions"]:
        raise RuntimeError("legacy owner/intent census inconsistent")
    counts["owners"] = owners
    counts["possible_send_upper_count"] = len(possible_attempts)
    # The retained legacy admission has no native finite reservation. A
    # failed-before-transmit label is not a zero-dollar financial bound.
    counts["finite_financial_upper_bound"] = None if counts["admissions"] else "0.000000000"
    return counts


def _baseline(root):
    original = root / "plan.json"
    if not original.is_file() or original.is_symlink():
        raise RuntimeError("original immutable plan absent")
    original_raw = original.read_bytes()
    original_plan = json.loads(original_raw)
    envelope = original_plan["envelope"]
    if (envelope["campaign_id"], envelope["budget_account_id"], envelope["financial_owner_id"]) != (
        EXPECTED_CAMPAIGN,
        EXPECTED_BUDGET,
        EXPECTED_OWNER,
    ):
        raise RuntimeError("original scope differs")
    plans = [original_plan]
    for number in range(1, 9):
        path = root / f"plan.continuation{number}.json"
        receipt = root / f"preflight-receipt-continuation{number}.json"
        if not path.is_file() or not receipt.is_file():
            raise RuntimeError("original continuation plan or receipt missing")
        raw = path.read_bytes()
        if json.loads(receipt.read_bytes())["plan_sha256"] != sha256(raw).hexdigest():
            raise RuntimeError("original continuation receipt/plan differs")
        plans.append(json.loads(raw))
    by_id = {case["id"]: case for plan in plans for case in plan["cases"]}
    ended = [
        row for row in _journal_rows(root / "case-journal.jsonl") if row.get("kind") == "case_end"
    ]
    passed = [row for row in ended if row.get("status") == "PASS"]
    failed = [row for row in ended if row.get("status") == "FAIL"]
    if (
        len(passed) != len(REQUIRED_PAIRS)
        or len(failed) != 6
        or {(row["scenario_id"], row["variant"]) for row in passed} != REQUIRED_PAIRS
        or {row["case_id"] for row in failed} != EXPECTED_FAILURES
    ):
        raise RuntimeError("retained 80 PASS/six failure census differs")
    for row in passed:
        case = by_id.get(row["case_id"])
        if case is None or row["verification"]["status"] != "PASS":
            raise RuntimeError("retained case lacks original plan or verified result")
        checked = verify_case_result(
            case, row["result"], root, actual=row["actual_correlation"], require_actual=True
        )
        if checked["status"] != "PASS":
            raise RuntimeError("retained result/evidence differs: " + row["case_id"])
    release = _journal_rows(root / "release-identity.jsonl")[0]
    return {
        "original_plan_sha256": sha256(original_raw).hexdigest(),
        "original_source_tree": original_plan["source_tree"],
        "original_mounted_source": release["mounted_source"],
        "artifacts": original_plan["artifacts"],
        "envelope": envelope,
        "pass_count": len(passed),
        "failed_ids": sorted(EXPECTED_FAILURES),
        "journal_sha256": _sha(root / "case-journal.jsonl"),
    }


def _now():
    return datetime.now(timezone.utc)


def _eligible(
    campaign,
    *,
    legacy,
    allocated_admissions=0,
    allocated_sends=0,
    allocated_usd=Decimal(0),
    permit_paused=False,
):
    if (
        campaign.get("campaign_id"),
        campaign.get("budget_account_id"),
        campaign.get("financial_owner_id"),
        campaign.get("start_at"),
        campaign.get("expires_at"),
        campaign.get("currency"),
        campaign.get("ceiling_decimal"),
        campaign.get("max_attempts"),
        campaign.get("max_concurrent"),
    ) != (
        EXPECTED_CAMPAIGN,
        EXPECTED_BUDGET,
        EXPECTED_OWNER,
        EXPECTED_START,
        EXPECTED_EXPIRY,
        "USD",
        "6.000000000",
        512,
        2,
    ):
        raise RuntimeError("retained finite campaign identity/bounds differ")
    if _now() >= datetime.strptime(EXPECTED_EXPIRY, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    ):
        raise RuntimeError("original 24-hour campaign deadline expired")
    if campaign["inflight_count"] != 0 or (campaign["paused"] and not permit_paused):
        raise RuntimeError("retained campaign has in-flight work or active pause")
    if (
        campaign["attempt_count"] + legacy["admissions"] + allocated_admissions > 512
        or campaign["possible_send_count"] + legacy["possible_send_upper_count"] + allocated_sends
        > 512
    ):
        raise RuntimeError("remaining original aggregate allowance insufficient")
    if legacy["finite_financial_upper_bound"] is None:
        raise RuntimeError("legacy financial upper bound unestablished; mixed release fails closed")
    if Decimal(campaign["cumulative_reserved_decimal"]) + Decimal(
        legacy["finite_financial_upper_bound"]
    ) + allocated_usd > Decimal("6"):
        raise RuntimeError("remaining original aggregate financial allowance insufficient")


def _supplement_prefix(root):
    """Independently inspect accepted supplement evidence without replaying it."""
    rows = [
        row
        for row in _journal_rows(root / "case-journal.jsonl")
        if row.get("kind") in {"supplement_case_end", "supplement_case_reconciled"}
    ]
    completed = []
    for scenario, variant in ORDER:
        case_id = "case." + scenario + "." + variant
        matching = [
            row
            for row in rows
            if row.get("case_id") == case_id
            or str(row.get("case_id", "")).startswith(case_id + ".continuation")
        ]
        passed = [row for row in matching if row.get("status") == "PASS"]
        if scenario == "ct02_workkey" and variant == "wire03_first":
            # Plan 4's weak predicate accepted a prewrite FDC failure. Preserve
            # the historical PASS row but never credit it as qualification.
            passed = [row for row in passed if _wire03_sent_once(root, row)]
        if not passed:
            break
        if len(passed) != 1 or matching[-1] is not passed[0]:
            raise RuntimeError("supplement result repeated or contradicted")
        result = passed[0]["result"]
        checks = {item["id"]: item for item in result["assertions"]}
        if (
            result["status"] != "PASS"
            or set(checks) != set(SUPPLEMENT_PREDICATES[(scenario, variant)])
            or any(item.get("passed") is not True for item in checks.values())
        ):
            raise RuntimeError("prior supplement objective differs")
        for observation in result["observations"]:
            retained = snapshot(root / observation["evidence_path"])
            if retained["sha256"] != observation["sha256"]:
                raise RuntimeError("prior supplement primary evidence changed")
        completed.append((scenario, variant))
    for scenario, variant in ORDER[len(completed) + 1 :]:
        ident = "case." + scenario + "." + variant
        if any(
            (
                row.get("case_id") == ident
                or str(row.get("case_id", "")).startswith(ident + ".continuation")
            )
            and row.get("status") == "PASS"
            for row in rows
        ):
            raise RuntimeError("supplement journal skipped a required predecessor")
    if len(completed) == len(ORDER):
        raise RuntimeError("all supplement cases already complete")
    return completed


def _wire03_sent_once(root, row):
    result = row.get("result", {})
    observations = result.get("observations", [])
    if not observations:
        return False
    path = root / observations[0]["evidence_path"]
    if not path.is_file() or path.is_symlink():
        return False
    payload = json.loads(path.read_bytes()).get("payload", {})
    before, middle, first = (payload.get(name) for name in ("before", "middle", "first"))
    return bool(
        before
        and middle
        and first
        and first.get("status")
        and first["status"].get("submission_state") == "completed"
        and middle["receiver_arrivals"] == before["receiver_arrivals"] + 1
        and middle["guard_ownership"] == before["guard_ownership"] + 1
    )


def reconcile_contention(root):
    """Credit the already observed HTTP race after independent no-send audit."""
    if not _clean_relevant_source():
        raise RuntimeError("reconciliation requires committed source")
    case_id = "case.ct02_workkey.http_contention.continuation5"
    source = root / "cases" / (case_id + ".json")
    output = root / "cases" / (case_id + ".reconciled.json")
    if not source.is_file() or source.is_symlink() or output.exists():
        raise RuntimeError("exact retained failed case or one-use output unavailable")
    ends = [
        row
        for row in _journal_rows(root / "case-journal.jsonl")
        if row.get("kind") == "supplement_case_end"
    ]
    if not ends or ends[-1].get("case_id") != case_id or ends[-1].get("status") != "FAIL":
        raise RuntimeError("retained HTTP contention stop differs")
    document = json.loads(source.read_bytes())
    if (
        document.get("case_id") != case_id
        or document.get("checks", {}).get("ct02_workkey.http_contention", {}).get("passed")
        is not False
    ):
        raise RuntimeError("original weak-predicate evidence differs")
    evidence = document["payload"]
    first, conflict = evidence["first"], evidence["conflict"]
    before, after = evidence["before"], evidence["after"]
    attempt_id = first.get("reply", {}).get("attempt_id")
    submission_id = first.get("reply", {}).get("handle", {}).get("submission_id")
    campaign, counts, _ = _durable(root)
    with sqlite3.connect("file:" + str(root / "campaign.sqlite") + "?immutable=1", uri=True) as db:
        ownership = db.execute(
            "SELECT COUNT(*) FROM dev12_send_ownership WHERE attempt_id=? AND submission_id=?",
            (attempt_id, submission_id),
        ).fetchone()[0]
        current = db.execute(
            "SELECT record FROM dev12_submissions WHERE submission_id=?", (submission_id,)
        ).fetchone()
    receiver = [
        row for row in _journal_rows(root / "receiver.jsonl") if row.get("attempt_id") == attempt_id
    ]
    checked = bool(
        attempt_id
        and submission_id
        and ownership == 1
        and len(receiver) == 1
        and current
        and json.loads(current[0])["submission_state"] == "completed"
        and first.get("status", {}).get("submission_state") == "completed"
        and conflict.get("http_status") == 409
        and conflict.get("reply", {}).get("code") == "WORK_CONFLICT"
        and conflict.get("reply", {}).get("retry_guidance") == "never"
        and evidence["owner"] == {"contract_version": "0.3", "submission_id": submission_id}
        and evidence["legacy_after"] == evidence["legacy_before"]
        and after["submissions"] == before["submissions"] + 1
        and after["guard_ownership"] == before["guard_ownership"] + 1
        and after["receiver_arrivals"] == before["receiver_arrivals"] + 1
        and after["campaign"]["attempt_count"] == before["campaign"]["attempt_count"] + 1
        and after["campaign"]["possible_send_count"]
        == before["campaign"]["possible_send_count"] + 1
        and campaign == after["campaign"]
        and counts["receiver_arrivals"] == after["receiver_arrivals"]
    )
    if not checked:
        raise RuntimeError("retained contention did not prove one owned HTTP send")
    value = {
        "kind": "dev12_contention_read_only_reconciliation_v1",
        "case_id": case_id,
        "source_evidence_sha256": _sha(source),
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "source_tree": _tree(),
        "attempt_id": attempt_id,
        "submission_id": submission_id,
        "guard_ownership_rows": ownership,
        "receiver_arrival_rows": len(receiver),
        "campaign_before": campaign,
        "counts_before": counts,
        "reason": "same-wire 0.3 conflict is WORK_CONFLICT; old predicate expected cross-version code",
        "real_provider_calls": 0,
    }
    with output.open("xb") as stream:
        stream.write(_json_bytes(value))
        stream.flush()
        os.fsync(stream.fileno())
    after_campaign, after_counts, _ = _durable(root)
    if after_campaign != campaign or after_counts != counts:
        raise RuntimeError("read-only reconciliation changed durable campaign")
    retained = snapshot(output)
    relative = str(output.relative_to(root))
    result = {
        "status": "PASS",
        "assertions": [
            {
                "id": "ct02_workkey.http_contention",
                "passed": True,
                "executed": True,
                "detail": "Recomputed one normal HTTP winner and WORK_CONFLICT loser from retained primary evidence",
                "evidence_paths": [relative],
            }
        ],
        "observations": [
            {
                "stage": "admission",
                "evidence_path": relative,
                "sha256": retained["sha256"],
                "case_id": case_id,
                "observed": {
                    "attempt_id": attempt_id,
                    "submission_id": submission_id,
                    "guard_rows": ownership,
                    "receiver_rows": len(receiver),
                },
            }
        ],
    }
    append_durable(
        root / "case-journal.jsonl",
        {
            "kind": "supplement_case_reconciled",
            "at": time.time_ns(),
            "case_id": case_id,
            "status": "PASS",
            "result": result,
            "source_evidence_sha256": _sha(source),
            "campaign_after": campaign,
            "receiver_arrivals_after": counts["receiver_arrivals"],
            "no_new_admission_or_send": True,
        },
    )
    return {
        "status": "PASS",
        "case_id": case_id,
        "evidence": retained,
        "campaign_attempts": campaign["attempt_count"],
        "receiver_arrivals": counts["receiver_arrivals"],
    }


def build(root, ordinal):
    if not _clean_relevant_source():
        raise RuntimeError("reviewed source must be committed before a prospective plan")
    baseline = _baseline(root)
    campaign, counts, states = _durable(root)
    completed = _supplement_prefix(root)
    if not completed and (
        campaign["attempt_count"],
        campaign["possible_send_count"],
        campaign["cumulative_reserved_decimal"],
        campaign["inflight_count"],
        counts["submissions"],
        counts["ownership"],
        counts["usage_revisions"],
        counts["receiver_arrivals"],
    ) != (91, 91, "0.027600030", 0, 91, 91, 94, 80):
        raise RuntimeError("initial reviewed durable state differs; inspect before planning")
    if completed:
        last = next(
            row
            for row in reversed(_journal_rows(root / "case-journal.jsonl"))
            if row.get("kind") == "supplement_case_end"
        )
        for field in (
            "attempt_count",
            "possible_send_count",
            "start_at",
            "expires_at",
            "cumulative_reserved_decimal",
        ):
            if campaign[field] != last["campaign_after"][field]:
                raise RuntimeError("durable campaign differs from stopped supplement")
        if counts["receiver_arrivals"] != last["receiver_arrivals_after"]:
            raise RuntimeError("independent receiver census differs from stopped supplement")
    cases = []
    for scenario, variant in ORDER[len(completed) :]:
        admissions, sends = SUPPLEMENT_LIMITS.get((scenario, variant), (0, 0))
        if sends > admissions:
            raise RuntimeError("prospective send exceeds admission allocation")
        base_id = "case." + scenario + "." + variant
        case_id = (
            base_id + ".continuation" + str(ordinal)
            if (root / "cases" / (base_id + ".json")).exists()
            else base_id
        )
        cases.append(
            {
                "id": case_id,
                "scenario_id": scenario,
                "variant": variant,
                "handler": "supplement",
                "predicates": list(SUPPLEMENT_PREDICATES[(scenario, variant)]),
                "max_admissions": admissions,
                "max_possible_sends": sends,
                "max_exposure_decimal": f"{Decimal(admissions) / 100:.9f}",
                "classification": "read-only reporting"
                if scenario == "ct02_reporting"
                else "missing/affected target case",
                "phase": "terminal" if scenario == "ct02_authority_wait" else "normal",
                "attempt_group": "attempt-group." + scenario + "." + variant,
                "evidence_paths": ["cases/" + case_id + ".json"],
                "handler_sha256": _sha(HERE / "dev12_completion_supplement_handlers.py"),
            }
        )
    plan = {
        "kind": "dev12_completion02_same_campaign_supplement_v1",
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "source_tree": _tree(),
        "mounted_source_identity": mounted_source_identity(),
        "original": baseline,
        "envelope": baseline["envelope"],
        "before": {"campaign": campaign, "counts": counts, "states": states},
        "completed_pairs": [list(pair) for pair in completed],
        "cases": cases,
        "artifacts": baseline["artifacts"],
    }
    _eligible(
        campaign,
        legacy=_legacy_durable(root),
        allocated_admissions=sum(c["max_admissions"] for c in cases),
        allocated_sends=sum(c["max_possible_sends"] for c in cases),
        allocated_usd=sum((Decimal(c["max_exposure_decimal"]) for c in cases), Decimal(0)),
    )
    return plan


def check(plan, root, *, host):
    if plan.get("kind") != "dev12_completion02_same_campaign_supplement_v1":
        raise RuntimeError("supplement plan kind differs")
    completed = _supplement_prefix(root)
    if plan.get("completed_pairs") != [list(pair) for pair in completed] or [
        (c["scenario_id"], c["variant"]) for c in plan["cases"]
    ] != list(ORDER[len(completed) :]):
        raise RuntimeError("fixed missing-case inventory differs")
    if not all(
        c["predicates"] == list(SUPPLEMENT_PREDICATES[(c["scenario_id"], c["variant"])])
        and (c["max_admissions"], c["max_possible_sends"])
        == SUPPLEMENT_LIMITS.get((c["scenario_id"], c["variant"]), (0, 0))
        and c["handler_sha256"] == _sha(HERE / "dev12_completion_supplement_handlers.py")
        for c in plan["cases"]
    ):
        raise RuntimeError("handler, predicates or resource allocation differs")
    for case in plan["cases"]:
        base_id = "case." + case["scenario_id"] + "." + case["variant"]
        if case["id"] != base_id and not case["id"].startswith(base_id + ".continuation"):
            raise RuntimeError("supplement retry case identity differs")
        if (root / case["evidence_paths"][0]).exists():
            raise RuntimeError("supplement evidence path already consumed")
    if plan["mounted_source_identity"] != mounted_source_identity():
        raise RuntimeError("mounted source differs from prospective plan")
    if host and (
        not _clean_relevant_source()
        or plan["source_tree"] != _tree()
        or plan["source_commit"]
        != subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    ):
        raise RuntimeError("committed reviewed source differs")
    baseline = _baseline(root)
    if baseline != plan["original"] or baseline["artifacts"] != plan["artifacts"]:
        raise RuntimeError("retained original plan/artifacts changed")
    for artifact in plan["artifacts"]:
        if artifact["kind"] in {"python_wheel", "js_tarball"}:
            if host and _sha(artifact["path"]) != artifact["sha256"]:
                raise RuntimeError("exact installed-client archive changed")
        elif host:
            found = subprocess.run(
                ["docker", "image", "inspect", artifact["path"], "--format", "{{.Id}}"],
                capture_output=True,
                text=True,
            )
            if found.returncode or found.stdout.strip() != artifact["path"]:
                raise RuntimeError("exact frozen target image unavailable")
    campaign, counts, _states = _durable(root)
    initial = plan["before"]
    if campaign != initial["campaign"] or counts != initial["counts"]:
        raise RuntimeError("durable state changed since prospective build")
    _eligible(
        campaign,
        legacy=_legacy_durable(root),
        allocated_admissions=sum(c["max_admissions"] for c in plan["cases"]),
        allocated_sends=sum(c["max_possible_sends"] for c in plan["cases"]),
        allocated_usd=sum((Decimal(c["max_exposure_decimal"]) for c in plan["cases"]), Decimal(0)),
    )
    return {
        "kind": "dev12_completion02_supplement_no_send_gate_v1",
        "status": "PASS",
        "plan_sha256": None,
        "source_commit": plan["source_commit"],
        "source_tree": plan["source_tree"],
        "mounted_source_identity": plan["mounted_source_identity"],
        "original_plan_sha256": baseline["original_plan_sha256"],
        "campaign_before": campaign,
        "counts_before": counts,
        "case_count": len(plan["cases"]),
        "completed_pairs": plan["completed_pairs"],
        "pairs": [list(p) for p in ORDER],
        "max_new_admissions": sum(c["max_admissions"] for c in plan["cases"]),
        "max_new_possible_sends": sum(c["max_possible_sends"] for c in plan["cases"]),
        "max_new_exposure_decimal": str(
            sum((Decimal(c["max_exposure_decimal"]) for c in plan["cases"]), Decimal(0))
        ),
        "real_provider_calls": 0,
    }


def release(plan, root, receipt):
    raw = _json_bytes(plan)
    if (
        receipt.get("kind") != "dev12_completion02_supplement_no_send_gate_v1"
        or receipt.get("status") != "PASS"
        or receipt.get("plan_sha256") != sha256(raw).hexdigest()
        or receipt.get("mounted_source_identity") != mounted_source_identity()
    ):
        raise RuntimeError("exact host no-send gate receipt differs")
    # Inside the image, verify original evidence and mutable durable state
    # immediately before the only release; host checked exact local images.
    check(plan, root, host=False)
    old = plan["original"]
    checkpoint = {
        "last_campaign": plan["before"]["campaign"],
        "original_expires_at": EXPECTED_EXPIRY,
        "original_start_at": EXPECTED_START,
        "original_plan_sha256": old["original_plan_sha256"],
        "original_source_tree": old["original_source_tree"],
        "original_mounted_source": old["original_mounted_source"],
    }
    append_durable(
        root / "release-gate.jsonl",
        {
            "kind": "supplement_release_gate",
            "at": time.time_ns(),
            "plan_sha256": receipt["plan_sha256"],
            "preflight_receipt_sha256": sha256(_json_bytes(receipt)).hexdigest(),
            "original_start_at": EXPECTED_START,
            "original_expires_at": EXPECTED_EXPIRY,
        },
    )
    runtime = CompletionRuntime(plan, root, {"supplement": supplement})
    try:
        runtime.continue_existing(checkpoint, receipt)
        for case in plan["cases"]:
            before = runtime.allowance.inspect()
            _eligible(
                before,
                legacy=_legacy_durable(root),
                allocated_admissions=case["max_admissions"],
                allocated_sends=case["max_possible_sends"],
                allocated_usd=Decimal(case["max_exposure_decimal"]),
            )
            arrivals_before = len(runtime.receiver_log.read_bytes().splitlines())
            append_durable(
                runtime.journal,
                {
                    "kind": "supplement_case_begin",
                    "at": time.time_ns(),
                    "case_id": case["id"],
                    "plan_sha256": receipt["plan_sha256"],
                    "campaign_before": before,
                    "receiver_arrivals_before": arrivals_before,
                },
            )
            try:
                result = supplement(runtime, case)
                after = runtime.allowance.inspect()
                arrivals_after = len(runtime.receiver_log.read_bytes().splitlines())
                assertions = {row["id"]: row for row in result["assertions"]}
                if (
                    result["status"] != "PASS"
                    or set(assertions) != set(case["predicates"])
                    or any(
                        row["passed"] is not True or row["executed"] is not True
                        for row in assertions.values()
                    )
                    or after["attempt_count"] - before["attempt_count"] > case["max_admissions"]
                    or after["possible_send_count"] - before["possible_send_count"]
                    > case["max_possible_sends"]
                    or arrivals_after - arrivals_before > case["max_possible_sends"]
                    or Decimal(after["cumulative_reserved_decimal"])
                    - Decimal(before["cumulative_reserved_decimal"])
                    > Decimal(case["max_exposure_decimal"])
                ):
                    raise AssertionError("objective or finite case bound failed")
                for row in result["observations"]:
                    evidence = snapshot(root / row["evidence_path"])
                    if row["sha256"] != evidence["sha256"]:
                        raise AssertionError("case evidence differs from retained bytes")
                append_durable(
                    runtime.journal,
                    {
                        "kind": "supplement_case_end",
                        "at": time.time_ns(),
                        "case_id": case["id"],
                        "status": "PASS",
                        "result": result,
                        "campaign_after": after,
                        "receiver_arrivals_after": arrivals_after,
                    },
                )
            except BaseException as exc:
                append_durable(
                    runtime.journal,
                    {
                        "kind": "supplement_case_end",
                        "at": time.time_ns(),
                        "case_id": case["id"],
                        "status": "FAIL",
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:1000],
                        "campaign_after": runtime.allowance.inspect(),
                        "receiver_arrivals_after": len(
                            runtime.receiver_log.read_bytes().splitlines()
                        ),
                    },
                )
                raise
    finally:
        runtime.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "preflight", "release", "reconcile-contention"))
    parser.add_argument("artifact_root")
    parser.add_argument("--ordinal", type=int, default=1)
    args = parser.parse_args(argv)
    root = _root(args.artifact_root)
    if args.action == "reconcile-contention":
        if args.ordinal != 5:
            raise RuntimeError("retained contention reconciliation requires plan 5")
        print(json.dumps(reconcile_contention(root), sort_keys=True))
        return
    if not 1 <= args.ordinal <= 32:
        raise RuntimeError("bounded supplement plan ordinal required")
    plan_path = root / f"plan.supplement{args.ordinal}.json"
    receipt_path = root / f"preflight-receipt-supplement{args.ordinal}.json"
    if args.action == "build":
        if args.ordinal > 1:
            previous_plan = root / f"plan.supplement{args.ordinal - 1}.json"
            previous_receipt = root / f"preflight-receipt-supplement{args.ordinal - 1}.json"
            if not previous_plan.is_file() or not previous_receipt.is_file():
                raise RuntimeError("prior supplement plan and receipt absent")
            previous_hash = _sha(previous_plan)
            if json.loads(previous_receipt.read_bytes())["plan_sha256"] != previous_hash:
                raise RuntimeError("prior supplement receipt differs")
            gates = [
                row
                for row in _journal_rows(root / "release-gate.jsonl")
                if row.get("kind") == "supplement_release_gate"
                and row.get("plan_sha256") == previous_hash
            ]
            entries = [
                row
                for row in _journal_rows(root / "case-journal.jsonl")
                if row.get("kind") == "supplement_case_end"
            ]
            if len(gates) != 1 or (entries and entries[-1]["status"] != "FAIL"):
                raise RuntimeError("prior supplement is not a stopped failed release")
            _supplement_prefix(root)
        plan = build(root, args.ordinal)
        with plan_path.open("xb") as stream:
            stream.write(_json_bytes(plan))
            stream.flush()
            os.fsync(stream.fileno())
        print(
            json.dumps(
                {"plan": str(plan_path), "sha256": _sha(plan_path), "cases": len(plan["cases"])}
            )
        )
        return
    plan_bytes = plan_path.read_bytes()
    plan = json.loads(plan_bytes)
    if plan_bytes != _json_bytes(plan):
        raise RuntimeError("prospective plan canonical bytes differ")
    if args.action == "preflight":
        receipt = check(plan, root, host=True)
        receipt["plan_sha256"] = sha256(plan_bytes).hexdigest()
        with receipt_path.open("xb") as stream:
            stream.write(_json_bytes(receipt))
            stream.flush()
            os.fsync(stream.fileno())
        print(json.dumps(receipt, sort_keys=True))
        return
    receipt_bytes = receipt_path.read_bytes()
    receipt = json.loads(receipt_bytes)
    if receipt_bytes != _json_bytes(receipt):
        raise RuntimeError("host receipt canonical bytes differ")
    release(plan, root, receipt)


if __name__ == "__main__":
    main()
