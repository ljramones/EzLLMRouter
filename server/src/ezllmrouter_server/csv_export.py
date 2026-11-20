"""Keep exported text inert in spreadsheets while preserving decimal amounts."""

import csv
import io
from collections.abc import Iterable, Mapping, Sequence
import re


def spreadsheet_cell(value: object) -> object:
    if not isinstance(value, str) or not value:
        return value
    if value[0] in "\t\r\n" or (
        value.lstrip().startswith(("=", "+", "-", "@"))
        and not re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value)
    ):
        return "'" + value
    return value


def spreadsheet_row(row: Mapping[str, object]) -> dict[str, object]:
    return {key: spreadsheet_cell(value) for key, value in row.items()}


def csv_bytes(columns: Sequence[str], rows: Iterable[Mapping[str, object]]) -> bytes:
    """Preserve column order, exact strings and the existing CSV dialect."""
    out = io.StringIO()
    writer = csv.DictWriter(out, columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(spreadsheet_row(row) for row in rows)
    return out.getvalue().encode("utf-8")
