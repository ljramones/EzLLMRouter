"""Focused taint, assessment, and first-write target cases.

These functions are invoked only by the reviewed Completion 02 handler registry.
Importing this module never opens a target or changes durable state.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def taint_boundary(runtime, case):
    """Exercise the unchanged wire-0.2 caller-owned tool-result validator."""
    from dev12_completion_handlers import _census, _evidence
    from ezllmrouter_server.canonical import ContractError, validate_text_request

    if (case["scenario_id"], case["variant"]) != ("t03", "composed"):
        raise NotImplementedError("unsupported taint case")
    request = json.loads((ROOT / "tests/development_slice/request.json").read_text())
    scenarios = json.loads((ROOT / "tests/tool_cycle/scenarios.json").read_text())
    request["deadline"] = (datetime.now(timezone.utc) + timedelta(minutes=30)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    request["requested_features"] = ["text", "tools"]
    request["tool_definitions"] = [scenarios["tool_definition"]]
    request["tool_choice"] = "auto"
    call = {
        "block_id": "block.call.1",
        "kind": "tool_call",
        "call_id": "call.lookup.1",
        "tool_name": "lookup",
        "arguments": {"key": "synthetic"},
        "source_labels": {
            "lineage_ids": ["src.candidate.tool"],
            "sensitivity": "internal",
            "restrictions": [],
        },
    }
    request["messages"].append({"role": "assistant", "blocks": [call]})
    request["messages"].append(
        {
            "role": "tool",
            "blocks": [
                {
                    "block_id": "block.result.1",
                    "kind": "tool_result",
                    "call_id": "call.lookup.1",
                    "result_value": {"value": "synthetic"},
                    "source_labels": scenarios["result_source_labels"],
                }
            ],
        }
    )
    labels = request["messages"][-1]["blocks"][0]
    trusted = {
        "task_id": request["task_id"],
        "principal_id": "user.demo",
        "charging_owner_id": "team.demo",
        "prompt_id": request["resolved_prompt"]["prompt_id"],
        "prompt_version": request["resolved_prompt"]["prompt_version"],
    }
    config = {"configuration_ref": request["requested_configuration_ref"]}
    prompt = request["messages"][0]["blocks"]
    lineages = ("src.prompt.1", "src.user.1", "src.candidate.tool", "src.tool.1")

    def evaluate(candidate):
        try:
            value = validate_text_request(candidate, trusted, config, prompt, lineages)
            return {"accepted": True, "message_roles": [m["role"] for m in value[0]]}
        except ContractError as exc:
            return {"accepted": False, "code": exc.code, "http_status": exc.status}

    before = _census(runtime)
    valid = evaluate(request)
    missing = deepcopy(request)
    del missing["messages"][-1]["blocks"][0]["source_labels"]
    missing_result = evaluate(missing)
    migration = deepcopy(missing)
    # The supported legacy migration metadata can describe a gap, but it is
    # never a source-taint authority. This is a bounded caller trace claim.
    migration["trace_context"] = {"metadata_migration": "source-labels-absent"}
    migration_result = evaluate(migration)
    after = _census(runtime)
    unchanged = (
        before["submissions"] == after["submissions"]
        and before["guard_ownership"] == after["guard_ownership"]
        and before["receiver_arrivals"] == after["receiver_arrivals"]
        and before["campaign"] == after["campaign"]
    )
    checks = {
        "t03.missing_taint": (
            not missing_result["accepted"] and unchanged,
            "Missing tool-result source labels fail legacy canonical ingress without admission/send",
        ),
        "t03.migration_missing_taint": (
            not migration_result["accepted"] and unchanged,
            "Caller migration trace cannot waive the tool-result label requirement",
        ),
        "t03.valid_taint": (
            valid["accepted"] and valid["message_roles"] == ["system", "user", "assistant", "tool"],
            "Correctly labelled caller-owned tool result passes the bounded legacy validator",
        ),
    }
    return _evidence(
        runtime,
        case,
        {
            "ingress": {
                "valid": valid,
                "missing": missing_result,
                "migration_missing": migration_result,
            },
            "admission": {
                "new_submissions": after["submissions"] - before["submissions"],
                "new_receiver_arrivals": after["receiver_arrivals"] - before["receiver_arrivals"],
            },
        },
        checks,
        {
            "request": request,
            "missing": missing_result,
            "migration_missing": migration_result,
            "before": before,
            "after": after,
        },
        case["attempt_group"],
    )


def assessment_transition(runtime, case):
    """Append later assessments, then prove duplicate ownership is unchanged."""
    from dev12_completion_handlers import (
        _case_request,
        _census,
        _current_utc,
        _evidence,
        _headers,
        _post,
        _trusted,
    )

    if (case["scenario_id"], case["variant"]) != ("t14_a", "composed"):
        raise NotImplementedError("unsupported assessment case")
    request = _case_request(runtime, case, "DELEGATED_RERANK")
    before = _census(runtime)
    first = _post(runtime, request, _headers(runtime, "DELEGATED_RERANK"))
    sid = first["reply"].get("handle", {}).get("submission_id")
    if not sid:
        raise AssertionError("commission/delegation control was not admitted")
    original = runtime.store.successor_get(sid)
    accepted = _census(runtime)
    if first["status"].get("submission_state") != "completed":
        raise AssertionError("commission/delegation control did not complete")

    transitions = (
        (
            "commission_verified",
            {
                "commission": {
                    "status": "verified",
                    "evidence_scope": "synthetic.review",
                    "evidence_ref": "review.synthetic",
                }
            },
        ),
        (
            "delegation_coverage",
            {"delegation": {"coverage": "partial", "verified_link_indices": [0]}},
        ),
        (
            "commission_available",
            {
                "commission": {
                    "status": "available",
                    "evidence_scope": "synthetic.review",
                    "evidence_ref": "review.available",
                }
            },
        ),
    )
    duplicates = []
    for kind, assessment in transitions:
        runtime.store.successor_append_evidence(
            sid,
            "later_assessment",
            _current_utc(),
            {
                "kind": kind,
                "assessment": assessment,
                "admission_snapshot_digest": original["admission_snapshot_digest"],
            },
        )
        duplicate = _post(runtime, request, _headers(runtime, "DELEGATED_RERANK"))
        duplicates.append({"kind": kind, "reply": duplicate})

    omitted = _case_request(runtime, case, "DIRECT_DOCUMENT")
    omitted["work_selector"]["step_id"] += ".omitted"
    omitted_first = _post(runtime, omitted, _headers(runtime))
    omitted_sid = omitted_first["reply"].get("handle", {}).get("submission_id")
    omitted_record = runtime.store.successor_get(omitted_sid) if omitted_sid else None
    if omitted_record is None:
        raise AssertionError("omitted commission control not admitted")
    for reason in ("not_yet_issued", "caller_omitted"):
        runtime.store.successor_append_evidence(
            omitted_sid,
            "later_assessment",
            _current_utc(),
            {
                "kind": "commission_absence_review",
                "reason": reason,
                "admission_snapshot_digest": omitted_record["admission_snapshot_digest"],
            },
        )
        duplicates.append({"kind": reason, "reply": _post(runtime, omitted, _headers(runtime))})

    changed = deepcopy(request)
    changed["metadata"]["commission"]["reference"] = "commission.changed"
    conflict = _post(runtime, changed, _headers(runtime, "DELEGATED_RERANK"))
    identity = runtime.contexts_by_credential[runtime.credentials["DELEGATED_RERANK"]]["identity"]
    runtime.authority.set_historical_access(
        identity, read=False, write=True, resume=True, observed_at=_current_utc()
    )
    try:
        denied = _post(runtime, request, _headers(runtime, "DELEGATED_RERANK"))
    finally:
        runtime.authority.set_historical_access(
            identity, read=True, write=True, resume=True, observed_at=_current_utc()
        )
    final = _census(runtime)
    retained = runtime.store.successor_get(sid)
    stable = (
        final["submissions"] == before["submissions"] + 2
        and final["receiver_arrivals"] == before["receiver_arrivals"] + 2
        and final["guard_ownership"] == before["guard_ownership"] + 2
        and retained["work_digest"] == original["work_digest"]
        and retained["admission_snapshot"] == original["admission_snapshot"]
        and retained["signed_plan"] == original["signed_plan"]
        and all(
            item["reply"]["reply"].get("handle", {}).get("submission_id") in {sid, omitted_sid}
            for item in duplicates
        )
    )
    checks = {
        "t14_a.assessment_transition": (
            stable
            and all(
                item["reply"]["reply"].get("handle", {}).get("submission_id") == sid
                for item in duplicates[:3]
            ),
            "Later commission evidence leaves the original signed admission and send ownership fixed",
        ),
        "t14_a.omitted_reason_transition": (
            stable
            and omitted_record["admission_snapshot"]["commission"]["absence_reason"]
            == "caller_omitted"
            and all(
                item["reply"]["reply"].get("handle", {}).get("submission_id") == omitted_sid
                for item in duplicates[3:]
            ),
            "Later absence reasoning cannot alter an omitted caller assertion or create a new attempt",
        ),
        "t14_a.delegation_coverage_transition": (
            stable and original["admission_snapshot"]["delegation"]["coverage"] == "none",
            "Later delegation evidence remains outside immutable WorkKey and signed plan",
        ),
        "t14_a.changed_caller_assertion": (
            conflict["http_status"] == 409
            and conflict["reply"].get("code") == "WORK_CONFLICT"
            and stable,
            "Changed caller commission assertion under the same key conflicts",
        ),
        "t14_a.read_denied": (
            denied["http_status"] == 404 and stable,
            "Current historical read authority still gates duplicate retrieval",
        ),
    }
    return _evidence(
        runtime,
        case,
        {
            "admission": {"first_submission_id": sid, "omitted_submission_id": omitted_sid},
            "signed_plan": {"plan_id": original["signed_plan"]["plan_id"]},
            "authority": {"read_denied_http": denied["http_status"]},
            "guard": {"new_guard_ownership": final["guard_ownership"] - before["guard_ownership"]},
            "first_write": {
                "new_receiver_arrivals": final["receiver_arrivals"] - before["receiver_arrivals"]
            },
        },
        checks,
        {
            "original": original,
            "retained": retained,
            "duplicates": duplicates,
            "omitted_record": omitted_record,
            "conflict": conflict,
            "denied": denied,
            "before": before,
            "after": final,
        },
        original["attempt_id"],
    )


def first_write_order(runtime, case):
    """Exercise actual guarded local TLS first-write order and bounded faults."""
    from unittest.mock import patch
    from dev12_completion_fault_transport import CompletionTLSHTTPTransport
    from dev12_completion_handlers import (
        _case_request,
        _census,
        _current_utc,
        _evidence,
        _headers,
        _post,
        _trusted,
    )

    if case["scenario_id"] != "t24_b" or case["variant"] not in {
        "revocation_before_write",
        "write_before_revocation",
        "would_block",
        "partial_write",
    }:
        raise NotImplementedError("unsupported first-write order case")
    variant = case["variant"]
    before = _census(runtime)
    fired = []

    def permission(allowed):
        def update(state):
            state["send_permission"] = allowed

        runtime.authority.update(
            update,
            {"kind": "completion02_t24b_send_permission", "allowed": allowed, "at": _current_utc()},
        )

    async def revoke_before_write():
        if not fired:
            fired.append("revoked_before_first_write")
            permission(False)

    request = _case_request(runtime, case)
    fault = None
    if variant == "revocation_before_write":
        runtime.executor.first_write_wait = revoke_before_write
    elif variant in {"would_block", "partial_write"}:
        fault = {
            "mode": (
                "would_block_once" if variant == "would_block" else "partial_after_first_bytes"
            ),
            "fired": False,
            "observations": [],
        }
        CompletionTLSHTTPTransport.fault = fault
    try:
        if fault is None:
            reply = _post(runtime, request, _headers(runtime))
        else:
            with patch("dev12_executor.OwnedSyntheticTLSHTTPTransport", CompletionTLSHTTPTransport):
                reply = _post(runtime, request, _headers(runtime))
    finally:
        runtime.executor.first_write_wait = None
        CompletionTLSHTTPTransport.fault = None
        if variant == "revocation_before_write" and fired:
            permission(True)

    sid = reply["reply"].get("handle", {}).get("submission_id")
    record = runtime.store.successor_get(sid) if sid else None
    if record is None:
        raise AssertionError("first-write control was not admitted")
    after_send = _census(runtime)
    late = None
    duplicate = None
    if variant == "write_before_revocation":
        permission(False)
        try:
            duplicate = _post(runtime, request, _headers(runtime))
        finally:
            permission(True)
    elif variant == "partial_write":
        if (
            not fault["fired"]
            or reply["status"].get("submission_state") != "unknown"
            or after_send["receiver_arrivals"] != before["receiver_arrivals"] + 1
            or not after_send["campaign"]["paused"]
        ):
            raise AssertionError(
                "partial first write did not preserve unknown exposure and receiver receipt"
            )
        trusted = _trusted(runtime)
        accepted = runtime.successor.collect_receiver_receipt(sid, trusted)
        corrected = runtime.successor.status(sid, trusted)
        resume = runtime.successor.resume_campaign(
            sid, trusted, "partial TLS write receipt verified; no replay"
        )
        late = {"collection": accepted, "status": corrected, "resume": resume}
    final = _census(runtime)
    status = reply["status"] or {}
    no_repeat = (
        final["receiver_arrivals"] - before["receiver_arrivals"]
        == (0 if variant == "revocation_before_write" else 1)
        and final["submissions"] == before["submissions"] + 1
        and final["campaign"]["attempt_count"] == before["campaign"]["attempt_count"] + 1
        and final["campaign"]["possible_send_count"] - before["campaign"]["possible_send_count"]
        == 1
    )
    if variant == "revocation_before_write":
        passed = (
            bool(fired)
            and status.get("submission_state") == "failed"
            and record.get("dispatch_state") == "blocked"
            and no_repeat
        )
        detail = "Revocation during lower wait blocked first TLS request bytes after durable guard ownership"
    elif variant == "write_before_revocation":
        passed = (
            status.get("submission_state") == "completed"
            and duplicate["reply"].get("handle", {}).get("submission_id") == sid
            and no_repeat
        )
        detail = (
            "Completed first write remained owned once after a later revocation and duplicate POST"
        )
    elif variant == "would_block":
        passed = (
            fault["fired"]
            and "SYNTHETIC_WOULD_BLOCK_BEFORE_FIRST_BYTE" in fault["observations"]
            and status.get("submission_state") == "completed"
            and no_repeat
        )
        detail = "Synthetic would-block fault at the owned local TLS write was retried under the same guard and attempt"
    else:
        passed = (
            fault["fired"]
            and "SYNTHETIC_PARTIAL_TLS_RECORD_AFTER_FIRST_BYTE" in fault["observations"]
            and "RESPONSE_DROPPED_AFTER_FRAGMENTED_REQUEST" in fault["observations"]
            and status.get("submission_state") == "unknown"
            and no_repeat
            and late["collection"] == "accepted"
            and late["status"]["attempts"][0]["usage_revision"]["cost_status"] == "calculated"
            and late["resume"]["decision"] == "resumed"
            and not final["campaign"]["paused"]
        )
        detail = "Fragmented first TLS record retained possible-send exposure until genuine receipt and audited no-send resume"
    checks = {f"t24_b.{variant}": (bool(passed), detail)}
    return _evidence(
        runtime,
        case,
        {
            "admission": {"submission_id": sid},
            "signed_plan": {"plan_id": record["signed_plan"]["plan_id"]},
            "authority": {
                "revoked_before_write": bool(fired),
                "revisions": runtime.authority.revisions(),
            },
            "guard": {"new_ownership": final["guard_ownership"] - before["guard_ownership"]},
            "first_write": {
                "receiver_delta": final["receiver_arrivals"] - before["receiver_arrivals"],
                "fault": fault,
            },
        },
        checks,
        {
            "reply": reply,
            "record": record,
            "duplicate": duplicate,
            "late": late,
            "before": before,
            "after_send": after_send,
            "final": final,
        },
        record["attempt_id"],
    )


def crash_recovery(runtime, case):
    """Interrupt completion after real send, reopen the same store, never replay."""
    from dev12_completion_handlers import (
        _case_request,
        _census,
        _evidence,
        _headers,
        _post,
        _trusted,
    )

    if (case["scenario_id"], case["variant"]) != ("t24_c", "composed"):
        raise NotImplementedError("unsupported recovery case")
    request = _case_request(runtime, case)
    before = _census(runtime)
    with runtime.store._lock:
        prior_ids = {
            row[0]
            for row in runtime.store.db.execute("SELECT submission_id FROM dev12_submissions")
        }
    real_execute = runtime.executor.execute
    interruption = []

    def interrupted_after_send(record, authority, store, allowance):
        outcome = real_execute(record, authority, store, allowance)
        if outcome.get("state") != "observed":
            raise AssertionError("controlled send did not return an observation")
        interruption.append({"attempt_id": record["attempt_id"], "outcome_state": outcome["state"]})
        # BaseException crosses the worker future without SuccessorService's
        # ordinary Exception reconciliation. It models an interrupted process
        # after committed first-write and receiver delivery, before status/usage
        # publication. The actual service/DB is reopened below.
        raise SystemExit("synthetic process interruption after guarded send")

    runtime.executor.execute = interrupted_after_send
    initial_reply = None
    initial_error = None
    try:
        try:
            initial_reply = _post(runtime, request, _headers(runtime))
        except Exception as exc:
            initial_error = {"type": type(exc).__name__, "message": str(exc)[:160]}
    finally:
        runtime.executor.execute = real_execute
    with runtime.store._lock:
        new_ids = {
            row[0]
            for row in runtime.store.db.execute("SELECT submission_id FROM dev12_submissions")
        } - prior_ids
    if len(new_ids) != 1 or len(interruption) != 1:
        raise AssertionError("one interrupted admitted attempt required")
    sid = next(iter(new_ids))
    pending = runtime.store.successor_get(sid)
    before_restart = _census(runtime)
    if (
        pending["submission_state"] != "pending"
        or before_restart["receiver_arrivals"] != before["receiver_arrivals"] + 1
        or before_restart["guard_ownership"] != before["guard_ownership"] + 1
    ):
        raise AssertionError("interruption did not leave one possibly sent pending attempt")
    restart = runtime.restart_service()
    recovered = runtime.store.successor_get(sid)
    after_restart = _census(runtime)
    duplicate = _post(runtime, request, _headers(runtime))
    after_duplicate = _census(runtime)
    trusted = _trusted(runtime)
    collection = runtime.successor.collect_receiver_receipt(sid, trusted)
    settled = runtime.successor.status(sid, trusted)
    resume = runtime.successor.resume_campaign(
        sid, trusted, "interrupted send recovered from one retained receiver receipt"
    )
    final = _census(runtime)
    fixed_counts = (
        restart["receiver_arrivals_before"]
        == restart["receiver_arrivals_after"]
        == before_restart["receiver_arrivals"]
        and after_restart["receiver_arrivals"]
        == after_duplicate["receiver_arrivals"]
        == final["receiver_arrivals"]
        and final["campaign"]["possible_send_count"]
        == before["campaign"]["possible_send_count"] + 1
        and final["campaign"]["attempt_count"] == before["campaign"]["attempt_count"] + 1
    )
    checks = {
        "t24_c.restart_possibly_sent": (
            bool(
                recovered["submission_state"] == "unknown"
                and recovered["dispatch_state"] == "possible_send"
                and after_restart["campaign"]["paused"]
                and fixed_counts
            ),
            "Same durable campaign reopened a committed pending attempt as unknown without resend",
        ),
        "t24_c.no_replay": (
            bool(
                duplicate["reply"].get("handle", {}).get("submission_id") == sid
                and collection == "accepted"
                and settled["attempts"][0]["usage_revision"]["cost_status"] == "calculated"
                and resume["decision"] == "resumed"
                and not final["campaign"]["paused"]
                and fixed_counts
            ),
            "Duplicate recovery stayed on original attempt; genuine late receipt settled once and resume sent nothing",
        ),
    }
    return _evidence(
        runtime,
        case,
        {
            "admission": {"submission_id": sid},
            "signed_plan": {"plan_id": pending["signed_plan"]["plan_id"]},
            "authority": {"restart_key_version": restart["authority_key_version"]},
            "guard": {"new_ownership": final["guard_ownership"] - before["guard_ownership"]},
            "first_write": {
                "receiver_delta": final["receiver_arrivals"] - before["receiver_arrivals"]
            },
        },
        checks,
        {
            "initial_reply": initial_reply,
            "initial_error": initial_error,
            "interruption": interruption,
            "pending": pending,
            "recovered": recovered,
            "restart": restart,
            "duplicate": duplicate,
            "collection": collection,
            "settled": settled,
            "resume": resume,
            "before": before,
            "final": final,
        },
        pending["attempt_id"],
    )
