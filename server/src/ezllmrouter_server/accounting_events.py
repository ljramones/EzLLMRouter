"""External accounting events operations under the existing service context."""

from __future__ import annotations

import hashlib
import json
from .repositories import integration_accounting as _queries
from .store import encode
from . import integration_accounting as _api


def _bind_run(self, db, event):
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


def _check_lineage(self, db, event):
    did = event["dataset_id"]
    aid = event["attempt_id"]
    component = db.execute(
        _queries.LINEAGE_COMPONENT, (did, aid, event.get("predecessor_attempt_id"))
    ).fetchall()
    starts = {key: json.loads(raw) for key, raw, _ in component if raw is not None}
    accepted_links = {key: json.loads(raw) for key, _, raw in component if raw is not None}
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
    # A new start can settle a pending predecessor, while a new link can
    # affect its descendants. Validate that connected component only:
    # immutable contradictory history elsewhere must not veto new work.
    neighbors = {}
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
        cursor = current_aid
        while cursor and cursor not in checked:
            if cursor in path:
                raise _api.IntegrationError("SEMANTIC_INVALID")
            path.add(cursor)
            cursor = links.get(cursor, (None, None, None))[1]
        checked.update(path)


def _check_decision_evidence(self, db, event):
    evidence = event["eligibility_evidence"]
    if "eligibility_id" not in evidence:
        return
    row = db.execute(
        _queries.CHECK_DECISION_EVIDENCE_SELECT_INTEGRATION_ELIGIBILITY_READS,
        (event["dataset_id"], evidence["eligibility_id"]),
    ).fetchone()
    if not row:
        raise _api.IntegrationError("SEMANTIC_INVALID")
    observed = json.loads(row[0])
    history = [
        json.loads(r[0])
        for r in db.execute(
            _queries.CHECK_DECISION_EVIDENCE_SELECT_INTEGRATION_ACCOUNT_HISTORY,
            (event["selected_account_id"], event["dataset_id"]),
        )
    ]
    assessment = _api._eligibility_assessment(event, observed, history)
    if assessment == "binding_conflict":
        raise _api.IntegrationError("EVENT_CONFLICT", 409)
    if (
        assessment == "indeterminate"
        and evidence["status"] not in ("verified", "stale")
        or assessment != "indeterminate"
        and evidence["status"] != assessment
    ):
        raise _api.IntegrationError("SEMANTIC_INVALID")


def _check_snapshot_reference(self, db, dataset_id, snapshot_id, attempt_id, kind):
    row = db.execute(
        _queries.CHECK_SNAPSHOT_REFERENCE_SELECT_INTEGRATION_SNAPSHOTS,
        (dataset_id, snapshot_id),
    ).fetchone()
    if row and row != (attempt_id, kind):
        raise _api.IntegrationError("EVENT_CONFLICT", 409)


def append_event(self, principal, event, required_version=None):
    version = event.get("integration_version") if type(event) is dict else None
    if version not in _api.SCHEMAS or required_version and version != required_version:
        raise _api.IntegrationError("UNSUPPORTED_VERSION", 426)
    event = _api._checked(event, "event", version)
    dataset = self._dataset(event["dataset_id"])
    self._authorize(principal, dataset, "ingest")
    digest = hashlib.sha256(encode(event).encode()).hexdigest()

    def action():
        db = self.store.database
        self._authorize(principal, self._dataset(event["dataset_id"]), "ingest")
        did, eid, kind = event["dataset_id"], event["event_id"], event["kind"]
        old = db.execute(_queries.EVENT_RECEIPT, (did, eid)).fetchone()
        if old:
            if old[0] != digest:
                raise _api.IntegrationError("EVENT_CONFLICT", 409)
            return 200, json.loads(old[1])
        attempt_id = event.get("attempt_id")
        start = None
        if attempt_id:
            row = db.execute(_queries.ATTEMPT_FOR_UPDATE, (did, attempt_id)).fetchone()
            start = json.loads(row[0]) if row else None
        if kind in ("activity", "attempt_started"):
            self._bind_run(db, event)
        if kind in ("attempt_started", "lineage"):
            self._check_lineage(db, event)
        if kind == "attempt_started":
            if start:
                raise _api.IntegrationError("EVENT_CONFLICT", 409)
            account = db.execute(
                _queries.ACTION_SELECT_INTEGRATION_ACCOUNTS, (event["provider_account_id"], did)
            ).fetchone()
            if not account and version == "1":
                raise _api.IntegrationError("NOT_FOUND_OR_FORBIDDEN", 404)
            if version in ("2", "3"):
                self._check_snapshot_reference(db, did, event["context_ref"], attempt_id, "feature")
                for sid, snapshot_kind, metadata in db.execute(
                    _queries.ACTION_SELECT_INTEGRATION_SNAPSHOTS, (did, attempt_id)
                ):
                    if snapshot_kind == "feature" and sid != event["context_ref"]:
                        raise _api.IntegrationError("EVENT_CONFLICT", 409)
                    if (
                        snapshot_kind == "decision"
                        and json.loads(metadata)["available_at"] > event["started_at"]
                    ):
                        raise _api.IntegrationError("SEMANTIC_INVALID")
                for (raw,) in db.execute(_queries.ACCOUNT_RESOLUTION_RECORD, (did, attempt_id)):
                    if json.loads(raw)["resolved_account_id"] != event["provider_account_id"]:
                        raise _api.IntegrationError("EVENT_CONFLICT", 409)
            for (raw,) in db.execute(_queries.DECISION_EVENT_RECORD, (did, attempt_id)):
                decision = json.loads(raw)
                if (
                    decision["selected_account_id"] != event["provider_account_id"]
                    or decision.get("selected_model_id") != event.get("model_id")
                    or decision.get("integration_version") == "3"
                    and (
                        decision["operation_family"] != event.get("operation_family")
                        or decision["selection_kind"]
                        != (
                            "known_model"
                            if event.get("model_identity_state") == "known"
                            else "provider_selected"
                            if event.get("model_identity_state") == "unknown"
                            else "not_applicable"
                        )
                    )
                    or decision["occurred_at"] > event["started_at"]
                ):
                    raise _api.IntegrationError("EVENT_CONFLICT", 409)
            db.execute(
                _queries.ACTION_INSERT_INTEGRATION_ATTEMPTS,
                (
                    did,
                    attempt_id,
                    eid,
                    encode(event),
                    int(event["started_at"] >= dataset["activated_at"]),
                ),
            )
        if kind == "decision":
            previous = db.execute(_queries.DECISION_EVENT_ID, (did, attempt_id)).fetchone()
            if previous:
                raise _api.IntegrationError("EVENT_CONFLICT", 409)
            if start and (
                event["selected_account_id"] != start["provider_account_id"]
                or event.get("selected_model_id") != start.get("model_id")
                or version == "3"
                and (
                    event["operation_family"] != start.get("operation_family")
                    or event["selection_kind"]
                    != (
                        "known_model"
                        if start.get("model_identity_state") == "known"
                        else "provider_selected"
                        if start.get("model_identity_state") == "unknown"
                        else "not_applicable"
                    )
                )
                or event["occurred_at"] > start["started_at"]
            ):
                raise _api.IntegrationError("EVENT_CONFLICT", 409)
            if version in ("2", "3"):
                self._check_decision_evidence(db, event)
                self._check_snapshot_reference(
                    db, did, event["decision_ref"], attempt_id, "decision"
                )
                snapshot = db.execute(
                    _queries.DECISION_SNAPSHOT_CONTENT,
                    (did, event["decision_ref"], attempt_id),
                ).fetchone()
                if snapshot and snapshot[0]:
                    action = json.loads(snapshot[0])["selected_action"]
                    if any(
                        action.get(key) != event.get(key)
                        for key in (
                            "selected_account_id",
                            "selected_model_id",
                            "policy_version",
                            "eligibility_evidence",
                        )
                        + (
                            ("operation_family", "capability", "selection_kind")
                            if version == "3"
                            else ()
                        )
                    ):
                        raise _api.IntegrationError("EVENT_CONFLICT", 409)
        if kind == "account_resolution":
            resolved = db.execute(
                _queries.INTEGRATION_ACCOUNT_EXISTS,
                (event["resolved_account_id"], did),
            ).fetchone()
            if (
                not resolved
                or db.execute(_queries.ACCOUNT_RESOLUTION_EXISTS, (did, attempt_id)).fetchone()
            ):
                raise _api.IntegrationError("EVENT_CONFLICT", 409)
            if start and start["provider_account_id"] != event["resolved_account_id"]:
                raise _api.IntegrationError("EVENT_CONFLICT", 409)
        if (
            kind == "lineage"
            and db.execute(_queries.LINEAGE_EVENT_EXISTS, (did, attempt_id)).fetchone()
        ):
            raise _api.IntegrationError("EVENT_CONFLICT", 409)
        ordinal = event.get("usage_revision") if kind == "usage" else None
        if (
            ordinal is not None
            and db.execute(_queries.USAGE_REVISION_EXISTS, (did, attempt_id, ordinal)).fetchone()
        ):
            raise _api.IntegrationError("EVENT_CONFLICT", 409)
        membership = (
            (
                "included"
                if event["started_at"] >= dataset["activated_at"]
                else "excluded_before_activation"
            )
            if kind == "attempt_started"
            else (
                "included"
                if start and start["started_at"] >= dataset["activated_at"]
                else "excluded_before_activation"
                if start
                else "pending_start"
            )
        )
        receipt = {
            "integration_version": version,
            "dataset_id": did,
            "event_id": eid,
            "event_digest": "sha256:" + digest,
            "kind": kind,
            "membership_at_receipt": membership,
            "received_at": _api._time(),
        }
        db.execute(
            _queries.ACTION_INSERT_INTEGRATION_EVENTS,
            (did, eid, kind, attempt_id, ordinal, digest, encode(event), encode(receipt)),
        )
        return 201, receipt

    return self.store.database.transaction(action)


def receipt(self, principal, dataset_id, event_id):
    dataset = self._dataset(dataset_id)
    self._authorize(principal, dataset, "receipt")
    with self.store.database.read():
        row = self.store.database.execute(
            _queries.RECEIPT_SELECT_INTEGRATION_EVENTS, (dataset_id, event_id)
        ).fetchone()
    if not row:
        raise _api.IntegrationError("NOT_FOUND_OR_FORBIDDEN", 404)
    return json.loads(row[0])
