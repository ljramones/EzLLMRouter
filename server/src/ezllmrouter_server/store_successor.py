"""SQLiteStore successor records; lifecycle/transaction ownership stays on the store."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import cast
from collections.abc import Callable
from .database import Database
from .records import Record as Record
from .formatting import money, utc_timestamp
from .repositories import store as _queries
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .store import SQLiteStore, SendAllowance
    from . import store as _api


def successor_create(
    self: SQLiteStore, record: _api.Record, reserve: _api.Reserve | None = None
) -> None:
    """Add a distinct wire-0.3 row without rewriting legacy submissions."""
    from . import store as _api

    def action() -> None:
        self._claim_work_in_tx(record["work_key"], "0.3", record["submission_id"])
        if reserve is not None:
            reserve(self.database, record)
        self.database.execute(
            _queries.ACTION_INSERT_DEV12_SUBMISSIONS,
            (
                record["submission_id"],
                record["work_key"]["principal_id"],
                _api.encode(record["work_key"]),
                record["work_digest"],
                _api.encode(record),
            ),
        )

    self._transaction(action)


def successor_get(self: SQLiteStore, submission_id: str) -> _api.Record | None:
    from . import store as _api

    with self._lock:
        row = self.database.execute(
            _queries.SUCCESSOR_GET_SELECT_DEV12_SUBMISSIONS, (submission_id,)
        ).fetchone()
        return _api.decode_record(row[0]) if row else None


def successor_by_work(self: SQLiteStore, key: _api.Record) -> _api.Record | None:
    from . import store as _api

    with self._lock:
        row = self.database.execute(
            _queries.SUCCESSOR_BY_WORK_SELECT_DEV12_SUBMISSIONS,
            (key["principal_id"], _api.encode(key)),
        ).fetchone()
        return _api.decode_record(row[0]) if row else None


def successor_append_evidence(
    self: SQLiteStore, submission_id: str, event_kind: str, observed_at: str, evidence: _api.Record
) -> None:
    """Later assessments and observations append; admitted bytes stay immutable."""
    from . import store as _api

    def action() -> None:
        if not self.database.execute(
            _queries.SUCCESSOR_SUBMISSION_EXISTS, (submission_id,)
        ).fetchone():
            raise KeyError(submission_id)
        self.database.execute(
            _queries.ACTION_INSERT_DEV12_EVIDENCE_EVENTS,
            (submission_id, event_kind, observed_at, _api.encode(evidence)),
        )

    self._transaction(action)


def successor_update(
    self: SQLiteStore,
    submission_id: str,
    fields: _api.Record,
    observed_at: str,
    *,
    on_update: Callable[[Database], None] | None = None,
) -> _api.Record:
    from . import store as _api

    allowed = {
        "submission_state",
        "dispatch_state",
        "delivery_state",
        "candidate_access",
        "result",
        "failure",
        "failure_stage",
        "exposure_state",
        "result_available_at",
    }
    if set(fields) - allowed:
        raise ValueError("immutable successor field")

    def action() -> _api.Record:
        row = self.database.execute(
            _queries.SUCCESSOR_GET_SELECT_DEV12_SUBMISSIONS, (submission_id,)
        ).fetchone()
        if not row:
            raise KeyError(submission_id)
        record = _api.decode_record(row[0])
        record.update(fields)
        record["status_revision"] += 1
        record["updated_at"] = observed_at
        self.database.execute(
            _queries.ACTION_UPDATE_DEV12_SUBMISSIONS, (_api.encode(record), submission_id)
        )
        if on_update is not None:
            on_update(self.database)
        return record

    return self._transaction(action)


def successor_guard_commit(
    self: SQLiteStore,
    submission_id: str,
    attempt_id: str,
    receipt: _api.Record,
    observed_at: str,
    allowance: SendAllowance,
) -> None:
    """Durably claim the one final first-write authority for a guarded attempt."""
    from . import store as _api

    def action() -> None:
        row = self.database.execute(
            _queries.SUCCESSOR_GET_SELECT_DEV12_SUBMISSIONS, (submission_id,)
        ).fetchone()
        if not row:
            raise KeyError(submission_id)
        record = _api.decode_record(row[0])
        if (
            record["attempt_id"] != attempt_id
            or receipt.get("attempt_id") != attempt_id
            or receipt.get("plan_id") != record["signed_plan"]["plan_id"]
            or (receipt.get("work_digest") != record["work_digest"])
        ):
            raise ValueError("unbound final guard receipt")
        allowance.mark_possible_send(attempt_id, db=self.database)
        self.database.execute(
            _queries.ACTION_INSERT_DEV12_SEND_OWNERSHIP,
            (attempt_id, submission_id, observed_at, _api.encode(receipt)),
        )
        self.database.execute(
            _queries.ACTION_INSERT_DEV12_EVIDENCE_EVENTS,
            (submission_id, "guard_committed", observed_at, _api.encode(receipt)),
        )
        record["dispatch_state"] = "committed"
        record["status_revision"] += 1
        record["updated_at"] = observed_at
        self.database.execute(
            _queries.ACTION_UPDATE_DEV12_SUBMISSIONS, (_api.encode(record), submission_id)
        )

    self._transaction(action)


def successor_append_usage(
    self: SQLiteStore,
    submission_id: str,
    usage: _api.Record,
    observed_at: str,
    *,
    write_allowed: bool,
    on_settlement: Callable[[Database, str], None] | None = None,
    receipt_event: _api.Record | None = None,
) -> str:
    """Replace the effective contribution once, using the actual stored predecessor.

    No offline 32-row bound is imposed on durable product history.
    """
    from . import store as _api
    from .successor_contract import canonical, usage_valid

    def action() -> str:
        row = self.database.execute(
            _queries.SUCCESSOR_GET_SELECT_DEV12_SUBMISSIONS, (submission_id,)
        ).fetchone()
        if not row:
            raise KeyError(submission_id)
        record = _api.decode_record(row[0])
        if not write_allowed:
            raise PermissionError("native usage write denied")
        attempt_id = record["attempt_id"]
        if usage.get("attempt_id") != attempt_id:
            raise ValueError("foreign attempt")
        ordinal = usage.get("revision")
        prior_same = self.database.execute(
            _queries.ACTION_SELECT_DEV12_USAGE_REVISIONS, (attempt_id, ordinal)
        ).fetchone()
        if prior_same:
            if canonical(_api.decode_record(prior_same[0])) == canonical(usage):
                return "duplicate"
            raise ValueError("conflicting native revision")
        latest = self.database.execute(
            _queries.LATEST_SUCCESSOR_USAGE_REVISION, (attempt_id,)
        ).fetchone()
        last = cast(int, latest[0]) if latest else None
        if (
            type(ordinal) is not int
            or ordinal != (last or 0) + 1
            or (last is None and "previous_revision" in usage)
            or (last is not None and usage.get("previous_revision") != last)
        ):
            raise ValueError("stale or fabricated native predecessor")
        reservation = record["reservation"]
        if not usage_valid(
            usage,
            record["request"],
            attempt_id,
            reservation["price_ref"],
            reservation["usage_ref"],
            reservation["max_exposure_decimal"],
        ):
            raise ValueError("native revision violates admitted scope")
        self.database.execute(
            _queries.ACTION_INSERT_DEV12_USAGE_REVISIONS,
            (attempt_id, ordinal, submission_id, _api.encode(usage)),
        )
        if receipt_event is not None:
            self.database.execute(
                _queries.ACTION_INSERT_DEV12_EVIDENCE_EVENTS,
                (
                    submission_id,
                    "late_receiver_receipt_collected",
                    observed_at,
                    _api.encode(receipt_event),
                ),
            )
        self.database.execute(
            _queries.ACTION_INSERT_DEV12_EVIDENCE_EVENTS,
            (submission_id, "native_usage_accepted", observed_at, _api.encode(usage)),
        )
        record["effective_usage_revision"] = ordinal
        record["settlement_state"] = usage["cost_status"]
        record["exposure_state"] = (
            "outstanding"
            if usage["cost_status"] == "unknown"
            else "over_bound"
            if usage["cost_status"] == "over_bound"
            else "settled"
        )
        record["status_revision"] += 1
        record["updated_at"] = observed_at
        self.database.execute(
            _queries.ACTION_UPDATE_DEV12_SUBMISSIONS, (_api.encode(record), submission_id)
        )
        if on_settlement is not None:
            on_settlement(self.database, usage["cost_status"])
        return "accepted"

    return self._transaction(action)


def successor_latest_usage(self: SQLiteStore, attempt_id: str) -> _api.Record | None:
    from . import store as _api

    with self._lock:
        row = self.database.execute(
            _queries.SUCCESSOR_LATEST_USAGE_SELECT_DEV12_USAGE_REVISIONS, (attempt_id,)
        ).fetchone()
        return _api.decode_record(row[0]) if row else None


def successor_totals(self: SQLiteStore, principal_id: str) -> _api.Record:
    """Direct expenditure counts each distinct attempt's latest revision once."""
    from . import store as _api
    from decimal import Decimal

    with self._lock:
        rows = self.database.execute(
            _queries.SUCCESSOR_TOTALS_SELECT_DEV12_SUBMISSIONS, (principal_id,)
        ).fetchall()
    known = Decimal(0)
    unknown = 0
    for _record, raw in rows:
        usage = _api.decode_record(raw) if raw else None
        if usage is None or usage["cost_status"] == "unknown":
            unknown += 1
        else:
            known += Decimal(usage["amount_decimal"])
    return {
        "known_amount_decimal": money(known.quantize(Decimal("0.000000001"))),
        "unknown_attempts": unknown,
        "distinct_attempts": len(rows),
    }


def successor_expire_results(self: SQLiteStore, now: str) -> list[str]:
    """Explicit maintenance sweep; status GET itself remains read only.

    Only result content is removed. Immutable admission, dispatch, native
    revisions, settlement and exposure retain their original evidence.
    """
    from . import store as _api

    instant = datetime.fromisoformat(now.replace("Z", "+00:00"))
    cutoff = utc_timestamp(instant - timedelta(days=7) + timedelta(seconds=1))

    def candidates() -> list[tuple[str, _api.Record]]:
        found = []
        for sid, raw in self.database.execute(_queries.ACTION_SELECT_DEV12_SUBMISSIONS, (cutoff,)):
            record = _api.decode_record(raw)
            origin = datetime.fromisoformat(record["result_available_at"].replace("Z", "+00:00"))
            if origin + timedelta(days=7) <= instant:
                found.append((cast(str, sid), record))
        return found

    with self.database.read():
        if not candidates():
            return []

    def action() -> list[str]:
        expired = []
        for sid, record in candidates():
            record.pop("result", None)
            record["candidate_access"] = "expired"
            record["updated_at"] = now
            record["status_revision"] += 1
            self.database.execute(
                _queries.ACTION_UPDATE_DEV12_SUBMISSIONS, (_api.encode(record), sid)
            )
            expired.append(sid)
        return expired

    return self.database.transaction(action)
