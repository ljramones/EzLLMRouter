"""Dataset export projection; reads stay in the original caller snapshot."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast
from .records import Record
from .store import decode_record
from .accounting_types import EventGroups, SnapshotData, SnapshotIndex

if TYPE_CHECKING:
    from .integration_accounting import ExternalAccounting
import hashlib
from collections import defaultdict
from .repositories import integration_accounting as _queries
from .store import encode
from . import integration_accounting as _api


def dataset_export(
    self: ExternalAccounting, principal: Record, dataset_id: str, version: str = "2"
) -> Record:
    dataset = self._dataset(dataset_id)
    self._authorize(principal, dataset, "report")
    at = _api._time()
    with self.store.database.read():
        attempts, included, events, eligibility, snapshots, history = _read_export_snapshot(
            self, dataset_id, at
        )
    snapshot_rows, snapshot_by_id = _export_snapshots(snapshots, included)
    reference_assessments = _snapshot_references(attempts, events, included, snapshot_by_id)
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


def _read_export_snapshot(
    self: ExternalAccounting, dataset_id: str, at: str
) -> tuple[list[Record], set[str], list[Record], list[Record], list[SnapshotData], EventGroups]:
    db = self.store.database
    attempts = [
        decode_record(r[0])
        for r in db.execute(_queries.DATASET_EXPORT_SELECT_INTEGRATION_ATTEMPTS, (dataset_id,))
    ]
    included = {item["attempt_id"] for item in attempts}
    events = [
        decode_record(r[0])
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
        decode_record(r[0])
        for r in db.execute(
            _queries.DATASET_EXPORT_SELECT_INTEGRATION_ELIGIBILITY_READS, (dataset_id,)
        )
        if decode_record(r[0])["eligibility_id"] in eligible_ids
    ]
    snapshots = [
        _api._snapshot_record(*cast(tuple[object, object, object], r), at)
        for r in db.execute(_queries.DATASET_EXPORT_SELECT_INTEGRATION_SNAPSHOTS, (dataset_id,))
    ]
    history = defaultdict(list)
    for (raw,) in db.execute(
        _queries.DATASET_EXPORT_SELECT_INTEGRATION_ACCOUNT_HISTORY, (dataset_id,)
    ):
        item = decode_record(raw)
        if item["dataset_id"] == dataset_id:
            history[item["account_id"]].append(item)
    return attempts, included, events, eligibility, snapshots, history


def _export_snapshots(
    snapshots: list[SnapshotData], included: set[str]
) -> tuple[list[Record], SnapshotIndex]:
    snapshot_rows = []
    snapshot_by_id = {
        meta["snapshot_id"]: (meta, content, digest) for meta, content, digest in snapshots
    }
    for meta, content, digest in snapshots:
        if meta["attempt_id"] not in included:
            continue
        decoded = decode_record(content) if content else {}
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
    return snapshot_rows, snapshot_by_id


def _snapshot_references(
    attempts: list[Record], events: list[Record], included: set[str], snapshot_by_id: SnapshotIndex
) -> list[Record]:
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
    return reference_assessments
