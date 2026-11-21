"""External accounting events operations under the existing service context."""

from __future__ import annotations

from typing import TYPE_CHECKING
from .database import Database
from .records import Record
from .store import decode_record
from .accounting_types import ReceiptResult

if TYPE_CHECKING:
    from .integration_accounting import ExternalAccounting

import hashlib
from .repositories import integration_accounting as _queries
from .store import encode
from . import integration_accounting as _api


def _check_decision_evidence(self: ExternalAccounting, db: Database, event: Record) -> None:
    evidence = event["eligibility_evidence"]
    if "eligibility_id" not in evidence:
        return
    row = db.execute(
        _queries.CHECK_DECISION_EVIDENCE_SELECT_INTEGRATION_ELIGIBILITY_READS,
        (event["dataset_id"], evidence["eligibility_id"]),
    ).fetchone()
    if not row:
        raise _api.IntegrationError("SEMANTIC_INVALID")
    observed = decode_record(row[0])
    history = [
        decode_record(r[0])
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


def _check_snapshot_reference(
    self: ExternalAccounting,
    db: Database,
    dataset_id: str,
    snapshot_id: str,
    attempt_id: str | None,
    kind: str,
) -> None:
    row = db.execute(
        _queries.CHECK_SNAPSHOT_REFERENCE_SELECT_INTEGRATION_SNAPSHOTS,
        (dataset_id, snapshot_id),
    ).fetchone()
    if row and row != (attempt_id, kind):
        raise _api.IntegrationError("EVENT_CONFLICT", 409)


def append_event(
    self: ExternalAccounting, principal: Record, event: Record, required_version: str | None = None
) -> ReceiptResult:
    version = event.get("integration_version") if type(event) is dict else None
    if version not in _api.SCHEMAS or required_version and version != required_version:
        raise _api.IntegrationError("UNSUPPORTED_VERSION", 426)
    event = _api._checked(event, "event", version)
    dataset = self._dataset(event["dataset_id"])
    self._authorize(principal, dataset, "ingest")
    digest = hashlib.sha256(encode(event).encode()).hexdigest()

    def action() -> ReceiptResult:
        return _ingest_event(self, principal, event, version, dataset, digest)

    return self.store.database.transaction(action)


def receipt(self: ExternalAccounting, principal: Record, dataset_id: str, event_id: str) -> Record:
    dataset = self._dataset(dataset_id)
    self._authorize(principal, dataset, "receipt")
    with self.store.database.read():
        row = self.store.database.execute(
            _queries.RECEIPT_SELECT_INTEGRATION_EVENTS, (dataset_id, event_id)
        ).fetchone()
    if not row:
        raise _api.IntegrationError("NOT_FOUND_OR_FORBIDDEN", 404)
    return decode_record(row[0])


def _record_attempt_start(
    self: ExternalAccounting,
    db: Database,
    event: Record,
    version: str,
    dataset: Record,
    did: str,
    eid: str,
    attempt_id: str | None,
    start: Record | None,
) -> None:
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
                and decode_record(metadata)["available_at"] > event["started_at"]
            ):
                raise _api.IntegrationError("SEMANTIC_INVALID")
        for (raw,) in db.execute(_queries.ACCOUNT_RESOLUTION_RECORD, (did, attempt_id)):
            if decode_record(raw)["resolved_account_id"] != event["provider_account_id"]:
                raise _api.IntegrationError("EVENT_CONFLICT", 409)
    for (raw,) in db.execute(_queries.DECISION_EVENT_RECORD, (did, attempt_id)):
        decision = decode_record(raw)
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


def _check_decision_event(
    self: ExternalAccounting,
    db: Database,
    event: Record,
    version: str,
    did: str,
    attempt_id: str | None,
    start: Record | None,
) -> None:
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
        self._check_snapshot_reference(db, did, event["decision_ref"], attempt_id, "decision")
        snapshot = db.execute(
            _queries.DECISION_SNAPSHOT_CONTENT,
            (did, event["decision_ref"], attempt_id),
        ).fetchone()
        if snapshot and snapshot[0]:
            action = decode_record(snapshot[0])["selected_action"]
            if any(
                action.get(key) != event.get(key)
                for key in (
                    "selected_account_id",
                    "selected_model_id",
                    "policy_version",
                    "eligibility_evidence",
                )
                + (("operation_family", "capability", "selection_kind") if version == "3" else ())
            ):
                raise _api.IntegrationError("EVENT_CONFLICT", 409)


def _check_account_resolution(
    db: Database, event: Record, did: str, attempt_id: str | None, start: Record | None
) -> None:
    resolved = db.execute(
        _queries.INTEGRATION_ACCOUNT_EXISTS,
        (event["resolved_account_id"], did),
    ).fetchone()
    if not resolved or db.execute(_queries.ACCOUNT_RESOLUTION_EXISTS, (did, attempt_id)).fetchone():
        raise _api.IntegrationError("EVENT_CONFLICT", 409)
    if start and start["provider_account_id"] != event["resolved_account_id"]:
        raise _api.IntegrationError("EVENT_CONFLICT", 409)


def _record_event(
    self: ExternalAccounting,
    db: Database,
    event: Record,
    version: str,
    dataset: Record,
    digest: str,
    did: str,
    eid: str,
    kind: str,
    attempt_id: str | None,
    start: Record | None,
) -> ReceiptResult:
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


def _ingest_event(
    self: ExternalAccounting,
    principal: Record,
    event: Record,
    version: str,
    dataset: Record,
    digest: str,
) -> ReceiptResult:
    db = self.store.database
    self._authorize(principal, self._dataset(event["dataset_id"]), "ingest")
    did, eid, kind = event["dataset_id"], event["event_id"], event["kind"]
    old = db.execute(_queries.EVENT_RECEIPT, (did, eid)).fetchone()
    if old:
        if old[0] != digest:
            raise _api.IntegrationError("EVENT_CONFLICT", 409)
        return 200, decode_record(old[1])
    attempt_id = event.get("attempt_id")
    start = None
    if attempt_id:
        row = db.execute(_queries.ATTEMPT_FOR_UPDATE, (did, attempt_id)).fetchone()
        start = decode_record(row[0]) if row else None
    if kind in ("activity", "attempt_started"):
        self._bind_run(db, event)
    if kind in ("attempt_started", "lineage"):
        self._check_lineage(db, event)
    if kind == "attempt_started":
        _record_attempt_start(self, db, event, version, dataset, did, eid, attempt_id, start)
    if kind == "decision":
        _check_decision_event(self, db, event, version, did, attempt_id, start)
    if kind == "account_resolution":
        _check_account_resolution(db, event, did, attempt_id, start)
    if (
        kind == "lineage"
        and db.execute(_queries.LINEAGE_EVENT_EXISTS, (did, attempt_id)).fetchone()
    ):
        raise _api.IntegrationError("EVENT_CONFLICT", 409)
    return _record_event(
        self, db, event, version, dataset, digest, did, eid, kind, attempt_id, start
    )
