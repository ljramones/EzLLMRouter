"""External accounting reports operations under the existing service context."""

from __future__ import annotations

from .accounting_types import MoneyTotals, MoneyGroups

from typing import TYPE_CHECKING, cast
from .records import Record
from .store import decode_record
from .accounting_types import RecordIndex, EventGroups, SnapshotIndex

if TYPE_CHECKING:
    from .integration_accounting import ExternalAccounting
    from . import integration_accounting as _api

from collections import defaultdict
from decimal import Decimal
from .formatting import money as format_money
from .repositories import integration_accounting as _queries


def report(
    self: ExternalAccounting,
    principal: Record,
    dataset_id: str,
    filters: dict[str, str] | None = None,
    version: str = "1",
) -> Record:
    from . import integration_accounting as _api

    dataset = self._dataset(dataset_id)
    self._authorize(principal, dataset, "report")
    at = _api._time()
    filters = filters or {}
    _validate_report_filters(filters)
    data = self._read_report_snapshot(dataset_id, version, at)
    by_attempt = defaultdict(list)
    lineage_links = {
        event["attempt_id"]: event for event in data.events if event["kind"] == "lineage"
    }
    outcomes = defaultdict(list)
    for event in data.events:
        if "attempt_id" in event:
            by_attempt[event["attempt_id"]].append(event)
        if event["kind"] == "activity" and event["activity_kind"] == "outcome":
            outcomes[event["task_id"]].append(event)
    rows = []
    totals: MoneyTotals = defaultdict(Decimal)
    by_actor: MoneyGroups = defaultdict(lambda: defaultdict(Decimal))
    by_account: MoneyGroups = defaultdict(lambda: defaultdict(Decimal))
    by_root: MoneyGroups = defaultdict(lambda: defaultdict(Decimal))
    by_inclusive_run: MoneyGroups = defaultdict(lambda: defaultdict(Decimal))
    unknown = 0
    for start in data.attempts:
        row = self._report_attempt_row(
            data.account_history,
            data.all_starts,
            by_attempt,
            dataset,
            dataset_id,
            data.eligibility_reads,
            filters,
            lineage_links,
            outcomes,
            data.snapshots,
            start,
            version,
        )
        if row is None:
            continue
        status = row["cost_status"]
        rows.append(row)
        if status != "known":
            unknown += 1
            continue
        currency = row["currency"]
        amount = Decimal(row["amount_decimal"])
        totals[currency] += amount
        by_actor[start["actor_id"]][currency] += amount
        by_account[start["provider_account_id"]][currency] += amount
        by_root[start["root_run_id"]][currency] += amount
        run, seen = start["run_id"], set()
        while run and run not in seen:
            seen.add(run)
            by_inclusive_run[run][currency] += amount
            run = data.runs.get(run)
    return {
        "integration_version": version,
        "dataset_id": dataset_id,
        "attempt_count": len(rows),
        "unknown_cost_attempts": unknown,
        "known_total_by_currency": {
            currency: format_money(value, places=9) for currency, value in sorted(totals.items())
        },
        "by_actor": _money_groups(by_actor),
        "by_account": _money_groups(by_account),
        "by_root_workflow": _money_groups(by_root),
        "by_run_including_descendants": _money_groups(by_inclusive_run),
        "attempts": rows,
    }


def _enrich_report_row(
    self: ExternalAccounting,
    row: Record,
    account_history: EventGroups,
    all_starts: RecordIndex,
    effective: Record | None,
    eligibility_reads: RecordIndex,
    lineage_links: RecordIndex,
    related: list[Record],
    snapshots: SnapshotIndex,
    start: Record,
) -> None:
    from . import integration_accounting as _api

    v2 = start.get("integration_version") in ("2", "3")
    decision = next((item for item in related if item["kind"] == "decision"), None)
    resolution = next((item for item in related if item["kind"] == "account_resolution"), None)
    role, predecessor, lineage_status = _api._lineage_projection(
        start, lineage_links.get(start["attempt_id"]), all_starts, lineage_links
    )
    history = account_history.get(start["provider_account_id"], ())
    registration = history[0]["registered_at"] if history else None
    account_status = _account_status(registration, resolution, start)

    feature_status, feature_digest = _snapshot_state(
        start.get("context_ref") if v2 else None, "feature", start, snapshots
    )
    decision_status, decision_digest = _snapshot_state(
        decision.get("decision_ref") if decision else None, "decision", start, snapshots
    )
    evidence = decision.get("eligibility_evidence", {}) if decision else {}
    assessment = (
        _api._eligibility_assessment(
            decision,
            eligibility_reads.get(cast(str, evidence.get("eligibility_id"))),
            account_history.get(decision["selected_account_id"], ()),
        )
        if decision and decision.get("integration_version") in ("2", "3")
        else "legacy_absent"
        if decision
        else "missing"
    )
    selected_action = _selected_action(decision)
    row.update(
        operation_family_version=start.get("operation_family_version"),
        operation_family=start.get("operation_family"),
        model_identity_state=start.get("model_identity_state", "legacy_absent"),
        logical_operation_id=start.get("logical_operation_id"),
        attempt_role=role,
        predecessor_attempt_id=predecessor,
        lineage_status=lineage_status,
        account_resolution_status=account_status,
        resolved_account_id=resolution.get("resolved_account_id") if resolution else None,
        decision_ref=decision.get("decision_ref") if decision else None,
        selected_action=selected_action,
        eligibility_evidence_status=evidence.get("status", "missing"),
        eligibility_assessment=assessment,
        eligibility_record=eligibility_reads.get(cast(str, evidence.get("eligibility_id"))),
        feature_snapshot_status=feature_status,
        feature_snapshot_digest=feature_digest,
        feature_available_before_start=(
            snapshots[start["context_ref"]][0]["available_at"] <= start["started_at"]
            if feature_status == "captured"
            else None
        ),
        decision_snapshot_status=decision_status,
        decision_snapshot_digest=decision_digest,
        usage_provenance=effective.get("usage_provenance") if effective else None,
        usage_state=(effective["usage_state"] if effective else "not_observed")
        if v2
        else "legacy_absent",
    )


def _report_attempt_row(
    self: ExternalAccounting,
    account_history: EventGroups,
    all_starts: RecordIndex,
    by_attempt: EventGroups,
    dataset: Record,
    dataset_id: str,
    eligibility_reads: RecordIndex,
    filters: dict[str, str],
    lineage_links: RecordIndex,
    outcomes: EventGroups,
    snapshots: SnapshotIndex,
    start: Record,
    version: str,
) -> Record | None:
    if not _attempt_matches_filters(start, filters):
        return None
    related = by_attempt[start["attempt_id"]]
    ordinal, effective, latest_result, task_outcome, status = _attempt_evidence(
        related, outcomes, start
    )
    row = {
        "dataset_id": dataset_id,
        "platform_id": dataset["platform_id"],
        "environment_id": dataset["environment_id"],
        "owner_id": dataset["owner_id"],
        **{
            key: start.get(key)
            for key in (
                "attempt_id",
                "started_at",
                "task_id",
                "step_id",
                "run_id",
                "root_run_id",
                "parent_run_id",
                "actor_kind",
                "actor_id",
                "initiating_user_id",
                "provider_account_id",
                "model_id",
                "context_ref",
            )
        },
        "result_state": latest_result["result_state"] if latest_result else "not_observed",
        "result_observed_at": latest_result["occurred_at"] if latest_result else None,
        "task_outcome": task_outcome.get("outcome", "not_observed")
        if task_outcome
        else "not_observed",
        "task_outcome_observed_at": task_outcome.get("occurred_at") if task_outcome else None,
        "usage_revision": ordinal or None,
        "cost_status": status,
        "usage_observed_at": effective.get("occurred_at") if effective else None,
        "currency": effective.get("currency") if effective else None,
        "amount_decimal": effective.get("amount_decimal") if effective else None,
        "native_units": effective.get("native_units") if effective else None,
        "cost_basis": effective.get("cost_basis") if effective else None,
        "price_ref": effective.get("price_ref") if effective else None,
        "price_version": effective.get("price_version") if effective else None,
    }
    if version in ("2", "3"):
        self._enrich_report_row(
            row,
            account_history,
            all_starts,
            effective,
            eligibility_reads,
            lineage_links,
            related,
            snapshots,
            start,
        )
    return row


def _read_report_snapshot(
    self: ExternalAccounting, dataset_id: str, version: str, at: str
) -> _api.AccountingReportData:
    from . import integration_accounting as _api

    snapshots: SnapshotIndex = {}
    eligibility_reads: RecordIndex = {}
    account_history: EventGroups = {}
    with self.store.database.read():
        attempts = [
            decode_record(row[0])
            for row in self.store.database.execute(
                _queries.DATASET_EXPORT_SELECT_INTEGRATION_ATTEMPTS, (dataset_id,)
            )
        ]
        all_starts = {
            cast(str, row[0]): decode_record(row[1])
            for row in self.store.database.execute(
                _queries.ACTION_SELECT_INTEGRATION_ATTEMPTS, (dataset_id,)
            )
        }
        events = [
            decode_record(row[0])
            for row in self.store.database.execute(
                _queries.DATASET_EXPORT_SELECT_INTEGRATION_EVENTS, (dataset_id,)
            )
        ]
        runs = {
            cast(str, row[0]): cast(str | None, row[1])
            for row in self.store.database.execute(
                _queries.REPORT_SELECT_INTEGRATION_RUNS, (dataset_id,)
            )
        }
        if version in ("2", "3"):
            snapshots = {
                cast(str, row[0]): _api._snapshot_record(row[1], row[2], row[3], at)
                for row in self.store.database.execute(
                    _queries.REPORT_SELECT_INTEGRATION_SNAPSHOTS, (dataset_id,)
                )
            }
            eligibility_reads = {
                cast(str, row[0]): decode_record(row[1])
                for row in self.store.database.execute(
                    _queries.REPORT_SELECT_INTEGRATION_ELIGIBILITY_READS, (dataset_id,)
                )
            }
            account_history = defaultdict(list)
            for (raw,) in self.store.database.execute(
                _queries.DATASET_EXPORT_SELECT_INTEGRATION_ACCOUNT_HISTORY, (dataset_id,)
            ):
                item = decode_record(raw)
                if item["dataset_id"] == dataset_id:
                    account_history[item["account_id"]].append(item)
    return _api.AccountingReportData(
        attempts, all_starts, events, runs, snapshots, eligibility_reads, account_history
    )


def _validate_report_filters(filters: dict[str, str]) -> None:
    from . import integration_accounting as _api

    if set(filters) - {
        "actor_id",
        "provider_account_id",
        "task_id",
        "model_id",
        "initiating_user_id",
        "root_run_id",
        "run_id",
        "from",
        "to",
    }:
        raise _api.IntegrationError("SCHEMA_INVALID")
    if (
        any(
            not _api._shape(value, _api.SCHEMA["$defs"]["id"])
            for key, value in filters.items()
            if key not in ("from", "to")
        )
        or any(not _api._utc(value) for key, value in filters.items() if key in ("from", "to"))
        or (filters.get("from") and filters.get("to") and filters["from"] > filters["to"])
    ):
        raise _api.IntegrationError("SCHEMA_INVALID")


def _snapshot_state(
    sid: str | None, expected_kind: str, start: Record, snapshots: SnapshotIndex
) -> tuple[str, str | None]:
    if not sid or sid not in snapshots:
        return "missing", None
    meta, content, digest = snapshots[sid]
    if meta["attempt_id"] != start["attempt_id"] or meta["snapshot_kind"] != expected_kind:
        return "binding_conflict", None
    return (
        "expired" if meta["status"] == "captured" and content is None else meta["status"],
        digest,
    )


def _account_status(registration: str | None, resolution: Record | None, start: Record) -> str:
    if resolution:
        account_status = "resolved"
    elif not registration:
        account_status = "unresolved"
    elif registration > start["started_at"]:
        account_status = "registered_after_start_unconfirmed"
    else:
        account_status = "registered_at_start"
    return account_status


def _selected_action(decision: Record | None) -> Record | None:
    selected_action = (
        {
            key: decision.get(key)
            for key in (
                "selected_account_id",
                "selected_model_id",
                "operation_family",
                "capability",
                "selection_kind",
                "policy_version",
                "eligibility_evidence",
            )
        }
        if decision
        else None
    )
    return selected_action


def _attempt_matches_filters(start: Record, filters: dict[str, str]) -> bool:
    if any(
        (key in filters and start.get(key) != filters[key])
        for key in (
            "actor_id",
            "provider_account_id",
            "task_id",
            "model_id",
            "initiating_user_id",
            "root_run_id",
            "run_id",
        )
    ):
        return False
    if filters.get("from") and start["started_at"] < filters["from"]:
        return False
    if filters.get("to") and start["started_at"] >= filters["to"]:
        return False
    return True


def _attempt_evidence(
    related: list[Record], outcomes: EventGroups, start: Record
) -> tuple[int, Record | None, Record | None, Record | None, str]:
    usage = {item["usage_revision"]: item for item in related if item["kind"] == "usage"}
    ordinal = 0
    while ordinal + 1 in usage:
        ordinal += 1
    effective = usage.get(ordinal)
    results = [item for item in related if item["kind"] == "result"]
    latest_result = (
        max(results, key=lambda x: (x["occurred_at"], x["event_id"])) if results else None
    )
    task_outcome = (
        max(outcomes[start["task_id"]], key=lambda x: (x["occurred_at"], x["event_id"]))
        if (outcomes[start["task_id"]])
        else None
    )
    status = effective.get("cost_state", effective["usage_state"]) if effective else "not_observed"
    return ordinal, effective, latest_result, task_outcome, cast(str, status)


def _money_groups(group: MoneyGroups) -> dict[str, dict[str, str]]:
    return {
        key: {
            currency: format_money(amount, places=9) for currency, amount in sorted(values.items())
        }
        for key, values in sorted(group.items())
    }
