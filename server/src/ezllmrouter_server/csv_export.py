"""Keep exported text inert in spreadsheets while preserving decimal amounts."""

from collections.abc import Mapping
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
