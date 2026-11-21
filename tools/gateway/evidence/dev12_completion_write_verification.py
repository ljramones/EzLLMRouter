"""dev12_completion_runner write verification domain; entry points remain on the facade."""

from __future__ import annotations


def _repair_partial_write(self, case: dict, checkpoint: dict) -> tuple[dict, dict]:
    """Re-evaluate the retained failed attempt after a scoped product fix.

    This is a late, no-send continuation of the original partial-write
    attempt.  It never calls submit, invokes the transport, or allocates a
    second WorkKey. The original FAIL and its evidence remain immutable.
    """
    from tools.gateway.evidence import dev12_completion_runner as _api
    from tools.gateway.evidence.dev12_completion_handlers import _evidence, _trusted

    if (case["scenario_id"], case["variant"], case["id"]) != (
        "t24_b",
        "partial_write",
        checkpoint["failed_id"] + ".continuation1",
    ):
        raise RuntimeError("unregistered continuation repair case")
    original_path = _api.Path(checkpoint["failed_evidence"]["path"])
    if _api.snapshot(original_path) != checkpoint["failed_evidence"]:
        raise RuntimeError("original failed case evidence changed")
    original = _api.json.loads(original_path.read_bytes())
    aid = checkpoint["failed_attempt_id"]
    old = original["payload"]
    admitted = old["record"]
    sid = admitted["submission_id"]
    if (
        original["actual_attempt_id"] != aid
        or admitted["attempt_id"] != aid
        or old["late"]["collection"] != "accepted"
        or old["reply"]["status"]["submission_state"] != "unknown"
    ):
        raise RuntimeError("original partial-write attempt lineage differs")
    retained = self.store.successor_get(sid)
    before = self.allowance.inspect()
    census_before = self._correlation_snapshot()
    receiver_before = len(self.receiver_log.read_bytes().splitlines())
    if (
        retained["attempt_id"] != aid
        or retained["signed_plan"]["plan_id"] != admitted["signed_plan"]["plan_id"]
        or aid not in census_before["guards"]
        or sum(row.get("attempt_id") == aid for row in census_before["receiver_rows"]) != 1
        or aid not in census_before["latest_usage"]
        or census_before["latest_usage"][aid][2]["cost_status"] != "calculated"
    ):
        raise RuntimeError("retained guard, receiver and usage lineage incomplete")
    status = self.successor.status(sid, _trusted(self))
    resume = self.successor.resume_campaign(
        sid,
        _trusted(self),
        "continuation: original partial TLS write receipt and usage verified; no replay",
    )
    after = self.allowance.inspect()
    census_after = self._correlation_snapshot()
    receiver_after = len(self.receiver_log.read_bytes().splitlines())
    no_send = (
        before["start_at"] == after["start_at"] == checkpoint["original_start_at"]
        and before["expires_at"] == after["expires_at"] == checkpoint["original_expires_at"]
        and before["attempt_count"] == after["attempt_count"]
        and before["possible_send_count"] == after["possible_send_count"]
        and before["cumulative_reserved_decimal"] == after["cumulative_reserved_decimal"]
        and receiver_before == receiver_after
        and census_before["submissions"] == census_after["submissions"]
        and census_before["guards"] == census_after["guards"]
        and census_before["usage_rows"] == census_after["usage_rows"]
    )
    # The immutable original case document retained the actual transport
    # observations and the refused resume audit. The new audit is distinct.
    passed = (
        no_send
        and before["paused"]
        and not after["paused"]
        and resume.get("decision") == "resumed"
        and status.get("submission_state") == "unknown"
        and status.get("attempts", [{}])[0].get("usage_revision", {}).get("cost_status")
        == "calculated"
        and old["late"]["resume"]["decision"] == "refused"
        and original["checks"]["t24_b.partial_write"]["passed"] is False
        and original["observed_stages"]["first_write"]["receiver_delta"] == 1
    )
    stages = dict(original["observed_stages"])
    stages["authority"] = {
        **stages["authority"],
        "continuation_resume_decision": resume.get("decision"),
        "original_refused_decision": old["late"]["resume"]["decision"],
    }
    result = _evidence(
        self,
        case,
        stages,
        {
            "t24_b.partial_write": (
                bool(passed),
                "Original guarded partial write and one receiver arrival retained; "
                "corrected campaign resume used the same late usage and made no new send",
            )
        },
        {
            "continuation_of_case_id": checkpoint["failed_id"],
            "continuation_of_attempt_id": aid,
            "original_failed_evidence": checkpoint["failed_evidence"],
            "original_failed_resume_audit": old["late"]["resume"],
            "retained_record": retained,
            "status": status,
            "new_resume_audit": resume,
            "campaign_before": before,
            "campaign_after": after,
            "receiver_arrivals_before": receiver_before,
            "receiver_arrivals_after": receiver_after,
            "new_admissions": 0,
            "new_possible_sends": 0,
        },
        aid,
    )
    actual = {
        "primary_attempt_id": aid,
        "terminal_status": "unknown",
        "rejection": None,
        "primary_stages": [
            "admission",
            "signed_plan",
            "authority",
            "guard",
            "first_write",
            "receiver",
            "delivery",
            "settlement",
        ],
        "reservation_delta_decimal": "0.000000000",
        "continuation_of_case_id": checkpoint["failed_id"],
        "continuation_of_attempt_id": aid,
        "receiver_attempt_ids": [],
        "new_attempt_ids": [],
        "new_guard_attempt_ids": [],
        "new_usage_revisions": [],
        "effective_known_delta_decimal": "0.000000000",
    }
    return result, actual


def _verify_resumed_partial_write(self, case: dict, checkpoint: dict) -> tuple[dict, dict]:
    """Read-only second continuation of the same guarded first write."""
    from tools.gateway.evidence import dev12_completion_runner as _api
    from tools.gateway.evidence.dev12_completion_handlers import _evidence

    if (case["scenario_id"], case["variant"], case["id"]) != (
        "t24_b",
        "partial_write",
        checkpoint["failed_id"] + ".continuation2",
    ):
        raise RuntimeError("unregistered second continuation case")
    original_ref = checkpoint["failed_evidence"]
    cont1_ref = checkpoint["latest_failed_evidence"]
    for ref in (original_ref, cont1_ref):
        if _api.snapshot(_api.Path(ref["path"])) != ref:
            raise RuntimeError("retained continuation evidence changed")
    original = _api.json.loads(_api.Path(original_ref["path"]).read_bytes())
    cont1 = _api.json.loads(_api.Path(cont1_ref["path"]).read_bytes())
    aid = checkpoint["failed_attempt_id"]
    sid = original["payload"]["record"]["submission_id"]
    audit = cont1["payload"]["new_resume_audit"]
    blockers = {
        item.removeprefix("unresolved_exposure:")
        for item in original["payload"]["late"]["resume"]["blockers"]
        if item.startswith("unresolved_exposure:")
    }
    before = self.allowance.inspect()
    correlated = self._correlation_snapshot()
    receiver_before = len(self.receiver_log.read_bytes().splitlines())
    retained = self.store.successor_get(sid)
    with self.store._lock:
        audits = [
            _api.json.loads(row[0])
            for row in self.store.db.execute(
                "SELECT record FROM dev12_campaign_audit WHERE campaign_id=?",
                (self.allowance.campaign_id,),
            )
        ]
    matching_audits = [row for row in audits if row == audit]
    reconciled = {
        item
        for item in blockers
        if item in correlated["submissions"]
        and correlated["submissions"][item][1].get("exposure_state") == "not_sent"
        and correlated["submissions"][item][1].get("dispatch_state") == "blocked"
        and correlated["submissions"][item][1].get("failure_stage") == "before_send"
        and correlated["submissions"][item][1].get("failure", {}).get("code") == "FDC_REJECTED"
    }
    usage = correlated["latest_usage"].get(aid)
    fault = original["observed_stages"]["first_write"].get("fault", {})
    original_arrivals = [row for row in correlated["receiver_rows"] if row.get("attempt_id") == aid]
    after = self.allowance.inspect()
    receiver_after = len(self.receiver_log.read_bytes().splitlines())
    passed = (
        len(blockers) == 3
        and reconciled == blockers
        and set(audit.get("definite_no_send_reconciled", [])) == blockers
        and len(matching_audits) == 1
        and audit.get("decision") == "resumed"
        and before == after == checkpoint["last_campaign"]
        and before["paused"] is False
        and before["attempt_count"] == before["possible_send_count"] == 11
        and before["cumulative_reserved_decimal"] == "0.002900002"
        and receiver_before == receiver_after == 8
        and len(original_arrivals) == 1
        and aid in correlated["guards"]
        and retained["attempt_id"] == aid
        and retained["submission_state"] == "unknown"
        and usage is not None
        and usage[2]["cost_status"] == "calculated"
        and usage[2]["amount_decimal"] == "0.000200000"
        and fault.get("fired") is True
        and "SYNTHETIC_PARTIAL_TLS_RECORD_AFTER_FIRST_BYTE" in fault.get("observations", [])
        and "RESPONSE_DROPPED_AFTER_FRAGMENTED_REQUEST" in fault.get("observations", [])
    )
    stages = dict(original["observed_stages"])
    stages["authority"] = {
        **stages["authority"],
        "retained_resume_audit_decision": audit.get("decision"),
        "definite_no_send_reconciled": sorted(reconciled),
    }
    result = _evidence(
        self,
        case,
        stages,
        {
            "t24_b.partial_write": (
                bool(passed),
                "Original first-write attempt retained one receiver arrival and calculated "
                "usage; audited resume reconciled three definite no-send rows without "
                "another admission, send, or charge",
            )
        },
        {
            "continuation_of_case_id": checkpoint["latest_failed_id"],
            "continuation_of_attempt_id": aid,
            "original_failed_evidence": original_ref,
            "first_continuation_evidence": cont1_ref,
            "durable_resume_audit": audit,
            "durable_audit_matches": len(matching_audits),
            "definite_no_send_attempts": sorted(reconciled),
            "retained_record": retained,
            "effective_usage": usage[2] if usage else None,
            "campaign_before": before,
            "campaign_after": after,
            "receiver_arrivals_before": receiver_before,
            "receiver_arrivals_after": receiver_after,
            "new_admissions": 0,
            "new_possible_sends": 0,
        },
        aid,
    )
    actual = {
        "primary_attempt_id": aid,
        "terminal_status": "unknown",
        "rejection": None,
        "primary_stages": [
            "admission",
            "signed_plan",
            "authority",
            "guard",
            "first_write",
            "receiver",
            "delivery",
            "settlement",
        ],
        "reservation_delta_decimal": "0.000000000",
        "continuation_of_case_id": checkpoint["latest_failed_id"],
        "continuation_of_attempt_id": aid,
        "receiver_attempt_ids": [],
        "new_attempt_ids": [],
        "new_guard_attempt_ids": [],
        "new_usage_revisions": [],
        "effective_known_delta_decimal": "0.000000000",
    }
    return result, actual
