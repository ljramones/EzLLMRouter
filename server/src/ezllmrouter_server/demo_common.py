"""Shared rendering and fictional arithmetic for immutable demo projections."""

from decimal import Decimal
from .reporting import Totals
from .store import Record

LABEL = "DEMO — scripted activity and simulated USD; no real provider calls"


def total(items: list[Record]) -> Record:
    total = Totals()
    for item in items:
        total.add(item)
    return total.public()


def amount(attempt: Record, rate: Record) -> str:
    value = (
        Decimal(attempt["input"]) * Decimal(rate["input_per_1000_usd"])
        + Decimal(attempt["output"]) * Decimal(rate["output_per_1000_usd"])
    ) / Decimal(1000)
    return format(value.quantize(Decimal("0.01")), ".2f")


def basis(attempt: Record, rate: Record) -> str:
    return (
        f"{attempt['input']} input × USD {rate['input_per_1000_usd']}/1k + "
        f"{attempt['output']} output × USD {rate['output_per_1000_usd']}/1k"
    )


def select_attempts(attempts: list[Record], actor: str, person: str, provider: str) -> list[Record]:
    return [
        item
        for item in attempts
        if (not actor or item["actor"] == actor)
        and (not person or item["user"] == (None if person == "__autonomous__" else person))
        and (not provider or item["provider"] == provider)
    ]
