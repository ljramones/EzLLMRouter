"""dev12_completion_runner usage verification domain; entry points remain on the facade."""

from __future__ import annotations


def _verify_installed_client_attempts(self, case: dict, checkpoint: dict) -> tuple[dict, dict]:
    """Reduce two retained live installed-client attempts without replay."""
    from tools.gateway.evidence import dev12_completion_runner as _api
    from tools.gateway.evidence.dev12_completion_handlers import _evidence

    if (case["scenario_id"], case["variant"], case["id"]) != (
        "t47_a",
        "composed",
        checkpoint["failed_id"] + ".continuation3",
    ):
        raise RuntimeError("unregistered installed-client continuation case")
    original_ref = checkpoint["latest_failed_evidence"]
    if _api.snapshot(_api.Path(original_ref["path"])) != original_ref:
        raise RuntimeError("retained installed-client evidence changed")
    original = _api.json.loads(_api.Path(original_ref["path"]).read_bytes())
    live = original["payload"]["live_target"]
    py_reply, py_status = live["python_reply"], live["python_status"]
    js_reply = live["commonjs_observed"]["reply"]
    js_status = live["commonjs_observed"]["status"]
    pairs = (("python_wheel", py_reply, py_status), ("js_tarball", js_reply, js_status))
    before = self.allowance.inspect()
    correlated_before = self._correlation_snapshot()
    receiver_before = len(self.receiver_log.read_bytes().splitlines())
    per_client = []
    for kind, reply, status in pairs:
        aid, sid = reply["attempt_id"], reply["handle"]["submission_id"]
        stored_sid, record = correlated_before["submissions"].get(aid, (None, None))
        guard_sid, guard = correlated_before["guards"].get(aid, (None, None))
        usage = correlated_before["latest_usage"].get(aid)
        arrivals = [
            row for row in correlated_before["receiver_rows"] if row.get("attempt_id") == aid
        ]
        per_client.append(
            {
                "kind": kind,
                "attempt_id": aid,
                "submission_id": sid,
                "stored_submission_id": stored_sid,
                "guard_submission_id": guard_sid,
                "reply_state": reply["state"],
                "status_state": status["submission_state"],
                "stored_state": record.get("submission_state") if record else None,
                "work_key_matches": (
                    record.get("work_key") == reply["handle"]["work_key"] if record else False
                ),
                "guard_binds_plan": (
                    guard.get("plan_id") == record["signed_plan"]["plan_id"]
                    if guard and record
                    else False
                ),
                "receiver_arrivals": len(arrivals),
                "receiver_body_matches_guard": (
                    arrivals[0].get("body_sha256") == guard.get("body_sha256")
                    if len(arrivals) == 1 and guard
                    else False
                ),
                "usage_status": usage[2].get("cost_status") if usage else None,
                "usage_amount": usage[2].get("amount_decimal") if usage else None,
                "status_usage_matches": (
                    usage[2] == status["attempts"][0].get("usage_revision")
                    if usage and status.get("attempts")
                    else False
                ),
                "reply_attempt_matches_status": (
                    status.get("attempts", [{}])[0].get("attempt_id") == aid
                ),
                "reply_handle_matches_status": (reply["handle"] == status.get("handle")),
            }
        )
    after = self.allowance.inspect()
    correlated_after = self._correlation_snapshot()
    receiver_after = len(self.receiver_log.read_bytes().splitlines())
    unchanged = (
        before == after == checkpoint["last_campaign"]
        and correlated_before == correlated_after
        and receiver_before == receiver_after == 24
    )
    distinct = (
        len({row["attempt_id"] for row in per_client}) == 2
        and len({row["submission_id"] for row in per_client}) == 2
    )
    complete = all(
        row["stored_submission_id"] == row["submission_id"]
        and row["guard_submission_id"] == row["submission_id"]
        and row["reply_state"] == row["status_state"] == row["stored_state"] == "completed"
        and row["work_key_matches"]
        and row["guard_binds_plan"]
        and row["receiver_arrivals"] == 1
        and row["receiver_body_matches_guard"]
        and row["usage_status"] == "calculated"
        and row["status_usage_matches"]
        and row["reply_attempt_matches_status"]
        and row["reply_handle_matches_status"]
        for row in per_client
    )
    live_before, live_after = live["before"], live["after"]
    boundary = (
        live_after["campaign"] == before
        and live_after["campaign"]["attempt_count"] - live_before["campaign"]["attempt_count"] == 2
        and live_after["campaign"]["possible_send_count"]
        - live_before["campaign"]["possible_send_count"]
        == 2
        and live_after["receiver_arrivals"] - live_before["receiver_arrivals"] == 2
        and live_after["campaign"]["cumulative_reserved_decimal"] == "0.008000003"
    )
    package_identity = (
        original["payload"]["exact_installed_assets"] is True
        and live["commonjs_actor"]["exit"] == 0
        and _api.Path(original["payload"]["wheel_root"]) == self.installed_python_root
        and _api.Path(original["payload"]["commonjs_root"]) == self.installed_js_root
        and set(original["checks"]) == set(case["predicates"])
        and all(value["passed"] is True for value in original["checks"].values())
    )
    passed = unchanged and distinct and complete and boundary and package_identity
    checks = {
        name: (
            bool(passed),
            "Retained installed Python wheel and CommonJS tarball each completed one "
            "distinct guarded receiver attempt; status, usage, and campaign totals "
            "reconcile without resubmission",
        )
        for name in case["predicates"]
    }
    stages = {
        "client": {
            "python_attempt_id": per_client[0]["attempt_id"],
            "commonjs_attempt_id": per_client[1]["attempt_id"],
            "two_distinct_completed_attempts": distinct and complete,
            "receiver_arrivals": receiver_before,
        }
    }
    result = _evidence(
        self,
        case,
        stages,
        checks,
        {
            "continuation_of_case_id": checkpoint["latest_failed_id"],
            "original_failed_evidence": original_ref,
            "installed_client_attempts": per_client,
            "campaign_before": before,
            "campaign_after": after,
            "receiver_arrivals_before": receiver_before,
            "receiver_arrivals_after": receiver_after,
            "new_admissions": 0,
            "new_possible_sends": 0,
        },
        per_client[0]["attempt_id"],
    )
    actual = {
        "primary_attempt_id": per_client[0]["attempt_id"],
        "terminal_status": "completed",
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
        "receiver_attempt_ids": [],
        "new_attempt_ids": [],
        "new_guard_attempt_ids": [],
        "new_usage_revisions": [],
        "effective_known_delta_decimal": "0.000000000",
    }
    return result, actual


def _verify_native_revision_history(self, case: dict, checkpoint: dict) -> tuple[dict, dict]:
    """Reduce the three retained native-evidence attempts without a send."""
    from tools.gateway.evidence import dev12_completion_runner as _api
    from tools.gateway.evidence.dev12_completion_handlers import _evidence

    if (case["scenario_id"], case["variant"], case["id"]) != (
        "t49_d",
        "composed",
        checkpoint["failed_id"] + ".continuation4",
    ):
        raise RuntimeError("unregistered native-evidence continuation case")
    original_ref = checkpoint["latest_failed_evidence"]
    if _api.snapshot(_api.Path(original_ref["path"])) != original_ref:
        raise RuntimeError("retained native-evidence case changed")
    original = _api.json.loads(_api.Path(original_ref["path"]).read_bytes())
    observations = original["payload"]["observations"]
    before = self.allowance.inspect()
    correlated_before = self._correlation_snapshot()
    receiver_before = len(self.receiver_log.read_bytes().splitlines())
    reduced = []
    for item in observations:
        reply = item["reply"]["reply"]
        status_before, status_after = item["status_before"], item["status_after"]
        aid, sid = reply["attempt_id"], reply["handle"]["submission_id"]
        stored_sid, record = correlated_before["submissions"].get(aid, (None, None))
        guard_sid, guard = correlated_before["guards"].get(aid, (None, None))
        revisions = sorted(
            (revision, row)
            for row_aid, revision, row_sid, row in correlated_before["usage_rows"]
            if row_aid == aid and row_sid == sid
        )
        arrivals = [
            row for row in correlated_before["receiver_rows"] if row.get("attempt_id") == aid
        ]
        rev1 = status_before["attempts"][0]["usage_revision"]
        rev2 = status_after["attempts"][0]["usage_revision"]
        reduced.append(
            {
                "attempt_id": aid,
                "submission_id": sid,
                "stored_submission_id": stored_sid,
                "guard_submission_id": guard_sid,
                "record_state": record.get("submission_state") if record else None,
                "record_result_retained": bool(record and record.get("result")),
                "guard_binds_plan": (
                    guard.get("plan_id") == record["signed_plan"]["plan_id"]
                    if guard and record
                    else False
                ),
                "receiver_arrivals": len(arrivals),
                "receiver_body_matches_guard": (
                    arrivals[0].get("body_sha256") == guard.get("body_sha256")
                    if len(arrivals) == 1 and guard
                    else False
                ),
                "revision_numbers": [revision for revision, _ in revisions],
                "first_usage_matches_retained": (
                    revisions[0][1] == rev1 if len(revisions) == 2 else False
                ),
                "effective_usage_matches_retained": (
                    revisions[-1][1] == rev2 if len(revisions) == 2 else False
                ),
                "first_usage": rev1,
                "effective_usage": rev2,
                "first_delivery_valid": (
                    status_before["attempts"][0]["delivery_state"] == "valid"
                    and reply["state"] == "completed"
                ),
                "effective_delivery_valid": (
                    status_after["attempts"][0]["delivery_state"] == "valid"
                    and status_after["submission_state"] == "completed"
                ),
                "result_unchanged": (
                    reply.get("result")
                    == status_before["attempts"][0].get("result")
                    == status_after["attempts"][0].get("result")
                ),
                "receipt_collection": item.get("collection"),
                "audited_resume_decision": item.get("resume", {}).get("decision"),
            }
        )
    after = self.allowance.inspect()
    correlated_after = self._correlation_snapshot()
    receiver_after = len(self.receiver_log.read_bytes().splitlines())
    common = (
        len(reduced) == 3
        and len({row["attempt_id"] for row in reduced}) == 3
        and before == after == checkpoint["last_campaign"]
        and before["attempt_count"] == before["possible_send_count"] == 51
        and before["cumulative_reserved_decimal"] == "0.012200008"
        and before["paused"] is False
        and receiver_before == receiver_after == 40
        and correlated_before == correlated_after
        and all(
            row["stored_submission_id"] == row["guard_submission_id"] == row["submission_id"]
            and row["record_state"] == "completed"
            and row["record_result_retained"]
            and row["guard_binds_plan"]
            and row["receiver_arrivals"] == 1
            and row["receiver_body_matches_guard"]
            and row["revision_numbers"] == [1, 2]
            and row["first_usage_matches_retained"]
            and row["effective_usage_matches_retained"]
            and row["first_delivery_valid"]
            and row["effective_delivery_valid"]
            and row["result_unchanged"]
            and row["receipt_collection"] == "accepted"
            and row["audited_resume_decision"] == "resumed"
            and row["first_usage"]["cost_status"] == "unknown"
            and "amount_decimal" not in row["first_usage"]
            and row["effective_usage"]["cost_status"] == "calculated"
            and row["effective_usage"].get("previous_revision") == 1
            and row["effective_usage"]["amount_decimal"] == "0.000200000"
            for row in reduced
        )
    )
    invalid = (
        common
        and reduced[0]["first_usage"]["components"][0]["presence"] == "invalid"
        and "raw_digest" in reduced[0]["first_usage"]["components"][0]
    )
    out_domain = (
        common
        and reduced[1]["first_usage"]["components"][0]["presence"] == "known"
        and reduced[1]["first_usage"]["components"][0]["quantity"] == 999999999
        and reduced[1]["first_usage"]["components"][0]["evidence"] == "reported"
    )
    contradictory = (
        common
        and reduced[2]["first_usage"]["components"][0]["presence"] == "known"
        and reduced[2]["first_usage"]["components"][0]["quantity"] == 0
        and reduced[2]["first_usage"]["components"][0]["evidence"] == "reported"
    )
    checks = {
        "t49_d.invalid_counter": (
            bool(invalid),
            "Malformed Unicode usage remained unknown with a digest and no amount; "
            "the retained result stayed delivered and revision two calculated once",
        ),
        "t49_d.out_of_domain": (
            bool(out_domain),
            "Reported out-of-domain quantity 999999999 remained a known raw value "
            "with unknown cost and no amount until independent revision two",
        ),
        "t49_d.contradictory_counter": (
            bool(contradictory),
            "Contradictory reported zero remained explicit and unpriced until "
            "independent revision two; no new attempt or send occurred",
        ),
    }
    stages = dict(original["observed_stages"])
    stages["settlement"] = {
        **stages["settlement"],
        "retained_revision_pairs": [row["revision_numbers"] for row in reduced],
        "out_of_domain_quantity": 999999999,
    }
    result = _evidence(
        self,
        case,
        stages,
        checks,
        {
            "continuation_of_case_id": checkpoint["latest_failed_id"],
            "original_failed_evidence": original_ref,
            "native_evidence_attempts": reduced,
            "campaign_before": before,
            "campaign_after": after,
            "receiver_arrivals_before": receiver_before,
            "receiver_arrivals_after": receiver_after,
            "new_admissions": 0,
            "new_possible_sends": 0,
        },
        reduced[0]["attempt_id"],
    )
    actual = {
        "primary_attempt_id": reduced[0]["attempt_id"],
        "terminal_status": "completed",
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
        "receiver_attempt_ids": [],
        "new_attempt_ids": [],
        "new_guard_attempt_ids": [],
        "new_usage_revisions": [],
        "effective_known_delta_decimal": "0.000000000",
    }
    return result, actual
