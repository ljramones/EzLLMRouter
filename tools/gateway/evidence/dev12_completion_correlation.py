"""dev12_completion_runner correlation domain; entry points remain on the facade."""

from __future__ import annotations


def _correlation_snapshot(self):
    """Independent durable IDs and effective amounts at a case boundary."""
    from tools.gateway.evidence import dev12_completion_runner as _api

    with self.store._lock:
        submissions = {
            aid: (sid, _api.json.loads(raw))
            for sid, aid, raw in (
                (row[0], _api.json.loads(row[1])["attempt_id"], row[1])
                for row in self.store.db.execute(
                    "SELECT submission_id,record FROM dev12_submissions"
                )
            )
        }
        guards = {
            aid: (sid, _api.json.loads(raw))
            for aid, sid, raw in self.store.db.execute(
                "SELECT attempt_id,submission_id,guard_receipt FROM dev12_send_ownership"
            )
        }
        usage_rows = [
            (aid, revision, sid, _api.json.loads(raw))
            for aid, revision, sid, raw in self.store.db.execute(
                "SELECT attempt_id,revision,submission_id,usage FROM dev12_usage_revisions"
            )
        ]
        campaign_attempts = {
            aid: {
                "state": state,
                "possible_send": bool(possible),
                "reservation_decimal": reserved,
            }
            for aid, state, possible, reserved in self.store.db.execute(
                "SELECT attempt_id,state,possible_send,reservation_decimal "
                "FROM dev12_campaign_attempts"
            )
        }
    receiver_rows = (
        [_api.json.loads(line) for line in self.receiver_log.read_text().splitlines()]
        if self.receiver_log.exists()
        else []
    )
    latest = {}
    for aid, revision, sid, row in usage_rows:
        if aid not in latest or revision > latest[aid][0]:
            latest[aid] = (revision, sid, row)
    known = sum(
        (
            _api.Decimal(row[2]["amount_decimal"])
            for row in latest.values()
            if row[2]["cost_status"] in {"calculated", "over_bound"}
        ),
        _api.Decimal(0),
    )
    return {
        "submissions": submissions,
        "guards": guards,
        "usage_rows": usage_rows,
        "latest_usage": latest,
        "campaign_attempts": campaign_attempts,
        "receiver_rows": receiver_rows,
        "effective_known_decimal": known,
    }


def _verify_case_correlation(self, case, before, after, allowance_before, allowance_after, result):
    """Check actual receiver/guard/usage lineage and case financial allocation."""
    from tools.gateway.evidence import dev12_completion_runner as _api
    from ezllmrouter_server.successor_contract import usage_valid

    new_attempts = set(after["submissions"]) - set(before["submissions"])
    new_guards = set(after["guards"]) - set(before["guards"])
    new_usage = {(aid, revision) for aid, revision, _sid, _row in after["usage_rows"]} - {
        (aid, revision) for aid, revision, _sid, _row in before["usage_rows"]
    }
    arrivals = after["receiver_rows"][len(before["receiver_rows"]) :]
    if (
        not new_guards.issubset(new_attempts)
        or len(arrivals) > case["max_possible_sends"]
        or len(new_attempts) > case["max_admissions"]
        or len(new_guards) > case["max_possible_sends"]
    ):
        raise AssertionError("case admission/guard/receiver ID set exceeds exact scope")
    for aid in new_attempts:
        sid, record = after["submissions"][aid]
        campaign = after["campaign_attempts"].get(aid)
        if (
            record["contract_version"] != "0.3"
            or record["campaign_id"] != self.allowance.campaign_id
            or record["trusted_identity"]["charging_owner_id"]
            != self.plan["envelope"]["financial_owner_id"]
            or record["reservation"]["budget_account_id"]
            != self.plan["envelope"]["budget_account_id"]
            or campaign is None
            or _api.Decimal(campaign["reservation_decimal"])
            != _api.Decimal(record["reservation"]["max_exposure_decimal"])
        ):
            raise AssertionError("new attempt differs from admitted campaign/owner/reservation")
    for aid in new_guards:
        sid, guard = after["guards"][aid]
        admitted_sid, record = after["submissions"][aid]
        if (
            sid != admitted_sid
            or guard["attempt_id"] != aid
            or guard["plan_id"] != record["signed_plan"]["plan_id"]
            or guard["work_digest"] != record["work_digest"]
            or not after["campaign_attempts"][aid]["possible_send"]
        ):
            raise AssertionError("guard does not bind admitted attempt and durable send allowance")
    arrival_ids = []
    for arrival in arrivals:
        aid = arrival["attempt_id"]
        arrival_ids.append(aid)
        if aid not in new_guards or aid not in after["submissions"]:
            raise AssertionError("receiver arrival has no same-case guarded attempt")
        _sid, record = after["submissions"][aid]
        _guard_sid, guard = after["guards"][aid]
        if (
            arrival["body_sha256"] != guard["body_sha256"]
            or arrival["body_bytes"] != guard["body_bytes"]
            or arrival["path"] != record["signed_plan"]["execution_descriptor"]["route"]
            or arrival["request_valid"] is not True
        ):
            raise AssertionError("receiver body/route differs from retained guard receipt")
    if len(arrival_ids) != len(set(arrival_ids)):
        raise AssertionError("duplicate receiver arrival for one case attempt")
    for aid, revision, sid, usage in after["usage_rows"]:
        if (aid, revision) not in new_usage:
            continue
        record_sid, record = after["submissions"].get(aid, (None, None))
        if (
            record is None
            or sid != record_sid
            or not usage_valid(
                usage,
                record["request"],
                aid,
                record["reservation"]["price_ref"],
                record["reservation"]["usage_ref"],
                record["reservation"]["max_exposure_decimal"],
            )
        ):
            raise AssertionError("new usage revision differs from original admitted scope")
    reserved_delta = _api.Decimal(allowance_after["cumulative_reserved_decimal"]) - _api.Decimal(
        allowance_before["cumulative_reserved_decimal"]
    )
    known_delta = after["effective_known_decimal"] - before["effective_known_decimal"]
    allocation = _api.Decimal(case["max_exposure_decimal"])
    if (
        reserved_delta < 0
        or reserved_delta > allocation
        or known_delta > allocation
        and case["phase"] not in {"late_evidence", "resume"}
    ):
        raise AssertionError("case reservation/effective cost exceeds planned allocation")
    claimed_primary = None
    if result["observations"]:
        path = self.root / result["observations"][0]["evidence_path"]
        retained = _api.json.loads(path.read_text())
        value = retained.get("actual_attempt_id")
        if value in new_attempts:
            claimed_primary = value
    if claimed_primary is None and len(new_attempts) == 1:
        claimed_primary = next(iter(new_attempts))
    primary_record = after["submissions"][claimed_primary][1] if claimed_primary else None
    terminal = primary_record["submission_state"] if primary_record else "completed"
    failure = primary_record.get("failure") if primary_record else None
    stage = primary_record.get("failure_stage") if primary_record else None
    mapped_stage = {"before_send": "first_write", "result_validation": "delivery"}.get(stage, stage)
    rejection = (
        {
            "stage": mapped_stage,
            "code": failure["code"],
            "http_status": (409 if stage == "before_send" else 502),
        }
        if failure
        else None
    )
    primary_stages = []
    if claimed_primary:
        primary_stages.append("admission")
        if primary_record.get("signed_plan"):
            primary_stages.extend(("signed_plan", "authority"))
        if claimed_primary in after["guards"]:
            primary_stages.extend(("guard", "first_write"))
        if claimed_primary in arrival_ids:
            primary_stages.append("receiver")
        if primary_record.get("submission_state") in {"completed", "unknown"} or stage not in {
            "before_send",
            None,
        }:
            primary_stages.append("delivery")
        # Financial history is separately validated even when delivery
        # validation failed; it is not evidence that execution progressed
        # beyond the rejected delivery boundary.
        if claimed_primary in after["latest_usage"] and not failure:
            primary_stages.append("settlement")
    return {
        "new_attempt_ids": sorted(new_attempts),
        "new_guard_attempt_ids": sorted(new_guards),
        "receiver_attempt_ids": arrival_ids,
        "new_usage_revisions": sorted([list(pair) for pair in new_usage]),
        "reserved_delta_decimal": str(reserved_delta),
        "effective_known_delta_decimal": str(known_delta),
        "primary_attempt_id": claimed_primary,
        "primary_stages": primary_stages,
        "reservation_delta_decimal": str(reserved_delta),
        "terminal_status": terminal,
        "rejection": rejection,
    }
