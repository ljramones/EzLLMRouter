"""Public transaction boundary for the named queries owned by repositories."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
import re
import sqlite3
import threading
from typing import Protocol, TypeVar

T = TypeVar("T")
Row = tuple[object, ...]
Parameters = Sequence[object] | Mapping[str, object]


class Transaction(Protocol):
    def __call__(self, action: Callable[[], T]) -> T: ...


@dataclass(frozen=True)
class Query:
    sql: str


def identifier(value: str) -> str:
    if type(value) is not str or not re.fullmatch(r"[a-z_][a-z_0-9]*", value):
        raise ValueError("invalid repository identifier")
    return value


def predicate(value: str) -> str:
    allowed = {"id=?", "ref=?", "principal_id=? AND config_ref=?", "1=1", "s.principal_id=?"}
    allowed |= {
        prefix + " AND json_extract(s.record,'$.submission_state')=?"
        for prefix in ("1=1", "s.principal_id=?")
    }
    if value not in allowed:
        raise ValueError("invalid repository predicate")
    return value


class Result:
    def __init__(self, rows: list[Row], rowcount: int, lastrowid: int | None) -> None:
        self._rows = rows
        self._offset = 0
        self.rowcount = rowcount
        self.lastrowid = lastrowid

    def fetchone(self) -> Row | None:
        if self._offset == len(self._rows):
            return None
        value = self._rows[self._offset]
        self._offset += 1
        return value

    def fetchall(self) -> list[Row]:
        values = self._rows[self._offset :]
        self._offset = len(self._rows)
        return values

    def __iter__(self) -> Iterator[Row]:
        return iter(self.fetchall())


class Database:
    def __init__(
        self, connection: sqlite3.Connection, gate: threading.RLock, transaction: Transaction
    ) -> None:
        self._connection = connection
        self._gate = gate
        self._transaction = transaction

    @contextmanager
    def read(self) -> Iterator[Database]:
        with self._gate:
            yield self

    def transaction(self, action: Callable[[], T]) -> T:
        return self._transaction(action)

    def execute(self, query: Query, parameters: Parameters = ()) -> Result:
        if not isinstance(query, Query):
            raise TypeError("database operations require a repository query")
        with self._gate:
            cursor = self._connection.execute(query.sql, parameters)
            try:
                rows = cursor.fetchall() if cursor.description is not None else []
                return Result(rows, cursor.rowcount, cursor.lastrowid)
            finally:
                cursor.close()
