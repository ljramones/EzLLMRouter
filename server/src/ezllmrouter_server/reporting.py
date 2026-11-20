"""Read-only, scope-first reporting over unique durable attempts and revisions."""

from __future__ import annotations

from .repositories import reporting as _queries
from .identifiers import valid_identifier

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN
import json
from statistics import median


KNOWN = frozenset({"reported", "calculated", "reconciled"})

REPORT_BUCKETS = {
    "agent_id": {"__direct_human__", "__unattributed__"},
    "initiating_user_id": {"__autonomous__", "__unknown__"},
    "charging_owner_id": {"__unknown__"},
}


def _utc(value):
    if value is None:
        return None
    if type(value) is not str or len(value) != 20 or not value.endswith("Z"):
        raise ValueError("invalid UTC filter")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValueError("invalid UTC filter") from exc
    return parsed.replace(tzinfo=timezone.utc)


def _money(value):
    rendered = format(value, "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _ratio(numerator, denominator, places="0.000000001"):
    return _money(
        (Decimal(numerator) / Decimal(denominator)).quantize(
            Decimal(places), rounding=ROUND_HALF_EVEN
        )
    )


def _matches(record, field, value):
    observed = record.get(field)
    return observed is not None and str(observed) == value


class Totals:
    def __init__(self):
        self.attempts = 0
        self.known_attempts = 0
        self.unknown_attempts = 0
        self.estimated_attempts = 0
        self.no_provider_charge_attempts = 0
        self.amounts = {}
        self.estimated_amounts = {}

    def add(self, item):
        self.attempts += 1
        status = item["cost_status"]
        if status in KNOWN:
            self.known_attempts += 1
            currency = item["currency"]
            self.amounts[currency] = self.amounts.get(currency, Decimal(0)) + Decimal(
                item["amount_decimal"]
            )
        elif status == "no_provider_charge":
            self.no_provider_charge_attempts += 1
        elif status == "estimated":
            self.estimated_attempts += 1
            if item.get("currency") and item.get("estimated_amount_decimal") is not None:
                currency = item["currency"]
                self.estimated_amounts[currency] = self.estimated_amounts.get(
                    currency, Decimal(0)
                ) + Decimal(item["estimated_amount_decimal"])
        else:
            self.unknown_attempts += 1

    def public(self):
        return {
            "attempts": self.attempts,
            "known_cost_attempts": self.known_attempts,
            "unknown_cost_attempts": self.unknown_attempts,
            "estimated_attempts": self.estimated_attempts,
            "no_provider_charge_attempts": self.no_provider_charge_attempts,
            "known_subtotals": {key: _money(value) for key, value in sorted(self.amounts.items())},
            "estimated_subtotals": {
                key: _money(value) for key, value in sorted(self.estimated_amounts.items())
            },
            "cost_coverage": f"{self.known_attempts + self.no_provider_charge_attempts}/{self.attempts}",
        }


def _group(items, field):
    result = {}
    for item in items:
        key = item.get(field) or "__unknown__"
        result.setdefault(key, Totals()).add(item)
    return [{"id": key, **total.public()} for key, total in sorted(result.items())]


def _descendants(items, runs):
    by_run = {}
    for item in items:
        if item["run_id"]:
            by_run.setdefault(item["run_id"], set()).add(item["attempt_id"])
    descendants = {run_id: set(ids) for run_id, ids in by_run.items()}
    for run_id, ids in by_run.items():
        parent = runs.get(run_id, {}).get("parent_run_id")
        seen = set()
        while parent and parent not in seen:
            seen.add(parent)
            descendants.setdefault(parent, set()).update(ids)
            parent = runs.get(parent, {}).get("parent_run_id")
    return descendants


def _latest_outcomes(db, cutoff):
    rows = db.execute(_queries.LATEST_OUTCOMES_SELECT_ATTRIBUTION_OUTCOMES, (cutoff,)).fetchall()
    latest = {}
    for raw, at in rows:
        event = json.loads(raw)
        if event["kind"] == "task_outcome":
            latest[event["run_id"]] = {
                "verdict": event["verdict"],
                "recorded_at": at,
                "evaluation_ref": event["evaluator_version"],
                "revision": event["subject_revision"],
            }
    return latest


def _visible(record, scope):
    if scope["role"] != "ordinary":
        return True
    principal = scope["principal_id"]
    return (
        record.get("principal_id") == principal
        or record.get("attribution", {}).get("initiating_user_id") == principal
    )


def usage_costs(registry, scope, filters=None, *, page=1, limit=50):
    """Apply visibility before any count, aggregate, table, or export."""
    filters = filters or {}
    allowed = {
        "from",
        "to",
        "cutoff",
        "currency",
        "environment",
        "provider",
        "connection_id",
        "model",
        "configuration_ref",
        "agent_id",
        "agent_version",
        "initiating_user_id",
        "charging_owner_id",
        "task_class",
        "purpose",
        "agent_search",
    }
    if (
        set(filters) - allowed
        or any(type(v) is not str or len(v) > 256 for v in filters.values())
        or any(
            not valid_identifier(filters[key]) and filters[key] not in REPORT_BUCKETS.get(key, ())
            for key in {
                "connection_id",
                "configuration_ref",
                "agent_id",
                "agent_version",
                "initiating_user_id",
                "charging_owner_id",
                "task_class",
                "purpose",
            }
            & filters.keys()
        )
        or type(page) is not int
        or not 1 <= page <= 10000
        or type(limit) is not int
        or not 1 <= limit <= 100
    ):
        raise ValueError("invalid report filters")
    start, end = _utc(filters.get("from")), _utc(filters.get("to"))
    if start and end and start >= end:
        raise ValueError("invalid report interval")
    cutoff = _utc(filters.get("cutoff")) or datetime.now(timezone.utc).replace(microsecond=0)
    cutoff_text = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    with registry.store.database.read():
        db = registry.store.database
        raw = db.execute(_queries.USAGE_COSTS_SELECT_SUBMISSIONS).fetchall()
        revisions = db.execute(
            _queries.USAGE_COSTS_SELECT_USAGE_REVISIONS, (cutoff_text,)
        ).fetchall()
        runs = {
            r["run_id"]: r
            for (value,) in db.execute(_queries.USAGE_COSTS_SELECT_ATTRIBUTION_RUNS).fetchall()
            for r in (json.loads(value),)
            if r["created_at"] <= cutoff_text
        }
        outcomes = _latest_outcomes(db, cutoff_text)
    latest = {attempt: json.loads(value) for attempt, value in revisions}
    connections = {c["connection_id"]: c for c in registry.list_connections()}
    all_items = []
    for record_raw, intent_raw in raw:
        record = json.loads(record_raw)
        if not _visible(record, scope):
            continue
        when = _utc(record.get("created_at")) if record.get("created_at") else None
        if when and when > cutoff:
            continue
        intent = json.loads(intent_raw) if intent_raw else {}
        dest = (
            intent.get("destination")
            or record.get("selected_destination")
            or record.get("fixture_destination")
            or {}
        )
        attribution = record.get("attribution") or {}
        run = runs.get(attribution.get("run_id"))
        connection_id = dest.get("connection_id")
        connection = connections.get(connection_id)
        service = dest.get("service")
        environment = record.get("provenance") or (
            "synthetic_legacy"
            if service == "litellm.dev04" or not service
            else "provider_provenance_unknown"
        )
        usage = latest.get(record["attempt_id"])
        cost = usage.get("cost", {}) if usage else {}
        cost_status = cost.get("status", "unknown")
        if cost_status not in (KNOWN | {"estimated"}):
            # No preparatory intent is a durable no-provider-send disposition.
            cost_status = (
                "no_provider_charge"
                if not intent and record.get("submission_state") == "failed_before_transmit"
                else "unknown"
            )
        direct_human = (
            attribution.get("mode") == "direct_human" or record.get("principal_kind") == "human"
        )
        agent = attribution.get("agent_id") or (
            "__direct_human__" if direct_human else "__unattributed__"
        )
        user = attribution.get("initiating_user_id") or (
            record.get("principal_id")
            if direct_human
            else "__autonomous__"
            if attribution.get("mode") in ("autonomous_agent", "nested_agent")
            else "__unknown__"
        )
        item = {
            "attempt_id": record["attempt_id"],
            "submission_id": record["submission_id"],
            "principal_id": record["principal_id"],
            "agent_id": agent,
            "agent_version": attribution.get("agent_version"),
            "run_id": attribution.get("run_id"),
            "parent_run_id": attribution.get("parent_run_id"),
            "root_run_id": attribution.get("root_run_id"),
            "initiating_user_id": user,
            "charging_owner_id": attribution.get("charging_owner_id")
            or record.get("charging_owner_id")
            or (record.get("registry_decision", {}).get("charging_owner_id") or "__unknown__"),
            "task_id": record.get("task_id"),
            "task_class": attribution.get("task_class") or record.get("task_class"),
            "purpose": record.get("purpose"),
            "configuration_ref": dest.get("configuration_ref"),
            "provider": connection["provider_id"] if connection else service or "__unknown__",
            "connection_id": connection_id,
            "model": record.get("provider_model_reported") or dest.get("model"),
            "environment": environment,
            "attempt_at": record.get("created_at"),
            "submission_state": record.get("submission_state"),
            "dispatch_state": record.get("dispatch_state"),
            "cost_status": cost_status,
            "currency": cost.get("currency") if cost.get("currency") else None,
            "amount_decimal": cost.get("amount_decimal") if cost_status in KNOWN else None,
            "estimated_amount_decimal": cost.get("amount_decimal")
            if cost_status == "estimated"
            else None,
            "price_version": usage.get("price_version") if usage else None,
            "usage_revision": usage.get("revision") if usage else None,
            "input_tokens": (
                usage.get("normalized_usage", {}).get("input_uncached", {}).get("count")
                if usage
                else None
            ),
            "output_tokens": (
                usage.get("normalized_usage", {}).get("output_text", {}).get("count")
                if usage
                else None
            ),
        }
        all_items.append(item)
    items = [
        item
        for item in all_items
        if not (
            (start or end)
            and (
                item["attempt_at"] is None
                or (start and _utc(item["attempt_at"]) < start)
                or (end and _utc(item["attempt_at"]) >= end)
            )
        )
        and not any(
            not _matches(item, key, value)
            for key, value in filters.items()
            if key not in ("from", "to", "cutoff", "currency", "agent_search")
        )
        and (not filters.get("currency") or item["currency"] == filters["currency"])
    ]
    grand = Totals()
    for item in items:
        grand.add(item)
    by_attempt = {item["attempt_id"]: item for item in items}
    descendants = _descendants(items, runs)
    cohort_by_attempt = {item["attempt_id"]: item for item in all_items}
    cohort_descendants = _descendants(all_items, runs)
    agent_rows = []
    for agent in registry.attribution.agents():
        aid = agent["agent_id"]
        if filters.get("agent_id") and filters["agent_id"] != aid:
            continue
        if (
            filters.get("agent_search")
            and filters["agent_search"].casefold()
            not in (aid + " " + agent["display_name"]).casefold()
        ):
            continue
        owned_runs = [
            run_id
            for run_id, run in runs.items()
            if run["agent_id"] == aid
            and (
                scope["role"] != "ordinary"
                or run["principal_id"] == scope["principal_id"]
                or run["initiating_user_id"] == scope["principal_id"]
            )
        ]
        if (
            scope["role"] == "ordinary"
            and not owned_runs
            and agent["owner"] != scope["principal_id"]
        ):
            continue
        direct_ids = {item["attempt_id"] for item in items if item["agent_id"] == aid}
        inclusive_ids = (
            set().union(*(descendants.get(run_id, set()) for run_id in owned_runs))
            if owned_runs
            else set()
        )
        direct, inclusive = Totals(), Totals()
        for attempt in direct_ids:
            direct.add(by_attempt[attempt])
        for attempt in inclusive_ids:
            if attempt in by_attempt:
                inclusive.add(by_attempt[attempt])
        agent_rows.append(
            {
                "agent_id": aid,
                "display_name": agent["display_name"],
                "versions": agent["versions"],
                "owner": agent["owner"],
                "status": agent["status"],
                "revision": agent["revision"],
                "instrumentation_ref": agent.get("instrumentation_ref"),
                "instrumentation": "instrumented"
                if owned_runs or agent.get("instrumentation_status") == "instrumented"
                else "not_instrumented",
                "activity": "recorded" if direct_ids else "no_activity_recorded",
                "runs": len(owned_runs),
                "direct": direct.public(),
                "inclusive_workflow": inclusive.public(),
                "delegated": _totals_for_ids(inclusive_ids - direct_ids, by_attempt),
                "outcome_coverage": {
                    "reported": sum(run_id in outcomes for run_id in owned_runs),
                    "runs": len(owned_runs),
                },
            }
        )
    workflows = []
    for run_id, run in sorted(runs.items()):
        if (
            scope["role"] == "ordinary"
            and run["principal_id"] != scope["principal_id"]
            and run["initiating_user_id"] != scope["principal_id"]
        ):
            continue
        direct_ids = {item["attempt_id"] for item in items if item["run_id"] == run_id}
        inclusive_ids = descendants.get(run_id, set())
        workflows.append(
            {
                "run_id": run_id,
                "root_run_id": run["root_run_id"],
                "parent_run_id": run["parent_run_id"],
                "task_id": run["task_id"],
                "task_class": run["task_class"],
                "evaluation_ref": run["evaluation_ref"],
                "agent_id": run["agent_id"],
                "agent_version": run["agent_version"],
                "initiating_user_id": run["initiating_user_id"],
                "charging_owner_id": run["charging_owner_id"],
                "status": run["status"],
                "started_at": run["created_at"],
                "terminal_at": run.get("terminal_at"),
                "outcome": outcomes.get(run_id),
                "direct": _totals_for_ids(direct_ids, by_attempt),
                "delegated": _totals_for_ids(inclusive_ids - direct_ids, by_attempt),
                "inclusive_workflow": _totals_for_ids(inclusive_ids, by_attempt),
            }
        )
    roots = [
        run
        for run in runs.values()
        if run["parent_run_id"] is None
        and (
            scope["role"] != "ordinary"
            or run["principal_id"] == scope["principal_id"]
            or run["initiating_user_id"] == scope["principal_id"]
        )
    ]
    cohorts = {}
    cohort_root_ids = set()
    run_filters = (
        "agent_id",
        "agent_version",
        "initiating_user_id",
        "charging_owner_id",
        "task_class",
    )
    attempt_filters = (
        "currency",
        "environment",
        "provider",
        "connection_id",
        "configuration_ref",
        "model",
        "purpose",
    )
    for run in roots:
        started = _utc(run["created_at"])
        if (start and started < start) or (end and started >= end) or started > cutoff:
            continue
        if any(
            not _matches(run, field, filters[field]) for field in run_filters if filters.get(field)
        ):
            continue
        if any(filters.get(field) for field in attempt_filters) and not any(
            item["root_run_id"] == run["run_id"]
            and all(
                _matches(item, field, filters[field])
                for field in attempt_filters
                if filters.get(field)
            )
            for item in all_items
        ):
            continue
        cohort_root_ids.add(run["run_id"])
        key = (
            run["task_class"],
            run["evaluation_ref"],
            run["agent_id"] or "__direct_human__",
            run["agent_version"] or "__none__",
        )
        member = cohorts.setdefault(
            key,
            {
                "runs": [],
                "ids": set(),
                "accepted": 0,
                "rejected": 0,
                "abandoned": 0,
                "unreported": 0,
            },
        )
        member["runs"].append(run["run_id"])
        member["ids"].update(cohort_descendants.get(run["run_id"], set()))
        verdict = outcomes.get(run["run_id"], {}).get("verdict")
        member[verdict if verdict in ("accepted", "rejected", "abandoned") else "unreported"] += 1
    cohort_rows = []
    workflows = [run for run in workflows if run["root_run_id"] in cohort_root_ids]
    for key, member in sorted(cohorts.items()):
        totals = _totals_for_ids(member["ids"], cohort_by_attempt)
        amounts = totals["known_subtotals"]
        accepted_durations = []
        for run_id in member["runs"]:
            run = runs[run_id]
            if outcomes.get(run_id, {}).get("verdict") == "accepted" and run.get("terminal_at"):
                seconds = (_utc(run["terminal_at"]) - _utc(run["created_at"])).total_seconds()
                if seconds >= 0:
                    accepted_durations.append(int(seconds))
        member_attempts = [
            cohort_by_attempt[aid] for aid in member["ids"] if aid in cohort_by_attempt
        ]
        token_complete = bool(member_attempts) and all(
            type(row["input_tokens"]) is int and type(row["output_tokens"]) is int
            for row in member_attempts
        )
        performance = {
            "acceptance_rate_percent": _ratio(
                member["accepted"] * 100, len(member["runs"]), "0.01"
            ),
            "calls_per_accepted_task": (
                _ratio(len(member["ids"]), member["accepted"]) if member["accepted"] else None
            ),
            "tokens_per_accepted_task": (
                {
                    "input": _ratio(
                        sum(row["input_tokens"] for row in member_attempts), member["accepted"]
                    ),
                    "output": _ratio(
                        sum(row["output_tokens"] for row in member_attempts), member["accepted"]
                    ),
                }
                if member["accepted"] and token_complete
                else None
            ),
            "token_coverage_attempts": sum(
                type(row["input_tokens"]) is int and type(row["output_tokens"]) is int
                for row in member_attempts
            ),
            "latency_accepted_samples": len(accepted_durations),
            "median_seconds_to_accepted": median(accepted_durations)
            if accepted_durations
            else None,
            "p95_seconds_to_accepted": (
                sorted(accepted_durations)[int((len(accepted_durations) - 1) * 0.95)]
                if len(accepted_durations) >= 20
                else None
            ),
            "retry_rate": "not_measured",
            "escalation_rate": "not_measured",
            "human_intervention_rate": "not_measured",
        }
        if member["accepted"] == 0:
            efficiency = {"state": "no_accepted_tasks", "cost_per_accepted_task": None}
        elif (
            member["unreported"]
            or totals["unknown_cost_attempts"]
            or totals["estimated_attempts"]
            or len(amounts) != 1
        ):
            efficiency = {"state": "incomplete", "cost_per_accepted_task": None}
        else:
            currency, amount = next(iter(amounts.items()))
            efficiency = {
                "state": "complete",
                "currency": currency,
                "cost_per_accepted_task": _ratio(amount, member["accepted"]),
            }
        cohort_rows.append(
            {
                "task_class": key[0],
                "evaluation_ref": key[1],
                "agent_id": key[2],
                "agent_version": key[3],
                "total_tasks": len(member["runs"]),
                "accepted": member["accepted"],
                "rejected": member["rejected"],
                "abandoned": member["abandoned"],
                "unreported": member["unreported"],
                "attempt_cost": totals,
                "efficiency": efficiency,
                "performance": performance,
                "sample_note": "Low sample · descriptive only"
                if len(member["runs"]) < 10
                else "Descriptive comparison",
            }
        )
    groupings = {
        field: _group(items, field)
        for field in (
            "provider",
            "connection_id",
            "configuration_ref",
            "model",
            "agent_id",
            "initiating_user_id",
            "charging_owner_id",
            "task_id",
            "root_run_id",
            "environment",
        )
    }
    trend_items = [
        {**item, "day": item["attempt_at"][:10] if item["attempt_at"] else "__unknown_time__"}
        for item in items
    ]
    agent_rows.sort(key=lambda row: (row["display_name"].casefold(), row["agent_id"]))
    all_agents = len(agent_rows)
    attribution_coverage = {
        "registered_agent_attempts": sum(
            item["agent_id"] not in ("__unattributed__", "__direct_human__") for item in items
        ),
        "direct_human_attempts": sum(item["agent_id"] == "__direct_human__" for item in items),
        "unknown_agent_attempts": sum(item["agent_id"] == "__unattributed__" for item in items),
    }
    return {
        "scope": "Recorded through EzLLMRouter",
        "cutoff": cutoff_text,
        "period": {"from": filters.get("from"), "to": filters.get("to"), "timezone": "UTC"},
        "filters": filters,
        "total": grand.public(),
        "groupings": groupings,
        "trend": _group(trend_items, "day"),
        "agents": {
            "page": page,
            "limit": limit,
            "total": all_agents,
            "items": agent_rows[(page - 1) * limit : page * limit],
        },
        "cohorts": cohort_rows,
        "cohort_filter_basis": "task_start; full descendant attempt cost through cutoff",
        "workflows": workflows,
        "attempts": items,
        "attribution_coverage": attribution_coverage,
        "outcome_coverage": {
            "reported_root_runs": sum(run_id in outcomes for run_id in cohort_root_ids),
            "visible_root_runs": len(cohort_root_ids),
        },
    }


def _totals_for_ids(ids, by_attempt):
    totals = Totals()
    for attempt in ids:
        if attempt in by_attempt:
            totals.add(by_attempt[attempt])
    return totals.public()
