"""Shared registry value validation and persisted connection scheduling shape."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re
from typing import TypedDict
from .formatting import money, utc_timestamp
from .identifiers import require_identifier


MODELS = {"model.demo", "model.demo.alt"}


DESTINATION = (
    "configuration_ref",
    "service",
    "endpoint",
    "model",
    "model_version",
    "processing_region",
)


RATE_CATEGORIES = (
    "input_uncached",
    "input_cache_read",
    "input_cache_write",
    "output_text",
    "output_reasoning",
    "other_billable",
)


def timestamp() -> str:
    return utc_timestamp(datetime.now(timezone.utc))


def identifier(value: object) -> str:
    return require_identifier(value)


def exact_rate(value: object) -> str:
    if type(value) is not str or not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,12})?", value):
        raise ValueError("invalid decimal rate")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid decimal rate") from exc
    if not amount.is_finite() or amount < 0 or amount > Decimal("1000000"):
        raise ValueError("invalid decimal rate")
    return money(amount)


class ConnectionSchedule(TypedDict):
    """Scheduling fields present in each persisted connection record."""

    connection_id: str
    checks_scheduled: bool
    status: str
    revision: int
    scheduled_operation: str | None
    check_interval_seconds: int | None
