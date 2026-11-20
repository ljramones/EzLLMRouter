"""Replaceable local store boundary; SQLite is DEV-01 only."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

from .database import Database
from .instance_lock import InstanceLease
from .formatting import money, utc_timestamp
from .repositories import store as _queries
from .states import DispatchState, SubmissionState


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


class Store(Protocol):
    def create(self, record: dict, reserve=None) -> None: ...
    def intent(self, submission_id: str, attempt_id: str, intent: dict) -> None: ...
    def guard_commit(self, submission_id: str, attempt_id: str, receipt: dict) -> None: ...
    def update(self, submission_id: str, fields: dict, usage: dict | None = None) -> dict: ...
    def mark_wait_expired_no_store(self, submission_id: str, at: str) -> dict: ...
    def complete_candidate(
        self,
        submission_id: str,
        candidate: dict,
        usage: dict | None,
        raw_usage_digest: str | None,
        current_allowed: bool,
        current_expiry: str | None,
        at: str,
        live_source_tags: list[str] | None = None,
    ) -> dict: ...
    def get(self, submission_id: str) -> dict | None: ...
    def by_work(self, key: dict) -> dict | None: ...
    def has_authorized_tool_call(
        self,
        principal_id: str,
        task_id: str,
        source_authority_id: str,
        context_id: str,
        block: dict,
        live_source_tag: str,
    ) -> bool: ...


class SQLiteStore:
    def __init__(self, path: str | Path):
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
        self.database = Database(self.db, self._lock, self._transaction)
        from .schema import initialize

        try:
            initialize(self.db)
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute("PRAGMA foreign_keys=ON")
        except BaseException:
            self.close()
            raise

    def work_owner(self, key):
        with self._lock:
            row = self.database.execute(
                _queries.WORK_OWNER_SELECT_WORK_KEY_OWNERS, (key["principal_id"], encode(key))
            ).fetchone()
            return {"contract_version": row[0], "submission_id": row[1]} if row else None

    def _claim_work_in_tx(self, key, version, submission_id):
        self.database.execute(
            _queries.CLAIM_WORK_IN_TX_INSERT_WORK_KEY_OWNERS,
            (key["principal_id"], encode(key), version, submission_id),
        )

    @classmethod
    def open_existing(cls, path, *, read_only=False, maintenance=False):
        """Open for offline maintenance without creating a database or running schema setup."""
        result = cls.__new__(cls)
        result.path = str(path)
        result._lock = threading.RLock()
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
        result.database = Database(result.db, result._lock, result._transaction)
        return result

    def close(self):
        try:
            self.db.close()
        finally:
            self._lease.close()

    def successor_create(self, record, reserve=None):
        """Add a distinct wire-0.3 row without rewriting legacy submissions."""

        def action():
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

    def successor_get(self, submission_id):
        with self._lock:
            row = self.database.execute(
                _queries.SUCCESSOR_GET_SELECT_DEV12_SUBMISSIONS, (submission_id,)
            ).fetchone()
            return json.loads(row[0]) if row else None

    def successor_by_work(self, key):
        with self._lock:
            row = self.database.execute(
                _queries.SUCCESSOR_BY_WORK_SELECT_DEV12_SUBMISSIONS,
                (key["principal_id"], encode(key)),
            ).fetchone()
            return json.loads(row[0]) if row else None

    def successor_append_evidence(self, submission_id, event_kind, observed_at, evidence):
        """Later assessments and observations append; admitted bytes stay immutable."""

        def action():
            if not self.database.execute(
                _queries.ACTION_SELECT_DEV12_SUBMISSIONS_2, (submission_id,)
            ).fetchone():
                raise KeyError(submission_id)
            self.database.execute(
                _queries.ACTION_INSERT_DEV12_EVIDENCE_EVENTS,
                (submission_id, event_kind, observed_at, encode(evidence)),
            )

        self._transaction(action)

    def successor_update(self, submission_id, fields, observed_at, *, on_update=None):
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

        def action():
            row = self.database.execute(
                _queries.SUCCESSOR_GET_SELECT_DEV12_SUBMISSIONS, (submission_id,)
            ).fetchone()
            if not row:
                raise KeyError(submission_id)
            record = json.loads(row[0])
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

    def successor_guard_commit(self, submission_id, attempt_id, receipt, observed_at, allowance):
        """Durably claim the one final first-write authority for a guarded attempt."""

        def action():
            row = self.database.execute(
                _queries.SUCCESSOR_GET_SELECT_DEV12_SUBMISSIONS, (submission_id,)
            ).fetchone()
            if not row:
                raise KeyError(submission_id)
            record = json.loads(row[0])
            if (
                record["attempt_id"] != attempt_id
                or receipt.get("attempt_id") != attempt_id
                or receipt.get("plan_id") != record["signed_plan"]["plan_id"]
                or receipt.get("work_digest") != record["work_digest"]
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
        submission_id,
        usage,
        observed_at,
        *,
        write_allowed,
        on_settlement=None,
        receipt_event=None,
    ):
        """Replace the effective contribution once, using the actual stored predecessor.

        No offline 32-row bound is imposed on durable product history.
        """
        from .successor_contract import canonical, usage_valid

        def action():
            row = self.database.execute(
                _queries.SUCCESSOR_GET_SELECT_DEV12_SUBMISSIONS, (submission_id,)
            ).fetchone()
            if not row:
                raise KeyError(submission_id)
            record = json.loads(row[0])
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
                if canonical(json.loads(prior_same[0])) == canonical(usage):
                    return "duplicate"
                raise ValueError("conflicting native revision")
            latest = self.database.execute(
                _queries.ACTION_SELECT_DEV12_USAGE_REVISIONS_2, (attempt_id,)
            ).fetchone()
            last = latest[0] if latest else None
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

    def successor_latest_usage(self, attempt_id):
        with self._lock:
            row = self.database.execute(
                _queries.SUCCESSOR_LATEST_USAGE_SELECT_DEV12_USAGE_REVISIONS, (attempt_id,)
            ).fetchone()
            return json.loads(row[0]) if row else None

    def successor_totals(self, principal_id):
        """Direct expenditure counts each distinct attempt's latest revision once."""
        from decimal import Decimal

        with self._lock:
            rows = self.database.execute(
                _queries.SUCCESSOR_TOTALS_SELECT_DEV12_SUBMISSIONS, (principal_id,)
            ).fetchall()
        known = Decimal(0)
        unknown = 0
        for _record, raw in rows:
            usage = json.loads(raw) if raw else None
            if usage is None or usage["cost_status"] == "unknown":
                unknown += 1
            else:
                known += Decimal(usage["amount_decimal"])
        return {
            "known_amount_decimal": money(known.quantize(Decimal("0.000000001"))),
            "unknown_attempts": unknown,
            "distinct_attempts": len(rows),
        }

    def successor_expire_results(self, now):
        """Explicit maintenance sweep; status GET itself remains read only.

        Only result content is removed. Immutable admission, dispatch, native
        revisions, settlement and exposure retain their original evidence.
        """
        instant = datetime.fromisoformat(now.replace("Z", "+00:00"))

        # Broad indexed cutoff includes the boundary second; Python keeps the
        # exact timestamp comparison, including fractional seconds.
        cutoff = utc_timestamp(instant - timedelta(days=7) + timedelta(seconds=1))

        def candidates():
            found = []
            for sid, raw in self.database.execute(
                _queries.ACTION_SELECT_DEV12_SUBMISSIONS, (cutoff,)
            ):
                record = json.loads(raw)
                origin = datetime.fromisoformat(
                    record["result_available_at"].replace("Z", "+00:00")
                )
                if origin + timedelta(days=7) <= instant:
                    found.append((sid, record))
            return found

        with self.database.read():
            if not candidates():
                return []

        def action():
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

    def _transaction(self, action):
        with self._lock:
            if self.db.in_transaction:
                # A unique live name lets independent domains compose safely.
                savepoint = "nested_" + uuid.uuid4().hex
                self.db.execute(f"SAVEPOINT {savepoint}")
                try:
                    result = action()
                except BaseException:
                    self.db.execute(f"ROLLBACK TO {savepoint}")
                    self.db.execute(f"RELEASE {savepoint}")
                    raise
                self.db.execute(f"RELEASE {savepoint}")
                return result
            self.db.execute("BEGIN IMMEDIATE")
            try:
                result = action()
            except BaseException as exc:
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK")
                try:
                    exc.ezllmrouter_definite_rollback = True
                except (AttributeError, TypeError):
                    pass
                raise
            # A COMMIT exception may be ambiguous, even if ROLLBACK succeeds.
            try:
                self.db.execute("COMMIT")
            except BaseException:
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK")
                raise
            return result

    def create(self, record, reserve=None):
        def action():
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

    def intent(self, submission_id, attempt_id, intent):
        def action():
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

    def guard_commit(self, submission_id, attempt_id, receipt):
        """Durable, single-use final-request acknowledgement before lower send."""

        def action():
            row = self.database.execute(
                _queries.UPDATE_IN_TX_SELECT_SUBMISSIONS, (submission_id,)
            ).fetchone()
            preparatory = self.database.execute(
                _queries.ACTION_SELECT_INTENTS, (submission_id, attempt_id)
            ).fetchone()
            if not row or json.loads(row[0])["attempt_id"] != attempt_id or not preparatory:
                raise ValueError("unadmitted guard attempt")
            bound = json.loads(preparatory[0])
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

    def guard_record(self, attempt_id):
        with self._lock:
            row = self.database.execute(
                _queries.GUARD_RECORD_SELECT_GUARD_DISPATCHES, (attempt_id,)
            ).fetchone()
            return json.loads(row[0]) if row else None

    def _update_in_tx(self, submission_id, fields):
        row = self.database.execute(
            _queries.UPDATE_IN_TX_SELECT_SUBMISSIONS, (submission_id,)
        ).fetchone()
        if not row:
            raise KeyError(submission_id)
        record = json.loads(row[0])
        record.update(fields)
        record["status_revision"] += 1
        self.database.execute(
            _queries.UPDATE_IN_TX_UPDATE_SUBMISSIONS, (encode(record), submission_id)
        )
        return record

    def _append_usage_in_tx(self, submission_id, attempt_id, usage):
        """Append to the attempt ledger inside the caller's publishing transaction."""
        existing = self.database.execute(
            _queries.ACTION_SELECT_USAGE_REVISIONS, (attempt_id,)
        ).fetchone()[0]
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

    def update(self, submission_id, fields, usage=None):
        new_fields = dict(fields)

        def action():
            latest_usage = {"state": "not_recorded"}
            if usage is not None:
                row = self.database.execute(
                    _queries.UPDATE_IN_TX_SELECT_SUBMISSIONS, (submission_id,)
                ).fetchone()
                if not row:
                    raise KeyError(submission_id)
                attempt_id = json.loads(row[0])["attempt_id"]
                latest_usage = self._append_usage_in_tx(submission_id, attempt_id, usage)
            elif "candidate" in new_fields and new_fields["candidate"] is not None:
                row = self.database.execute(
                    _queries.UPDATE_IN_TX_SELECT_SUBMISSIONS, (submission_id,)
                ).fetchone()
                if not row:
                    raise KeyError(submission_id)
                attempt_id = json.loads(row[0])["attempt_id"]
                prior = self.database.execute(_queries.LATEST_USAGE, (attempt_id,)).fetchone()
                if prior:
                    latest_usage = {"state": "available", "revision": json.loads(prior[0])}
            if "candidate" in new_fields and new_fields["candidate"] is not None:
                new_fields["candidate"] = {**new_fields["candidate"], "usage": latest_usage}
            return self._update_in_tx(submission_id, new_fields)

        return self._transaction(action)

    def mark_wait_expired_no_store(self, submission_id, at):
        def action():
            row = self.database.execute(
                _queries.UPDATE_IN_TX_SELECT_SUBMISSIONS, (submission_id,)
            ).fetchone()
            if not row:
                raise KeyError(submission_id)
            record = json.loads(row[0])
            fields = {"wait_expired_no_store": True, "updated_at": at}
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
        submission_id,
        candidate,
        usage,
        raw_usage_digest,
        current_allowed,
        current_expiry,
        at,
        live_source_tags=None,
    ):
        def action():
            row = self.database.execute(
                _queries.UPDATE_IN_TX_SELECT_SUBMISSIONS, (submission_id,)
            ).fetchone()
            if not row:
                raise KeyError(submission_id)
            record = json.loads(row[0])
            if record["submission_state"] == "completed":
                raise ValueError("candidate already completed")
            expiry = min(
                (x for x in (record.get("content_expires_at"), current_expiry) if x), default=None
            )
            expired = bool(
                expiry
                and datetime.fromisoformat(expiry.replace("Z", "+00:00"))
                <= datetime.now(timezone.utc)
            )
            retain = bool(
                record["content_store_allowed"]
                and current_allowed
                and not record["wait_expired_no_store"]
                and not expired
            )
            latest_usage = {"state": "not_recorded"}
            if usage is not None:
                attempt_id = record["attempt_id"]
                latest_usage = self._append_usage_in_tx(submission_id, attempt_id, usage)
            else:
                prior = self.database.execute(
                    _queries.LATEST_USAGE, (record["attempt_id"],)
                ).fetchone()
                if prior:
                    latest_usage = {"state": "available", "revision": json.loads(prior[0])}
            fields = {
                "submission_state": SubmissionState.COMPLETED.value,
                "dispatch_state": DispatchState.RESPONSE_OBSERVED.value,
                "attempt_revision": 4,
                "updated_at": at,
                "content_store_allowed": retain,
                "candidate_access": "present"
                if retain
                else (
                    "not_retained"
                    if record["wait_expired_no_store"]
                    else "expired"
                    if expired
                    else "not_retained"
                ),
                "candidate": {**candidate, "usage": latest_usage} if retain else None,
            }
            if not retain and not record["wait_expired_no_store"] and not expired:
                fields["live_source_tags"] = list(live_source_tags or [])
            if raw_usage_digest is not None:
                fields["raw_usage_digest"] = raw_usage_digest
            if record["wait_expired_no_store"]:
                fields["result_unavailable_reason"] = "wait_expired_no_store"
            result = self._update_in_tx(submission_id, fields)
            result["usage"] = latest_usage
            return result

        return self._transaction(action)

    def get(self, submission_id):
        def load():
            row = self.database.execute(
                _queries.UPDATE_IN_TX_SELECT_SUBMISSIONS, (submission_id,)
            ).fetchone()
            if not row:
                return None
            return json.loads(row[0])

        def with_usage(record):
            if record is None:
                return None
            usage = self.database.execute(_queries.LATEST_USAGE, (record["attempt_id"],)).fetchone()
            record["usage"] = (
                {"state": "available", "revision": json.loads(usage[0])}
                if usage
                else {"state": "not_recorded"}
            )
            return record

        def expired(record):
            expiry = record.get("content_expires_at") if record else None
            return bool(
                record
                and record.get("candidate")
                and expiry
                and datetime.fromisoformat(expiry.replace("Z", "+00:00"))
                <= datetime.now(timezone.utc)
            )

        with self.database.read():
            record = load()
            if not expired(record):
                return with_usage(record)

        def expire():
            # Re-read after acquiring write ownership; never overwrite a newer revision.
            record = load()
            if expired(record):
                record["candidate"] = None
                record["candidate_access"] = "expired"
                record["status_revision"] += 1
                record["updated_at"] = utc_timestamp(datetime.now(timezone.utc))
                self.database.execute(
                    _queries.UPDATE_IN_TX_UPDATE_SUBMISSIONS, (encode(record), submission_id)
                )
            return with_usage(record)

        return self.database.transaction(expire)

    def by_work(self, key):
        with self._lock:
            row = self.database.execute(
                _queries.BY_WORK_SELECT_SUBMISSIONS, (key["principal_id"], encode(key))
            ).fetchone()
        return self.get(row[0]) if row else None

    def has_authorized_tool_call(
        self, principal_id, task_id, source_authority_id, context_id, block, live_source_tag
    ):
        """Verify retained content or a delivered live block tag in the authenticated scope."""
        with self._lock:
            rows = self.database.execute(
                _queries.HAS_AUTHORIZED_TOOL_CALL_SELECT_SUBMISSIONS, (principal_id, task_id)
            ).fetchall()
        for (raw,) in rows:
            record = json.loads(raw)
            if (
                record.get("source_authority_id") != source_authority_id
                or record.get("context_id") != context_id
            ):
                continue
            if (
                record.get("candidate_access") == "present"
                and record.get("candidate")
                and any(
                    source == block
                    for source in record["candidate"]["output_blocks"]
                    if source.get("kind") == "tool_call"
                )
            ):
                return True
            if (
                record.get("delivery_state") == "candidate_delivered"
                and not record.get("wait_expired_no_store")
                and live_source_tag in record.get("live_source_tags", ())
            ):
                return True
        return False

    def intent_count(self, submission_id):
        with self._lock:
            return self.database.execute(
                _queries.INTENT_COUNT_SELECT_INTENTS, (submission_id,)
            ).fetchone()[0]
