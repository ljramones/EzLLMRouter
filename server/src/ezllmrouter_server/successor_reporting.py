"""Authorized read-only reporting over distinct wire-0.3 synthetic attempts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

from .formatting import money, utc_timestamp
from .repositories import successor_reporting as _queries
from .successor_contract import valid_utc_second

SYNTHETIC_ENVIRONMENT = "standalone-synthetic"


def _money(amount):
    return money(amount.quantize(Decimal("0.000000001")))


def _aggregate(rows):
    known = Decimal(0)
    held = Decimal(0)
    held_count = 0
    calculated = unknown = not_sent = over_bound = 0
    for item in rows:
        if item["exposure_state"] == "outstanding":
            held_count += 1
            held += Decimal(item["reservation_decimal"])
        if item["cost_status"] in ("calculated", "over_bound"):
            known += Decimal(item["amount_decimal"])
            calculated += 1
            over_bound += item["cost_status"] == "over_bound"
        elif item["cost_status"] == "not_sent":
            not_sent += 1
        else:
            unknown += 1
    return {
        "attempts": len(rows),
        "known_attempts": calculated,
        "unknown_cost_attempts": unknown,
        "not_sent_attempts": not_sent,
        "over_bound_attempts": over_bound,
        "known_usd": _money(known),
        "current_held_reservations": held_count,
        "current_held_bound_usd": _money(held),
    }


def usage_report(store, scope, filters=None):
    """Scope first, then select the latest accepted revision at a UTC cutoff.

    Inclusive workflow and alternate groupings are views of the same rows; their
    subtotals must never be added together. There is no provider invoice claim.
    """
    filters = filters or {}
    permitted = {
        "from",
        "to",
        "cutoff",
        "operation",
        "actor_id",
        "provider_ref",
        "initiating_user_id",
        "charging_owner_id",
        "root_workflow_id",
        "configuration_ref",
        "task_id",
        "environment",
    }
    if (
        set(filters) - permitted
        or any(type(value) is not str or len(value) > 160 for value in filters.values())
        or any(
            not valid_utc_second(filters[key]) for key in ("from", "to", "cutoff") if key in filters
        )
        or ("from" in filters and "to" in filters and filters["from"] >= filters["to"])
    ):
        raise ValueError("invalid successor report filter")
    if (
        scope.get("role") not in ("ordinary", "registry_admin", "read_only_operator")
        or type(scope.get("principal_id")) is not str
    ):
        raise PermissionError("authenticated reporting scope required")
    operational_as_of = utc_timestamp(datetime.now(timezone.utc))
    with store.database.read():
        records = [
            json.loads(row[0])
            for row in store.database.execute(
                _queries.USAGE_REPORT_SELECT_DEV12_SUBMISSIONS
            ).fetchall()
        ]
        usage_events = [
            (sid, json.loads(raw), observed_at)
            for sid, raw, observed_at in store.database.execute(
                _queries.USAGE_REPORT_SELECT_DEV12_EVIDENCE_EVENTS
            ).fetchall()
        ]
    by_submission = {}
    for sid, usage, observed_at in usage_events:
        if "cutoff" not in filters or observed_at <= filters["cutoff"]:
            current = by_submission.get(sid)
            if current is None or usage["revision"] > current["revision"]:
                by_submission[sid] = usage
    rows = []
    run_parents = {}
    for record in records:
        meta = record["request"]["metadata"]
        identity = record["trusted_identity"]
        if scope["role"] == "ordinary" and not (
            record["work_key"]["principal_id"] == scope["principal_id"]
            or meta.get("initiating_user_id") == scope["principal_id"]
        ):
            continue
        if (
            "from" in filters
            and record["created_at"] < filters["from"]
            or "to" in filters
            and record["created_at"] >= filters["to"]
            or "cutoff" in filters
            and record["created_at"] > filters["cutoff"]
        ):
            continue
        dimensions = {
            "operation": record["request"]["operation"]["type"],
            "task_id": record["work_key"]["task_id"],
            "environment": SYNTHETIC_ENVIRONMENT,
            "actor_id": identity["actor_id"],
            "initiating_user_id": meta.get("initiating_user_id"),
            "charging_owner_id": identity["charging_owner_id"],
            "root_workflow_id": meta["root_workflow_id"],
            "provider_ref": record["signed_plan"]["destination_ref"],
            "configuration_ref": record["request"]["requested_configuration_ref"],
        }
        if any(dimensions[key] != value for key, value in filters.items() if key in dimensions):
            continue
        lineage_scope = (
            meta.get("initiating_user_id") or record["work_key"]["principal_id"],
            record["work_key"]["task_id"],
            meta["root_workflow_id"],
        )
        for link in meta["delegation"]:
            run_parents[(*lineage_scope, link["to_run_id"])] = link["from_run_id"]
        if meta.get("parent_run_id"):
            run_parents[(*lineage_scope, meta["run_id"])] = meta["parent_run_id"]
        usage = by_submission.get(record["submission_id"])
        status = (
            usage["cost_status"]
            if usage
            else "not_sent"
            if record["dispatch_state"] == "blocked"
            else "unknown"
        )
        item = {
            "submission_id": record["submission_id"],
            "attempt_id": record["attempt_id"],
            "created_at": record["created_at"],
            "principal_id": record["work_key"]["principal_id"],
            "task_id": record["work_key"]["task_id"],
            "run_id": meta["run_id"],
            "parent_run_id": meta.get("parent_run_id"),
            "operation": dimensions["operation"],
            "input_role": record["request"]["input"].get("role", "rerank"),
            "handling_profile": record["request"]["handling_profile"],
            "price_ref": record["reservation"]["price_ref"],
            "usage_ref": record["reservation"]["usage_ref"],
            "reservation_decimal": record["reservation"]["max_exposure_decimal"],
            "submission_state": record["submission_state"],
            "dispatch_state": record["dispatch_state"],
            "delivery_state": record["delivery_state"],
            "candidate_access": record["candidate_access"],
            "exposure_state": record["exposure_state"],
            "exposure_state_as_of": operational_as_of,
            "cost_status": status,
            "currency": "USD",
            "usage_revision": usage["revision"] if usage else None,
            "native_components": usage["components"] if usage else [],
            "amount_decimal": usage.get("amount_decimal") if usage else None,
            **dimensions,
        }
        rows.append(item)
    groupings = {}
    for key in (
        "operation",
        "actor_id",
        "initiating_user_id",
        "charging_owner_id",
        "provider_ref",
        "task_id",
        "environment",
        "root_workflow_id",
        "configuration_ref",
    ):
        grouped = {}
        for row in rows:
            grouped.setdefault(row[key] or "__absent__", []).append(row)
        groupings[key] = [
            {"id": name, **_aggregate(group)} for name, group in sorted(grouped.items())
        ]
    direct = {}
    inclusive = {}
    for row in rows:
        run = row["run_id"]
        lineage_scope = (
            row["initiating_user_id"] or row["principal_id"],
            row["task_id"],
            row["root_workflow_id"],
        )
        direct.setdefault((*lineage_scope, run), []).append(row)
        visited = set()
        while run and run not in visited:
            visited.add(run)
            inclusive.setdefault((*lineage_scope, run), {})[row["attempt_id"]] = row
            run = run_parents.get((*lineage_scope, run))
    workflows = [
        {
            "initiating_or_autonomous_principal_id": key[0],
            "task_id": key[1],
            "root_workflow_id": key[2],
            "run_id": key[3],
            "parent_run_id": run_parents.get(key),
            "direct": _aggregate(direct.get(key, [])),
            "total_including_delegated": _aggregate(list(members.values())),
        }
        for key, members in sorted(inclusive.items())
    ]
    return {
        "profile": "retrieval-synthetic@1",
        "contract_version": "0.3",
        "scope": scope,
        "filters": filters,
        "total": _aggregate(rows),
        "usage_cutoff": filters.get("cutoff"),
        "operational_as_of": operational_as_of,
        "operational_state_basis": "current; independent of historical usage cutoff",
        "groupings": groupings,
        "workflows": workflows,
        "attempts": rows,
        "notice": "Controlled synthetic operations and fictional USD. No commercial provider cost or infrastructure allocation measured.",
    }
