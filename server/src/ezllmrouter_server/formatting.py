"""Exact decimal rendering and UTC timestamps shared by server domains."""

import re
from datetime import datetime, timezone
from decimal import Decimal

UTC_SECONDS = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
UTC_OFFSET_SECONDS = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})")


def money(value: Decimal, *, places: int | None = None, compact: bool = False) -> str:
    """Render without floats; callers choose the adopted lexical precision."""
    rendered = format(value, "f" if places is None else f".{places}f")
    return rendered.rstrip("0").rstrip(".") if compact and "." in rendered else rendered


def utc_timestamp(instant: datetime | None = None, *, precise: bool = False) -> str:
    instant = instant if instant is not None else datetime.now(timezone.utc)
    if instant.utcoffset() is None:
        raise ValueError("naive timestamp")
    instant = instant.astimezone(timezone.utc)
    return instant.isoformat() if precise else instant.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc_second(value: object, *, allow_offset: bool = False) -> datetime:
    pattern = UTC_OFFSET_SECONDS if allow_offset else UTC_SECONDS
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ValueError("invalid UTC timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("naive timestamp")
    return parsed.astimezone(timezone.utc)


def is_utc_second(value: object) -> bool:
    try:
        return utc_timestamp(parse_utc_second(value)) == value
    except (ValueError, OverflowError):
        return False
