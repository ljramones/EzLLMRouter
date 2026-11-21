"""Stream bounded attempt projections into report-sized accounting aggregates."""

from __future__ import annotations

from collections.abc import Generator, Mapping
from contextlib import closing
from datetime import datetime
from decimal import Decimal
import json
from typing import TYPE_CHECKING, cast

from .database import Database
from .records import Record
from .repositories import reporting as queries
from . import reporting as api
from . import reporting_metrics as metrics

if TYPE_CHECKING:
    from .registry import Registry

GROUP_FIELDS = (
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
ATTEMPT_FILTERS = (
    "currency",
    "environment",
    "provider",
    "connection_id",
    "configuration_ref",
    "model",
    "purpose",
)


class Measure(api.Totals):
    """Exact monetary counters and complete-token coverage, without attempt IDs."""

    def __init__(self) -> None:
        super().__init__()
        self.known_tokens = self.input_tokens = self.output_tokens = 0

    def add(self, item: Record) -> None:
        super().add(item)
        if type(item["input_tokens"]) is int and type(item["output_tokens"]) is int:
            self.known_tokens += 1
            self.input_tokens += item["input_tokens"]
            self.output_tokens += item["output_tokens"]

    def merge(self, other: Measure) -> None:
        self.attempts += other.attempts
        self.known_attempts += other.known_attempts
        self.unknown_attempts += other.unknown_attempts
        self.estimated_attempts += other.estimated_attempts
        self.no_provider_charge_attempts += other.no_provider_charge_attempts
        self.known_tokens += other.known_tokens
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        for target, source in (
            (self.amounts, other.amounts),
            (self.estimated_amounts, other.estimated_amounts),
        ):
            for currency, amount in source.items():
                target[currency] = target.get(currency, Decimal(0)) + amount


def visible_run(run: Record, scope: dict[str, str]) -> bool:
    return scope["role"] != "ordinary" or scope["principal_id"] in (
        run["principal_id"],
        run["initiating_user_id"],
    )


def selected(
    item: Record, filters: dict[str, str], start: datetime | None, end: datetime | None
) -> bool:
    if (start or end) and (
        item["attempt_at"] is None
        or (start and cast(datetime, api._utc(item["attempt_at"])) < start)
        or (end and cast(datetime, api._utc(item["attempt_at"])) >= end)
    ):
        return False
    return not any(
        not api._matches(item, key, value)
        for key, value in filters.items()
        if key not in ("from", "to", "cutoff", "currency", "agent_search")
    ) and (not filters.get("currency") or item["currency"] == filters["currency"])


def ancestors(run_id: str, runs: dict[str, Record]) -> set[str]:
    result = {run_id}
    parent = runs.get(run_id, {}).get("parent_run_id")
    seen: set[str] = set()
    while parent and parent not in seen:
        seen.add(parent)
        result.add(parent)
        parent = runs.get(parent, {}).get("parent_run_id")
    return result


class Accumulator:
    def __init__(
        self,
        runs: dict[str, Record],
        scope: dict[str, str],
        filters: dict[str, str],
        start: datetime | None,
        end: datetime | None,
        offset: int,
        limit: int,
    ) -> None:
        self.runs, self.scope, self.filters = runs, scope, filters
        self.start, self.end, self.offset, self.limit = start, end, offset, limit
        self.total = api.Totals()
        self.groups: dict[str, dict[str, api.Totals]] = {key: {} for key in (*GROUP_FIELDS, "day")}
        self.all_inclusive: dict[str, Measure] = {}
        self.direct_runs: dict[str, Measure] = {}
        self.inclusive_runs: dict[str, Measure] = {}
        self.delegated_runs: dict[str, Measure] = {}
        self.direct_agents: dict[str, Measure] = {}
        self.inclusive_agents: dict[str, Measure] = {}
        self.delegated_agents: dict[str, Measure] = {}
        self.matched_roots: set[str] = set()
        self.lineages: dict[str, set[str]] = {}
        self.page: list[Record] = []
        self.coverage = {
            "registered_agent_attempts": 0,
            "direct_human_attempts": 0,
            "unknown_agent_attempts": 0,
        }

    def add(self, item: Record) -> None:
        run_id = item["run_id"]
        lineage = (
            self.lineages.setdefault(run_id, ancestors(run_id, self.runs)) if run_id else set()
        )
        for ancestor in lineage:
            self.all_inclusive.setdefault(ancestor, Measure()).add(item)
        if all(
            api._matches(item, field, self.filters[field])
            for field in ATTEMPT_FILTERS
            if self.filters.get(field)
        ):
            if item["root_run_id"] in self.runs:
                self.matched_roots.add(item["root_run_id"])
        if not selected(item, self.filters, self.start, self.end):
            return
        index = self.total.attempts
        self.total.add(item)
        if self.offset <= index < self.offset + self.limit:
            self.page.append(item)
        for field in GROUP_FIELDS:
            self.groups[field].setdefault(item.get(field) or "__unknown__", api.Totals()).add(item)
        day = item["attempt_at"][:10] if item["attempt_at"] else "__unknown_time__"
        self.groups["day"].setdefault(day, api.Totals()).add(item)
        field = (
            "direct_human_attempts"
            if item["agent_id"] == "__direct_human__"
            else "unknown_agent_attempts"
            if item["agent_id"] == "__unattributed__"
            else "registered_agent_attempts"
        )
        self.coverage[field] += 1
        self.direct_agents.setdefault(item["agent_id"], Measure()).add(item)
        if run_id in self.runs:
            self.direct_runs.setdefault(run_id, Measure()).add(item)
        for ancestor in lineage:
            self.inclusive_runs.setdefault(ancestor, Measure()).add(item)
            if ancestor != run_id:
                self.delegated_runs.setdefault(ancestor, Measure()).add(item)
        agent_ids = {
            self.runs[ancestor]["agent_id"]
            for ancestor in lineage
            if ancestor in self.runs and visible_run(self.runs[ancestor], self.scope)
        }
        for agent_id in agent_ids:
            if agent_id is None:
                continue
            self.inclusive_agents.setdefault(agent_id, Measure()).add(item)
            if agent_id != item["agent_id"]:
                self.delegated_agents.setdefault(agent_id, Measure()).add(item)

    def grouped(self, field: str) -> list[Record]:
        return [{"id": key, **total.public()} for key, total in sorted(self.groups[field].items())]


def _metadata(db: Database, cutoff: str) -> tuple[dict[str, Record], dict[str, Record]]:
    run_rows = db.execute(queries.USAGE_COSTS_SELECT_ATTRIBUTION_RUNS).fetchall()
    outcome_rows = db.execute(
        queries.LATEST_OUTCOMES_SELECT_ATTRIBUTION_OUTCOMES, (cutoff,)
    ).fetchall()
    runs = {
        run["run_id"]: run
        for (raw,) in run_rows
        for run in (json.loads(cast(str, raw)),)
        if run["created_at"] <= cutoff
    }
    outcomes: dict[str, Record] = {}
    for raw, at in outcome_rows:
        event = json.loads(cast(str, raw))
        if event["kind"] == "task_outcome":
            outcomes[event["run_id"]] = {
                "verdict": event["verdict"],
                "recorded_at": at,
                "evaluation_ref": event["evaluator_version"],
                "revision": event["subject_revision"],
            }
    return runs, outcomes


def _facts(
    db: Database,
    cutoff: datetime,
    cutoff_text: str,
    scope: dict[str, str],
    connections: Mapping[str, Mapping[str, object]],
) -> Generator[Record, None, None]:
    parameters = (
        cutoff_text,
        cutoff_text,
        scope["role"],
        scope["principal_id"],
        scope["principal_id"],
    )
    with db.stream(queries.USAGE_FACTS, parameters) as rows:
        for attempt_id, record, intent, usage in rows:
            latest: dict[object, Record] = (
                {cast(str, attempt_id): json.loads(cast(str, usage))} if usage else {}
            )
            yield from api._visible_attempts(connections, cutoff, latest, [(record, intent)], scope)


def _agents(registry: Registry, state: Accumulator, outcomes: dict[str, Record]) -> list[Record]:
    rows = api._agent_summary(
        {}, {}, state.filters, [], outcomes, registry, state.runs, state.scope
    )
    for row in rows:
        aid = row["agent_id"]
        direct = state.direct_agents.get(aid, Measure())
        row.update(
            direct=direct.public(),
            inclusive_workflow=state.inclusive_agents.get(aid, Measure()).public(),
            delegated=state.delegated_agents.get(aid, Measure()).public(),
            activity="recorded" if direct.attempts else "no_activity_recorded",
        )
    rows.sort(key=lambda row: (row["display_name"].casefold(), row["agent_id"]))
    return rows


def _cohorts(
    state: Accumulator, cutoff: datetime, outcomes: dict[str, Record]
) -> tuple[list[Record], set[str]]:
    filters = {key: value for key, value in state.filters.items() if key not in ATTEMPT_FILTERS}
    runs = state.runs
    if any(state.filters.get(key) for key in ATTEMPT_FILTERS):
        runs = {key: run for key, run in runs.items() if key in state.matched_roots}
    cohorts, root_ids = api._cohort_members(
        [], {}, cutoff, state.end, filters, outcomes, runs, state.scope, state.start
    )
    rows = []
    for key, member in sorted(cohorts.items()):
        measure = Measure()
        for run_id in member["runs"]:
            measure.merge(state.all_inclusive.get(run_id, Measure()))
        totals = measure.public()
        performance = metrics.performance(
            metrics.durations(member, outcomes, state.runs),
            member,
            measure.attempts,
            bool(measure.attempts) and measure.known_tokens == measure.attempts,
            measure.known_tokens,
            measure.input_tokens,
            measure.output_tokens,
        )
        rows.append(
            metrics.cohort_row(key, member, totals, performance, metrics.efficiency(member, totals))
        )
    return rows, root_ids


def _workflows(state: Accumulator, outcomes: dict[str, Record], root_ids: set[str]) -> list[Record]:
    rows = api._workflow_summary({}, {}, [], outcomes, state.runs, state.scope)
    for row in rows:
        rid = row["run_id"]
        row.update(
            direct=state.direct_runs.get(rid, Measure()).public(),
            inclusive_workflow=state.inclusive_runs.get(rid, Measure()).public(),
            delegated=state.delegated_runs.get(rid, Measure()).public(),
        )
    return [row for row in rows if row["root_run_id"] in root_ids]


def build_report(
    registry: Registry,
    scope: dict[str, str],
    filters: dict[str, str] | None = None,
    *,
    page: int = 1,
    limit: int = 50,
    attempt_page: int = 1,
    attempt_limit: int = 100,
) -> Record:
    filters = filters or {}
    api._report_window(filters, attempt_limit, attempt_page)
    start, end, cutoff, cutoff_text = api._report_window(filters, limit, page)
    connections = {c["connection_id"]: c for c in registry.list_connections()}
    with registry.store.database.snapshot() as db:
        runs, outcomes = _metadata(db, cutoff_text)
        state = Accumulator(
            runs, scope, filters, start, end, (attempt_page - 1) * attempt_limit, attempt_limit
        )
        with closing(_facts(db, cutoff, cutoff_text, scope, connections)) as facts:
            for item in facts:
                state.add(item)
    agents = _agents(registry, state, outcomes)
    cohorts, root_ids = _cohorts(state, cutoff, outcomes)
    return {
        "scope": "Recorded through EzLLMRouter",
        "cutoff": cutoff_text,
        "period": {"from": filters.get("from"), "to": filters.get("to"), "timezone": "UTC"},
        "filters": filters,
        "total": state.total.public(),
        "groupings": {field: state.grouped(field) for field in GROUP_FIELDS},
        "trend": state.grouped("day"),
        "agents": {
            "page": page,
            "limit": limit,
            "total": len(agents),
            "items": agents[(page - 1) * limit : page * limit],
        },
        "cohorts": cohorts,
        "cohort_filter_basis": "task_start; full descendant attempt cost through cutoff",
        "workflows": _workflows(state, outcomes, root_ids),
        "attempts": state.page,
        "attempt_pagination": {
            "page": attempt_page,
            "limit": attempt_limit,
            "total": state.total.attempts,
        },
        "attribution_coverage": state.coverage,
        "outcome_coverage": {
            "reported_root_runs": sum(rid in outcomes for rid in root_ids),
            "visible_root_runs": len(root_ids),
        },
    }
