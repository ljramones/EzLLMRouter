"""dev12_completion_runner identity verification domain; entry points remain on the facade."""

from __future__ import annotations


def _verify_operator_identity_continuation(self, case: dict, checkpoint: dict) -> tuple[dict, dict]:
    """Finish authenticated T60 reads and preadmission negatives, no positives."""
    from copy import deepcopy
    from tools.gateway.evidence.dev12_completion_handlers import _case_request, _headers, _post
    from tools.gateway.evidence.dev12_completion_operator_handlers import (
        _census,
        _operator_client,
        _read,
        _retained,
    )
    from ezllmrouter_server.successor_contract import classify_request

    if (case["scenario_id"], case["variant"], case["id"]) != (
        "t60",
        "composed",
        checkpoint["failed_id"] + ".continuation5",
    ):
        raise RuntimeError("unregistered operator-identity continuation case")
    before = _census(self)
    before_campaign = self.allowance.inspect()
    correlated_before, expected, positives = _retained_positive_identities(checkpoint, self)
    delegated = _case_request(self, case, "DELEGATED_RERANK")
    forged_agent = deepcopy(delegated)
    forged_agent["work_selector"]["step_id"] += ".forged.agent"
    forged_agent["metadata"]["run_id"] = "run.forged.agent"
    forged_owner = deepcopy(delegated)
    forged_owner["work_selector"]["step_id"] += ".forged.owner"
    forged_owner["charging_owner_id"] = "team.forged"
    forged_delegation = deepcopy(delegated)
    forged_delegation["work_selector"]["step_id"] += ".forged.delegation"
    forged_delegation["metadata"]["delegation"][-1]["to_actor_id"] = "agent.forged"
    cyclic = deepcopy(delegated)
    cyclic["work_selector"]["step_id"] += ".cycle"
    cyclic["metadata"]["delegation"][-1]["to_actor_id"] = "user.demo"
    context = self.contexts_by_credential[self.credentials["DELEGATED_RERANK"]]
    negatives_requests = (forged_agent, forged_owner, forged_delegation, cyclic)
    classifications = [classify_request(value, context) for value in negatives_requests]
    if classifications != [
        "SEMANTIC_INVALID",
        "SCHEMA_INVALID",
        "SEMANTIC_INVALID",
        "SEMANTIC_INVALID",
    ]:
        raise RuntimeError("T60 negative preflight became eligible")
    negatives = [
        _post(self, value, _headers(self, "DELEGATED_RERANK")) for value in negatives_requests
    ]
    with _operator_client(self) as client:
        report_result = _read(client)
    rows = report_result.get("report", {}).get("attempts", [])
    selected = {row.get("attempt_id"): row for row in rows if row.get("attempt_id") in expected}
    after = _census(self)
    after_campaign = self.allowance.inspect()
    correlated_after = self._correlation_snapshot()
    no_send = (
        before == after
        and before_campaign == after_campaign == checkpoint["last_campaign"]
        and correlated_before == correlated_after
        and before_campaign["attempt_count"] == before_campaign["possible_send_count"] == 76
        and before_campaign["cumulative_reserved_decimal"] == "0.020400018"
        and len(correlated_before["receiver_rows"]) == 65
    )
    report_ok = (
        report_result.get("status") == 200
        and len(selected) == 3
        and all(
            selected[aid].get("actor_id") == positives[principal]["actor_id"]
            for principal, aid in zip(("user.demo", "svc.vega", "svc.orion"), expected, strict=True)
        )
    )
    direct = selected.get(expected[0], {})
    delegated_row = selected.get(expected[1], {})
    autonomous = selected.get(expected[2], {})
    checks = {
        "t60.direct_human": (
            bool(
                no_send
                and report_ok
                and direct.get("actor_id") == "user.demo"
                and direct.get("initiating_user_id") == "user.demo"
            ),
            "Retained direct human attempt appears under its own actor and initiator",
        ),
        "t60.delegated_agent": (
            bool(
                no_send
                and report_ok
                and delegated_row.get("actor_id") == "agent.vega"
                and delegated_row.get("initiating_user_id") == "user.demo"
                and delegated_row.get("parent_run_id") == "run.bud"
            ),
            "Retained delegated agent has the human initiator and immediate parent run",
        ),
        "t60.autonomous": (
            bool(
                no_send
                and report_ok
                and autonomous.get("actor_id") == "svc.orion"
                and autonomous.get("initiating_user_id") is None
            ),
            "Retained autonomous actor has no fabricated initiating human",
        ),
        "t60.forged_agent": (
            bool(
                no_send
                and classifications[0] == "SEMANTIC_INVALID"
                and negatives[0]["http_status"] >= 400
            ),
            "Forged agent run was rejected without admission or receiver work",
        ),
        "t60.forged_owner": (
            bool(
                no_send
                and classifications[1] == "SCHEMA_INVALID"
                and negatives[1]["http_status"] >= 400
            ),
            "Caller-supplied owner was rejected before admission",
        ),
        "t60.forged_delegation": (
            bool(
                no_send
                and classifications[2] == "SEMANTIC_INVALID"
                and negatives[2]["http_status"] >= 400
            ),
            "Forged final delegation endpoint was rejected before admission",
        ),
        "t60.cycle": (
            bool(
                no_send
                and classifications[3] == "SEMANTIC_INVALID"
                and negatives[3]["http_status"] >= 400
            ),
            "Cyclic delegation was rejected without another receiver arrival",
        ),
    }
    stages = {
        "operator": {
            "report_attempts": len(rows),
            "selected_attempts": list(expected),
            "negative_http": [value["http_status"] for value in negatives],
        }
    }
    result = _retained(
        self,
        case,
        stages,
        checks,
        {
            "continuation_of_case_id": checkpoint["latest_failed_id"],
            "retained_positive_attempts": positives,
            "selected_operator_rows": [direct, delegated_row, autonomous],
            "negative_classifications": classifications,
            "negative_http": [value["http_status"] for value in negatives],
            "campaign_before": before_campaign,
            "campaign_after": after_campaign,
            "receiver_arrivals_before": len(correlated_before["receiver_rows"]),
            "receiver_arrivals_after": len(correlated_after["receiver_rows"]),
            "new_admissions": 0,
            "new_possible_sends": 0,
        },
    )
    actual = {
        "primary_attempt_id": None,
        "terminal_status": "completed",
        "rejection": None,
        "primary_stages": [],
        "reservation_delta_decimal": "0.000000000",
        "receiver_attempt_ids": [],
        "new_attempt_ids": [],
        "new_guard_attempt_ids": [],
        "new_usage_revisions": [],
        "effective_known_delta_decimal": "0.000000000",
    }
    return result, actual


def _retained_positive_identities(checkpoint, self):
    correlated_before = self._correlation_snapshot()
    expected = checkpoint["retained_t60_positive_attempt_ids"]
    positives = {}
    for principal, aid in zip(("user.demo", "svc.vega", "svc.orion"), expected, strict=True):
        sid, record = correlated_before["submissions"].get(aid, (None, None))
        guard_sid, guard = correlated_before["guards"].get(aid, (None, None))
        usage = correlated_before["latest_usage"].get(aid)
        arrivals = [
            row for row in correlated_before["receiver_rows"] if row.get("attempt_id") == aid
        ]
        if (
            record is None
            or record["work_key"]["principal_id"] != principal
            or record["work_key"]["step_id"] != "step.completion02.t60.composed"
            or record["campaign_id"] != self.allowance.campaign_id
            or record["submission_state"] != "completed"
            or record["delivery_state"] != "valid"
            or guard_sid != sid
            or guard.get("plan_id") != record["signed_plan"]["plan_id"]
            or len(arrivals) != 1
            or arrivals[0]["body_sha256"] != guard["body_sha256"]
            or usage is None
            or usage[2]["cost_status"] != "calculated"
        ):
            raise RuntimeError("retained T60 positive attempt lineage differs")
        positives[principal] = {
            "attempt_id": aid,
            "submission_id": sid,
            "actor_id": record["trusted_identity"]["actor_id"],
            "initiating_user_id": record["request"]["metadata"].get("initiating_user_id"),
            "delegation": record["request"]["metadata"].get("delegation", []),
            "cost_status": usage[2]["cost_status"],
            "receiver_arrivals": len(arrivals),
        }
    return correlated_before, expected, positives
