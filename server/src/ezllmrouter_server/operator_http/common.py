"""Strict operator JSON parsing and shared CSV serialization."""

from typing import TypeVar

from ..json_validation import reject_number, unique_pairs
from ..csv_export import csv_bytes as csv_bytes

T = TypeVar("T")
SESSION_SECONDS = 1800


def _pairs(items: list[tuple[str, T]]) -> dict[str, T]:
    return unique_pairs(items)


def _reject_number(_text: str) -> None:
    reject_number(_text)
