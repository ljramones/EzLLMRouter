"""Replaceable local store boundary; SQLite is DEV-01 only."""

from __future__ import annotations
import json
import sqlite3
import threading
import uuid
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, NoReturn, Protocol, TypeAlias, TypeVar, cast
from collections.abc import Callable, Iterator
from .database import Database
from .records import Record as Record
from .instance_lock import InstanceLease


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


from . import store_successor
from . import store_work
from . import store_results


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

    work_owner = store_work.work_owner

    _claim_work_in_tx = store_work._claim_work_in_tx

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

    successor_create = store_successor.successor_create

    successor_get = store_successor.successor_get

    successor_by_work = store_successor.successor_by_work

    successor_append_evidence = store_successor.successor_append_evidence

    successor_update = store_successor.successor_update

    successor_guard_commit = store_successor.successor_guard_commit

    successor_append_usage = store_successor.successor_append_usage

    successor_latest_usage = store_successor.successor_latest_usage

    successor_totals = store_successor.successor_totals

    successor_expire_results = store_successor.successor_expire_results

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

    create = store_work.create

    intent = store_work.intent

    guard_commit = store_work.guard_commit

    guard_record = store_work.guard_record

    _update_in_tx = store_results._update_in_tx

    _append_usage_in_tx = store_results._append_usage_in_tx

    update = store_results.update

    mark_wait_expired_no_store = store_results.mark_wait_expired_no_store

    complete_candidate = store_results.complete_candidate

    get = store_work.get

    by_work = store_work.by_work

    has_authorized_tool_call = store_work.has_authorized_tool_call

    intent_count = store_work.intent_count


def _check_store_contract(store: SQLiteStore) -> Store:
    return store
