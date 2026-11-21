"""Validated record collections used by external accounting projections."""

from decimal import Decimal
from .records import Record

ReceiptResult = tuple[int, Record]
RecordIndex = dict[str, Record]
EventGroups = dict[str, list[Record]]
SnapshotData = tuple[Record, str | None, str | None]
SnapshotIndex = dict[str, SnapshotData]
LineageLinks = dict[str, tuple[str, str | None, str]]

MoneyTotals = dict[str, Decimal]
MoneyGroups = dict[str, MoneyTotals]
