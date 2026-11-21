"""Connected lineage validation inside the existing event transaction."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast
from .database import Database
from .records import Record
from .store import decode_record
from .accounting_types import RecordIndex, LineageLinks

if TYPE_CHECKING:
    from .integration_accounting import ExternalAccounting
from .repositories import integration_accounting as _queries


def _bind_run(self: ExternalAccounting, db: Database, event: Record) -> None:
    from . import integration_accounting as _api

    dataset_id, run_id = event["dataset_id"], event["run_id"]
    root, parent, task = event["root_run_id"], event.get("parent_run_id"), event["task_id"]
    old = db.execute(_queries.RUN_LINEAGE, (dataset_id, run_id)).fetchone()
    if old:
        if old != (root, parent, task):
            raise _api.IntegrationError("EVENT_CONFLICT", 409)
        return
    seen = {run_id}
    ancestor = parent
    while ancestor:
        if ancestor in seen:
            raise _api.IntegrationError("SEMANTIC_INVALID")
        seen.add(ancestor)
        row = db.execute(_queries.RUN_LINEAGE, (dataset_id, ancestor)).fetchone()
        if not row:
            break  # Late parent delivery; binding is rechecked when that parent arrives.
        if row[0] != root or row[2] != task:
            raise _api.IntegrationError("EVENT_CONFLICT", 409)
        ancestor = row[1]
    for child_root, child_task in db.execute(
        _queries.BIND_RUN_SELECT_INTEGRATION_RUNS, (dataset_id, run_id)
    ):
        if child_root != root or child_task != task:
            raise _api.IntegrationError("EVENT_CONFLICT", 409)
    db.execute(_queries.BIND_RUN_INSERT_INTEGRATION_RUNS, (dataset_id, run_id, root, parent, task))


def _check_lineage(self: ExternalAccounting, db: Database, event: Record) -> None:
    from . import integration_accounting as _api

    did, aid, starts, accepted_links, links = _lineage_component(db, event)
    # A new start can settle a pending predecessor, while a new link can
    # affect its descendants. Validate that connected component only:
    # immutable contradictory history elsewhere must not veto new work.
    affected = _affected_attempts(aid, links)
    for current_aid in sorted(affected):
        start, link = starts.get(current_aid), accepted_links.get(current_aid)
        if (
            start
            and link
            and (
                start.get("integration_version") not in ("2", "3")
                or start["attempt_role"] != "unknown"
                or start["logical_operation_id"] != link["logical_operation_id"]
            )
        ):
            raise _api.IntegrationError("EVENT_CONFLICT", 409)
    for current_aid in sorted(affected):
        if current_aid not in links:
            continue
        _, predecessor, logical = links[current_aid]
        if not predecessor:
            continue
        if predecessor == current_aid:
            raise _api.IntegrationError("SEMANTIC_INVALID")
        prior = starts.get(predecessor)
        current = starts.get(current_aid)
        if (
            prior
            and prior.get("logical_operation_id") != logical
            or current
            and current.get("logical_operation_id") != logical
            or prior
            and current
            and prior.get("task_id") != current.get("task_id")
        ):
            raise _api.IntegrationError("EVENT_CONFLICT", 409)
        if (
            not prior
            and db.execute(
                _queries.CHECK_LINEAGE_SELECT_INTEGRATION_ATTEMPTS, (did, predecessor)
            ).fetchone()
        ):
            raise _api.IntegrationError("EVENT_CONFLICT", 409)
    # Visit each predecessor edge once, including long retry chains.
    checked = set()
    for current_aid in affected:
        path = set()
        cursor: str | None = current_aid
        while cursor and cursor not in checked:
            if cursor in path:
                raise _api.IntegrationError("SEMANTIC_INVALID")
            path.add(cursor)
            cursor = links.get(cursor, (None, None, None))[1]
        checked.update(path)


def _lineage_component(
    db: Database, event: Record
) -> tuple[str, str, RecordIndex, RecordIndex, LineageLinks]:
    from . import integration_accounting as _api

    did = event["dataset_id"]
    aid = event["attempt_id"]
    component = db.execute(
        _queries.LINEAGE_COMPONENT, (did, aid, event.get("predecessor_attempt_id"))
    ).fetchall()
    starts = {cast(str, key): decode_record(raw) for key, raw, _ in component if raw is not None}
    accepted_links = {
        cast(str, key): decode_record(raw) for key, _, raw in component if raw is not None
    }
    if event["kind"] == "attempt_started":
        prior_link = accepted_links.get(aid)
        if prior_link and (
            event.get("integration_version") not in ("2", "3")
            or event["attempt_role"] != "unknown"
            or event["logical_operation_id"] != prior_link["logical_operation_id"]
        ):
            raise _api.IntegrationError("EVENT_CONFLICT", 409)
        starts[aid] = event
    else:
        existing = starts.get(aid)
        if existing and (
            existing.get("attempt_role") != "unknown"
            or existing.get("logical_operation_id") != event["logical_operation_id"]
        ):
            raise _api.IntegrationError("EVENT_CONFLICT", 409)
        accepted_links[aid] = event
    links = {
        aid: (
            start["attempt_role"],
            start.get("predecessor_attempt_id"),
            start["logical_operation_id"],
        )
        for aid, start in starts.items()
        if start.get("integration_version") in ("2", "3")
    }
    for link in accepted_links.values():
        links[link["attempt_id"]] = (
            link["attempt_role"],
            link["predecessor_attempt_id"],
            link["logical_operation_id"],
        )
    return did, aid, starts, accepted_links, links


def _affected_attempts(aid: str, links: LineageLinks) -> set[str]:
    neighbors: dict[str, set[str]] = {}
    for child, (_, predecessor, _) in links.items():
        if predecessor:
            neighbors.setdefault(child, set()).add(predecessor)
            neighbors.setdefault(predecessor, set()).add(child)
    affected = {aid}
    pending = [aid]
    while pending:
        for adjacent in neighbors.get(pending.pop(), ()):
            if adjacent not in affected:
                affected.add(adjacent)
                pending.append(adjacent)
    return affected
