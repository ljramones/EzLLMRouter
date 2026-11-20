"""Shared rendering and fictional arithmetic for immutable demo projections."""

from decimal import Decimal
from .reporting import Totals

LABEL = "DEMO — scripted activity and simulated USD; no real provider calls"


def total(items):
    total = Totals()
    for item in items:
        total.add(item)
    return total.public()


def amount(attempt, rate):
    value = (
        Decimal(attempt["input"]) * Decimal(rate["input_per_1000_usd"])
        + Decimal(attempt["output"]) * Decimal(rate["output_per_1000_usd"])
    ) / Decimal(1000)
    return format(value.quantize(Decimal("0.01")), ".2f")


def basis(attempt, rate):
    return (
        f"{attempt['input']} input × USD {rate['input_per_1000_usd']}/1k + "
        f"{attempt['output']} output × USD {rate['output_per_1000_usd']}/1k"
    )
