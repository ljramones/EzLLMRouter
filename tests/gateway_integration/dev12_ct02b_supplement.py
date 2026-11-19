"""One-use, separately authorized CT02-02b synthetic first-owner target.

Preparation and accounting use only retained public evidence and a read-only
view of the original campaign.  The sole target action runs in its own root.
Importing this module has no target side effects.
"""
from __future__ import annotations

from base64 import b64encode
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import http.client
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

CASE = "case.ct02.first_owner.supp01"
CAMPAIGN = "campaign.dev12.c02.ct02b.supp01"
BUDGET = "budget.dev12.c02.ct02b.supp01"
OWNER = "team.dev12.c02.20261026.continue01"
ROOT_BASENAME = "dev12-ct02b-supplement01-20261027"
ORIGINAL = "campaign.dev12.c02.20261026.continue01"
EXPIRY = "2026-10-27T21:54:14Z"
ADJUDICATION_SHA = "cc91beb2b2e4bf4a6d550b6c6069f713c0823922fc9e0785a0887131a2634c19"
PREDECESSOR_PACKET_SHA = "f09496b63b84c726f34c80c74d5dd93c6d2b5282d58727be2d3de66695479a30"
SOURCE_DB_SHA = "dc464ddca3c06c2d39d1f04defa5668ceac18d5fb73576556dafc067cdcf676e"
STEP = "step.completion02.ct02.first_owner.supp01"
GENERATION = "gen.ct02b.supp01"
NANO = Decimal("0.000000001")
ALLOC = Decimal("0.010000000")
ROOT_FILES = ("campaign.sqlite", "receiver.jsonl", "receiver-receipts.jsonl",
              "guard.jsonl", "case-journal.jsonl", "release-identity.jsonl",
              "release-gate.jsonl")


def digest(raw):
    return sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def utc(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def now():
    return datetime.now(timezone.utc)


def durable_json(path, value):
    raw = json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True).encode() + b"\n"
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return digest(raw)


def original_snapshot(root):
    if not root.is_dir() or root.is_symlink():
        raise ValueError("original target root unavailable")
    result = {name: digest((root / name).read_bytes()) for name in ROOT_FILES}
    if result["campaign.sqlite"] != SOURCE_DB_SHA:
        raise AssertionError("original campaign database changed")
    db = sqlite3.connect(f"file:{root / 'campaign.sqlite'}?immutable=1", uri=True)
    try:
        row = db.execute("SELECT record FROM dev12_campaigns WHERE campaign_id=?",
                         (ORIGINAL,)).fetchone()
        if row is None:
            raise AssertionError("original campaign missing")
        campaign = json.loads(row[0])
        authority_row = db.execute("SELECT state FROM dev12_authority WHERE "
            "authority_id='standalone.synthetic'").fetchone()
        grant_row = db.execute("SELECT record FROM registry_grants WHERE "
            "principal_id='user.demo' AND config_ref='cfg.synthetic.dev12.operator'").fetchone()
        if authority_row is None or grant_row is None:
            raise AssertionError("current synthetic authority or grant missing")
        authority = json.loads(authority_row[0])
        grant = json.loads(grant_row[0])
        counts = {name: db.execute("SELECT COUNT(*) FROM " + name).fetchone()[0]
                  for name in ("dev12_submissions", "dev12_send_ownership",
                               "dev12_usage_revisions", "submissions", "intents",
                               "guard_dispatches", "usage_revisions")}
        rows = {name: [dict(zip([column[0] for column in db.execute(
            "SELECT * FROM " + name + " LIMIT 0").description], row))
            for row in db.execute("SELECT * FROM " + name)]
            for name in ("submissions", "intents", "work_key_owners")}
    finally:
        db.close()
    if (campaign["paused"] is not True or campaign["pause_reasons"] != ["authority"] or
            campaign["expires_at"] != EXPIRY or campaign["attempt_count"] != 123 or
            campaign["possible_send_count"] != 108 or
            campaign["cumulative_reserved_decimal"] != "0.034000030" or
            campaign["inflight_count"] != 0 or
            (counts["dev12_submissions"], counts["dev12_send_ownership"],
             counts["dev12_usage_revisions"], counts["submissions"],
             counts["intents"], counts["guard_dispatches"], counts["usage_revisions"]) !=
            (123, 108, 139, 1, 1, 0, 0)):
        raise AssertionError("original paused mixed ledger differs")
    if (authority.get("send_permission") is not True or
            grant.get("status") != "active" or "execution" not in grant.get("purposes", [])):
        raise PermissionError("independent synthetic send authority or grant denied")
    return {"file_sha256": result, "campaign": campaign, "counts": counts,
            "legacy_rows": rows, "authority_send_permission": True,
            "synthetic_grant_status": grant["status"]}


def verify_legacy(adjudication_path, predecessor, original_root):
    raw = adjudication_path.read_bytes()
    if digest(raw) != ADJUDICATION_SHA:
        raise AssertionError("legacy adjudication identity differs")
    adj = json.loads(raw)
    if (adj["status"] != "REVIEW_ADJUDICATED_TARGET_BOOKING_NOT_APPLIED" or
            adj["adjudication"]["target_booking_applied"] is not False or
            adj["legacy_attempt"]["observed_native_cost_decimal"] is not None or
            adj["historical_accounting"]["current_recorded_mixed_financial_upper_bound"] is not None or
            adj["adjudication"]["proposed_allocation_usd"] != "0.010000000"):
        raise AssertionError("adjudication prior null state or amount differs")
    bindings = adj["evidence_bindings"]
    for item in bindings.values():
        if isinstance(item, dict) and {"path", "sha256", "bytes"} <= set(item):
            path = predecessor / item["path"]
            if not path.is_file() or path.is_symlink() or path.stat().st_size != item["bytes"] or \
                    digest(path.read_bytes()) != item["sha256"]:
                raise AssertionError("review-bound evidence differs: " + item["path"])
    ledger = json.loads((predecessor / "evidence/final/ledger.json").read_bytes())
    snapshot = original_snapshot(original_root)
    select = adj["evidence_bindings"]["primary_rows"]
    for name, spec in select.items():
        matching = [row for row in ledger[name]["rows"] if all(
            row.get(key) == value for key, value in spec["selection"].items())]
        if len(matching) != 1 or digest(canonical(matching[0])) != spec["canonical_row_sha256"]:
            raise AssertionError("adjudicated public primary row differs: " + name)
        current = [row for row in snapshot["legacy_rows"][name] if all(
            row.get(key) == value for key, value in spec["selection"].items())]
        if current != matching:
            raise AssertionError("current original legacy row differs: " + name)
        for field, expected in (("record", spec.get("raw_record_string_utf8_sha256")),
                                ("intent", spec.get("raw_intent_string_utf8_sha256"))):
            if expected is not None and digest(matching[0][field].encode()) != expected:
                raise AssertionError("legacy raw string binding differs")
    if len(snapshot["legacy_rows"]["submissions"]) != 1 or \
            len(snapshot["legacy_rows"]["intents"]) != 1:
        raise AssertionError("additional unadjudicated legacy rows")
    if (bindings["original_raw_database"]["declared_sha256"] != SOURCE_DB_SHA or
            adj["historical_accounting"]["mixed_admissions"] != 124 or
            adj["historical_accounting"]["mixed_possible_send_conservative_upper_count"] != 109):
        raise AssertionError("legacy aggregate differs")
    for ref in ("case_journal", "release_gate", "release_identity"):
        lines = (predecessor / bindings[ref]["path"]).read_bytes().splitlines(keepends=True)
        for row in bindings[ref]["matched_lines"]:
            if digest(lines[row["line_number_1_based"] - 1]) != \
                    row["line_sha256_including_terminator"]:
                raise AssertionError("adjudicated journal/release line differs")
    source = bindings["tested_source"]
    archive = source["snapshot"]
    archive_path = predecessor / archive["path"]
    if (archive_path.stat().st_size != archive["bytes"] or
            digest(archive_path.read_bytes()) != archive["sha256"]):
        raise AssertionError("tested legacy source snapshot differs")
    with ZipFile(archive_path) as z:
        for name, spec in source["files_and_segments"].items():
            raw = z.read(spec["snapshot_member"])
            checked = (b"".join(raw.splitlines(keepends=True)[
                spec["first_line"] - 1:spec["last_line_inclusive"]])
                if "first_line" in spec else raw)
            if digest(checked) != spec["sha256"]:
                raise AssertionError("tested legacy source binding differs: " + name)
    from dev12_completion_source_audit import audit as source_audit
    checked = source_audit(predecessor / "evidence/source-lineage",
                           predecessor / "evidence/final")
    if checked["status"] != "PASS":
        raise AssertionError("source custody auditor rejected predecessor")
    return snapshot


def capacity_db(path):
    if path.is_symlink():
        raise ValueError("linked capacity record")
    db = sqlite3.connect(path, isolation_level=None, timeout=5)
    db.execute("PRAGMA synchronous=FULL")
    db.execute("CREATE TABLE IF NOT EXISTS allocations "
               "(allocation_key TEXT PRIMARY KEY, record TEXT NOT NULL)")
    return db


def _insert_once(path, key, value):
    raw = canonical(value).decode()
    db = capacity_db(path)
    try:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute("SELECT record FROM allocations WHERE allocation_key=?",
                              (key,)).fetchone()
        if existing is not None:
            if existing[0] != raw:
                raise AssertionError("single-use allocation conflict")
            outcome = "already_recorded"
        else:
            db.execute("INSERT INTO allocations VALUES (?,?)", (key, raw))
            outcome = "recorded"
        db.commit()
        returned = db.execute("SELECT record FROM allocations WHERE allocation_key=?",
                              (key,)).fetchone()
        if returned is None or returned[0] != raw:
            raise AssertionError("durable allocation readback differs")
        return outcome
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def book_legacy(capacity_path, adjudication_path, predecessor, original_root):
    snapshot = verify_legacy(adjudication_path, predecessor, original_root)
    key = ORIGINAL + "|attempt.c44e6978e5f24fcb891777dbfa0248bc|" + \
        "conservative_historical_case_capacity_consumption"
    record = {"kind": "historical_conservative_capacity_v1", "key": key,
              "adjudication_sha256": ADJUDICATION_SHA, "original_database_sha256": SOURCE_DB_SHA,
              "financial_owner_id": OWNER, "currency": "USD",
              "amount_decimal": "0.010000000", "observed_native_cost_decimal": None,
              "original_mixed_admissions": 124, "original_mixed_possible_send_slots": 109,
              "successor_cumulative_reservations_decimal": "0.034000030",
              "historical_conservative_consumption_decimal": "0.044000030",
              "original_file_sha256": snapshot["file_sha256"]}
    decision = _insert_once(capacity_path, key, record)
    return {"decision": decision, "record": record}


def release_allocation(capacity_path, adjudication_path, predecessor, original_root,
                       source_commit, source_tree, plan_sha, adopted_hash):
    booked = book_legacy(capacity_path, adjudication_path, predecessor, original_root)
    if now() >= utc(EXPIRY) - timedelta(minutes=20):
        raise PermissionError("insufficient original absolute window for sole target")
    if (Decimal(booked["record"]["historical_conservative_consumption_decimal"]) + ALLOC >
            Decimal("6.000000000")):
        raise AssertionError("aggregate ceiling insufficient")
    key = CAMPAIGN + "|single-use-release"
    record = {"kind": "ct02b_single_use_release_allocation_v1", "key": key,
              "campaign_id": CAMPAIGN, "budget_account_id": BUDGET,
              "financial_owner_id": OWNER, "currency": "USD",
              "max_admissions": 1, "max_possible_sends": 1, "max_concurrent": 1,
              "max_reservation_decimal": "0.010000000",
              "combined_max_admissions": 125, "combined_max_possible_send_slots": 110,
              "combined_max_conservative_consumption_decimal": "0.054000030",
              "original_expiry": EXPIRY, "original_database_sha256": SOURCE_DB_SHA,
              "original_file_sha256": booked["record"]["original_file_sha256"],
              "adjudication_sha256": ADJUDICATION_SHA,
              "source_commit": source_commit, "source_tree": source_tree,
              "plan_sha256": plan_sha, "adopted_instruction_sha256": adopted_hash}
    db = capacity_db(capacity_path)
    try:
        db.execute("BEGIN IMMEDIATE")
        rows = {row[0]: json.loads(row[1]) for row in db.execute(
            "SELECT allocation_key,record FROM allocations")}
        if (set(rows) != {booked["record"]["key"]} or
                rows[booked["record"]["key"]] != booked["record"]):
            raise PermissionError("single-use target allocation unavailable or already consumed")
        db.execute("INSERT INTO allocations VALUES (?,?)", (key, canonical(record).decode()))
        db.commit()
        if json.loads(db.execute("SELECT record FROM allocations WHERE allocation_key=?",
                                 (key,)).fetchone()[0]) != record:
            raise AssertionError("supplemental allocation readback differs")
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
    return record


def supplemental_limits(plan, finite_scope):
    envelope = plan["envelope"]
    expected = {"campaign_id": CAMPAIGN, "budget_account_id": BUDGET,
                "financial_owner_id": OWNER, "currency": "USD",
                "max_admissions": 1, "max_possible_sends": 1,
                "max_inflight": 1, "ceiling_decimal": "0.010000000",
                "absolute_expiry": EXPIRY}
    if any(envelope.get(key) != value for key, value in expected.items()):
        raise AssertionError("supplemental plan scope differs")
    if set(finite_scope) != {"resource_started_at", "original_expiry"} or \
            finite_scope["original_expiry"] != EXPIRY:
        raise AssertionError("single-use finite scope differs")
    started = utc(finite_scope["resource_started_at"])
    if now() >= started + timedelta(minutes=5) or now() >= utc(EXPIRY) - timedelta(minutes=11):
        raise PermissionError("ten-minute allowance cannot fit resource/absolute window")
    return {"max_attempts": 1, "max_concurrent": 1,
            "ceiling_decimal": "0.010000000", "window_hours": 1 / 6}


def verify_started_limits(campaign, finite_scope):
    started = utc(finite_scope["resource_started_at"])
    if (campaign["campaign_id"] != CAMPAIGN or campaign["budget_account_id"] != BUDGET or
            campaign["financial_owner_id"] != OWNER or campaign["currency"] != "USD" or
            campaign["max_attempts"] != 1 or campaign["max_concurrent"] != 1 or
            campaign["ceiling_decimal"] != "0.010000000" or
            campaign["attempt_count"] != 0 or campaign["possible_send_count"] != 0 or
            campaign["inflight_count"] != 0 or campaign["paused"] or
            utc(campaign["expires_at"]) > min(utc(EXPIRY), started + timedelta(minutes=15)) or
            utc(campaign["expires_at"]) <= now()):
        raise AssertionError("durable one-case allowance did not read back within bounds")
    return campaign


def request_pair(runtime):
    from dev12_integrated import fixture
    from ezllmrouter_server.successor_contract import work_projection, work_digest
    first, _context = fixture("DIRECT_DOCUMENT")
    trusted = runtime.contexts_by_credential[runtime.credentials["DIRECT_DOCUMENT"]]
    first["work_selector"] = {"task_id": "task.demo", "step_id": STEP,
        "step_revision": 1, "execution_generation": GENERATION}
    first["input"]["items"] = [{"item_id": "doc.1", "text": "Sky"}]
    second = deepcopy(first)
    second["input"]["items"][0]["text"] = "River"
    first_digest = work_digest(work_projection(first, trusted))
    second_digest = work_digest(work_projection(second, trusted))
    if first_digest == second_digest:
        raise AssertionError("contenders share canonical work digest")
    return first, second, first_digest, second_digest


def raw_post(runtime, request):
    from dev12_completion_handlers import _headers
    from dev12_completion_runner import append_durable
    headers = _headers(runtime)
    safe_headers = {key: value for key, value in headers.items() if key != "Authorization"}
    body = canonical(request)
    connection = http.client.HTTPConnection("127.0.0.1", runtime.service_port, timeout=15)
    try:
        connection.request("POST", "/v1/submissions", body, headers)
        response = connection.getresponse()
        raw = response.read()
        row = {"request_sha256": digest(body), "request_body_utf8": body.decode(),
                "request_headers_without_bearer": safe_headers,
                "http_status": response.status,
                "response_headers": dict(response.getheaders()),
                "response_body_utf8": raw.decode(), "response_sha256": digest(raw),
                "reply": json.loads(raw)}
        append_durable(runtime.root / "RAW-HTTP.jsonl", {"kind": "ct02b_raw_http",
            "thread_id": threading.get_ident(), "at_ns": time.time_ns(), **row})
        return row
    except BaseException as exc:
        append_durable(runtime.root / "RAW-HTTP.jsonl", {"kind": "ct02b_http_failure",
            "thread_id": threading.get_ident(), "at_ns": time.time_ns(),
            "request_sha256": digest(body), "request_body_utf8": body.decode(),
            "request_headers_without_bearer": safe_headers,
            "error_type": type(exc).__name__, "error": str(exc)[:300]})
        raise
    finally:
        connection.close()


def read_status(runtime, submission_id):
    token = runtime.credentials["DIRECT_DOCUMENT"]
    connection = http.client.HTTPConnection("127.0.0.1", runtime.service_port, timeout=10)
    try:
        connection.request("GET", "/v1/submissions/" + submission_id,
            headers={"Authorization": "Bearer " + token,
                     "EzLLMRouter-Contract-Version": "0.3"})
        reply = connection.getresponse()
        raw = reply.read()
        return {"http_status": reply.status, "response_headers": dict(reply.getheaders()),
                "body_sha256": digest(raw), "body": json.loads(raw)}
    finally:
        connection.close()


def retained_rows(runtime):
    names = ("dev12_campaign_attempts", "dev12_submissions", "dev12_send_ownership",
             "dev12_usage_revisions", "dev12_evidence_events", "work_key_owners")
    with runtime.store._lock:
        result = {}
        for name in names:
            cursor = runtime.store.db.execute("SELECT * FROM " + name + " ORDER BY rowid")
            columns = [column[0] for column in cursor.description]
            result[name] = [dict(zip(columns, row)) for row in cursor.fetchall()]
    return result


def run_single_target(runtime, plan, finite_scope):
    from dev12_completion_runner import append_durable
    from dev12_completion_sync_first_owner import synchronized_pair
    from dev12_completion_handlers import _census
    from ezllmrouter_server.successor_contract import work_projection, work_digest
    verify_started_limits(runtime.allowance.inspect(), finite_scope)
    first, second, first_digest, second_digest = request_pair(runtime)
    trusted = runtime.contexts_by_credential[runtime.credentials["DIRECT_DOCUMENT"]]
    key = {"principal_id": "user.demo", **first["work_selector"]}
    planned = {"kind": "ct02b_exact_pair_pre_submission_v1",
        "case_id": CASE, "campaign_id": CAMPAIGN, "work_key": key,
        "requests": [{"body_utf8": canonical(value).decode(),
                      "body_sha256": digest(canonical(value)),
                      "work_digest": work_digest(work_projection(value, trusted))}
                     for value in (first, second)],
        "finite_campaign": runtime.allowance.inspect(),
        "resource_started_at": finite_scope["resource_started_at"],
        "original_absolute_expiry": EXPIRY,
        "provider_route": "controlled synthetic TLS receiver",
        "real_provider_calls_authorized": 0}
    if [row["work_digest"] for row in planned["requests"]] != [first_digest, second_digest]:
        raise AssertionError("predeclared work digests differ")
    durable_json(runtime.root / "CASE-PREFLIGHT.json", planned)
    append_durable(runtime.journal, {"kind": "ct02b_case_begin", "case_id": CASE,
        "at_ns": time.time_ns(), "pair_preflight_sha256":
            digest((runtime.root / "CASE-PREFLIGHT.json").read_bytes())})
    before = _census(runtime)
    if before["submissions"] != 0 or before["guard_ownership"] != 0 or \
            before["receiver_arrivals"] != 0 or runtime.store.work_owner(key) is not None:
        raise AssertionError("supplemental target not empty before sole pair")
    transactions = []
    trace_lock = threading.Lock()
    original_claim = runtime.store.successor_create
    def observed_claim(*args, **kwargs):
        entry = {"thread_id": threading.get_ident(), "at_ns": time.monotonic_ns()}
        with trace_lock:
            transactions.append(entry)
        append_durable(runtime.root / "TRANSACTIONS.jsonl",
            {"kind": "ct02b_product_claim_entry", **entry})
        try:
            result = original_claim(*args, **kwargs)
            entry["outcome"] = "returned"
            append_durable(runtime.root / "TRANSACTIONS.jsonl",
                {"kind": "ct02b_product_claim_exit", **entry})
            return result
        except BaseException as exc:
            entry["outcome"] = type(exc).__name__
            append_durable(runtime.root / "TRANSACTIONS.jsonl",
                {"kind": "ct02b_product_claim_exit", **entry})
            raise
    runtime.store.successor_create = observed_claim
    try:
        replies, boundary = synchronized_pair(runtime.store, runtime.successor, key,
            lambda: raw_post(runtime, first), lambda: raw_post(runtime, second),
            trace_path=runtime.root / "BOUNDARY.jsonl")
    finally:
        runtime.store.successor_create = original_claim
    winner = [row for row in replies if row["reply"].get("handle")]
    statuses = []
    if len(winner) == 1:
        sid = winner[0]["reply"]["handle"]["submission_id"]
        for _ in range(40):
            current = read_status(runtime, sid)
            statuses.append(current)
            if current["body"].get("submission_state") != "pending":
                break
            time.sleep(.1)
    after = _census(runtime)
    owner = runtime.store.work_owner(key)
    loser = [row for row in replies if row["http_status"] == 409]
    rows = retained_rows(runtime)
    if len(rows["dev12_submissions"]) == 1:
        admitted = json.loads(rows["dev12_submissions"][0]["record"])
        admitted_attempt = admitted["attempt_id"]
    else:
        admitted = None
        admitted_attempt = None
    receiver_rows = [json.loads(line) for line in runtime.receiver_log.read_text().splitlines()]
    receipt_path = runtime.root / "receiver-receipts.jsonl"
    receipt_rows = [json.loads(line) for line in receipt_path.read_text().splitlines()] \
        if receipt_path.exists() else []
    guard_rows = [json.loads(line) for line in runtime.guard_log.read_text().splitlines()] \
        if runtime.guard_log.exists() else []
    if (len(winner) != 1 or len(loser) != 1 or owner is None or
            owner["contract_version"] != "0.3" or
            owner["submission_id"] != winner[0]["reply"]["handle"]["submission_id"] or
            loser[0]["reply"].get("code") != "WORK_CONFLICT" or
            loser[0]["reply"].get("retry_guidance") != "never" or
            loser[0]["response_headers"].get("EzLLMRouter-Contract-Version") != "0.3" or
            not boundary["owner_absent_when_both_arrived"] or
            len(transactions) != 2 or
            len({row["thread_id"] for row in transactions}) != 2 or
            not all(row["at_ns"] >= boundary["release_at_ns"] for row in transactions) or
            after["submissions"] != 1 or after["campaign"]["attempt_count"] != 1 or
            not 0 <= after["guard_ownership"] <= 1 or
            not 0 <= after["receiver_arrivals"] <= 1 or
            after["campaign"]["possible_send_count"] != after["guard_ownership"] or
            len(rows["dev12_campaign_attempts"]) != 1 or admitted is None or
            admitted["submission_id"] != owner["submission_id"] or
            any(row["attempt_id"] != admitted_attempt for row in
                rows["dev12_send_ownership"] + rows["dev12_usage_revisions"] + receiver_rows) or
            Decimal(after["campaign"]["cumulative_reserved_decimal"]) > ALLOC):
        raise AssertionError("sole synchronized target pair did not conserve ownership")
    result = {"kind": "ct02b_synchronized_target_observation_v1", "status": "PASS",
        "case_id": CASE, "boundary": boundary, "transaction_entries": transactions,
        "responses": replies, "read_only_statuses": statuses,
        "read_only_status_gets": len(statuses),
        "owner": owner, "before": before, "after": after,
        "durable_rows": rows, "receiver_arrival_rows": receiver_rows,
        "receiver_receipt_rows": receipt_rows, "guard_event_rows": guard_rows,
        "new_admissions": 1, "new_possible_sends": after["guard_ownership"],
        "new_receiver_arrivals": after["receiver_arrivals"]}
    durable_json(runtime.root / "TARGET-OBSERVATION.json", result)
    append_durable(runtime.journal, {"kind": "ct02b_case_end", "case_id": CASE,
        "status": "PASS", "at_ns": time.time_ns(),
        "observation_sha256": digest((runtime.root / "TARGET-OBSERVATION.json").read_bytes())})
    return result
