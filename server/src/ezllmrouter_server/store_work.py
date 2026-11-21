"""SQLiteStore work records; lifecycle/transaction ownership stays on the store."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import cast
from .records import Record as Record
from .formatting import utc_timestamp
from .repositories import store as _queries
from .states import DispatchState, SubmissionState
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .store import SQLiteStore
    from . import store as _api


def work_owner(self: SQLiteStore, key: _api.Record) -> _api.Record | None:
    from . import store as _api

    with self._lock:
        row = self.database.execute(
            _queries.WORK_OWNER_SELECT_WORK_KEY_OWNERS, (key["principal_id"], _api.encode(key))
        ).fetchone()
        return {"contract_version": row[0], "submission_id": row[1]} if row else None


def _claim_work_in_tx(
    self: SQLiteStore, key: _api.Record, version: str, submission_id: str
) -> None:
    from . import store as _api

    self.database.execute(
        _queries.CLAIM_WORK_IN_TX_INSERT_WORK_KEY_OWNERS,
        (key["principal_id"], _api.encode(key), version, submission_id),
    )


def create(self: SQLiteStore, record: _api.Record, reserve: _api.Reserve | None = None) -> None:
    from . import store as _api

    def action() -> None:
        self._claim_work_in_tx(record["work_key"], "0.2", record["submission_id"])
        if reserve is not None:
            record["campaign"] = reserve(self.database, record)
        self.database.execute(
            _queries.ACTION_INSERT_SUBMISSIONS,
            (
                record["submission_id"],
                record["principal_id"],
                record["task_id"],
                _api.encode(record["work_key"]),
                record["work_digest"],
                _api.encode(record),
            ),
        )

    self._transaction(action)


def intent(self: SQLiteStore, submission_id: str, attempt_id: str, intent: _api.Record) -> None:
    from . import store as _api

    def action() -> None:
        self.database.execute(
            _queries.ACTION_INSERT_INTENTS, (attempt_id, submission_id, _api.encode(intent))
        )
        self._update_in_tx(
            submission_id,
            {
                "submission_state": SubmissionState.ADMITTED.value,
                "dispatch_state": DispatchState.INTENT_PERSISTED.value,
                "attempt_revision": 2,
            },
        )

    self._transaction(action)


def guard_commit(
    self: SQLiteStore, submission_id: str, attempt_id: str, receipt: _api.Record
) -> None:
    """Durable, single-use final-request acknowledgement before lower send."""
    from . import store as _api

    def action() -> None:
        row = self.database.execute(
            _queries.UPDATE_IN_TX_SELECT_SUBMISSIONS, (submission_id,)
        ).fetchone()
        preparatory = self.database.execute(
            _queries.ACTION_SELECT_INTENTS, (submission_id, attempt_id)
        ).fetchone()
        if not row or _api.decode_record(row[0])["attempt_id"] != attempt_id or (not preparatory):
            raise ValueError("unadmitted guard attempt")
        bound = _api.decode_record(preparatory[0])
        if (
            receipt.get("attempt_id") != attempt_id
            or receipt.get("plan_id") != bound.get("plan_id")
            or receipt.get("work_digest") != bound.get("work_digest")
        ):
            raise ValueError("guard receipt does not match preparatory intent")
        self.database.execute(
            _queries.ACTION_INSERT_GUARD_DISPATCHES,
            (attempt_id, submission_id, _api.encode(receipt)),
        )

    self._transaction(action)


def guard_record(self: SQLiteStore, attempt_id: str) -> _api.Record | None:
    from . import store as _api

    with self._lock:
        row = self.database.execute(
            _queries.GUARD_RECORD_SELECT_GUARD_DISPATCHES, (attempt_id,)
        ).fetchone()
        return _api.decode_record(row[0]) if row else None


def get(self: SQLiteStore, submission_id: str) -> _api.Record | None:
    from . import store as _api

    def load() -> _api.Record | None:
        row = self.database.execute(
            _queries.UPDATE_IN_TX_SELECT_SUBMISSIONS, (submission_id,)
        ).fetchone()
        if not row:
            return None
        return _api.decode_record(row[0])

    def with_usage(record: _api.Record | None) -> _api.Record | None:
        if record is None:
            return None
        usage = self.database.execute(_queries.LATEST_USAGE, (record["attempt_id"],)).fetchone()
        record["usage"] = (
            {"state": "available", "revision": _api.decode_record(usage[0])}
            if usage
            else {"state": "not_recorded"}
        )
        return record

    def expired(record: _api.Record | None) -> bool:
        expiry = record.get("content_expires_at") if record else None
        return bool(
            record
            and record.get("candidate")
            and expiry
            and (
                datetime.fromisoformat(expiry.replace("Z", "+00:00")) <= datetime.now(timezone.utc)
            )
        )

    with self.database.read():
        record = load()
        if not expired(record):
            return with_usage(record)

    def expire() -> _api.Record | None:
        record = load()
        if record is not None and expired(record):
            record["candidate"] = None
            record["candidate_access"] = "expired"
            record["status_revision"] += 1
            record["updated_at"] = utc_timestamp(datetime.now(timezone.utc))
            self.database.execute(
                _queries.UPDATE_IN_TX_UPDATE_SUBMISSIONS, (_api.encode(record), submission_id)
            )
        return with_usage(record)

    return self.database.transaction(expire)


def by_work(self: SQLiteStore, key: _api.Record) -> _api.Record | None:
    from . import store as _api

    with self._lock:
        row = self.database.execute(
            _queries.BY_WORK_SELECT_SUBMISSIONS, (key["principal_id"], _api.encode(key))
        ).fetchone()
    return self.get(cast(str, row[0])) if row else None


def has_authorized_tool_call(
    self: SQLiteStore,
    principal_id: str,
    task_id: str,
    source_authority_id: str,
    context_id: str,
    block: _api.Record,
    live_source_tag: str,
) -> bool:
    """Verify retained content or a delivered live block tag in the authenticated scope."""
    from . import store as _api

    with self._lock:
        rows = self.database.execute(
            _queries.HAS_AUTHORIZED_TOOL_CALL_SELECT_SUBMISSIONS, (principal_id, task_id)
        ).fetchall()
    for (raw,) in rows:
        record = _api.decode_record(raw)
        if (
            record.get("source_authority_id") != source_authority_id
            or record.get("context_id") != context_id
        ):
            continue
        if (
            record.get("candidate_access") == "present"
            and record.get("candidate")
            and any(
                (
                    source == block
                    for source in record["candidate"]["output_blocks"]
                    if source.get("kind") == "tool_call"
                )
            )
        ):
            return True
        if (
            record.get("delivery_state") == "candidate_delivered"
            and (not record.get("wait_expired_no_store"))
            and (live_source_tag in record.get("live_source_tags", ()))
        ):
            return True
    return False


def intent_count(self: SQLiteStore, submission_id: str) -> int:
    with self._lock:
        row = self.database.execute(
            _queries.INTENT_COUNT_SELECT_INTENTS, (submission_id,)
        ).fetchone()
        if row is None:
            raise RuntimeError("intent count missing")
        return cast(int, row[0])
