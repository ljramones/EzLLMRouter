"""Objective, source-bound handlers for the finite DEV-12 target.

The registry intentionally lists only implemented scenario/variant pairs.
An unimplemented assurance variant cannot pass preflight by falling through to
a nominal generic handler.  Each handler retains the concrete HTTP, store,
receiver and accounting observations used by its assertions.
"""
from __future__ import annotations

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_EVEN
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from dev12_completion_catalog import CaseHandler
from dev12_completion_operator_handlers import OPERATOR_CASE_HANDLERS


SOURCE = Path(__file__).resolve()


def _current_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _case_request(runtime, case, vector="DIRECT_DOCUMENT", *, item_id="doc.valid"):
    from dev12_integrated import fixture
    request, _ = fixture(vector)
    request["work_selector"]["step_id"] = ("step.completion02." +
        case["scenario_id"].replace("_", ".") + "." +
        case["variant"].replace("_", "."))[:150]
    if case["scenario_id"].startswith("ct02_") and ".continuation" in case["id"]:
        # A failed supplemental case with retained evidence gets a distinct
        # declared WorkKey; never replay its earlier possibly sent attempt.
        request["work_selector"]["step_id"] += "." + case["id"].rsplit(
            ".continuation", 1)[1]
    if request["operation"]["type"] == "embedding.create":
        request["input"]["items"] = [{"item_id": item_id, "text": "Sky"}]
    return request


def _headers(runtime, vector="DIRECT_DOCUMENT", *, version="0.3"):
    return {"Authorization": "Bearer " + runtime.credentials[vector],
            "Duranki-Contract-Version": version,
            "Content-Type": "application/json", "Duranki-Wait-Ms": "5000"}


def _census(runtime):
    from dev12_integrated import observations
    with runtime.store._lock:
        submissions = runtime.store.db.execute(
            "SELECT COUNT(*) FROM dev12_submissions").fetchone()[0]
        guard = runtime.store.db.execute(
            "SELECT COUNT(*) FROM dev12_send_ownership").fetchone()[0]
        usage = runtime.store.db.execute(
            "SELECT COUNT(*) FROM dev12_usage_revisions").fetchone()[0]
    arrivals = len(observations(runtime.receiver_log))
    return {"submissions": submissions, "guard_ownership": guard,
            "usage_revisions": usage, "receiver_arrivals": arrivals,
            "campaign": runtime.allowance.inspect()}


def _post(runtime, request, headers):
    import httpx
    with httpx.Client(base_url=runtime.base_url, timeout=12,
                      trust_env=False) as client:
        reply = client.post("/v1/submissions", headers=headers, json=request)
        value = reply.json()
        status = None
        sid = value.get("handle", {}).get("submission_id")
        if sid:
            for _ in range(100):
                current = client.get("/v1/submissions/" + sid, headers={
                    "Authorization": headers["Authorization"],
                    "Duranki-Contract-Version": headers["Duranki-Contract-Version"]})
                status = current.json()
                if status.get("submission_state") != "pending":
                    break
                time.sleep(.05)
        return {"http_status": reply.status_code, "reply": value, "status": status}


def _trusted(runtime, vector="DIRECT_DOCUMENT"):
    from dev12_integrated import fixture
    context = runtime.contexts_by_credential[runtime.credentials[vector]]
    return {**context["identity"],
            "task_id": fixture(vector)[0]["work_selector"]["task_id"],
            "expires_at": context["expires_at"]}


def _unknown_then_retained_correction(runtime, case, item_id, suffix):
    """One genuine unknown native observation, then an independent receipt."""
    request = _case_request(runtime, case, item_id=item_id)
    request["work_selector"]["step_id"] += "." + suffix
    before = _census(runtime)
    reply = _post(runtime, request, _headers(runtime))
    paused = _census(runtime)
    status = reply["status"] or {}
    sid = reply["reply"].get("handle", {}).get("submission_id")
    usage = status.get("attempts", [{}])[0].get("usage_revision", {})
    if (not sid or status.get("submission_state") != "completed" or
            usage.get("cost_status") != "unknown" or not paused["campaign"]["paused"] or
            paused["receiver_arrivals"] != before["receiver_arrivals"] + 1):
        raise AssertionError("native unknown observation/delivery/receiver correlation missing")
    outcome = runtime.successor.collect_receiver_receipt(sid, _trusted(runtime))
    corrected = runtime.successor.status(sid, _trusted(runtime))
    decision = runtime.successor.resume_campaign(sid, _trusted(runtime),
        "test retained native receipt correction")
    after = _census(runtime)
    if (outcome != "accepted" or decision.get("decision") != "resumed" or
            corrected["attempts"][0]["usage_revision"].get("cost_status") != "calculated" or
            after["receiver_arrivals"] != paused["receiver_arrivals"] or
            after["campaign"]["possible_send_count"] != paused["campaign"]["possible_send_count"]):
        raise AssertionError("historical correction or same-scope resume was not no-send")
    return {"request": request, "reply": reply, "status_before": status,
            "before": before, "paused": paused, "collection": outcome,
            "status_after": corrected, "resume": decision, "after": after}


def _evidence(runtime, case, stages, checks, payload, attempt_group):
    """Retain one bounded case document and bind every assertion to its hash."""
    expected = set(case["predicates"])
    if set(checks) != expected:
        raise AssertionError("handler did not execute exact registered assertions")
    if not all(type(value) is tuple and len(value) == 2 and
               type(value[0]) is bool and type(value[1]) is str and value[1]
               for value in checks.values()):
        raise AssertionError("objective assertion result malformed")
    directory = runtime.root / "cases"
    directory.mkdir(exist_ok=True)
    path = directory / (case["id"] + ".json")
    if path.exists() or path.is_symlink():
        raise RuntimeError("case evidence already exists; do not overwrite a run")
    document = {"case_id": case["id"], "scenario_id": case["scenario_id"],
                "variant": case["variant"], "at": _current_utc(),
                "attempt_group": case["attempt_group"],
                "actual_attempt_id": attempt_group, "observed_stages": stages,
                "checks": {name: {"passed": result[0], "detail": result[1]}
                           for name, result in checks.items()},
                "payload": payload}
    raw = (json.dumps(document, sort_keys=True, indent=2,
                      ensure_ascii=True) + "\n").encode()
    if len(raw) > 1_000_000:
        raise AssertionError("case evidence exceeds bound")
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        import os
        os.fsync(stream.fileno())
    digest = sha256(raw).hexdigest()
    relative = str(path.relative_to(runtime.root))
    stage_rows = [{"stage": name, "evidence_path": relative, "sha256": digest,
                   "case_id": case["id"], "attempt_group": case["attempt_group"],
                   "observed": observed}
                  for name, observed in stages.items()]
    assertions = [{"id": name, "passed": passed, "executed": True,
                   "evidence_paths": [relative], "detail": detail}
                  for name, (passed, detail) in checks.items()]
    return {"status": "PASS" if all(row["passed"] for row in assertions) else "FAIL",
            "observations": stage_rows, "assertions": assertions}


def ingress_identity(runtime, case):
    """Normal authenticated HTTP ingress; reject before any durable intent."""
    if (case["scenario_id"], case["variant"]) == ("t03", "composed"):
        from dev12_completion_boundary_handlers import taint_boundary
        return taint_boundary(runtime, case)
    if case["scenario_id"] in {"t79_c", "t79_d"} and case["variant"] == "composed":
        from duranki_server.successor_contract import (digest, work_digest,
            schema_valid, SCHEMAS)
        from duranki_server.successor_plan import execution_eligible
        request = _case_request(runtime, case, "DELEGATED_RERANK")
        before = _census(runtime)
        first = _post(runtime, request, _headers(runtime, "DELEGATED_RERANK"))
        admitted = _census(runtime)
        sid = first["reply"].get("handle", {}).get("submission_id")
        if not sid:
            raise AssertionError("asserted commission control missing")
        record = runtime.store.successor_get(sid)
        original = deepcopy(record["admission_snapshot"])
        original_digest = record["admission_snapshot_digest"]
        original_work_digest = record["work_digest"]
        original_plan = deepcopy(record["signed_plan"])
        current = runtime.authority.current_context(record, _current_utc())
        changed = deepcopy(request)
        changed["metadata"]["commission"]["reference"] = "commission.changed.assertion"
        conflict = _post(runtime, changed, _headers(runtime, "DELEGATED_RERANK"))
        status_tamper = deepcopy(original)
        status_tamper["commission"] = {"status": "verified",
            "evidence_scope": "synthetic.review", "evidence_ref": "evidence.synthetic"}
        reason_tamper = deepcopy(original)
        reason_tamper["delegation"]["absence_reason"] = "not_yet_issued"
        link_tamper = deepcopy(original)
        link_tamper["work_digest"] = "sha256:" + "0" * 64
        rejected = {name: not execution_eligible(original_plan, record["request"],
                        record["canonical_work"], changed_snapshot, current)
                    for name, changed_snapshot in (("status", status_tamper),
                                                   ("reason", reason_tamper),
                                                   ("link", link_tamper))}
        at = _current_utc()
        evidence = {"kind": "later_synthetic_commission_review",
                    "status": "recorded_evidence_only", "observed_at": at,
                    "original_admission_digest": original_digest}
        runtime.store.successor_append_evidence(sid, "later_commission_review", at, evidence)
        duplicate = _post(runtime, request, _headers(runtime, "DELEGATED_RERANK"))
        after = _census(runtime)
        retained = runtime.store.successor_get(sid)
        no_retro = (retained["admission_snapshot"] == original and
            retained["admission_snapshot_digest"] == original_digest and
            retained["work_digest"] == original_work_digest and
            retained["signed_plan"] == original_plan and
            duplicate["reply"].get("handle", {}).get("submission_id") == sid and
            after["submissions"] == admitted["submissions"] and
            after["receiver_arrivals"] == admitted["receiver_arrivals"])
        if case["scenario_id"] == "t79_c":
            checks = {
                "t79_c.caller_assertion_mutation": (conflict["http_status"] == 409 and
                    conflict["reply"].get("code") == "WORK_CONFLICT" and
                    after["submissions"] == before["submissions"] + 1,
                    "Changed canonical caller commission under same WorkKey conflicts"),
                "t79_c.signed_status_reason_tamper": (
                    schema_valid(status_tamper, SCHEMAS["$defs"]["AdmissionSnapshot"]) and
                    schema_valid(reason_tamper, SCHEMAS["$defs"]["AdmissionSnapshot"]) and
                    rejected["status"] and rejected["reason"],
                    "Schema-valid assessment status and reason edits fail unchanged signed admission binding"),
                "t79_c.digest_link_tamper": (rejected["link"] and
                    original["work_digest"] == work_digest(record["canonical_work"]) and
                    digest("duranki-admission-v1\n", original) == original_digest,
                    "Changing snapshot work-digest link cannot validate against original plan" )}
        else:
            checks = {"t79_d.later_verification_no_retroactive_upgrade": (
                no_retro and rejected["status"] and
                retained["admission_snapshot"]["commission"] ==
                    {"status": "asserted", "evidence_scope": "record_only"},
                "Later linked review evidence did not upgrade original admission or authorize replay")}
        return _evidence(runtime, case,
            {"ingress": {"initial_http": first["http_status"],
                         "changed_caller_http": conflict["http_status"],
                         "duplicate_http": duplicate["http_status"]},
             "admission": {"submission_id": sid,
                           "original_snapshot_digest": original_digest,
                           "new_submissions": after["submissions"] - before["submissions"]}},
            checks, {"first": first, "conflict": conflict,
                     "duplicate": duplicate, "record": record,
                     "retained": retained, "evidence": evidence,
                     "tampered": {"status": status_tamper,
                                  "reason": reason_tamper,
                                  "link": link_tamper},
                     "rejected": rejected, "before": before, "after": after},
            record["attempt_id"])
    if case["scenario_id"] in {"t77_a", "t77_b", "t77_c", "t77_d"} and \
            case["variant"] == "composed":
        from duranki_server.successor_contract import (SCHEMAS, schema_valid,
            digest, work_digest)
        from duranki_server.successor_plan import execution_eligible
        request = _case_request(runtime, case)
        before = _census(runtime)
        missing = None
        if case["scenario_id"] == "t77_d":
            missing_headers = _headers(runtime)
            del missing_headers["Authorization"]
            missing = _post(runtime, request, missing_headers)
        response = _post(runtime, request, _headers(runtime))
        after = _census(runtime)
        sid = response["reply"].get("handle", {}).get("submission_id")
        if not sid:
            raise AssertionError("shared-envelope control not admitted")
        record = runtime.store.successor_get(sid)
        snapshot = record["admission_snapshot"]
        plan = record["signed_plan"]
        current = runtime.authority.current_context(record, _current_utc())
        original_eligible = execution_eligible(plan, record["request"],
            record["canonical_work"], snapshot, current)
        supplemental = {}
        if case["scenario_id"] == "t77_a":
            checks = {
                "t77_a.applicable_fields_reasons": (bool(original_eligible and
                    snapshot["work_digest"] == work_digest(record["canonical_work"]) and
                    snapshot["commission"] == {"status": "absent",
                        "evidence_scope": "none", "absence_reason": "caller_omitted"} and
                    snapshot["delegation"] == {"coverage": "none",
                        "verified_link_indices": [], "absence_reason": "not_applicable"}),
                    "Applicable direct-human snapshot includes exact work linkage and reasoned absence" )}
        elif case["scenario_id"] == "t77_b":
            invalid_reason = deepcopy(snapshot)
            invalid_reason["commission"]["absence_reason"] = "fabricated"
            inconsistent = deepcopy(snapshot)
            inconsistent["delegation"]["verified_link_indices"] = [0]
            checks = {
                "t77_b.invalid_reason": (
                    not schema_valid(invalid_reason, SCHEMAS["$defs"]["AdmissionSnapshot"]) and
                    not execution_eligible(plan, record["request"],
                        record["canonical_work"], invalid_reason, current),
                    "Unregistered absence reason fails bounded schema and signed admission binding"),
                "t77_b.inconsistent_combination": (
                    schema_valid(inconsistent, SCHEMAS["$defs"]["AdmissionSnapshot"]) and
                    not execution_eligible(plan, record["request"],
                        record["canonical_work"], inconsistent, current),
                    "Syntactically valid none-coverage plus verified link fails semantic/signature binding")}
            supplemental = {"invalid_reason": invalid_reason,
                            "inconsistent": inconsistent}
        elif case["scenario_id"] == "t77_c":
            # A separate pre-successor row is read through the additive store
            # without backfilling a fictional admission assessment.
            from duranki_server.store import SQLiteStore
            old_path = runtime.root / "cases" / (case["id"] + "-preadmission.sqlite")
            old_path.parent.mkdir(exist_ok=True)
            if old_path.exists():
                raise RuntimeError("preadmission evidence fixture already exists")
            old = SQLiteStore(old_path)
            old_record = {"submission_id": "submission.preadmission.synthetic",
                          "contract_version": "0.2",
                          "attribution_applicability": "pre_admission"}
            try:
                with old._lock:
                    old.db.execute("CREATE TABLE IF NOT EXISTS dev12_preadmission_fixture "
                                   "(id TEXT PRIMARY KEY, record TEXT NOT NULL)")
                    old.db.execute("INSERT INTO dev12_preadmission_fixture VALUES (?,?)",
                                   ("old", json.dumps(old_record, sort_keys=True)))
                    old.db.commit()
            finally:
                old.close()
            reopened = SQLiteStore(old_path)
            try:
                readback = json.loads(reopened.db.execute(
                    "SELECT record FROM dev12_preadmission_fixture WHERE id='old'").fetchone()[0])
            finally:
                reopened.close()
            checks = {
                "t77_c.preadmission_applicability": (
                    readback == old_record and "admission_snapshot" not in readback,
                    "Pre-admission fixture remains explicitly inapplicable without invented snapshot"),
                "t77_c.legacy_applicability": (
                    readback["contract_version"] == "0.2" and
                    snapshot["snapshot_version"] == "dev12-admission@1" and
                    record["contract_version"] == "0.3",
                    "Legacy wire row and successor admission keep distinct applicability")}
            supplemental = {"legacy_path": str(old_path), "readback": readback}
        else:
            checks = {"t77_d.absence_not_authority": (
                snapshot["commission"]["absence_reason"] == "caller_omitted" and
                missing["http_status"] == 401 and
                after["submissions"] == before["submissions"] + 1 and
                after["receiver_arrivals"] == before["receiver_arrivals"] + 1 and
                original_eligible,
                "Missing commission remains allowed only with independently authenticated identity")}
        return _evidence(runtime, case,
            {"ingress": {"positive_http": response["http_status"],
                         "missing_auth_http": missing["http_status"] if missing else "not_tested"},
             "admission": {"submission_id": sid,
                           "snapshot_digest": digest("duranki-admission-v1\n", snapshot),
                           "snapshot_valid": schema_valid(snapshot, SCHEMAS["$defs"]["AdmissionSnapshot"])}},
            checks, {"response": response, "record": record,
                     "missing": missing, "before": before,
                     "after": after, "supplemental": supplemental}, record["attempt_id"])
    if case["scenario_id"] in {"t79_a", "t79_b"} and case["variant"] == "composed":
        direct = _case_request(runtime, case, "DIRECT_DOCUMENT")
        delegated = _case_request(runtime, case, "DELEGATED_RERANK")
        before = _census(runtime)
        first = _post(runtime, direct, _headers(runtime, "DIRECT_DOCUMENT"))
        second = _post(runtime, delegated, _headers(runtime, "DELEGATED_RERANK"))
        admitted = _census(runtime)
        direct_sid = first["reply"].get("handle", {}).get("submission_id")
        delegated_sid = second["reply"].get("handle", {}).get("submission_id")
        if not direct_sid or not delegated_sid:
            raise AssertionError("commission control admissions missing")
        direct_record = runtime.store.successor_get(direct_sid)
        delegated_record = runtime.store.successor_get(delegated_sid)
        absence = direct_record["admission_snapshot"]["commission"]
        asserted = delegated_record["admission_snapshot"]["commission"]
        forged = deepcopy(delegated)
        forged["work_selector"]["step_id"] += ".forged"
        forged["metadata"]["delegation"][-1]["to_actor_id"] = "agent.forged"
        forged["metadata"]["commission"]["reference"] = "commission.claimed.authority"
        negative = _post(runtime, forged, _headers(runtime, "DELEGATED_RERANK"))
        after = _census(runtime)
        no_negative_admission = (after["submissions"] == admitted["submissions"] and
            after["receiver_arrivals"] == admitted["receiver_arrivals"])
        if case["scenario_id"] == "t79_a":
            checks = {
                "t79_a.absent_commission_reason": (
                    absence == {"status": "absent", "evidence_scope": "none",
                                "absence_reason": "caller_omitted"} and
                    first["status"].get("submission_state") == "completed",
                    "Omitted commission receives explicit caller-omitted assessment"),
                "t79_a.asserted_record_only": (
                    asserted == {"status": "asserted", "evidence_scope": "record_only"} and
                    second["status"].get("submission_state") == "completed" and
                    direct_record["work_digest"] != delegated_record["work_digest"],
                    "Caller asserted commission is recorded without verified authority")}
        else:
            checks = {"t79_b.record_only_no_execution_authority": (
                asserted["evidence_scope"] == "record_only" and
                negative["http_status"] == 422 and no_negative_admission and
                after["receiver_arrivals"] == before["receiver_arrivals"] + 2,
                "Asserted record-only commission could not authorize forged executing actor")}
        return _evidence(runtime, case,
            {"ingress": {"direct_http": first["http_status"],
                         "delegated_http": second["http_status"],
                         "forged_http": negative["http_status"]},
             "admission": {"direct_submission": direct_sid,
                           "delegated_submission": delegated_sid,
                           "negative_admitted": not no_negative_admission}},
            checks, {"direct": first, "delegated": second,
                     "forged": negative, "direct_record": direct_record,
                     "delegated_record": delegated_record,
                     "before": before, "after_positive": admitted, "after": after},
            delegated_record["attempt_id"])
    if case["scenario_id"] in {"t78_a", "t78_b", "t78_c", "t78_d"} and \
            case["variant"] == "composed":
        from duranki_server.successor_contract import classify_request
        scenario = case["scenario_id"]
        vector = ("DIRECT_DOCUMENT" if scenario == "t78_a" else
                  "AUTONOMOUS_QUERY" if scenario == "t78_c" else
                  "DELEGATED_RERANK")
        request = _case_request(runtime, case, vector)
        before = _census(runtime)
        positive = _post(runtime, request, _headers(runtime, vector))
        admitted = _census(runtime)
        sid = positive["reply"].get("handle", {}).get("submission_id")
        if not sid:
            raise AssertionError("attribution control was not admitted")
        record = runtime.store.successor_get(sid)
        metadata = record["canonical_work"]["metadata"]
        identity = record["canonical_work"]["trusted"]
        negatives = {}
        classifications = {}
        if scenario == "t78_d":
            forged = deepcopy(request)
            forged["work_selector"]["step_id"] += ".forged"
            forged["metadata"]["delegation"][-1]["to_actor_id"] = "agent.forged"
            cyclic = deepcopy(request)
            cyclic["work_selector"]["step_id"] += ".cycle"
            cyclic["metadata"]["delegation"][-1]["to_actor_id"] = "user.demo"
            excess = deepcopy(request)
            excess["work_selector"]["step_id"] += ".excess"
            excess["metadata"]["delegation"] = excess["metadata"]["delegation"] * 20
            asserted = deepcopy(request)
            asserted["work_selector"]["step_id"] += ".asserted"
            asserted["metadata"]["delegation"][-1]["to_actor_id"] = "agent.forged"
            asserted["metadata"]["commission"]["reference"] = "commission.forged"
            context = runtime.contexts_by_credential[runtime.credentials[vector]]
            for name, value in (("forged", forged), ("cycle", cyclic),
                                ("excess", excess), ("asserted", asserted)):
                classifications[name] = classify_request(value, context)
                negatives[name] = _post(runtime, value, _headers(runtime, vector))
        after = _census(runtime)
        same_control = (positive["status"] and
            positive["status"].get("submission_state") == "completed" and
            admitted["submissions"] == before["submissions"] + 1 and
            admitted["receiver_arrivals"] == before["receiver_arrivals"] + 1)
        if scenario == "t78_a":
            checks = {
                "t78_a.direct_binding": (bool(same_control and
                    metadata["invocation_mode"] == "direct_human" and
                    identity["actor_id"] == metadata["initiating_user_id"] and
                    identity["actor_kind"] == "human"),
                    "Authenticated direct human is both actor and initiating user"),
                "t78_a.chain_representation": (metadata["delegation"] == [] and
                    "parent_run_id" not in metadata,
                    "Direct-human canonical work has no invented delegation chain")}
        elif scenario == "t78_b":
            links = metadata["delegation"]
            checks = {
                "t78_b.delegated_binding": (bool(same_control and
                    identity["actor_kind"] == "agent" and
                    identity["actor_id"] == links[-1]["to_actor_id"] and
                    metadata["initiating_user_id"] != identity["actor_id"]),
                    "Authenticated executing agent remains distinct from initiator"),
                "t78_b.ordered_asserted_links": (len(links) == 2 and
                    links[0]["to_actor_id"] == links[1]["from_actor_id"] and
                    links[0]["to_run_id"] == links[1]["from_run_id"] and
                    record["admission_snapshot"]["delegation"]["coverage"] == "none" and
                    record["admission_snapshot"]["delegation"]["absence_reason"] == "unavailable",
                    "Ordered caller links are retained as assertions without invented verification")}
        elif scenario == "t78_c":
            checks = {
                "t78_c.autonomous_owner": (bool(same_control and
                    identity["actor_kind"] == "service" and
                    identity["charging_owner_id"] == runtime.plan["envelope"]["financial_owner_id"]),
                    "Autonomous service has trusted fictional financial owner"),
                "t78_c.no_fictitious_person": ("initiating_user_id" not in metadata and
                    "initiating_user_id" not in record["canonical_work"]["trusted"],
                    "Autonomous canonical work contains no fabricated initiating human")}
        else:
            no_admission = (after["submissions"] == admitted["submissions"] and
                            after["receiver_arrivals"] == admitted["receiver_arrivals"])
            checks = {
                "t78_d.forged_endpoint": (classifications["forged"] == "SEMANTIC_INVALID" and
                    negatives["forged"]["http_status"] == 422 and no_admission,
                    "Forged final actor endpoint rejected against authenticated current actor"),
                "t78_d.cycle": (classifications["cycle"] == "SEMANTIC_INVALID" and
                    negatives["cycle"]["http_status"] == 422 and no_admission,
                    "Cyclic delegation rejected before admission"),
                "t78_d.excess_bound": (classifications["excess"] == "SCHEMA_INVALID" and
                    negatives["excess"]["http_status"] == 400 and no_admission,
                    "Over-bound delegation chain rejected by bounded schema"),
                "t78_d.record_not_authority": (classifications["asserted"] == "SEMANTIC_INVALID" and
                    negatives["asserted"]["http_status"] == 422 and no_admission,
                    "Asserted commission/reference did not authorize a forged actor endpoint")}
        stages = {"ingress": {"positive_http": positive["http_status"],
                              "negative_http": {key: value["http_status"]
                                                for key, value in negatives.items()}},
                  "admission": {"submission_id": sid,
                                "new_submissions": after["submissions"] - before["submissions"],
                                "trusted_actor_id": identity["actor_id"]}}
        return _evidence(runtime, case, stages, checks,
                         {"positive": positive, "record": record,
                          "negatives": negatives, "classifications": classifications,
                          "before": before, "after_positive": admitted,
                          "after": after}, record["attempt_id"])
    if (case["scenario_id"], case["variant"]) == ("t02", "composed"):
        request = _case_request(runtime, case)
        forbidden = deepcopy(request)
        forbidden["requested_configuration_ref"] = "cfg.forbidden.synthetic"
        before = _census(runtime)
        rejection = _post(runtime, forbidden, _headers(runtime))
        denied = _census(runtime)
        allowed = _post(runtime, request, _headers(runtime))
        after = _census(runtime)
        checks = {
            "t02.forbidden_destination": (rejection["http_status"] == 422 and
                denied["submissions"] == before["submissions"] and
                denied["receiver_arrivals"] == before["receiver_arrivals"],
                "Unregistered requested destination configuration rejected before admission"),
            "t02.fixed_destination": (allowed["status"] and
                allowed["status"].get("submission_state") == "completed" and
                after["receiver_arrivals"] == before["receiver_arrivals"] + 1 and
                after["submissions"] == before["submissions"] + 1,
                "Exact registered fixed destination completed one guarded controlled send")}
        return _evidence(runtime, case,
            {"ingress": {"forbidden_http": rejection["http_status"],
                         "fixed_http": allowed["http_status"]},
             "admission": {"before": before["submissions"],
                           "after_denial": denied["submissions"],
                           "after_positive": after["submissions"]}},
            checks, {"forbidden": rejection, "fixed": allowed,
                     "before": before, "denied": denied, "after": after},
            allowed["reply"].get("attempt_id", "none"))
    if (case["scenario_id"], case["variant"]) == ("t01", "composed"):
        request = _case_request(runtime, case)
        before = _census(runtime)
        missing = _headers(runtime)
        del missing["Authorization"]
        invalid = _headers(runtime)
        invalid["Authorization"] = "Bearer dev12.invalid.synthetic"
        first = _post(runtime, request, missing)
        middle = _post(runtime, request, invalid)
        after_rejections = _census(runtime)
        good = _post(runtime, request, _headers(runtime))
        after = _census(runtime)
        sid = good["reply"].get("handle", {}).get("submission_id")
        checks = {
            "t01.missing_identity": (first["http_status"] == 401 and
                first["reply"].get("contract_version") == "0.3" and
                after_rejections["submissions"] == before["submissions"],
                "Missing bearer rejected with HTTP 401 before admission"),
            "t01.invalid_identity": (middle["http_status"] == 401 and
                after_rejections["guard_ownership"] == before["guard_ownership"] and
                after_rejections["receiver_arrivals"] == before["receiver_arrivals"],
                "Unknown bearer rejected without guard ownership or receiver arrival"),
            "t01.valid_identity": (bool(good["http_status"] in (200, 202) and
                good["status"] and good["status"].get("submission_state") == "completed" and
                sid and after["submissions"] == before["submissions"] + 1 and
                after["receiver_arrivals"] == before["receiver_arrivals"] + 1),
                "Known synthetic bearer admitted exactly one completed guarded send")}
        stages = {"ingress": {"missing_status": first["http_status"],
                              "invalid_status": middle["http_status"],
                              "valid_status": good["http_status"]},
                  "admission": {"before": before["submissions"],
                                "after_rejections": after_rejections["submissions"],
                                "after_valid": after["submissions"]}}
        return _evidence(runtime, case, stages, checks,
                         {"missing": first, "invalid": middle, "valid": good,
                          "before": before, "after_rejections": after_rejections,
                          "after": after}, sid or "none")
    if (case["scenario_id"], case["variant"]) == ("t42", "composed"):
        request = _case_request(runtime, case)
        before = _census(runtime)
        wrong_operation = deepcopy(request)
        wrong_operation["operation"]["type"] = "text.generate"
        unsupported = _post(runtime, wrong_operation, _headers(runtime))
        wrong_version = deepcopy(request)
        wrong_version["contract_version"] = "0.2"
        mismatch = _post(runtime, wrong_version, _headers(runtime))
        unknown_field = deepcopy(request)
        unknown_field["unknown_extension"] = "forbidden"
        schema = _post(runtime, unknown_field, _headers(runtime))
        legacy = _post(runtime, request, _headers(runtime, version="0.2"))
        after_rejections = _census(runtime)
        valid = _post(runtime, request, _headers(runtime))
        after = _census(runtime)
        rejected_without_send = (after_rejections["submissions"] == before["submissions"] and
            after_rejections["guard_ownership"] == before["guard_ownership"] and
            after_rejections["receiver_arrivals"] == before["receiver_arrivals"])
        checks = {
            "t42.unsupported_operation": (unsupported["http_status"] >= 400 and
                unsupported["reply"].get("contract_version") == "0.3" and
                rejected_without_send,
                "Unsupported operation rejected before successor admission and receiver"),
            "t42.mismatched_contract": (mismatch["http_status"] == 426 and
                rejected_without_send,
                "Mismatched body/header successor contract rejected before admission"),
            "t42.unknown_schema": (schema["http_status"] >= 400 and
                rejected_without_send,
                "Unknown successor request field rejected without transmission"),
            "t42.legacy_rejection": (legacy["http_status"] >= 400 and
                legacy["reply"].get("contract_version") == "0.2" and
                rejected_without_send,
                "Legacy wire selection did not interpret successor operation"),
            "t42.supported_operation": (bool(valid["status"] and
                valid["status"].get("submission_state") == "completed" and
                after["submissions"] == before["submissions"] + 1 and
                after["receiver_arrivals"] == before["receiver_arrivals"] + 1),
                "Fixed supported operation completed through guarded receiver once")}
        stages = {"ingress": {"unsupported": unsupported["http_status"],
                              "mismatched": mismatch["http_status"],
                              "schema": schema["http_status"],
                              "legacy": legacy["http_status"],
                              "supported": valid["http_status"]},
                  "admission": {"before": before["submissions"],
                                "after_rejections": after_rejections["submissions"],
                                "after_valid": after["submissions"]}}
        return _evidence(runtime, case, stages, checks,
                         {"responses": {"unsupported": unsupported,
                             "mismatched": mismatch, "schema": schema,
                             "legacy": legacy, "supported": valid},
                          "before": before, "after_rejections": after_rejections,
                          "after": after},
                         valid["reply"].get("attempt_id", "none"))
    raise NotImplementedError(f"unimplemented ingress variant: {case['scenario_id']}/{case['variant']}")


def recovery_chain(runtime, case):
    """One unknown attempt, independent receipt, historical append and resume."""
    from dev12_integrated import fixture, observations
    variant = case["variant"]
    chain_path = runtime.root / "recovery-chain-reference.json"
    if variant == "unknown_pause":
        if chain_path.exists():
            raise RuntimeError("recoverable chain already started")
        request = _case_request(runtime, case, item_id="doc.unknown.recoverable")
        before = _census(runtime)
        sent = _post(runtime, request, _headers(runtime))
        after = _census(runtime)
        status = sent["status"] or {}
        sid = sent["reply"].get("handle", {}).get("submission_id")
        aid = status.get("attempts", [{}])[0].get("attempt_id")
        receipt_rows = observations(runtime.root / "receiver-receipts.jsonl")
        matched = [row for row in receipt_rows if row.get("attempt_id") == aid]
        okay = (sid and aid and status.get("submission_state") == "unknown" and
                after["campaign"]["paused"] is True and
                after["receiver_arrivals"] == before["receiver_arrivals"] + 1 and
                len(matched) == 1 and
                after["guard_ownership"] == before["guard_ownership"] + 1)
        checks = {"recovery_chain.unknown_pause": (
            bool(okay), "Unknown reply retained receiver arrival, guarded ownership, exposure and same-scope pause")}
        stages = {"admission": {"submission_id": sid or "absent"},
                  "guard": {"guard_ownership_delta": after["guard_ownership"] - before["guard_ownership"]},
                  "first_write": {"possible_send_delta": after["campaign"]["possible_send_count"] -
                                  before["campaign"]["possible_send_count"]},
                  "receiver": {"arrival_delta": after["receiver_arrivals"] - before["receiver_arrivals"]},
                  "delivery": {"state": status.get("submission_state", "absent")},
                  "settlement": {"paused": after["campaign"]["paused"],
                                 "exposure_state": status.get("attempts", [{}])[0].get("settlement_state", "absent")}}
        result = _evidence(runtime, case, stages, checks,
            {"request": request, "reply": sent, "before": before, "after": after,
             "receiver_receipts": matched}, aid or "none")
        if result["status"] != "PASS":
            return result
        chain_path.write_text(json.dumps({"submission_id": sid, "attempt_id": aid,
                                          "credential": "DIRECT_DOCUMENT",
                                          "campaign_id": runtime.plan["envelope"]["campaign_id"]},
                                         sort_keys=True) + "\n")
        return result

    if not chain_path.is_file():
        raise RuntimeError("recoverable chain predecessor absent")
    ref = json.loads(chain_path.read_text())
    sid, aid = ref["submission_id"], ref["attempt_id"]
    context = runtime.contexts_by_credential[runtime.credentials[ref["credential"]]]
    trusted = {**context["identity"],
               "task_id": fixture(ref["credential"])[0]["work_selector"]["task_id"],
               "expires_at": context["expires_at"]}
    before = _census(runtime)
    if variant == "retained_receipt":
        from duranki_server.successor_receiver_evidence import DurableReceiverReceipts
        with runtime.store._lock:
            record = runtime.store.successor_get(sid)
            guard_row = runtime.store.db.execute(
                "SELECT guard_receipt FROM dev12_send_ownership WHERE attempt_id=?",
                (aid,)).fetchone()
        if not guard_row:
            raise AssertionError("durable guard receipt absent")
        guard = json.loads(guard_row[0])
        retained = DurableReceiverReceipts(runtime.root / "receiver-receipts.jsonl")
        receipt, digest = retained.find(aid, body_sha256=guard["body_sha256"],
            body_bytes=guard["body_bytes"],
            route=record["signed_plan"]["execution_descriptor"]["route"])
        after = _census(runtime)
        checks = {"recovery_chain.retained_receipt": (
            receipt["attempt_id"] == aid and digest.startswith("sha256:") and
            before == after and ref["campaign_id"] == runtime.allowance.campaign_id,
            "Independent retained receipt binds guarded attempt/body/route without a new send")}
        stages = {"receiver": {"attempt_id": aid, "receipt_digest": digest,
                               "body_sha256": receipt["body_sha256"]}}
        return _evidence(runtime, case, stages, checks,
                         {"receipt": receipt, "guard": guard, "before": before,
                          "after": after}, aid)

    if variant == "authorized_late_append":
        # The service records UTC seconds.  Keep the two genuine revision
        # observations separable for the later operator cutoff assertion.
        time.sleep(1.05)
        outcome = runtime.successor.collect_receiver_receipt(sid, trusted)
        after = _census(runtime)
        status = runtime.successor.status(sid, trusted)
        usage = status["attempts"][0].get("usage_revision", {})
        checks = {"recovery_chain.authorized_late_append": (
            outcome != "duplicate" and usage.get("cost_status") == "calculated" and
            after["usage_revisions"] == before["usage_revisions"] + 1 and
            after["receiver_arrivals"] == before["receiver_arrivals"] and
            after["campaign"]["possible_send_count"] == before["campaign"]["possible_send_count"],
            "Authenticated historical append replaced unknown effective usage once without a send")}
        stages = {"receiver": {"attempt_id": aid,
                               "arrival_count": after["receiver_arrivals"]},
                  "settlement": {"previous_revision_count": before["usage_revisions"],
                                 "revision_count": after["usage_revisions"],
                                 "cost_status": usage.get("cost_status", "absent")}}
        return _evidence(runtime, case, stages, checks,
                         {"append_outcome": outcome, "status": status,
                          "before": before, "after": after}, aid)

    if variant == "denied_resume":
        runtime.authority.set_historical_access(context["identity"], read=True,
            write=True, resume=False, observed_at=_current_utc())
        denied = False
        try:
            runtime.successor.resume_campaign(sid, trusted, "test denied historical resume")
        except PermissionError:
            denied = True
        after = _census(runtime)
        checks = {"recovery_chain.denied_resume": (
            denied and after["campaign"]["paused"] and
            after["campaign"]["attempt_count"] == before["campaign"]["attempt_count"] and
            after["receiver_arrivals"] == before["receiver_arrivals"],
            "Revoked historical resume permission denied while exposure/counters remained fixed")}
        stages = {"authority": {"historical_resume_permission": False,
                                "denied": denied},
                  "settlement": {"paused": after["campaign"]["paused"],
                                 "possible_sends": after["campaign"]["possible_send_count"]}}
        return _evidence(runtime, case, stages, checks,
                         {"before": before, "after": after}, aid)

    if variant == "eligible_resume":
        runtime.authority.set_historical_access(context["identity"], read=True,
            write=True, resume=True, observed_at=_current_utc())
        decision = runtime.successor.resume_campaign(sid, trusted,
            "test same-scope supported recovery")
        after = _census(runtime)
        checks = {"recovery_chain.eligible_resume": (
            decision.get("decision") == "resumed" and not after["campaign"]["paused"] and
            after["campaign"]["attempt_count"] == before["campaign"]["attempt_count"] and
            after["campaign"]["possible_send_count"] == before["campaign"]["possible_send_count"] and
            after["receiver_arrivals"] == before["receiver_arrivals"],
            "Audited same-scope eligibility resumed only after retained receipt settlement")}
        stages = {"authority": {"actor_id": decision.get("actor_id", "absent"),
                                "decision": decision.get("decision", "absent")},
                  "settlement": {"paused": after["campaign"]["paused"],
                                 "blockers": decision.get("blockers", [])}}
        return _evidence(runtime, case, stages, checks,
                         {"decision": decision, "before": before, "after": after}, aid)
    raise NotImplementedError(f"unimplemented recovery-chain variant: {variant}")


def authority_recovery(runtime, case):
    """Fresh first-write authority checks under the same accepted plan."""
    if (case["scenario_id"], case["variant"]) == ("t14_a", "composed"):
        from dev12_completion_boundary_handlers import assessment_transition
        return assessment_transition(runtime, case)
    if case["scenario_id"] == "t24_b":
        from dev12_completion_boundary_handlers import first_write_order
        return first_write_order(runtime, case)
    if (case["scenario_id"], case["variant"]) == ("t24_c", "composed"):
        from dev12_completion_boundary_handlers import crash_recovery
        return crash_recovery(runtime, case)
    if case["scenario_id"].startswith("t45_"):
        from duranki_server.successor_plan import execution_eligible
        scenario = case["scenario_id"]
        before = _census(runtime)
        outcomes = {}
        observed = {}

        def changed_revision(name, *, send_permission=None):
            def mutate(state):
                state["revisions"][name] += 1
                if send_permission is not None:
                    state["send_permission"] = send_permission
            runtime.authority.update(mutate, {"kind": "completion02_named_authority_change",
                "revision": name, "send_permission": send_permission, "at": _current_utc()})

        def queued(label, revision):
            request = _case_request(runtime, case)
            request["work_selector"]["step_id"] += "." + label
            fired = []
            async def lower_wait():
                if not fired:
                    fired.append(True)
                    changed_revision(revision)
            runtime.executor.first_write_wait = lower_wait
            try:
                response = _post(runtime, request, _headers(runtime))
            finally:
                runtime.executor.first_write_wait = None
            status = response["status"] or {}
            sid = response["reply"].get("handle", {}).get("submission_id")
            record = runtime.store.successor_get(sid) if sid else None
            observations = {"fired": bool(fired), "response": response,
                "record": record, "revision": revision}
            outcomes[label] = observations
            return observations

        def positive(label):
            request = _case_request(runtime, case)
            request["work_selector"]["step_id"] += "." + label
            response = _post(runtime, request, _headers(runtime))
            sid = response["reply"].get("handle", {}).get("submission_id")
            record = runtime.store.successor_get(sid) if sid else None
            item = {"response": response, "record": record}
            outcomes[label] = item
            return item

        if scenario == "t45_a":
            control = positive("control")
            record = control["record"]
            if not record:
                raise AssertionError("source/account/operation control absent")
            context = runtime.authority.current_context(record, _current_utc())
            plan = record["signed_plan"]
            negatives = {}
            for name, mutation in (
                    ("source_isolation", {"expected_work_digest": "sha256:" + "0" * 64}),
                    ("account_isolation", {"expected_financial_owner_id": "team.other.synthetic"}),
                    ("operation_isolation", {"expected_reservation": {
                        **context["expected_reservation"],
                        "price_ref": "price.rerank.synthetic.a"}})):
                changed = deepcopy(context)
                changed.update(mutation)
                negatives[name] = not execution_eligible(plan, record["request"],
                    record["canonical_work"], record["admission_snapshot"], changed)
            observed = {"signed_plan": plan, "negative_decisions": negatives}
            checks = {f"t45_a.{name}": (bool(value and
                control["response"]["status"].get("submission_state") == "completed"),
                "Independent source, account or operation scope change cannot execute the admitted signed plan")
                for name, value in negatives.items()}
        elif scenario in {"t45_b", "t45_c", "t45_d"}:
            mapping = {"t45_b": [("source_disallow_after_wait", "source_permission")],
                "t45_c": [("grant_revoke_after_wait", "grant"),
                          ("delegation_revoke_after_wait", "registry")],
                "t45_d": [("credential_scope_change", "credential_scope"),
                          ("compromise", "source_permission"),
                          ("revocation", "credential_scope")]}
            blocked = {name: queued(name, revision)
                       for name, revision in mapping[scenario]}
            control = positive("after_revision_control")
            checks = {f"{scenario}.{name}": (bool(item["fired"] and
                item["response"]["status"] and
                item["response"]["status"].get("submission_state") == "failed" and
                item["record"] and
                item["record"].get("dispatch_state") == "blocked" and
                control["response"]["status"] and
                control["response"]["status"].get("submission_state") == "completed"),
                "Named current authority revision changed during lower wait; old plan was blocked and new plan succeeded")
                for name, item in blocked.items()}
            observed = {"named_revision_cases": list(blocked),
                        "control_submission": control["record"]["submission_id"]}
        elif scenario == "t45_e":
            from cryptography.hazmat.primitives.asymmetric import ed25519
            first = positive("rotation_control")
            old = first["record"]
            old_plan = old["signed_plan"]
            new_key = ed25519.Ed25519PrivateKey.generate()
            new_version = "v.t45.rotation"
            runtime.persist_signer(new_key, new_version)
            runtime.authority.rotate_minting_key(new_key,
                "key.synthetic.dev12", new_version, _current_utc())
            current = runtime.authority.current_context(old, _current_utc())
            old_eligible = execution_eligible(old_plan, old["request"],
                old["canonical_work"], old["admission_snapshot"], current)
            invalid = queued("changed_revision", "grant")
            control = positive("new_revision_control")
            checks = {
                "t45_e.eligible_rotation": (bool(old_eligible and
                    old_plan["key_version"] !=
                    control["record"]["signed_plan"]["key_version"] and
                    control["response"]["status"].get("submission_state") == "completed"),
                    "Old bound verification key remained eligible during ordinary active minting rotation"),
                "t45_e.changed_revision_without_authority": (bool(invalid["fired"] and
                    invalid["response"]["status"].get("submission_state") == "failed" and
                    invalid["record"].get("dispatch_state") == "blocked"),
                    "Unrelated changed grant revision remained a first-write blocker after key rotation")}
            observed = {"old_plan": old_plan, "old_eligible_after_rotation": old_eligible,
                "changed_revision": invalid}
        else:
            raise NotImplementedError("unknown T-45 scenario")
        after = _census(runtime)
        if not control["record"]:
            raise AssertionError("T-45 positive control not admitted")
        stages = {"admission": {"before": before["submissions"],
                    "after": after["submissions"]},
                  "signed_plan": {"positive_plan_id": control["record"]["signed_plan"]["plan_id"]},
                  "authority": {"named_revisions": runtime.authority.revisions()},
                  "guard": {"before": before["guard_ownership"],
                            "after": after["guard_ownership"]},
                  "first_write": {"receiver_before": before["receiver_arrivals"],
                                  "receiver_after": after["receiver_arrivals"]}}
        return _evidence(runtime, case, stages, checks,
            {"outcomes": outcomes, "observed": observed,
             "before": before, "after": after}, control["record"]["attempt_id"])
    if case["scenario_id"] == "t24_a" and case["variant"] in {
            "queued_revocation", "eligible_control"}:
        request = _case_request(runtime, case)
        before = _census(runtime)
        fired = []
        def set_permission(allowed):
            def change(state):
                state["send_permission"] = allowed
            runtime.authority.update(change, {"kind": "completion02_send_permission",
                "allowed": allowed, "at": _current_utc()})
        async def lower_wait():
            if not fired:
                fired.append(True)
                set_permission(False)
        if case["variant"] == "queued_revocation":
            runtime.executor.first_write_wait = lower_wait
        try:
            reply = _post(runtime, request, _headers(runtime))
        finally:
            runtime.executor.first_write_wait = None
            if fired:
                set_permission(True)
        after = _census(runtime)
        status = reply["status"] or {}
        if case["variant"] == "queued_revocation":
            passed = (bool(fired) and status.get("submission_state") == "failed" and
                status.get("attempts", [{}])[0].get("dispatch_state") == "blocked" and
                after["receiver_arrivals"] == before["receiver_arrivals"] and
                after["submissions"] == before["submissions"] + 1)
            detail = "Durable local send revocation at queued first-write wait blocked receiver bytes"
        else:
            passed = (not fired and status.get("submission_state") == "completed" and
                after["receiver_arrivals"] == before["receiver_arrivals"] + 1 and
                after["submissions"] == before["submissions"] + 1)
            detail = "Eligible queued control completed one guarded receiver send"
        checks = {f"t24_a.{case['variant']}": (passed, detail)}
        sid = reply["reply"].get("handle", {}).get("submission_id")
        record = runtime.store.successor_get(sid) if sid else None
        return _evidence(runtime, case,
            {"admission": {"submission_id": sid or "absent"},
             "signed_plan": {"plan_id": record["signed_plan"]["plan_id"] if record else "absent"},
             "authority": {"revoked_at_lower_wait": bool(fired)},
             "guard": {"ownership_delta": after["guard_ownership"] - before["guard_ownership"]},
             "first_write": {"arrival_delta": after["receiver_arrivals"] - before["receiver_arrivals"]}},
            checks, {"reply": reply, "record": record,
                     "before": before, "after": after},
            record["attempt_id"] if record else "none")
    if case["scenario_id"] in {"t46_a", "t46_b", "t46_c", "t46_d"} and \
            case["variant"] == "composed":
        from duranki_server.successor_plan import execution_eligible, verified_signature
        request = _case_request(runtime, case)
        if case["scenario_id"] == "t46_a":
            request["input"]["items"] = [
                {"item_id": "doc.one", "text": "Sky"},
                {"item_id": "doc.two", "text": "Earth 🌍"}]
        before = _census(runtime)
        positive = _post(runtime, request, _headers(runtime))
        after = _census(runtime)
        sid = positive["reply"].get("handle", {}).get("submission_id")
        if not sid:
            raise AssertionError("signed-plan mutation control was not admitted")
        record = runtime.store.successor_get(sid)
        plan = record["signed_plan"]
        current = runtime.authority.current_context(record, _current_utc())
        key = next(item for item in current["verification_keys"]
                   if (item["key_id"], item["key_version"]) ==
                      (plan["key_id"], plan["key_version"]))
        def eligible(*, changed_plan=None, changed_request=None,
                     changed_work=None, changed_snapshot=None, changed_context=None):
            return execution_eligible(changed_plan or plan,
                changed_request or record["request"],
                changed_work or record["canonical_work"],
                changed_snapshot or record["admission_snapshot"],
                changed_context or current)
        original = eligible() and verified_signature(plan, key)
        negatives = {}
        supplemental = {}
        scenario = case["scenario_id"]
        if scenario == "t46_a":
            changes = {}
            op = deepcopy(record["request"])
            op["operation"]["version"] = 2
            changes["operation_mutation"] = op
            payload = deepcopy(record["request"])
            payload["input"]["items"][0]["text"] = "River"
            changes["payload_mutation"] = payload
            ordered = deepcopy(record["request"])
            ordered["input"]["items"].reverse()
            changes["order_mutation"] = ordered
            compatibility = deepcopy(record["request"])
            compatibility["requested_configuration_ref"] = "cfg.rerank.synthetic"
            changes["compatibility_mutation"] = compatibility
            negatives = {name: not eligible(changed_request=value)
                         for name, value in changes.items()}
            supplemental = {"mutated_requests": changes}
        elif scenario == "t46_b":
            snapshot = record["admission_snapshot"]
            changes = {}
            status = deepcopy(snapshot)
            status["commission"] = {"status": "verified", "evidence_scope": "synthetic.review",
                                    "evidence_ref": "evidence.synthetic"}
            changes["assessment_status_tamper"] = status
            coverage = deepcopy(snapshot)
            coverage["delegation"]["coverage"] = "partial"
            changes["coverage_tamper"] = coverage
            reason = deepcopy(snapshot)
            reason["commission"]["absence_reason"] = "not_yet_issued"
            changes["reason_tamper"] = reason
            link = deepcopy(snapshot)
            link["work_digest"] = "sha256:" + "0" * 64
            changes["digest_link_tamper"] = link
            negatives = {name: not eligible(changed_snapshot=value)
                         for name, value in changes.items()}
            before_later = deepcopy(runtime.store.successor_get(sid))
            runtime.store.successor_append_evidence(sid, "later_assessment",
                _current_utc(), {"kind": "synthetic_review", "status": "recorded_only"})
            after_later = runtime.store.successor_get(sid)
            negatives["later_assessment"] = (after_later["work_digest"] ==
                before_later["work_digest"] and
                after_later["admission_snapshot"] == before_later["admission_snapshot"] and
                after_later["signed_plan"] == before_later["signed_plan"])
            supplemental = {"mutated_snapshots": changes,
                            "before_later": before_later, "after_later": after_later}
        elif scenario == "t46_c":
            activation_plan = deepcopy(plan)
            activation_plan["execution_context"] = {"state": "tagged_fixture",
                                                    "epoch": "epoch.synthetic.changed"}
            activation_context = deepcopy(current)
            activation_context["expected_execution_context"] = {
                "state": "tagged_fixture", "epoch": "epoch.synthetic.changed"}
            negatives = {"activation_mutation": (
                not verified_signature(activation_plan, key) and
                not eligible(changed_plan=activation_plan) and
                not eligible(changed_context=activation_context)),
                "eligible_activation": original}
            supplemental = {"activation_plan": activation_plan,
                            "activation_context": activation_context}
        else:
            changed_price = deepcopy(plan)
            changed_price["price_ref"] = "price.rerank.synthetic.a"
            changed_owner = deepcopy(plan)
            changed_owner["financial_owner_id"] = "team.forged"
            negatives = {
                "price_mutation": (not verified_signature(changed_price, key) and
                                   not eligible(changed_plan=changed_price)),
                "owner_mutation": (not verified_signature(changed_owner, key) and
                                   not eligible(changed_plan=changed_owner))}
            supplemental = {"price_plan": changed_price, "owner_plan": changed_owner}
        checks = {f"{scenario}.{name}": (bool(original and rejected and
            positive["status"] and positive["status"].get("submission_state") == "completed" and
            after["receiver_arrivals"] == before["receiver_arrivals"] + 1),
            "Changed signed/admitted binding rejected by the execution eligibility validator used at first-write guard")
            for name, rejected in negatives.items()}
        stages = {"admission": {"submission_id": sid},
                  "signed_plan": {"plan_id": plan["plan_id"],
                                  "signature_valid": verified_signature(plan, key)},
                  "authority": {"evaluated_bindings": list(negatives)},
                  "guard": {"ownership_delta": after["guard_ownership"] - before["guard_ownership"]},
                  "first_write": {"arrival_delta": after["receiver_arrivals"] - before["receiver_arrivals"]}}
        return _evidence(runtime, case, stages, checks,
                         {"positive": positive, "record": record, "current": current,
                          "negative_decisions": negatives, "supplemental": supplemental,
                          "before": before, "after": after}, record["attempt_id"])
    if case["scenario_id"] != "t07_a" or case["variant"] not in {
            "eligible_current", "rotated_old_eligible", "revoked_key_after_wait",
            "revoked_plan_after_wait"}:
        raise NotImplementedError("authority/recovery variant not implemented")
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from duranki_server.successor_plan import verified_signature

    request = _case_request(runtime, case)
    before = _census(runtime)
    variant = case["variant"]
    fired = []
    action_record = {}
    rotation_version = "v.t07.rotated"
    recovery_version = "v.t07.recovery"

    async def after_lower_wait():
        if fired:
            return
        fired.append(True)
        stored = runtime.store.successor_by_work({
            "principal_id": runtime.contexts_by_credential[
                runtime.credentials["DIRECT_DOCUMENT"]]["identity"]["principal_id"],
            **request["work_selector"]})
        if stored is None:
            raise AssertionError("admitted plan not visible at lower wait")
        plan = stored["signed_plan"]
        action_record.update({"submission_id": stored["submission_id"],
                              "attempt_id": stored["attempt_id"],
                              "original_plan_id": plan["plan_id"],
                              "original_key_id": plan["key_id"],
                              "original_key_version": plan["key_version"],
                              "original_signature": plan["signature"]})
        if variant == "rotated_old_eligible":
            rotated = ed25519.Ed25519PrivateKey.generate()
            runtime.persist_signer(rotated, rotation_version)
            runtime.authority.rotate_minting_key(rotated,
                "key.synthetic.dev12", rotation_version, _current_utc())
        elif variant == "revoked_key_after_wait":
            runtime.authority.revoke_key_version(plan["key_id"],
                plan["key_version"], _current_utc())
        elif variant == "revoked_plan_after_wait":
            runtime.authority.revoke_plan(plan["plan_id"], _current_utc())

    if variant != "eligible_current":
        runtime.executor.first_write_wait = after_lower_wait
    try:
        outcome = _post(runtime, request, _headers(runtime))
    finally:
        runtime.executor.first_write_wait = None
    after = _census(runtime)
    sid = outcome["reply"].get("handle", {}).get("submission_id")
    if not sid:
        raise AssertionError("admitted authority case lacks submission handle")
    record = runtime.store.successor_get(sid)
    plan = record["signed_plan"]
    key = next((item for item in runtime.authority.state["verification_keys"]
                if item["key_id"] == plan["key_id"] and
                   item["key_version"] == plan["key_version"]), None)
    signature_valid = key is not None and verified_signature(plan, key)
    if variant == "revoked_key_after_wait":
        # Leave the run with a fresh eligible minting tuple; retain revoked v1/v2.
        recovery_key = ed25519.Ed25519PrivateKey.generate()
        runtime.persist_signer(recovery_key, recovery_version)
        runtime.authority.rotate_minting_key(recovery_key,
            "key.synthetic.dev12", recovery_version, _current_utc())
    completed = outcome["status"] and outcome["status"].get("submission_state") == "completed"
    blocked = outcome["status"] and outcome["status"].get("submission_state") == "failed"
    common = (signature_valid and after["submissions"] == before["submissions"] + 1 and
              after["campaign"]["attempt_count"] == before["campaign"]["attempt_count"] + 1)
    if variant == "eligible_current":
        passed = bool(common and completed and
            after["receiver_arrivals"] == before["receiver_arrivals"] + 1 and
            not fired)
        detail = "Eligible current signed key completed one guarded receiver send"
    elif variant == "rotated_old_eligible":
        passed = bool(common and completed and fired and
            plan["key_version"] == action_record.get("original_key_version") and
            runtime.authority.state["active_minting_key"]["key_version"] == rotation_version and
            plan["signature"] == action_record.get("original_signature") and
            after["receiver_arrivals"] == before["receiver_arrivals"] + 1)
        detail = "Rotation selected a new signer while the unchanged eligible old plan sent once"
    elif variant == "revoked_key_after_wait":
        passed = bool(common and blocked and fired and
            key["eligibility"] == "revoked" and
            plan["signature"] == action_record.get("original_signature") and
            after["receiver_arrivals"] == before["receiver_arrivals"])
        detail = "Correctly signed plan under newly revoked bound key was denied after lower wait"
    else:
        passed = bool(common and blocked and fired and
            plan["plan_id"] in runtime.authority.state["revoked_plans"] and
            plan["signature"] == action_record.get("original_signature") and
            after["receiver_arrivals"] == before["receiver_arrivals"])
        detail = "Unchanged signed plan was denied after lower-wait plan revocation"
    checks = {f"t07_a.{variant}": (passed, detail)}
    stages = {"admission": {"submission_id": sid},
              "signed_plan": {"plan_id": plan["plan_id"],
                              "key_version": plan["key_version"],
                              "signature_valid": signature_valid},
              "authority": {"lower_wait_hook_fired": bool(fired),
                            "bound_key_eligibility": key["eligibility"],
                            "plan_revoked": plan["plan_id"] in
                                            runtime.authority.state["revoked_plans"]},
              "guard": {"ownership_delta": after["guard_ownership"] -
                        before["guard_ownership"]},
              "first_write": {"receiver_arrival_delta": after["receiver_arrivals"] -
                              before["receiver_arrivals"]}}
    return _evidence(runtime, case, stages, checks,
        {"request": request, "outcome": outcome, "action_record": action_record,
         "original_plan": plan, "before": before, "after": after},
        record["attempt_id"])


def native_accounting(runtime, case):
    """Independently recompute all fixed native-unit tariff rows and bounds."""
    if (case["scenario_id"], case["variant"]) == ("t50_e", "composed"):
        # The current fixed mint reserves the upward rounded full tariff, so
        # a fresh supported send cannot exceed its own bound. Exercise the
        # adopted historical-underbound read/settlement path in a distinct,
        # zero-send imported fixture scope; leave the live campaign untouched.
        from duranki_server.store import SQLiteStore
        from duranki_server.successor_campaign import FiniteSuccessorCampaign
        from duranki_server.successor_contract import (native_usage_row, price_for,
            tariff, usage_valid)
        from duranki_server.successor_plan import (plan_valid, signing_message,
            verified_signature)
        from duranki_server.successor_reporting import usage_report
        import base64
        before = _census(runtime)
        with runtime.store._lock:
            source_rows = [json.loads(row[0]) for row in runtime.store.db.execute(
                "SELECT record FROM dev12_submissions ORDER BY rowid")]
        chosen = None
        for source in source_rows:
            latest = runtime.store.successor_latest_usage(source["attempt_id"])
            if (source["submission_state"] == "completed" and latest and
                    latest["cost_status"] == "calculated" and
                    Decimal(latest["amount_decimal"]) > Decimal("0.000100000") and
                    any(row["attempt_id"] == source["attempt_id"] for row in
                        [json.loads(line) for line in runtime.receiver_log.read_text().splitlines()])):
                chosen = (source, latest)
                break
        if chosen is None:
            raise AssertionError("genuine completed receiver/control attempt unavailable")
        source, source_usage = chosen
        historical = deepcopy(source)
        historical_scope = "campaign.fixture.imported.underbound"
        historical["campaign_id"] = historical_scope
        historical["reservation"]["max_exposure_decimal"] = "0.000100000"
        historical["signed_plan"]["reservation"] = deepcopy(historical["reservation"])
        historical["signed_plan"]["key_id"] = runtime.authority.key_id
        historical["signed_plan"]["key_version"] = runtime.authority.key_version
        historical["signed_plan"]["signature"] = base64.urlsafe_b64encode(
            runtime.authority.private_key.sign(
                signing_message(historical["signed_plan"]))).decode().rstrip("=")
        historical.pop("effective_usage_revision", None)
        historical["settlement_state"] = "pending"
        historical["exposure_state"] = "outstanding"
        fixture_path = runtime.root / "cases" / (case["id"] + "-historical.sqlite")
        fixture_path.parent.mkdir(exist_ok=True)
        if fixture_path.exists():
            raise RuntimeError("historical fixture path already exists")
        fixture = SQLiteStore(fixture_path)
        try:
            fixture.successor_create(historical)  # imported fixture; no reserve callback
            fixture_campaign = FiniteSuccessorCampaign(fixture, historical_scope,
                historical["reservation"]["budget_account_id"],
                financial_owner_id=historical["trusted_identity"]["charging_owner_id"])
            fixture_campaign.start({"kind": "imported_historical_underbound"},
                [str(fixture_path)], max_attempts=0, max_concurrent=0,
                ceiling_decimal="0.000100000", window_hours=1)
            component = deepcopy(source_usage["components"][0])
            usage = native_usage_row(historical["request"], historical["attempt_id"],
                1, component, historical["reservation"]["max_exposure_decimal"])
            import_result = fixture.successor_append_usage(historical["submission_id"],
                usage, _current_utc(), write_allowed=True,
                on_settlement=lambda db, state: fixture_campaign.pause_in_transaction(
                    db, "over_bound") if state == "over_bound" else None)
            retained = fixture.successor_get(historical["submission_id"])
            projected = usage_report(fixture,
                {"role": "registry_admin", "principal_id": "owner.synthetic"})
            fixture_state = fixture_campaign.inspect()
        finally:
            fixture.close()
        after = _census(runtime)
        price = price_for(historical["request"])
        exact = tariff(historical["request"], price)["settled"]
        key = next(item for item in runtime.authority.state["verification_keys"]
                   if item["key_id"] == runtime.authority.key_id and
                      item["key_version"] == runtime.authority.key_version)
        valid_history = plan_valid(historical["signed_plan"], historical["request"],
            historical["work_digest"], historical["admission_snapshot_digest"],
            historical["trusted_identity"]["charging_owner_id"],
            permit_historical_underbound=True)
        no_new = (before == after and fixture_state["attempt_count"] == 0 and
            fixture_state["possible_send_count"] == 0)
        checks = {
            "t50_e.above_bound_recorded": (bool(no_new and valid_history and
                verified_signature(historical["signed_plan"], key) and
                import_result == "accepted" and usage_valid(usage,
                    historical["request"], historical["attempt_id"],
                    historical["reservation"]["price_ref"],
                    historical["reservation"]["usage_ref"],
                    historical["reservation"]["max_exposure_decimal"]) and
                usage["cost_status"] == "over_bound" and
                usage["amount_decimal"] == exact and
                Decimal(exact) > Decimal("0.000100000") and
                projected["total"]["known_usd"] == exact and
                projected["total"]["over_bound_attempts"] == 1),
                "Imported historical underbound fixture records exact actual tariff above bound without clamping or a new send"),
            "t50_e.affected_scope_paused": (bool(no_new and
                retained["settlement_state"] == "over_bound" and
                retained["exposure_state"] == "over_bound" and
                fixture_state["paused"] and
                "over_bound" in fixture_state["pause_reasons"]),
                "Only the separate zero-send historical fixture scope paused on accepted over-bound usage")}
        stages = {"admission": {"kind": "imported_historical_fixture",
                    "source_submission_id": source["submission_id"],
                    "new_live_admissions": 0},
                  "receiver": {"source_attempt_id": source["attempt_id"],
                               "source_receipt": "retained_actual_receiver_arrival"},
                  "delivery": {"source_state": source["submission_state"],
                               "fixture_state": retained["submission_state"]},
                  "settlement": {"state": usage["cost_status"],
                                 "amount_decimal": usage["amount_decimal"],
                                 "historical_bound_decimal": "0.000100000"}}
        return _evidence(runtime, case, stages, checks,
            {"kind": "synthetic_imported_historical_underbound_no_live_admission",
             "source_record": source, "source_usage": source_usage,
             "imported_record": retained, "imported_usage": usage,
             "fixture_campaign": fixture_state, "fixture_report": projected,
             "fixture_sqlite_sha256": sha256(fixture_path.read_bytes()).hexdigest(),
             "main_before": before, "main_after": after}, case["attempt_group"])
    if (case["scenario_id"], case["variant"]) == ("t50_c", "composed"):
        request = _case_request(runtime, case, item_id="doc.unknown.recoverable")
        before = _census(runtime)
        first = _post(runtime, request, _headers(runtime))
        unknown = _census(runtime)
        sid = first["reply"].get("handle", {}).get("submission_id")
        if not sid or first["status"].get("submission_state") != "unknown":
            raise AssertionError("recoverable unknown target outcome absent")
        original = runtime.store.successor_get(sid)
        restarted = runtime.restart_service()
        retained = runtime.successor.status(sid, _trusted(runtime))
        after_restart = _census(runtime)
        denied_request = _case_request(runtime, case)
        denied_request["work_selector"]["step_id"] += ".after.restart"
        denied = _post(runtime, denied_request, _headers(runtime))
        still_paused = _census(runtime)
        collected = runtime.successor.collect_receiver_receipt(sid, _trusted(runtime))
        resumed = runtime.successor.resume_campaign(sid, _trusted(runtime),
            "same campaign retained receipt after restart")
        after = _census(runtime)
        passed = bool(unknown["campaign"]["paused"] and
            after_restart["campaign"]["paused"] and
            after_restart["campaign"]["start_at"] == before["campaign"]["start_at"] and
            retained["submission_state"] == "unknown" and
            retained["attempts"][0]["attempt_id"] == original["attempt_id"] and
            denied["http_status"] == 403 and
            still_paused["submissions"] == unknown["submissions"] and
            still_paused["receiver_arrivals"] == unknown["receiver_arrivals"] and
            still_paused["campaign"]["possible_send_count"] ==
                unknown["campaign"]["possible_send_count"] and
            collected == "accepted" and resumed.get("decision") == "resumed" and
            after["receiver_arrivals"] == unknown["receiver_arrivals"] and
            after["campaign"]["possible_send_count"] ==
                unknown["campaign"]["possible_send_count"])
        checks = {"t50_c.restart_unknown_exposure": (passed,
            "Restart retained one possible-send exposure and denied new admission before authenticated receipt correction")}
        stages = {"admission": {"submission_id": sid,
                    "attempt_id": original["attempt_id"]},
                  "receiver": {"arrivals_before": before["receiver_arrivals"],
                               "arrivals_after": after["receiver_arrivals"]},
                  "delivery": {"retained_state": retained["submission_state"],
                               "denied_http": denied["http_status"]},
                  "settlement": {"paused_after_restart": after_restart["campaign"]["paused"],
                                 "collected": collected, "resume": resumed.get("decision")}}
        return _evidence(runtime, case, stages, checks,
            {"first": first, "original": original, "restart": restarted,
             "retained": retained, "denied": denied, "collected": collected,
             "resumed": resumed, "before": before, "unknown": unknown,
             "after_restart": after_restart, "still_paused": still_paused,
             "after": after}, original["attempt_id"])
    if case["scenario_id"] == "t50_a" and case["variant"] == "composed":
        import asyncio
        release = threading.Event()
        arrived = threading.Event()
        lock = threading.Lock()
        waiting = []

        async def lower_wait():
            with lock:
                waiting.append(time.monotonic_ns())
                if len(waiting) == 2:
                    arrived.set()
            if not await asyncio.to_thread(release.wait, 10):
                raise TimeoutError("bounded first-write concurrency barrier expired")

        before = _census(runtime)
        runtime.executor.first_write_wait = lower_wait
        try:
            with ThreadPoolExecutor(max_workers=3) as pool:
                first = pool.submit(_post, runtime,
                    _retrieval_request(runtime, case, "DIRECT_DOCUMENT", "one", ["doc.one"]),
                    _headers(runtime))
                second = pool.submit(_post, runtime,
                    _retrieval_request(runtime, case, "DIRECT_DOCUMENT", "two", ["doc.two"]),
                    _headers(runtime))
                if not arrived.wait(8):
                    raise AssertionError("two in-flight first-write waits were not reached")
                held = _census(runtime)
                third = _post(runtime,
                    _retrieval_request(runtime, case, "DIRECT_DOCUMENT", "three", ["doc.three"]),
                    _headers(runtime))
                denied = _census(runtime)
                release.set()
                replies = [first.result(timeout=20), second.result(timeout=20)]
        finally:
            release.set()
            runtime.executor.first_write_wait = None
        after = _census(runtime)
        checks = {
            "t50_a.two_contenders": (len(waiting) == 2 and held["campaign"]["inflight_count"] == 2 and
                all(row["status"] and row["status"].get("submission_state") == "completed"
                    for row in replies) and
                after["receiver_arrivals"] == before["receiver_arrivals"] + 2,
                "Two distinct normal submissions held in flight and each completed one guarded send"),
            "t50_a.finite_cap": (third["http_status"] == 403 and
                denied["submissions"] == before["submissions"] + 2 and
                denied["receiver_arrivals"] == before["receiver_arrivals"] and
                after["campaign"]["inflight_count"] == 0,
                "Third concurrent admission rejected at selected two-in-flight cap before send")}
        stages = {"admission": {"before": before["submissions"],
                                "held": held["submissions"], "after": after["submissions"]},
                  "receiver": {"before": before["receiver_arrivals"],
                               "after": after["receiver_arrivals"]},
                  "delivery": {"states": [row["status"].get("submission_state")
                                          for row in replies]},
                  "settlement": {"held_inflight": held["campaign"]["inflight_count"],
                                 "after_inflight": after["campaign"]["inflight_count"]}}
        return _evidence(runtime, case, stages, checks,
                         {"before": before, "held": held, "denied": denied,
                          "third": third, "replies": replies, "after": after},
                         replies[0]["reply"].get("attempt_id", "none"))
    if case["scenario_id"] in {"t49_a", "t49_b", "t49_c", "t49_d",
                                "t49_e", "t50_d", "t48_f"}:
        scenario, variant = case["scenario_id"], case["variant"]
        if scenario == "t49_a" and variant == "composed":
            modes = [("doc.valid.absent", "absent")]
        elif scenario == "t49_b" and variant == "composed":
            modes = [("doc.valid.null", "null")]
        elif scenario == "t49_c" and variant == "contradictory_zero":
            modes = [("doc.valid.zero", "zero")]
        elif scenario == "t48_f" and variant == "composed":
            modes = [("doc.valid.absent", "missing"),
                     ("doc.valid.null", "null"),
                     ("doc.valid.array", "invalid"),
                     ("doc.valid.zero", "zero"),
                     ("doc.valid.derived", "contradictory")]
        elif scenario == "t49_d" and variant == "composed":
            modes = [("doc.valid.malformed_unicode", "invalid"),
                     ("doc.valid.out_of_domain", "out_of_domain"),
                     ("doc.valid.zero", "contradictory")]
        elif scenario in {"t49_e", "t50_d"} and variant == "composed":
            modes = [("doc.valid.absent", "late")]
        elif scenario == "t49_c" and variant == "consistent_zero":
            # This profile has no accepted zero-unit operation: every request
            # has at least one item at a strictly positive fictional rate.
            request = _case_request(runtime, case)
            before = _census(runtime)
            positive = _post(runtime, request, _headers(runtime))
            after = _census(runtime)
            usage = (positive["status"] or {}).get("attempts", [{}])[0].get("usage_revision", {})
            prices = json.loads((Path(__file__).resolve().parents[2] /
                "tests/fixtures/contracts/dev12-successor-01/tariffs.json").read_text())
            consistent = bool(usage.get("cost_status") == "calculated" and
                usage.get("components", [{}])[0].get("quantity") == 1 and
                all(Decimal(row["tariff_b"]["raw_usd"]) > 0 and
                    Decimal(row["tariff_a"]["raw_usd"]) > 0
                    for row in prices["rows"]) and
                Decimal(prices["embedding_document"]["per_item_usd"]) > 0 and
                Decimal(prices["embedding_query"]["per_item_usd"]) > 0 and
                after["receiver_arrivals"] == before["receiver_arrivals"] + 1)
            checks = {"t49_c.consistent_zero": (consistent,
                "A valid one-unit charged control confirms no zero-unit result is consistent with this fixed positive-domain profile")}
            stages = {"admission": {"submission_id": positive["reply"].get("handle", {}).get("submission_id", "absent")},
                      "receiver": {"arrivals_delta": after["receiver_arrivals"] - before["receiver_arrivals"]},
                      "delivery": {"state": (positive["status"] or {}).get("submission_state", "absent")},
                      "settlement": {"cost_status": usage.get("cost_status", "absent"),
                                     "quantity": usage.get("components", [{}])[0].get("quantity", -1)}}
            return _evidence(runtime, case, stages, checks,
                             {"positive": positive, "before": before, "after": after,
                              "fixed_tariff_domain": prices["domain"]},
                             positive["reply"].get("attempt_id", "none"))
        else:
            raise NotImplementedError("native zero/unknown branch not implemented")
        cases = [_unknown_then_retained_correction(runtime, case, item, suffix)
                 for item, suffix in modes]
        by_mode = {suffix: observation for (_item, suffix), observation in zip(modes, cases)}
        if scenario == "t49_a":
            checks = {"t49_a.absent_counter": (
                cases[0]["status_before"]["attempts"][0]["usage_revision"]["components"][0]["presence"] ==
                    "absent" and cases[0]["paused"]["campaign"]["paused"],
                "Absent counter retained as unknown liability before independent late receipt correction")}
        elif scenario == "t49_b":
            checks = {"t49_b.null_counter": (
                cases[0]["status_before"]["attempts"][0]["usage_revision"]["components"][0]["presence"] ==
                    "null" and cases[0]["paused"]["campaign"]["paused"],
                "Explicit null remains distinct from absence and unknown before correction")}
        elif scenario == "t49_c":
            zero_usage = cases[0]["status_before"]["attempts"][0]["usage_revision"]
            checks = {"t49_c.contradictory_zero": (
                zero_usage["cost_status"] == "unknown" and
                zero_usage["components"][0].get("quantity") == 0 and
                "amount_decimal" not in zero_usage,
                "Reported zero in positive-domain request is retained as unknown with no manufactured amount")}
        elif scenario == "t49_d":
            invalid = by_mode["invalid"]
            out_of_domain = by_mode["out_of_domain"]
            contradictory = by_mode["contradictory"]
            invalid_usage = invalid["status_before"]["attempts"][0]["usage_revision"]
            domain_usage = out_of_domain["status_before"]["attempts"][0]["usage_revision"]
            domain_corrected = out_of_domain["status_after"]["attempts"][0]["usage_revision"]
            zero_usage = contradictory["status_before"]["attempts"][0]["usage_revision"]
            checks = {
                "t49_d.invalid_counter": (
                    invalid["status_before"]["submission_state"] == "completed" and
                    invalid_usage["components"][0]["presence"] == "invalid" and
                    invalid_usage["cost_status"] == "unknown",
                    "Malformed Unicode native evidence preserves valid delivered content and unknown charge"),
                "t49_d.out_of_domain": (domain_usage["cost_status"] == "unknown" and
                    domain_usage["components"][0]["presence"] == "known" and
                    domain_usage["components"][0]["evidence"] == "reported" and
                    domain_usage["components"][0]["quantity"] == 999999999 and
                    "amount_decimal" not in domain_usage and
                    domain_corrected["revision"] == 2 and
                    domain_corrected["previous_revision"] == 1 and
                    domain_corrected["cost_status"] == "calculated",
                    "Out-of-domain reported quantity remains unpriced until an independent late correction"),
                "t49_d.contradictory_counter": (zero_usage["cost_status"] == "unknown" and
                    zero_usage["components"][0].get("quantity") == 0,
                    "Contradictory reported zero remains explicit and unpriced")}
        elif scenario == "t49_e":
            entry = cases[0]
            first_usage = entry["status_before"]["attempts"][0]["usage_revision"]
            last_usage = entry["status_after"]["attempts"][0]["usage_revision"]
            checks = {"t49_e.late_revision_no_resend": (
                first_usage["revision"] == 1 and last_usage["revision"] == 2 and
                last_usage["previous_revision"] == 1 and
                entry["after"]["usage_revisions"] == entry["paused"]["usage_revisions"] + 1 and
                entry["after"]["receiver_arrivals"] == entry["paused"]["receiver_arrivals"],
                "Independent retained receipt revised one historical attempt without a second send")}
        elif scenario == "t50_d":
            entry = cases[0]
            earlier = entry["status_before"]["attempts"][0]["usage_revision"]
            later = entry["status_after"]["attempts"][0]["usage_revision"]
            checks = {"t50_d.linked_correction_delta_once": (
                earlier["cost_status"] == "unknown" and
                later["cost_status"] == "calculated" and
                later["revision"] == earlier["revision"] + 1 and
                entry["after"]["campaign"]["possible_send_count"] ==
                    entry["paused"]["campaign"]["possible_send_count"] and
                entry["after"]["receiver_arrivals"] == entry["paused"]["receiver_arrivals"],
                "Linked correction replaces unknown effective amount once without new liability")}
        else:
            checks = {
                "t48_f.missing": (by_mode["missing"]["status_before"]["attempts"][0]["usage_revision"]["components"][0]["presence"] == "absent",
                    "Absent native component retained distinctly"),
                "t48_f.null": (by_mode["null"]["status_before"]["attempts"][0]["usage_revision"]["components"][0]["presence"] == "null",
                    "Explicit null native component retained distinctly"),
                "t48_f.invalid": (by_mode["invalid"]["status_before"]["attempts"][0]["usage_revision"]["components"][0]["presence"] == "invalid",
                    "Array native component normalized to bounded invalid evidence"),
                "t48_f.zero": (by_mode["zero"]["status_before"]["attempts"][0]["usage_revision"]["components"][0].get("quantity") == 0,
                    "Explicit zero native component retained rather than erased"),
                "t48_f.contradictory": (by_mode["contradictory"]["status_before"]["attempts"][0]["usage_revision"]["cost_status"] == "unknown",
                    "Derived rather than reported native quantity leaves cost unknown")}
        first, last = cases[0], cases[-1]
        stages = {"admission": {"attempts_in_case": len(cases),
                                "first_submission": first["reply"]["reply"]["handle"]["submission_id"]},
                  "receiver": {"arrival_delta": last["after"]["receiver_arrivals"] -
                               first["before"]["receiver_arrivals"]},
                  "delivery": {"states": [row["status_before"]["submission_state"] for row in cases]},
                  "settlement": {"unknown_before": [row["status_before"]["attempts"][0]["usage_revision"]["cost_status"]
                                                    for row in cases],
                                 "corrected_after": [row["status_after"]["attempts"][0]["usage_revision"]["cost_status"]
                                                     for row in cases]}}
        return _evidence(runtime, case, stages, checks,
                         {"observations": cases},
                         first["reply"]["reply"].get("attempt_id", "none"))
    if case["scenario_id"] == "t50_b" and case["variant"] in {
            "duplicate_submission", "competing_submission"}:
        request = _case_request(runtime, case)
        before = _census(runtime)
        if case["variant"] == "duplicate_submission":
            first = _post(runtime, request, _headers(runtime))
            middle = _census(runtime)
            second = _post(runtime, request, _headers(runtime))
            after = _census(runtime)
            first_id = first["reply"].get("handle", {}).get("submission_id")
            second_id = second["reply"].get("handle", {}).get("submission_id")
            checks = {"t50_b.duplicate_submission": (bool(
                first_id and first_id == second_id and
                first["status"] and first["status"].get("submission_state") == "completed" and
                middle["submissions"] == before["submissions"] + 1 and
                after["submissions"] == middle["submissions"] and
                after["guard_ownership"] == middle["guard_ownership"] and
                after["receiver_arrivals"] == middle["receiver_arrivals"] and
                after["campaign"]["cumulative_reserved_decimal"] ==
                    middle["campaign"]["cumulative_reserved_decimal"]),
                "Duplicate normal HTTP submit returned original handle without reservation or send")}
            payload = {"first": first, "duplicate": second,
                       "before": before, "middle": middle, "after": after}
            aid = first["reply"].get("attempt_id", "none")
        else:
            competing = deepcopy(request)
            competing["input"]["items"][0]["text"] = "River"
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(_post, runtime, item, _headers(runtime))
                           for item in (request, competing)]
                replies = [future.result(timeout=30) for future in futures]
            after = _census(runtime)
            admitted = [row for row in replies if row["reply"].get("handle")]
            conflicts = [row for row in replies if row["http_status"] == 409 and
                         row["reply"].get("code") == "WORK_CONFLICT"]
            checks = {"t50_b.competing_submission": (bool(
                len(admitted) == len(conflicts) == 1 and
                admitted[0]["status"] and
                admitted[0]["status"].get("submission_state") == "completed" and
                after["submissions"] == before["submissions"] + 1 and
                after["guard_ownership"] == before["guard_ownership"] + 1 and
                after["receiver_arrivals"] == before["receiver_arrivals"] + 1),
                "Concurrent changed-content contenders produced one owner and one 409 conflict")}
            payload = {"contenders": replies, "before": before, "after": after}
            aid = admitted[0]["reply"].get("attempt_id", "none") if admitted else "none"
        stages = {"admission": {"before": before["submissions"],
                                "after": after["submissions"]},
                  "receiver": {"arrivals_before": before["receiver_arrivals"],
                               "arrivals_after": after["receiver_arrivals"]},
                  "delivery": {"guard_ownership_before": before["guard_ownership"],
                               "guard_ownership_after": after["guard_ownership"]},
                  "settlement": {"reserved_before": before["campaign"]["cumulative_reserved_decimal"],
                                 "reserved_after": after["campaign"]["cumulative_reserved_decimal"]}}
        return _evidence(runtime, case, stages, checks, payload, aid)
    if case["scenario_id"] == "t48_g" and case["variant"] == "composed":
        before = _census(runtime)
        one_batch = _retrieval_request(runtime, case, "DELEGATED_RERANK", "one_batch",
                                       ["doc.a", "doc.b", "doc.c"])
        batch = _post(runtime, one_batch, _headers(runtime, "DELEGATED_RERANK"))
        after_batch = _census(runtime)
        duplicate = _post(runtime, one_batch, _headers(runtime, "DELEGATED_RERANK"))
        after_duplicate = _census(runtime)
        splits = []
        for index in range(3):
            request = _retrieval_request(runtime, case, "DELEGATED_RERANK",
                                         "split_" + str(index), ["doc." + str(index)])
            splits.append(_post(runtime, request, _headers(runtime, "DELEGATED_RERANK")))
        after = _census(runtime)
        batch_usage = batch["status"]["attempts"][0]["usage_revision"] if batch["status"] else {}
        split_usage = [row["status"]["attempts"][0]["usage_revision"]
                       for row in splits if row["status"]]
        split_total = sum((Decimal(row.get("amount_decimal", "0")) for row in split_usage),
                          Decimal("0"))
        checks = {
            "t48_g.three_distinct_minima": (len(split_usage) == 3 and
                all(row.get("cost_status") == "calculated" and
                    Decimal(row["amount_decimal"]) == Decimal("0.000300000")
                    for row in split_usage) and split_total == Decimal("0.000900000"),
                "Three distinct n=1 Tariff B attempts each settle the downward half-even tie"),
            "t48_g.one_batch_n3": (batch_usage.get("cost_status") == "calculated" and
                batch_usage.get("components", [{}])[0].get("quantity") == 3 and
                Decimal(batch_usage.get("amount_decimal", "0")) == Decimal("0.000900002"),
                "One n=3 Tariff B batch settles the opposite half-even tie"),
            "t48_g.repeated_attempt": (duplicate["reply"].get("handle") == batch["reply"].get("handle") and
                after_duplicate["submissions"] == after_batch["submissions"] and
                after_duplicate["receiver_arrivals"] == after_batch["receiver_arrivals"] and
                after_duplicate["campaign"]["cumulative_reserved_decimal"] ==
                    after_batch["campaign"]["cumulative_reserved_decimal"],
                "Exact repeated work returns original attempt with no second minimum or send"),
            "t48_g.split_batch": (after["receiver_arrivals"] == before["receiver_arrivals"] + 4 and
                after["submissions"] == before["submissions"] + 4 and
                split_total == Decimal("0.000900000") and
                split_total < Decimal(batch_usage.get("amount_decimal", "0")),
                "Equal raw aggregate rounds differently when split across three attempts")}
        stages = {"accounting": {"batch_amount": batch_usage.get("amount_decimal", "unknown"),
                                 "split_amounts": [row.get("amount_decimal") for row in split_usage],
                                 "attempt_delta": after["submissions"] - before["submissions"]}}
        return _evidence(runtime, case, stages, checks,
                         {"batch": batch, "duplicate": duplicate, "splits": splits,
                          "before": before, "after_batch": after_batch,
                          "after_duplicate": after_duplicate, "after": after},
                         batch["reply"].get("attempt_id", "none"))
    if case["variant"] != "composed" or case["scenario_id"] not in {
            "t48_a", "t48_b", "t48_c", "t48_d", "t48_e"}:
        raise NotImplementedError("native target/evidence branch is not implemented")
    table = json.loads((Path(__file__).resolve().parents[2] /
        "tests/fixtures/contracts/dev12-successor-01/tariffs.json").read_text())
    quantum = Decimal("0.000000001")
    assert table["fictional"] is True and table["currency"] == "USD"
    calculated = []
    for row in table["rows"]:
        n = row["documents"]
        a_units = (n + 9) // 10
        a_raw = max(Decimal("0.005"), Decimal(a_units) * Decimal("0.003"))
        b_rate = Decimal("0.0003000005" if n <= 10 else "0.0004000005")
        b_raw = Decimal(n) * b_rate
        projection = {"documents": n,
            "tariff_a": {"search_units": a_units, "raw_usd": a_raw,
                "settled_usd": a_raw.quantize(quantum, rounding=ROUND_HALF_EVEN),
                "request_bound_usd": a_raw.quantize(quantum, rounding=ROUND_CEILING)},
            "tariff_b": {"document_units": n, "raw_usd": b_raw,
                "settled_usd": b_raw.quantize(quantum, rounding=ROUND_HALF_EVEN),
                "request_bound_usd": b_raw.quantize(quantum, rounding=ROUND_CEILING)}}
        calculated.append(projection)
    def row_matches(index, schedule):
        expected = table["rows"][index][schedule]
        actual = calculated[index][schedule]
        return (all(actual[key] == Decimal(expected[key])
                    for key in ("raw_usd", "settled_usd", "request_bound_usd")) and
                actual["search_units" if schedule == "tariff_a" else "document_units"] ==
                    expected["search_units" if schedule == "tariff_a" else "document_units"])
    a_all = all(row_matches(index, "tariff_a") for index in range(25))
    b_all = all(row_matches(index, "tariff_b") for index in range(25))
    bindings = table["operation_bindings"]
    components = {row["component"] for row in bindings}
    calculated_data = []
    for row in calculated:
        projected = {"documents": row["documents"]}
        for schedule in ("tariff_a", "tariff_b"):
            projected[schedule] = {
                key: format(value, "f") if isinstance(value, Decimal) else value
                for key, value in row[schedule].items()}
        calculated_data.append(projected)
    scenario = case["scenario_id"]
    if scenario == "t48_a":
        checks = {
            "t48_a.native_non_token_quantity": (
                components == {"search_units", "document_units", "query_units"} and
                all(row["tariff_a"]["search_units"] == (row["documents"] + 9)//10 and
                    row["tariff_b"]["document_units"] == row["documents"] for row in calculated),
                "Search/document/query units are operation-native, not token quantities"),
            "t48_a.price_contract": (
                len(bindings) == 4 and len({row["price_ref"] for row in bindings}) == 4 and
                a_all and b_all and
                Decimal(table["embedding_document"]["per_item_usd"]) == Decimal("0.000200000") and
                Decimal(table["embedding_query"]["per_item_usd"]) == Decimal("0.000200000"),
                "Four fixed fictional price bindings and all listed rows match independent Decimal arithmetic")}
    elif scenario == "t48_b":
        checks = {
            "t48_b.tariff_a_all_25_inputs": (a_all and
                [row["documents"] for row in table["rows"]] == list(range(1, 26)),
                "All 25 Tariff A input counts match independent ceiling/minimum/settlement arithmetic"),
            "t48_b.minimum": (all(row["tariff_a"]["raw_usd"] >= Decimal("0.005")
                                   for row in calculated) and
                               calculated[0]["tariff_a"]["raw_usd"] == Decimal("0.005"),
                "Per-attempt USD 0.005 minimum applies at low counts"),
            "t48_b.ceiling": (calculated[9]["tariff_a"]["search_units"] == 1 and
                              calculated[10]["tariff_a"]["search_units"] == 2 and
                              calculated[20]["tariff_a"]["search_units"] == 3,
                "Search-unit ceiling changes at 10/11 and 20/21 documents")}
    elif scenario == "t48_c":
        checks = {
            "t48_c.tariff_b_n10": (b_all and
                calculated[9]["tariff_b"]["raw_usd"] == Decimal("0.0030000050"),
                "Tariff B n=10 uses lower whole-request rate for all ten units"),
            "t48_c.tariff_b_n11": (calculated[10]["tariff_b"]["raw_usd"] ==
                                 Decimal("0.0044000055") and
                                 calculated[10]["tariff_b"]["settled_usd"] ==
                                 Decimal("0.004400006"),
                "Tariff B n=11 applies upper rate to all eleven units")}
    elif scenario == "t48_d":
        checks = {
            "t48_d.half_even_up_tie": (
                calculated[2]["tariff_b"]["raw_usd"] == Decimal("0.0009000015") and
                calculated[2]["tariff_b"]["settled_usd"] == Decimal("0.000900002"),
                "Half-even rounds the n=3 tie upward to even nano digit"),
            "t48_d.half_even_down_tie": (
                calculated[0]["tariff_b"]["raw_usd"] == Decimal("0.0003000005") and
                calculated[0]["tariff_b"]["settled_usd"] == Decimal("0.000300000"),
                "Half-even rounds the n=1 tie downward to even nano digit")}
    else:
        checks = {
            "t48_e.reservation_raw": (
                all(row[schedule]["request_bound_usd"] >= row[schedule]["raw_usd"]
                    for row in calculated for schedule in ("tariff_a", "tariff_b")),
                "Upward reservation covers each unrounded raw amount at all 25 counts"),
            "t48_e.reservation_settled": (
                all(row[schedule]["request_bound_usd"] >= row[schedule]["settled_usd"]
                    for row in calculated for schedule in ("tariff_a", "tariff_b")),
                "Upward reservation covers every independently half-even settled amount")}
    return _evidence(runtime, case,
        {"accounting": {"fictional_currency": "USD", "checked_rows": 25,
                        "four_price_bindings": len(bindings)}}, checks,
        {"tariffs_sha256": sha256((Path(__file__).resolve().parents[2] /
            "tests/fixtures/contracts/dev12-successor-01/tariffs.json").read_bytes()).hexdigest(),
         "independent_rows": calculated_data,
         "fixture_rows": table["rows"], "operation_bindings": bindings},
        case["attempt_group"])


def _retrieval_request(runtime, case, vector, suffix, selectors):
    """Make independently keyed, valid requests for controlled receiver modes."""
    from duranki_server.successor_contract import content_digest
    request = _case_request(runtime, case, vector)
    request["work_selector"]["step_id"] += "." + suffix
    if request["operation"]["type"] == "embedding.create":
        request["input"]["items"] = [
            {"item_id": selector, "text": ("Sky", "Earth 🌍", "River")[index % 3]}
            for index, selector in enumerate(selectors)]
    else:
        sample = request["input"]["candidates"][0]
        request["input"]["candidates"] = []
        for index, selector in enumerate(selectors):
            candidate = {**sample, "candidate_id": selector,
                         "text": ("Sky", "Earth 🌍", "River")[index % 3]}
            candidate["content_digest"] = content_digest(candidate)
            request["input"]["candidates"].append(candidate)
        request["input"]["top_k"] = min(2, len(selectors))
    return request


def retrieval_workflow(runtime, case):
    """Exercise the normal fixed retrieval sends and controlled invalid replies."""
    scenario = case["scenario_id"]
    if case["variant"] != "composed" or scenario not in {
            "t51", "t52", "t53", "t54", "t55"}:
        raise NotImplementedError("retrieval workflow variant not implemented")
    from duranki_server.successor_contract import result_valid

    observations = {}
    supplemental = {}
    before = _census(runtime)

    def call(label, vector, selectors, *, mutate=None):
        request = _retrieval_request(runtime, case, vector, label, selectors)
        if mutate is not None:
            mutate(request)
        earlier = _census(runtime)
        response = _post(runtime, request, _headers(runtime, vector))
        later = _census(runtime)
        status = response["status"] or {}
        aid = response["reply"].get("attempt_id")
        attempt = status.get("attempts", [{}])[0]
        record = {"request": request, "response": response,
                  "before": earlier, "after": later,
                  "attempt_id": aid,
                  "one_arrival": later["receiver_arrivals"] == earlier["receiver_arrivals"] + 1,
                  "valid_result": result_valid(attempt.get("result"), request, aid)
                    if aid and "result" in attempt else False}
        observations[label] = record
        return record

    if scenario == "t51":
        good = call("ordered", "DIRECT_DOCUMENT", ["doc.first", "doc.second", "doc.third"])
        short = call("short", "DIRECT_DOCUMENT", ["doc.result.short", "doc.second"])
        dimension = call("dimension", "DIRECT_DOCUMENT", ["doc.result.dimension"])
        nonfinite = call("nonfinite", "DIRECT_DOCUMENT", ["doc.result.nonfinite"])
        vector = good["response"]["status"].get("attempts", [{}])[0].get("result", {})
        checks = {
            "t51.ordered_batch": (good["valid_result"] and good["one_arrival"] and
                [row["item_id"] for row in vector.get("vectors", [])] ==
                    ["doc.first", "doc.second", "doc.third"],
                "Three ordered items yielded exact item/index mapping through one real guarded send"),
            "t51.wrong_count": (short["one_arrival"] and
                short["response"]["status"].get("submission_state") == "failed" and
                short["response"]["status"]["attempts"][0]["delivery_state"] == "invalid",
                "Receiver omitted one vector; result validation rejected delivered result"),
            "t51.wrong_dimension": (dimension["one_arrival"] and
                dimension["response"]["status"].get("submission_state") == "failed",
                "Receiver returned two-dimensional vector against fixed three-dimensional binding"),
            "t51.nonfinite_vector": (nonfinite["one_arrival"] and
                nonfinite["response"]["status"].get("submission_state") == "failed",
                "Receiver returned NaN vector component; result validation rejected it"),
            "t51.no_truncation": (good["valid_result"] and
                len(vector.get("vectors", [])) == len(good["request"]["input"]["items"]) == 3,
                "Successful batch preserved all three input items without truncation")}
    elif scenario == "t52":
        wrong_space = call("space", "DIRECT_DOCUMENT", ["doc.result.space"])
        wrong_index = call("index", "DIRECT_DOCUMENT", ["doc.index"],
            mutate=lambda request: request["input"]["profile"].update({"index_version": "index.wrong"}))
        good = call("compatible", "DIRECT_DOCUMENT", ["doc.compatible"])
        checks = {
            "t52.wrong_vector_space": (wrong_space["one_arrival"] and
                wrong_space["response"]["status"].get("submission_state") == "failed",
                "Delivered wrong vector-space profile rejected after guarded arrival"),
            "t52.wrong_index_profile": (
                wrong_index["response"]["http_status"] >= 400 and
                wrong_index["after"]["receiver_arrivals"] == wrong_index["before"]["receiver_arrivals"],
                "Wrong index version rejected before send"),
            "t52.compatible_positive": (good["valid_result"] and good["one_arrival"] and
                good["response"]["status"].get("submission_state") == "completed",
                "Correct profile/index pair produced valid delivery")}
    elif scenario == "t53":
        good = call("ordered", "DELEGATED_RERANK", ["doc.first", "doc.second", "doc.third"])
        duplicate = call("duplicate", "DELEGATED_RERANK", ["doc.result.duplicate", "doc.second"])
        beyond = call("range", "DELEGATED_RERANK", ["doc.result.out_of_range"])
        wrong_order = call("order", "DELEGATED_RERANK", ["doc.result.order", "doc.second"])
        checks = {
            "t53.valid_rerank": (good["one_arrival"] and good["valid_result"] and
                good["response"]["status"].get("submission_state") == "completed",
                "Ordered top-k rerank result passed exact rank/index/candidate binding"),
            "t53.malformed_duplicate": (duplicate["one_arrival"] and
                duplicate["response"]["status"].get("submission_state") == "failed",
                "Duplicate candidate in delivered ranking rejected"),
            "t53.out_of_range": (beyond["one_arrival"] and
                beyond["response"]["status"].get("submission_state") == "failed",
                "Out-of-range candidate index in delivered ranking rejected"),
            "t53.wrong_order": (wrong_order["one_arrival"] and
                wrong_order["response"]["status"].get("submission_state") == "failed",
                "Ascending score order in delivered ranking rejected")}
    elif scenario == "t54":
        failed = call("failed", "DELEGATED_RERANK", ["doc.failure.known"])
        unknown = call("unknown", "DELEGATED_RERANK", ["doc.unknown.recoverable"])
        unknown_sid = unknown["response"]["reply"].get("handle", {}).get("submission_id")
        if not unknown_sid:
            raise AssertionError("rerank unknown outcome lacks admitted submission")
        paused = _census(runtime)
        collected = runtime.successor.collect_receiver_receipt(
            unknown_sid, _trusted(runtime, "DELEGATED_RERANK"))
        resumed = runtime.successor.resume_campaign(
            unknown_sid, _trusted(runtime, "DELEGATED_RERANK"),
            "test controlled rerank unknown receipt")
        after_correction = _census(runtime)
        supplemental = {"paused": paused, "receipt_collection": collected,
                        "resume": resumed, "after_correction": after_correction}
        status = failed["response"]["status"]
        usage = status.get("attempts", [{}])[0].get("usage_revision", {})
        checks = {
            "t54.rerank_failure_unknown": (failed["one_arrival"] and
                status.get("submission_state") == "failed" and
                status.get("attempts", [{}])[0].get("delivery_state") == "invalid" and
                usage.get("cost_status") == "calculated" and
                unknown["one_arrival"] and
                unknown["response"]["status"].get("submission_state") == "unknown" and
                paused["campaign"]["paused"] and collected == "accepted" and
                resumed.get("decision") == "resumed",
                "Failed known-charge and unknown-outcome reranks retain separate delivery and financial states"),
            "t54.labelled_degradation": (status.get("attempts", [{}])[0].get("failure", {}).get("code") ==
                "RESULT_INVALID" and status.get("candidate_access") == "unavailable_due_failure",
                "Failure is visibly labelled and does not masquerade as a successful fallback"),
            "t54.no_hidden_second_call": (failed["after"]["receiver_arrivals"] ==
                failed["before"]["receiver_arrivals"] + 1 and
                failed["after"]["guard_ownership"] == failed["before"]["guard_ownership"] + 1 and
                after_correction["receiver_arrivals"] == paused["receiver_arrivals"] and
                after_correction["campaign"]["possible_send_count"] ==
                    paused["campaign"]["possible_send_count"],
                "Each rerank used one guarded send; historical correction sent nothing")}
    else:
        document = call("document", "DIRECT_DOCUMENT", ["doc.ingest"])
        query = call("query", "AUTONOMOUS_QUERY", ["doc.query"])
        rerank = call("rerank", "DELEGATED_RERANK", ["doc.rank"])
        completed = all(row["valid_result"] and
                        row["response"]["status"].get("submission_state") == "completed"
                        for row in (document, query, rerank))
        distinct_attempts = {row["attempt_id"] for row in (document, query, rerank)}
        checks = {
            "t55.ingest_once": (completed and document["one_arrival"] and
                document["request"]["input"]["role"] == "document",
                "Document ingestion creates one isolated guarded embedding attempt"),
            "t55.distinct_query_rerank": (completed and
                query["request"]["input"]["role"] == "query" and
                rerank["request"]["operation"]["type"] == "rerank" and
                len(distinct_attempts) == 3,
                "Query embedding and rerank are distinct operations and attempts"),
            "t55.unique_allocation": (completed and len(distinct_attempts) == 3 and
                all(row["one_arrival"] for row in (document, query, rerank)),
                "Each operation owns one unique attempt, reservation and receiver arrival")}

    after = _census(runtime)
    stages = {"admission": {"new_submissions": after["submissions"] - before["submissions"]},
              "receiver": {"new_arrivals": after["receiver_arrivals"] - before["receiver_arrivals"]},
              "delivery": {label: row["response"]["status"].get("submission_state", "absent")
                           if row["response"]["status"] else "rejected"
                           for label, row in observations.items()},
              "settlement": {label: row["response"]["status"].get("attempts", [{}])[0]
                             .get("settlement_state", "absent")
                             if row["response"]["status"] else "not_admitted"
                             for label, row in observations.items()}}
    return _evidence(runtime, case, stages, checks,
                     {"runs": observations, "supplemental": supplemental,
                      "before": before, "after": after},
                     next((row["attempt_id"] for row in observations.values()
                           if row["attempt_id"]), "none"))


def _offline_command(runtime, label, command, *, env=None):
    merged = os.environ.copy()
    merged.update(env or {})
    process = subprocess.run(command, cwd=Path(__file__).resolve().parents[2],
        env=merged, capture_output=True, text=True, timeout=90, check=False)
    return {"label": label, "command": command, "exit": process.returncode,
            "stdout": process.stdout[-5000:], "stderr": process.stderr[-5000:]}


def client_contract(runtime, case):
    """Run exact unpacked Python/CommonJS artifacts against no-network goldens."""
    scenario = case["scenario_id"]
    if case["variant"] != "composed" or scenario not in {
            "t47_a", "t47_b", "t47_c", "t47_d"}:
        raise NotImplementedError("client-contract branch not implemented")
    root = Path(__file__).resolve().parents[2]
    python = _offline_command(runtime, "installed-python-successor",
        [sys.executable, "-I", "-B", str(root /
            "tests/development_slice/test_dev12_sdk.py")],
        env={"DEV12_PY_CLIENT_TARGET": str(runtime.installed_python_root)})
    js = _offline_command(runtime, "installed-commonjs-successor",
        ["/dev12-node", str(root / "tests/development_slice/test_dev12_sdk.cjs")],
        env={"DEV12_JS_CLIENT_DIR": str(runtime.installed_js_root)})
    source_schemas = (root / "tests/fixtures/contracts/dev12-successor-01/schemas.json").read_bytes()
    py_schemas = (runtime.installed_python_root /
                  "duranki_client/dev12_schemas.json").read_bytes()
    js_schemas = (runtime.installed_js_root / "dev12_schemas.json").read_bytes()
    source_registry = (root / "tests/fixtures/contracts/dev12-successor-01/registrations.json").read_bytes()
    py_registry = (runtime.installed_python_root /
                   "duranki_client/dev12_registrations.json").read_bytes()
    js_registry = (runtime.installed_js_root / "dev12_registrations.json").read_bytes()
    exact_assets = (source_schemas == py_schemas == js_schemas and
                    source_registry == py_registry == js_registry)
    common = python["exit"] == 0 and js["exit"] == 0 and exact_assets
    runs = [python, js]
    live = {}
    if scenario == "t47_a":
        from duranki_client import DurankiClient
        import duranki_client
        installed_python = Path(duranki_client.__file__).resolve().is_relative_to(
            runtime.installed_python_root.resolve())
        py_request = _case_request(runtime, case, "DIRECT_DOCUMENT")
        py_request["work_selector"]["step_id"] += ".wheel"
        live_before = _census(runtime)
        with DurankiClient(runtime.base_url, runtime.credentials["DIRECT_DOCUMENT"],
                           timeout=12) as installed:
            py_reply = installed.submit_embedding(py_request, {"wait_ms": 5000})
            py_status = installed.get_successor_status({
                "submission_id": py_reply["handle"]["submission_id"]})
        js_request = _retrieval_request(runtime, case, "DELEGATED_RERANK",
                                        "tarball", ["doc.js"])
        js_input = runtime.root / "cases" / (case["id"] + "-js-private-input.json")
        js_input.parent.mkdir(exist_ok=True)
        private = {"package_path": str(runtime.installed_js_root),
                   "base_url": runtime.base_url,
                   "token": runtime.credentials["DELEGATED_RERANK"],
                   "action": "submit", "request": js_request}
        with js_input.open("xb") as stream:
            stream.write((json.dumps(private, sort_keys=True,
                                     ensure_ascii=True) + "\n").encode())
        js_input.chmod(0o600)
        js_live = _offline_command(runtime, "installed-commonjs-live-target",
            ["/dev12-node", str(Path(__file__).with_name(
                "dev12_completion_js_actor.cjs")), str(js_input)])
        runs.append(js_live)
        try:
            js_observed = json.loads(js_live["stdout"].strip().splitlines()[-1])
        except (IndexError, ValueError):
            js_observed = {}
        live_after = _census(runtime)
        live = {"installed_python_source": str(Path(duranki_client.__file__).resolve()),
                "python_reply": py_reply, "python_status": py_status,
                "commonjs_actor": js_live, "commonjs_observed": js_observed,
                "before": live_before, "after": live_after,
                "private_js_input_path": str(js_input)}
        py_live_ok = (installed_python and py_reply.get("state") == "completed" and
            py_status.get("submission_state") == "completed")
        js_live_ok = (js_live["exit"] == 0 and
            js_observed.get("reply", {}).get("state") == "completed" and
            js_observed.get("status", {}).get("submission_state") == "completed")
        two_live = (live_after["receiver_arrivals"] == live_before["receiver_arrivals"] + 2 and
            live_after["submissions"] == live_before["submissions"] + 2 and
            js_observed.get("reply", {}).get("attempt_id") != py_reply.get("attempt_id"))
        checks = {
            "t47_a.python_defaults": (python["exit"] == 0 and "OK" in python["stderr"] and
                py_live_ok,
                "Exact unpacked Python wheel passed fixtures and submitted/statused one live controlled attempt"),
            "t47_a.commonjs_defaults": (js["exit"] == 0 and
                '"status":"PASS"' in js["stdout"] and js_live_ok,
                "Exact unpacked CommonJS tarball passed fixtures and submitted/statused one live controlled attempt"),
            "t47_a.parity": (common and two_live,
                "Both installed artifacts used exact schema bytes and distinct guarded live target attempts")}
    elif scenario == "t47_b":
        py_a1 = _offline_command(runtime, "independent-a1-python",
            [sys.executable, "-I", "-B", str(root /
                "tests/fixtures/contracts/dev12-successor-01/conformance/check.py")])
        js_a1 = _offline_command(runtime, "a1-javascript-conformance",
            ["/dev12-node", str(root /
                "tests/fixtures/contracts/dev12-successor-01/conformance/check.cjs")])
        runs.extend((py_a1, js_a1))
        checks = {
            "t47_b.domain_goldens": (py_a1["exit"] == 0 and js_a1["exit"] == 0 and
                "offline cross-check PASS" in py_a1["stdout"],
                "Independent Python projection and JavaScript conformance pass adopted domain-separated goldens"),
            "t47_b.order_sensitive": (common and py_a1["exit"] == 0 and
                js_a1["exit"] == 0,
                "Strict client fixtures and A1 checker reject order-sensitive/canonical negatives")}
    elif scenario == "t47_c":
        legacy_js = _offline_command(runtime, "installed-commonjs-legacy",
            ["/dev12-node", str(root / "tests/development_slice/test_client.cjs")],
            env={"DURANKI_INSTALLED_CLIENT": "1",
                 "NODE_PATH": str(runtime.installed_js_root.parents[1])})
        legacy_py = _offline_command(runtime, "legacy-python-contract",
            [sys.executable, "-I", "-B", str(root /
                "tests/development_slice/test_core.py")])
        legacy_http = _offline_command(runtime, "caller-owned-tool-cycle",
            [sys.executable, "-I", "-B", str(root /
                "tests/development_slice/test_http.py")])
        runs.extend((legacy_js, legacy_py, legacy_http))
        checks = {
            "t47_c.legacy_parser": (legacy_js["exit"] == 0 and legacy_py["exit"] == 0,
                "Installed CommonJS legacy parser and server strict parser controls pass"),
            "t47_c.legacy_digest": (legacy_py["exit"] == 0,
                "Legacy canonical/digest golden tests pass without rewriting bytes"),
            "t47_c.caller_tool_cycle": (legacy_http["exit"] == 0 and
                "OK" in legacy_http["stderr"] and legacy_js["exit"] == 0,
                "Legacy HTTP tool-result source/forgery scenario and installed client controls pass")}
    else:
        fixture = runtime.root / "cases" / "case.t47_a.composed.json"
        if not fixture.is_file() or fixture.is_symlink():
            raise AssertionError("retained installed-client positive response absent")
        commands = (
            ("wheel", [sys.executable, "-I", "-B", str(root /
                "tests/gateway_integration/dev12_completion_sdk_probe.py"),
                str(runtime.installed_python_root), str(fixture)]),
            ("tarball", ["/dev12-node", str(root /
                "tests/gateway_integration/dev12_completion_sdk_probe.cjs"),
                str(runtime.installed_js_root), str(fixture)]),
        )
        probes = {}
        for label, command in commands:
            process = subprocess.run(command, cwd=root, capture_output=True,
                text=True, timeout=30, check=False)
            if process.returncode or len(process.stdout) > 250000:
                raise AssertionError(f"{label} exact installed-client probe failed")
            probes[label] = json.loads(process.stdout)
            runs.append({"label": f"installed-{label}-explicit-boundary",
                         "command": command, "exit": process.returncode,
                         "stdout_sha256": sha256(process.stdout.encode()).hexdigest(),
                         "stderr": process.stderr[-1000:]})

        def paired(name):
            return all({(row["case"], row["selector"]) for row in
                probes[label]["outcomes"]} ==
                {(kind, selector) for kind in
                 ("positive", "unknown_version", "unknown_field") for selector in
                 ("submission_id", "work_selector")} and
                all(row["passed"] and row["observed"] == row["expected"] and
                    sha256(row["exact_body_utf8"].encode()).hexdigest() == row["body_sha256"]
                    for row in probes[label]["outcomes"] if row["case"] in (name, "positive"))
                for label in ("wheel", "tarball"))

        checks = {
            "t47_d.unknown_version": (common and paired("unknown_version"),
                "Both exact installed artifacts rejected explicit unknown-version responses through status"),
            "t47_d.unknown_field": (common and paired("unknown_field"),
                "Both exact installed artifacts rejected an extra response field through status"),
            "t47_d.strict_compatibility": (exact_assets and common and
                paired("positive"),
                "Both artifacts accepted positive immutable selectors with exact bounded schema bytes")}
        live = {"explicit_offline_probes": probes}
    return _evidence(runtime, case,
        {"client": {"python_exit": python["exit"], "commonjs_exit": js["exit"],
                    "live_python_completed": live.get("python_status", {}).get("submission_state", "not_run"),
                    "live_commonjs_completed": live.get("commonjs_observed", {}).get("status", {}).get("submission_state", "not_run"),
                    "schema_sha256": sha256(source_schemas).hexdigest(),
                    "registrations_sha256": sha256(source_registry).hexdigest()}},
        checks, {"offline_runs": runs, "exact_installed_assets": exact_assets,
                 "live_target": live,
                 "wheel_root": str(runtime.installed_python_root),
                 "commonjs_root": str(runtime.installed_js_root)},
        live.get("python_reply", {}).get("attempt_id", case["attempt_group"]))


def _registration(name, run, supported):
    return CaseHandler(name=name, source_path=str(SOURCE),
        source_sha256=sha256(SOURCE.read_bytes()).hexdigest(),
        supported=frozenset(supported), run=run)


DEV12_CASE_HANDLERS = {
    "ingress_identity": _registration("ingress_identity", ingress_identity,
                                      {("t01", "composed"), ("t02", "composed"),
                                       ("t03", "composed"),
                                       ("t42", "composed")} |
                                      {(scenario, "composed") for scenario in
                                       ("t77_a", "t77_b", "t77_c", "t77_d",
                                        "t78_a", "t78_b", "t78_c", "t78_d",
                                        "t79_a", "t79_b", "t79_c", "t79_d")}),
    "recovery_chain": _registration("recovery_chain", recovery_chain,
        {("recovery_chain", variant) for variant in
         ("unknown_pause", "retained_receipt", "authorized_late_append",
          "denied_resume", "eligible_resume")}),
    "native_accounting": _registration("native_accounting", native_accounting,
        {(scenario, "composed") for scenario in
         ("t48_a", "t48_b", "t48_c", "t48_d", "t48_e", "t48_f",
          "t48_g", "t49_a", "t49_b", "t49_d", "t49_e", "t50_a", "t50_c",
          "t50_d", "t50_e")} |
        {("t49_c", "consistent_zero"), ("t49_c", "contradictory_zero")} |
        {("t50_b", "duplicate_submission"),
         ("t50_b", "competing_submission")}),
    "client_contract": _registration("client_contract", client_contract,
        {(scenario, "composed") for scenario in
         ("t47_a", "t47_b", "t47_c", "t47_d")}),
    "authority_recovery": _registration("authority_recovery", authority_recovery,
        {("t14_a", "composed")} |
        {("t24_b", variant) for variant in
         ("revocation_before_write", "write_before_revocation",
          "would_block", "partial_write")} |
        {("t24_c", "composed")} |
        {("t07_a", variant) for variant in
         ("eligible_current", "rotated_old_eligible", "revoked_key_after_wait",
          "revoked_plan_after_wait")} |
        {("t24_a", variant) for variant in
         ("queued_revocation", "eligible_control")} |
        {(scenario, "composed") for scenario in
         ("t45_a", "t45_b", "t45_c", "t45_d", "t45_e",
          "t46_a", "t46_b", "t46_c", "t46_d")}),
    "retrieval_workflow": _registration("retrieval_workflow", retrieval_workflow,
        {(scenario, "composed") for scenario in
         ("t51", "t52", "t53", "t54", "t55")}),
    **OPERATOR_CASE_HANDLERS,
}
