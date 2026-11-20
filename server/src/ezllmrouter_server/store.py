"""Replaceable local store boundary; SQLite is DEV-01 only."""

from __future__ import annotations
import json
import sqlite3
import threading
import uuid
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, NoReturn, Protocol, TypeAlias, TypeVar, cast
from collections.abc import Callable, Iterator
from .database import Database
from .records import Record as Record
from .instance_lock import InstanceLease
from .formatting import earliest_timestamp, money, utc_timestamp
from .repositories import store as _queries
from .states import DispatchState, SubmissionState


def encode(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


Reserve: TypeAlias = Callable[[Database, Record], object]
T = TypeVar("T")


class SendAllowance(Protocol):
    def mark_possible_send(self, attempt_id: str, *, db: Database) -> object: ...


def decode_record(raw: object) -> Record:
    return cast(Record, json.loads(cast(str, raw)))


class Store(Protocol):
    database: Database
    path: str

    def work_owner(self, key: Record) -> Record | None: ...

    def close(self) -> None: ...

    def successor_create(self, record: Record, reserve: Reserve | None = None) -> None: ...

    def successor_get(self, submission_id: str) -> Record | None: ...

    def successor_by_work(self, key: Record) -> Record | None: ...

    def successor_append_evidence(
        self, submission_id: str, event_kind: str, observed_at: str, evidence: Record
    ) -> None: ...

    def successor_update(
        self,
        submission_id: str,
        fields: Record,
        observed_at: str,
        *,
        on_update: Callable[[Database], None] | None = None,
    ) -> Record: ...

    def successor_guard_commit(
        self,
        submission_id: str,
        attempt_id: str,
        receipt: Record,
        observed_at: str,
        allowance: SendAllowance,
    ) -> None: ...

    def successor_append_usage(
        self,
        submission_id: str,
        usage: Record,
        observed_at: str,
        *,
        write_allowed: bool,
        on_settlement: Callable[[Database, str], None] | None = None,
        receipt_event: Record | None = None,
    ) -> str: ...

    def successor_latest_usage(self, attempt_id: str) -> Record | None: ...

    def successor_totals(self, principal_id: str) -> Record: ...

    def successor_expire_results(self, now: str) -> list[str]: ...

    def create(self, record: Record, reserve: Reserve | None = None) -> None: ...

    def intent(self, submission_id: str, attempt_id: str, intent: Record) -> None: ...

    def guard_commit(self, submission_id: str, attempt_id: str, receipt: Record) -> None: ...

    def guard_record(self, attempt_id: str) -> Record | None: ...

    def update(self, submission_id: str, fields: Record, usage: Record | None = None) -> Record: ...

    def mark_wait_expired_no_store(self, submission_id: str, at: str) -> Record: ...

    def complete_candidate(
        self,
        submission_id: str,
        candidate: Record,
        usage: Record | None,
        raw_usage_digest: str | None,
        current_allowed: bool,
        current_expiry: str | None,
        at: str,
        live_source_tags: list[str] | None = None,
    ) -> Record: ...

    def get(self, submission_id: str) -> Record | None: ...

    def by_work(self, key: Record) -> Record | None: ...

    def has_authorized_tool_call(
        self,
        principal_id: str,
        task_id: str,
        source_authority_id: str,
        context_id: str,
        block: Record,
        live_source_tag: str,
    ) -> bool: ...

    def intent_count(self, submission_id: str) -> int: ...


class SQLiteStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        self._lease = InstanceLease(self.path, exclusive=self.path != ":memory:", create=True)
        connection = None
        try:
            connection = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
            self.db = connection
            self._lease.verify()
        except BaseException:
            try:
                if connection is not None:
                    connection.close()
            finally:
                self._lease.close()
            raise
        self._init_readers()
        self.database = Database(self.db, self._lock, self._transaction, self._snapshot)
        from .schema import initialize

        try:
            initialize(self.db)
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute("PRAGMA foreign_keys=ON")
        except BaseException:
            self.close()
            raise

    def work_owner(self, key: Record) -> Record | None:
        with self._lock:
            row = self.database.execute(
                _queries.WORK_OWNER_SELECT_WORK_KEY_OWNERS, (key["principal_id"], encode(key))
            ).fetchone()
            return {"contract_version": row[0], "submission_id": row[1]} if row else None

    def _claim_work_in_tx(self, key: Record, version: str, submission_id: str) -> None:
        self.database.execute(
            _queries.CLAIM_WORK_IN_TX_INSERT_WORK_KEY_OWNERS,
            (key["principal_id"], encode(key), version, submission_id),
        )

    @classmethod
    def open_existing(
        cls, path: str | Path, *, read_only: bool = False, maintenance: bool = False
    ) -> SQLiteStore:
        """Open for offline maintenance without creating a database or running schema setup."""
        result = cls.__new__(cls)
        result.path = str(path)
        result._lock = threading.RLock()
        result._init_readers()
        result._lease = InstanceLease(path, exclusive=maintenance or not read_only)
        connection = None
        try:
            connection = sqlite3.connect(
                Path(path).as_uri() + ("?mode=ro" if read_only else "?mode=rw"),
                uri=True,
                check_same_thread=False,
                isolation_level=None,
            )
            result.db = connection
            result._lease.verify()
        except BaseException:
            try:
                if connection is not None:
                    connection.close()
            finally:
                result._lease.close()
            raise
        try:
            result.db.execute("PRAGMA synchronous=FULL")
            result.db.execute("PRAGMA foreign_keys=ON")
            from .schema import validate

            validate(result.db)
        except BaseException:
            result.close()
            raise
        result.database = Database(result.db, result._lock, result._transaction, result._snapshot)
        return result

    def _init_readers(self) -> None:
        self._readers_changed = threading.Condition()
        self._readers: set[sqlite3.Connection] = set()
        self._closing = False

    @contextmanager
    def _snapshot(self) -> Iterator[Database]:
        if self.path == ":memory:":
            with self.database.read() as db:
                yield db
            return
        with self._readers_changed:
            if self._closing or len(self._readers) >= 4:
                raise RuntimeError("report reader unavailable")
            connection = sqlite3.connect(
                Path(self.path).resolve().as_uri() + "?mode=ro",
                uri=True,
                check_same_thread=False,
                isolation_level=None,
                timeout=1,
            )
            self._readers.add(connection)
        deadline = time.monotonic() + 10
        connection.set_progress_handler(lambda: time.monotonic() >= deadline, 1000)

        def no_write(action: Callable[[], object]) -> NoReturn:
            raise RuntimeError("read-only reporting snapshot")

        db = Database(connection, threading.RLock(), no_write)
        try:
            with db.read():
                yield db
        finally:
            with self._readers_changed:
                connection.close()
                self._readers.remove(connection)
                self._readers_changed.notify_all()

    def close(self) -> None:
        with self._readers_changed:
            self._closing = True
            for connection in self._readers:
                connection.interrupt()
            if not self._readers_changed.wait_for(lambda: not self._readers, timeout=5):
                raise RuntimeError("report readers did not stop; database lease retained")
        try:
            with self._lock:
                self.db.close()
        finally:
            self._lease.close()

    def successor_create(self, record: Record, reserve: Reserve | None = None) -> None:
        """Add a distinct wire-0.3 row without rewriting legacy submissions."""

        def action() -> None:
            self._claim_work_in_tx(record["work_key"], "0.3", record["submission_id"])
            if reserve is not None:
                reserve(self.database, record)
            self.database.execute(
                _queries.ACTION_INSERT_DEV12_SUBMISSIONS,
                (
                    record["submission_id"],
                    record["work_key"]["principal_id"],
                    encode(record["work_key"]),
                    record["work_digest"],
                    encode(record),
                ),
            )

        self._transaction(action)

    def successor_get(self, submission_id: str) -> Record | None:
        with self._lock:
            row = self.database.execute(
                _queries.SUCCESSOR_GET_SELECT_DEV12_SUBMISSIONS, (submission_id,)
            ).fetchone()
            return decode_record(row[0]) if row else None

    def successor_by_work(self, key: Record) -> Record | None:
        with self._lock:
            row = self.database.execute(
                _queries.SUCCESSOR_BY_WORK_SELECT_DEV12_SUBMISSIONS,
                (key["principal_id"], encode(key)),
            ).fetchone()
            return decode_record(row[0]) if row else None

    def successor_append_evidence(
        self, submission_id: str, event_kind: str, observed_at: str, evidence: Record
    ) -> None:
        """Later assessments and observations append; admitted bytes stay immutable."""

        def action() -> None:
            if not self.database.execute(
                _queries.SUCCESSOR_SUBMISSION_EXISTS, (submission_id,)
            ).fetchone():
                raise KeyError(submission_id)
            self.database.execute(
                _queries.ACTION_INSERT_DEV12_EVIDENCE_EVENTS,
                (submission_id, event_kind, observed_at, encode(evidence)),
            )

        self._transaction(action)

    def successor_update(
        self,
        submission_id: str,
        fields: Record,
        observed_at: str,
        *,
        on_update: Callable[[Database], None] | None = None,
    ) -> Record:
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

        def action() -> Record:
            row = self.database.execute(
                _queries.SUCCESSOR_GET_SELECT_DEV12_SUBMISSIONS, (submission_id,)
            ).fetchone()
            if not row:
                raise KeyError(submission_id)
            record = decode_record(row[0])
            record.update(fields)
            record["status_revision"] += 1
            record["updated_at"] = observed_at
            self.database.execute(
                _queries.ACTION_UPDATE_DEV12_SUBMISSIONS, (encode(record), submission_id)
            )
            if on_update is not None:
                on_update(self.database)
            return record

        return self._transaction(action)

    def successor_guard_commit(
        self,
        submission_id: str,
        attempt_id: str,
        receipt: Record,
        observed_at: str,
        allowance: SendAllowance,
    ) -> None:
        """Durably claim the one final first-write authority for a guarded attempt."""

        def action() -> None:
            row = self.database.execute(
                _queries.SUCCESSOR_GET_SELECT_DEV12_SUBMISSIONS, (submission_id,)
            ).fetchone()
            if not row:
                raise KeyError(submission_id)
            record = decode_record(row[0])
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
                (attempt_id, submission_id, observed_at, encode(receipt)),
            )
            self.database.execute(
                _queries.ACTION_INSERT_DEV12_EVIDENCE_EVENTS,
                (submission_id, "guard_committed", observed_at, encode(receipt)),
            )
            record["dispatch_state"] = "committed"
            record["status_revision"] += 1
            record["updated_at"] = observed_at
            self.database.execute(
                _queries.ACTION_UPDATE_DEV12_SUBMISSIONS, (encode(record), submission_id)
            )

        self._transaction(action)

    def successor_append_usage(
        self,
        submission_id: str,
        usage: Record,
        observed_at: str,
        *,
        write_allowed: bool,
        on_settlement: Callable[[Database, str], None] | None = None,
        receipt_event: Record | None = None,
    ) -> str:
        """Replace the effective contribution once, using the actual stored predecessor.

        No offline 32-row bound is imposed on durable product history.
        """
        from .successor_contract import canonical, usage_valid

        def action() -> str:
            row = self.database.execute(
                _queries.SUCCESSOR_GET_SELECT_DEV12_SUBMISSIONS, (submission_id,)
            ).fetchone()
            if not row:
                raise KeyError(submission_id)
            record = decode_record(row[0])
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
                if canonical(decode_record(prior_same[0])) == canonical(usage):
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
                (attempt_id, ordinal, submission_id, encode(usage)),
            )
            if receipt_event is not None:
                self.database.execute(
                    _queries.ACTION_INSERT_DEV12_EVIDENCE_EVENTS,
                    (
                        submission_id,
                        "late_receiver_receipt_collected",
                        observed_at,
                        encode(receipt_event),
                    ),
                )
            self.database.execute(
                _queries.ACTION_INSERT_DEV12_EVIDENCE_EVENTS,
                (submission_id, "native_usage_accepted", observed_at, encode(usage)),
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
                _queries.ACTION_UPDATE_DEV12_SUBMISSIONS, (encode(record), submission_id)
            )
            if on_settlement is not None:
                on_settlement(self.database, usage["cost_status"])
            return "accepted"

        return self._transaction(action)

    def successor_latest_usage(self, attempt_id: str) -> Record | None:
        with self._lock:
            row = self.database.execute(
                _queries.SUCCESSOR_LATEST_USAGE_SELECT_DEV12_USAGE_REVISIONS, (attempt_id,)
            ).fetchone()
            return decode_record(row[0]) if row else None

    def successor_totals(self, principal_id: str) -> Record:
        """Direct expenditure counts each distinct attempt's latest revision once."""
        from decimal import Decimal

        with self._lock:
            rows = self.database.execute(
                _queries.SUCCESSOR_TOTALS_SELECT_DEV12_SUBMISSIONS, (principal_id,)
            ).fetchall()
        known = Decimal(0)
        unknown = 0
        for _record, raw in rows:
            usage = decode_record(raw) if raw else None
            if usage is None or usage["cost_status"] == "unknown":
                unknown += 1
            else:
                known += Decimal(usage["amount_decimal"])
        return {
            "known_amount_decimal": money(known.quantize(Decimal("0.000000001"))),
            "unknown_attempts": unknown,
            "distinct_attempts": len(rows),
        }

    def successor_expire_results(self, now: str) -> list[str]:
        """Explicit maintenance sweep; status GET itself remains read only.

        Only result content is removed. Immutable admission, dispatch, native
        revisions, settlement and exposure retain their original evidence.
        """
        instant = datetime.fromisoformat(now.replace("Z", "+00:00"))
        cutoff = utc_timestamp(instant - timedelta(days=7) + timedelta(seconds=1))

        def candidates() -> list[tuple[str, Record]]:
            found = []
            for sid, raw in self.database.execute(
                _queries.ACTION_SELECT_DEV12_SUBMISSIONS, (cutoff,)
            ):
                record = decode_record(raw)
                origin = datetime.fromisoformat(
                    record["result_available_at"].replace("Z", "+00:00")
                )
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
                    _queries.ACTION_UPDATE_DEV12_SUBMISSIONS, (encode(record), sid)
                )
                expired.append(sid)
            return expired

        return self.database.transaction(action)

    def _rollback_preserving_error(self, error: BaseException) -> bool:
        try:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            return not self.db.in_transaction
        except sqlite3.Error as cleanup:
            error.add_note("rollback failed: " + type(cleanup).__name__)
            return False

    def _transaction(self, action: Callable[[], T]) -> T:
        with self._lock:
            if self.db.in_transaction:
                savepoint = "nested_" + uuid.uuid4().hex
                self.db.execute(f"SAVEPOINT {savepoint}")
                try:
                    result = action()
                except BaseException as exc:
                    if self.db.in_transaction:
                        try:
                            self.db.execute(f"ROLLBACK TO {savepoint}")
                            self.db.execute(f"RELEASE {savepoint}")
                        except sqlite3.Error as cleanup:
                            exc.add_note("nested rollback failed: " + type(cleanup).__name__)
                            self._rollback_preserving_error(exc)
                    raise
                self.db.execute(f"RELEASE {savepoint}")
                return result
            self.db.execute("BEGIN IMMEDIATE")
            try:
                result = action()
            except BaseException as exc:
                rolled_back = self._rollback_preserving_error(exc)
                try:
                    cast(Any, exc).ezllmrouter_definite_rollback = rolled_back
                except (AttributeError, TypeError):
                    pass
                raise
            try:
                self.db.execute("COMMIT")
            except BaseException as exc:
                self._rollback_preserving_error(exc)
                raise
            return result

    def create(self, record: Record, reserve: Reserve | None = None) -> None:
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
                    encode(record["work_key"]),
                    record["work_digest"],
                    encode(record),
                ),
            )

        self._transaction(action)

    def intent(self, submission_id: str, attempt_id: str, intent: Record) -> None:
        def action() -> None:
            self.database.execute(
                _queries.ACTION_INSERT_INTENTS, (attempt_id, submission_id, encode(intent))
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

    def guard_commit(self, submission_id: str, attempt_id: str, receipt: Record) -> None:
        """Durable, single-use final-request acknowledgement before lower send."""

        def action() -> None:
            row = self.database.execute(
                _queries.UPDATE_IN_TX_SELECT_SUBMISSIONS, (submission_id,)
            ).fetchone()
            preparatory = self.database.execute(
                _queries.ACTION_SELECT_INTENTS, (submission_id, attempt_id)
            ).fetchone()
            if not row or decode_record(row[0])["attempt_id"] != attempt_id or (not preparatory):
                raise ValueError("unadmitted guard attempt")
            bound = decode_record(preparatory[0])
            if (
                receipt.get("attempt_id") != attempt_id
                or receipt.get("plan_id") != bound.get("plan_id")
                or receipt.get("work_digest") != bound.get("work_digest")
            ):
                raise ValueError("guard receipt does not match preparatory intent")
            self.database.execute(
                _queries.ACTION_INSERT_GUARD_DISPATCHES,
                (attempt_id, submission_id, encode(receipt)),
            )

        self._transaction(action)

    def guard_record(self, attempt_id: str) -> Record | None:
        with self._lock:
            row = self.database.execute(
                _queries.GUARD_RECORD_SELECT_GUARD_DISPATCHES, (attempt_id,)
            ).fetchone()
            return decode_record(row[0]) if row else None

    def _update_in_tx(self, submission_id: str, fields: Record) -> Record:
        row = self.database.execute(
            _queries.UPDATE_IN_TX_SELECT_SUBMISSIONS, (submission_id,)
        ).fetchone()
        if not row:
            raise KeyError(submission_id)
        record = decode_record(row[0])
        record.update(fields)
        record["status_revision"] += 1
        self.database.execute(
            _queries.UPDATE_IN_TX_UPDATE_SUBMISSIONS, (encode(record), submission_id)
        )
        return record

    def _append_usage_in_tx(self, submission_id: str, attempt_id: str, usage: Record) -> Record:
        """Append to the attempt ledger inside the caller's publishing transaction."""
        row = self.database.execute(
            _queries.ACTION_SELECT_USAGE_REVISIONS, (attempt_id,)
        ).fetchone()
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
            (attempt_id, revision, submission_id, encode(revision_data)),
        )
        return {"state": "available", "revision": revision_data}

    def update(self, submission_id: str, fields: Record, usage: Record | None = None) -> Record:
        new_fields = dict(fields)

        def action() -> Record:
            latest_usage: Record = {"state": "not_recorded"}
            if usage is not None:
                row = self.database.execute(
                    _queries.UPDATE_IN_TX_SELECT_SUBMISSIONS, (submission_id,)
                ).fetchone()
                if not row:
                    raise KeyError(submission_id)
                attempt_id = decode_record(row[0])["attempt_id"]
                latest_usage = self._append_usage_in_tx(submission_id, attempt_id, usage)
            elif "candidate" in new_fields and new_fields["candidate"] is not None:
                row = self.database.execute(
                    _queries.UPDATE_IN_TX_SELECT_SUBMISSIONS, (submission_id,)
                ).fetchone()
                if not row:
                    raise KeyError(submission_id)
                attempt_id = decode_record(row[0])["attempt_id"]
                prior = self.database.execute(_queries.LATEST_USAGE, (attempt_id,)).fetchone()
                if prior:
                    latest_usage = {"state": "available", "revision": decode_record(prior[0])}
            if "candidate" in new_fields and new_fields["candidate"] is not None:
                new_fields["candidate"] = {**new_fields["candidate"], "usage": latest_usage}
            return self._update_in_tx(submission_id, new_fields)

        return self._transaction(action)

    def mark_wait_expired_no_store(self, submission_id: str, at: str) -> Record:
        def action() -> Record:
            row = self.database.execute(
                _queries.UPDATE_IN_TX_SELECT_SUBMISSIONS, (submission_id,)
            ).fetchone()
            if not row:
                raise KeyError(submission_id)
            record = decode_record(row[0])
            fields: Record = {"wait_expired_no_store": True, "updated_at": at}
            if record["submission_state"] == "completed":
                fields.update(
                    candidate=None,
                    candidate_access="not_retained",
                    result_unavailable_reason="wait_expired_no_store",
                )
            return self._update_in_tx(submission_id, fields)

        return self._transaction(action)

    def complete_candidate(
        self,
        submission_id: str,
        candidate: Record,
        usage: Record | None,
        raw_usage_digest: str | None,
        current_allowed: bool,
        current_expiry: str | None,
        at: str,
        live_source_tags: list[str] | None = None,
    ) -> Record:
        def action() -> Record:
            row = self.database.execute(
                _queries.UPDATE_IN_TX_SELECT_SUBMISSIONS, (submission_id,)
            ).fetchone()
            if not row:
                raise KeyError(submission_id)
            record = decode_record(row[0])
            if record["submission_state"] == "completed":
                raise ValueError("candidate already completed")
            expiry = earliest_timestamp(record.get("content_expires_at"), current_expiry)
            expired = bool(
                expiry
                and datetime.fromisoformat(expiry.replace("Z", "+00:00"))
                <= datetime.now(timezone.utc)
            )
            retain = bool(
                record["content_store_allowed"]
                and current_allowed
                and (not record["wait_expired_no_store"])
                and (not expired)
            )
            latest_usage: Record = {"state": "not_recorded"}
            if usage is not None:
                attempt_id = record["attempt_id"]
                latest_usage = self._append_usage_in_tx(submission_id, attempt_id, usage)
            else:
                prior = self.database.execute(
                    _queries.LATEST_USAGE, (record["attempt_id"],)
                ).fetchone()
                if prior:
                    latest_usage = {"state": "available", "revision": decode_record(prior[0])}
            fields: Record = {
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

    def get(self, submission_id: str) -> Record | None:
        def load() -> Record | None:
            row = self.database.execute(
                _queries.UPDATE_IN_TX_SELECT_SUBMISSIONS, (submission_id,)
            ).fetchone()
            if not row:
                return None
            return decode_record(row[0])

        def with_usage(record: Record | None) -> Record | None:
            if record is None:
                return None
            usage = self.database.execute(_queries.LATEST_USAGE, (record["attempt_id"],)).fetchone()
            record["usage"] = (
                {"state": "available", "revision": decode_record(usage[0])}
                if usage
                else {"state": "not_recorded"}
            )
            return record

        def expired(record: Record | None) -> bool:
            expiry = record.get("content_expires_at") if record else None
            return bool(
                record
                and record.get("candidate")
                and expiry
                and (
                    datetime.fromisoformat(expiry.replace("Z", "+00:00"))
                    <= datetime.now(timezone.utc)
                )
            )

        with self.database.read():
            record = load()
            if not expired(record):
                return with_usage(record)

        def expire() -> Record | None:
            record = load()
            if record is not None and expired(record):
                record["candidate"] = None
                record["candidate_access"] = "expired"
                record["status_revision"] += 1
                record["updated_at"] = utc_timestamp(datetime.now(timezone.utc))
                self.database.execute(
                    _queries.UPDATE_IN_TX_UPDATE_SUBMISSIONS, (encode(record), submission_id)
                )
            return with_usage(record)

        return self.database.transaction(expire)

    def by_work(self, key: Record) -> Record | None:
        with self._lock:
            row = self.database.execute(
                _queries.BY_WORK_SELECT_SUBMISSIONS, (key["principal_id"], encode(key))
            ).fetchone()
        return self.get(cast(str, row[0])) if row else None

    def has_authorized_tool_call(
        self,
        principal_id: str,
        task_id: str,
        source_authority_id: str,
        context_id: str,
        block: Record,
        live_source_tag: str,
    ) -> bool:
        """Verify retained content or a delivered live block tag in the authenticated scope."""
        with self._lock:
            rows = self.database.execute(
                _queries.HAS_AUTHORIZED_TOOL_CALL_SELECT_SUBMISSIONS, (principal_id, task_id)
            ).fetchall()
        for (raw,) in rows:
            record = decode_record(raw)
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

    def intent_count(self, submission_id: str) -> int:
        with self._lock:
            row = self.database.execute(
                _queries.INTENT_COUNT_SELECT_INTENTS, (submission_id,)
            ).fetchone()
            if row is None:
                raise RuntimeError("intent count missing")
            return cast(int, row[0])


def _check_store_contract(store: SQLiteStore) -> Store:
    return store
