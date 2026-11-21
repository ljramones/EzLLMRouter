"""SQLiteStore results records; lifecycle/transaction ownership stays on the store."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import cast
from .records import Record as Record
from .formatting import earliest_timestamp
from .repositories import store as _queries
from .states import DispatchState, SubmissionState
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .store import SQLiteStore
    from . import store as _api


def _update_in_tx(self: SQLiteStore, submission_id: str, fields: _api.Record) -> _api.Record:
    from . import store as _api

    row = self.database.execute(
        _queries.UPDATE_IN_TX_SELECT_SUBMISSIONS, (submission_id,)
    ).fetchone()
    if not row:
        raise KeyError(submission_id)
    record = _api.decode_record(row[0])
    record.update(fields)
    record["status_revision"] += 1
    self.database.execute(
        _queries.UPDATE_IN_TX_UPDATE_SUBMISSIONS, (_api.encode(record), submission_id)
    )
    return record


def _append_usage_in_tx(
    self: SQLiteStore, submission_id: str, attempt_id: str, usage: _api.Record
) -> _api.Record:
    """Append to the attempt ledger inside the caller's publishing transaction."""
    from . import store as _api

    row = self.database.execute(_queries.ACTION_SELECT_USAGE_REVISIONS, (attempt_id,)).fetchone()
    if row is None:
        raise RuntimeError("usage revision count missing")
    existing = cast(int | None, row[0])
    revision = (existing or 0) + 1
    revision_data = dict(usage)
    revision_data["revision"] = revision
    if existing:
        revision_data["previous_revision"] = existing
    self.database.execute(
        _queries.ACTION_INSERT_USAGE_REVISIONS,
        (attempt_id, revision, submission_id, _api.encode(revision_data)),
    )
    return {"state": "available", "revision": revision_data}


def update(
    self: SQLiteStore, submission_id: str, fields: _api.Record, usage: _api.Record | None = None
) -> _api.Record:
    from . import store as _api

    new_fields = dict(fields)

    def action() -> _api.Record:
        latest_usage: _api.Record = {"state": "not_recorded"}
        if usage is not None:
            row = self.database.execute(
                _queries.UPDATE_IN_TX_SELECT_SUBMISSIONS, (submission_id,)
            ).fetchone()
            if not row:
                raise KeyError(submission_id)
            attempt_id = _api.decode_record(row[0])["attempt_id"]
            latest_usage = self._append_usage_in_tx(submission_id, attempt_id, usage)
        elif "candidate" in new_fields and new_fields["candidate"] is not None:
            row = self.database.execute(
                _queries.UPDATE_IN_TX_SELECT_SUBMISSIONS, (submission_id,)
            ).fetchone()
            if not row:
                raise KeyError(submission_id)
            attempt_id = _api.decode_record(row[0])["attempt_id"]
            prior = self.database.execute(_queries.LATEST_USAGE, (attempt_id,)).fetchone()
            if prior:
                latest_usage = {"state": "available", "revision": _api.decode_record(prior[0])}
        if "candidate" in new_fields and new_fields["candidate"] is not None:
            new_fields["candidate"] = {**new_fields["candidate"], "usage": latest_usage}
        return self._update_in_tx(submission_id, new_fields)

    return self._transaction(action)


def mark_wait_expired_no_store(self: SQLiteStore, submission_id: str, at: str) -> _api.Record:
    from . import store as _api

    def action() -> _api.Record:
        row = self.database.execute(
            _queries.UPDATE_IN_TX_SELECT_SUBMISSIONS, (submission_id,)
        ).fetchone()
        if not row:
            raise KeyError(submission_id)
        record = _api.decode_record(row[0])
        fields: _api.Record = {"wait_expired_no_store": True, "updated_at": at}
        if record["submission_state"] == "completed":
            fields.update(
                candidate=None,
                candidate_access="not_retained",
                result_unavailable_reason="wait_expired_no_store",
            )
        return self._update_in_tx(submission_id, fields)

    return self._transaction(action)


def complete_candidate(
    self: SQLiteStore,
    submission_id: str,
    candidate: _api.Record,
    usage: _api.Record | None,
    raw_usage_digest: str | None,
    current_allowed: bool,
    current_expiry: str | None,
    at: str,
    live_source_tags: list[str] | None = None,
) -> _api.Record:
    from . import store as _api

    def action() -> _api.Record:
        row = self.database.execute(
            _queries.UPDATE_IN_TX_SELECT_SUBMISSIONS, (submission_id,)
        ).fetchone()
        if not row:
            raise KeyError(submission_id)
        record = _api.decode_record(row[0])
        if record["submission_state"] == "completed":
            raise ValueError("candidate already completed")
        expiry = earliest_timestamp(record.get("content_expires_at"), current_expiry)
        expired = bool(
            expiry
            and datetime.fromisoformat(expiry.replace("Z", "+00:00")) <= datetime.now(timezone.utc)
        )
        retain = bool(
            record["content_store_allowed"]
            and current_allowed
            and (not record["wait_expired_no_store"])
            and (not expired)
        )
        latest_usage: _api.Record = {"state": "not_recorded"}
        if usage is not None:
            attempt_id = record["attempt_id"]
            latest_usage = self._append_usage_in_tx(submission_id, attempt_id, usage)
        else:
            prior = self.database.execute(_queries.LATEST_USAGE, (record["attempt_id"],)).fetchone()
            if prior:
                latest_usage = {"state": "available", "revision": _api.decode_record(prior[0])}
        fields: _api.Record = {
            "submission_state": SubmissionState.COMPLETED.value,
            "dispatch_state": DispatchState.RESPONSE_OBSERVED.value,
            "attempt_revision": 4,
            "updated_at": at,
            "content_store_allowed": retain,
            "candidate_access": "present"
            if retain
            else "not_retained"
            if record["wait_expired_no_store"]
            else "expired"
            if expired
            else "not_retained",
            "candidate": {**candidate, "usage": latest_usage} if retain else None,
        }
        if not retain and (not record["wait_expired_no_store"]) and (not expired):
            fields["live_source_tags"] = list(live_source_tags or [])
        if raw_usage_digest is not None:
            fields["raw_usage_digest"] = raw_usage_digest
        if record["wait_expired_no_store"]:
            fields["result_unavailable_reason"] = "wait_expired_no_store"
        result = self._update_in_tx(submission_id, fields)
        result["usage"] = latest_usage
        return result

    return self._transaction(action)
