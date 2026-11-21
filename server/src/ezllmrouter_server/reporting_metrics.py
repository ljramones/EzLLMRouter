"""Shared cohort calculations from accumulated accounting facts."""

from __future__ import annotations
from datetime import datetime
from typing import cast
from . import reporting as _api
from .records import Record


def efficiency(member: Record, totals: Record) -> Record:
    amounts = totals["known_subtotals"]
    if member["accepted"] == 0:
        efficiency = {"state": "no_accepted_tasks", "cost_per_accepted_task": None}
    elif (
        member["unreported"]
        or totals["unknown_cost_attempts"]
        or totals["estimated_attempts"]
        or len(amounts) != 1
    ):
        efficiency = {"state": "incomplete", "cost_per_accepted_task": None}
    else:
        currency, amount = next(iter(amounts.items()))
        efficiency = {
            "state": "complete",
            "currency": currency,
            "cost_per_accepted_task": _api._ratio(amount, member["accepted"]),
        }
    return efficiency


def cohort_row(
    key: tuple[str, str, str, str],
    member: Record,
    totals: Record,
    performance: Record,
    efficiency: Record,
) -> Record:
    return {
        "task_class": key[0],
        "evaluation_ref": key[1],
        "agent_id": key[2],
        "agent_version": key[3],
        "total_tasks": len(member["runs"]),
        "accepted": member["accepted"],
        "rejected": member["rejected"],
        "abandoned": member["abandoned"],
        "unreported": member["unreported"],
        "attempt_cost": totals,
        "efficiency": efficiency,
        "performance": performance,
        "sample_note": "Low sample · descriptive only"
        if len(member["runs"]) < 10
        else "Descriptive comparison",
    }


def durations(member: Record, outcomes: dict[str, Record], runs: dict[str, Record]) -> list[int]:
    result = []
    for run_id in member["runs"]:
        run = runs[run_id]
        if outcomes.get(run_id, {}).get("verdict") == "accepted" and run.get("terminal_at"):
            seconds = (
                cast(datetime, _api._utc(run["terminal_at"]))
                - cast(datetime, _api._utc(run["created_at"]))
            ).total_seconds()
            if seconds >= 0:
                result.append(int(seconds))
    return result


def performance(
    accepted_durations: list[int],
    member: Record,
    attempts: int,
    token_complete: bool,
    known_tokens: int,
    input_tokens: int,
    output_tokens: int,
) -> Record:
    performance = {
        "acceptance_rate_percent": _api._ratio(
            member["accepted"] * 100, len(member["runs"]), "0.01"
        ),
        "calls_per_accepted_task": (
            _api._ratio(attempts, member["accepted"]) if member["accepted"] else None
        ),
        "tokens_per_accepted_task": (
            {
                "input": _api._ratio(input_tokens, member["accepted"]),
                "output": _api._ratio(output_tokens, member["accepted"]),
            }
            if member["accepted"] and token_complete
            else None
        ),
        "token_coverage_attempts": known_tokens,
        "latency_accepted_samples": len(accepted_durations),
        "median_seconds_to_accepted": _api.median(accepted_durations)
        if accepted_durations
        else None,
        "p95_seconds_to_accepted": (
            sorted(accepted_durations)[int((len(accepted_durations) - 1) * 0.95)]
            if len(accepted_durations) >= 20
            else None
        ),
        "retry_rate": "not_measured",
        "escalation_rate": "not_measured",
        "human_intervention_rate": "not_measured",
    }
    return performance
