"""Strict operator JSON parsing and shared CSV serialization."""

import csv
import io
from collections.abc import Iterable, Mapping, Sequence
from typing import TypeVar

from ..json_validation import reject_number, unique_pairs
from ..csv_export import spreadsheet_row

T = TypeVar("T")
SESSION_SECONDS = 1800


def _pairs(items: list[tuple[str, T]]) -> dict[str, T]:
    return unique_pairs(items)


def _reject_number(_text: str) -> None:
    reject_number(_text)


def csv_bytes(columns: Sequence[str], rows: Iterable[Mapping[str, object]]) -> bytes:
    """Preserve column order, exact strings and the existing CSV dialect."""
    out = io.StringIO()
    writer = csv.DictWriter(out, columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(spreadsheet_row(row) for row in rows)
    return out.getvalue().encode("utf-8")
