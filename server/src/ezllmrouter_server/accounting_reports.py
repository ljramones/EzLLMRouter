"""External accounting reports operations under the existing service context."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from decimal import Decimal
from .formatting import money as format_money
from .repositories import integration_accounting as _queries
from .store import encode
from . import integration_accounting as _api


def dataset_export(self, principal, dataset_id, version="2"):
    dataset = self._dataset(dataset_id)
    self._authorize(principal, dataset, "report")
    at = _api._time()
    with self.store.database.read():
        db = self.store.database
        attempts = [
            json.loads(r[0])
            for r in db.execute(_queries.DATASET_EXPORT_SELECT_INTEGRATION_ATTEMPTS, (dataset_id,))
        ]
        included = {item["attempt_id"] for item in attempts}
        events = [
            json.loads(r[0])
            for r in db.execute(_queries.DATASET_EXPORT_SELECT_INTEGRATION_EVENTS, (dataset_id,))
        ]
        eligible_ids = {
            e["eligibility_evidence"]["eligibility_id"]
            for e in events
            if e.get("attempt_id") in included
            and e["kind"] == "decision"
            and e.get("eligibility_evidence", {}).get("eligibility_id")
        }
        eligibility = [
            json.loads(r[0])
            for r in db.execute(
                _queries.DATASET_EXPORT_SELECT_INTEGRATION_ELIGIBILITY_READS, (dataset_id,)
            )
            if json.loads(r[0])["eligibility_id"] in eligible_ids
        ]
        snapshots = [
            _api._snapshot_record(*r, at)
            for r in db.execute(_queries.DATASET_EXPORT_SELECT_INTEGRATION_SNAPSHOTS, (dataset_id,))
        ]
        history = defaultdict(list)
        for (raw,) in db.execute(
            _queries.DATASET_EXPORT_SELECT_INTEGRATION_ACCOUNT_HISTORY, (dataset_id,)
        ):
            item = json.loads(raw)
            if item["dataset_id"] == dataset_id:
                history[item["account_id"]].append(item)
    snapshot_rows = []
    snapshot_by_id = {
        meta["snapshot_id"]: (meta, content, digest) for meta, content, digest in snapshots
    }
    for meta, content, digest in snapshots:
        if meta["attempt_id"] not in included:
            continue
        decoded = json.loads(content) if content else {}
        if (
            content
            and "sha256:" + hashlib.sha256(encode({**meta, **decoded}).encode()).hexdigest()
            != digest
        ):
            raise _api.IntegrationError("SNAPSHOT_INTEGRITY_FAILED", 503, "query_first")
        snapshot_rows.append(
            {
                **meta,
                "status": "expired"
                if meta["status"] == "captured" and content is None
                else meta["status"],
                "snapshot_digest": digest,
                **decoded,
            }
        )
    reference_assessments = []
    for event in attempts:
        if event.get("integration_version") not in ("2", "3"):
            continue
        sid, kind = event["context_ref"], "feature"
        target = snapshot_by_id.get(sid)
        status = (
            "missing"
            if target is None
            else "binding_conflict"
            if target[0]["attempt_id"] != event["attempt_id"] or target[0]["snapshot_kind"] != kind
            else "expired"
            if target[0]["status"] == "captured" and target[1] is None
            else target[0]["status"]
        )
        reference_assessments.append(
            {
                "attempt_id": event["attempt_id"],
                "reference_kind": kind,
                "snapshot_id": sid,
                "status": status,
            }
        )
    for event in events:
        if (
            event.get("attempt_id") not in included
            or event["kind"] != "decision"
            or event.get("integration_version") not in ("2", "3")
        ):
            continue
        sid = event["decision_ref"]
        target = snapshot_by_id.get(sid)
        status = (
            "missing"
            if target is None
            else "binding_conflict"
            if target[0]["attempt_id"] != event["attempt_id"]
            or target[0]["snapshot_kind"] != "decision"
            else "expired"
            if target[0]["status"] == "captured" and target[1] is None
            else target[0]["status"]
        )
        reference_assessments.append(
            {
                "attempt_id": event["attempt_id"],
                "reference_kind": "decision",
                "snapshot_id": sid,
                "status": status,
            }
        )
    return {
        "integration_version": version,
        "dataset": dataset,
        "attempts": attempts,
        "events": [
            e
            for e in events
            if e.get("attempt_id") in included
            or e["kind"] == "activity"
            and e["task_id"] in {a["task_id"] for a in attempts}
        ],
        "eligibility_reads": eligibility,
        "snapshots": snapshot_rows,
        "snapshot_reference_assessments": reference_assessments,
        "eligibility_assessments": [
            {
                "event_id": e["event_id"],
                "attempt_id": e["attempt_id"],
                "reported_status": e["eligibility_evidence"]["status"],
                "assessment": _api._eligibility_assessment(
                    e,
                    next(
                        (
                            answer
                            for answer in eligibility
                            if answer["eligibility_id"]
                            == e["eligibility_evidence"].get("eligibility_id")
                        ),
                        None,
                    ),
                    history.get(e["selected_account_id"], ()),
                ),
            }
            for e in events
            if e.get("attempt_id") in included
            and e["kind"] == "decision"
            and e.get("integration_version") in ("2", "3")
        ],
    }


def report(self, principal, dataset_id, filters=None, version="1"):
    dataset = self._dataset(dataset_id)
    self._authorize(principal, dataset, "report")
    at = _api._time()
    filters = filters or {}
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
    totals = defaultdict(Decimal)
    by_actor = defaultdict(lambda: defaultdict(Decimal))
    by_account = defaultdict(lambda: defaultdict(Decimal))
    by_root = defaultdict(lambda: defaultdict(Decimal))
    by_inclusive_run = defaultdict(lambda: defaultdict(Decimal))
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
    money = lambda group: {
        key: {
            currency: format_money(amount, places=9) for currency, amount in sorted(values.items())
        }
        for key, values in sorted(group.items())
    }
    return {
        "integration_version": version,
        "dataset_id": dataset_id,
        "attempt_count": len(rows),
        "unknown_cost_attempts": unknown,
        "known_total_by_currency": {
            currency: format_money(value, places=9) for currency, value in sorted(totals.items())
        },
        "by_actor": money(by_actor),
        "by_account": money(by_account),
        "by_root_workflow": money(by_root),
        "by_run_including_descendants": money(by_inclusive_run),
        "attempts": rows,
    }


def _enrich_report_row(
    self,
    row,
    account_history,
    all_starts,
    effective,
    eligibility_reads,
    lineage_links,
    related,
    snapshots,
    start,
):
    v2 = start.get("integration_version") in ("2", "3")
    decision = next((item for item in related if item["kind"] == "decision"), None)
    resolution = next((item for item in related if item["kind"] == "account_resolution"), None)
    role, predecessor, lineage_status = _api._lineage_projection(
        start, lineage_links.get(start["attempt_id"]), all_starts, lineage_links
    )
    history = account_history.get(start["provider_account_id"], ())
    registration = history[0]["registered_at"] if history else None
    if resolution:
        account_status = "resolved"
    elif not registration:
        account_status = "unresolved"
    elif registration > start["started_at"]:
        account_status = "registered_after_start_unconfirmed"
    else:
        account_status = "registered_at_start"

    def snapshot_state(sid, expected_kind, *, start=start):
        if not sid or sid not in snapshots:
            return "missing", None
        meta, content, digest = snapshots[sid]
        if meta["attempt_id"] != start["attempt_id"] or meta["snapshot_kind"] != expected_kind:
            return "binding_conflict", None
        return (
            "expired" if meta["status"] == "captured" and content is None else meta["status"],
            digest,
        )

    feature_status, feature_digest = snapshot_state(
        start.get("context_ref") if v2 else None, "feature"
    )
    decision_status, decision_digest = snapshot_state(
        decision.get("decision_ref") if decision else None, "decision"
    )
    evidence = decision.get("eligibility_evidence", {}) if decision else {}
    assessment = (
        _api._eligibility_assessment(
            decision,
            eligibility_reads.get(evidence.get("eligibility_id")),
            account_history.get(decision["selected_account_id"], ()),
        )
        if decision and decision.get("integration_version") in ("2", "3")
        else "legacy_absent"
        if decision
        else "missing"
    )
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
        eligibility_record=eligibility_reads.get(evidence.get("eligibility_id")),
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
    self,
    account_history,
    all_starts,
    by_attempt,
    dataset,
    dataset_id,
    eligibility_reads,
    filters,
    lineage_links,
    outcomes,
    snapshots,
    start,
    version,
):
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
        return None
    if filters.get("from") and start["started_at"] < filters["from"]:
        return None
    if filters.get("to") and start["started_at"] >= filters["to"]:
        return None
    related = by_attempt[start["attempt_id"]]
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


def _read_report_snapshot(self, dataset_id, version, at) -> _api.AccountingReportData:
    snapshots, eligibility_reads, account_history = {}, {}, {}
    with self.store.database.read():
        attempts = [
            json.loads(row[0])
            for row in self.store.database.execute(
                _queries.DATASET_EXPORT_SELECT_INTEGRATION_ATTEMPTS, (dataset_id,)
            )
        ]
        all_starts = {
            row[0]: json.loads(row[1])
            for row in self.store.database.execute(
                _queries.ACTION_SELECT_INTEGRATION_ATTEMPTS, (dataset_id,)
            )
        }
        events = [
            json.loads(row[0])
            for row in self.store.database.execute(
                _queries.DATASET_EXPORT_SELECT_INTEGRATION_EVENTS, (dataset_id,)
            )
        ]
        runs = {
            row[0]: row[1]
            for row in self.store.database.execute(
                _queries.REPORT_SELECT_INTEGRATION_RUNS, (dataset_id,)
            )
        }
        if version in ("2", "3"):
            snapshots = {
                row[0]: _api._snapshot_record(row[1], row[2], row[3], at)
                for row in self.store.database.execute(
                    _queries.REPORT_SELECT_INTEGRATION_SNAPSHOTS, (dataset_id,)
                )
            }
            eligibility_reads = {
                row[0]: json.loads(row[1])
                for row in self.store.database.execute(
                    _queries.REPORT_SELECT_INTEGRATION_ELIGIBILITY_READS, (dataset_id,)
                )
            }
            account_history = defaultdict(list)
            for (raw,) in self.store.database.execute(
                _queries.DATASET_EXPORT_SELECT_INTEGRATION_ACCOUNT_HISTORY, (dataset_id,)
            ):
                item = json.loads(raw)
                if item["dataset_id"] == dataset_id:
                    account_history[item["account_id"]].append(item)
    return _api.AccountingReportData(
        attempts, all_starts, events, runs, snapshots, eligibility_reads, account_history
    )
