"""DEV-11 immutable Responses text price contract and exact financial arithmetic.

This contract is deliberately narrow: one exact model, implicit caching, one
input price tier, no tools or streaming, and no explicit cache controls.  A
provider-enforced context limit bounds input tokens even for multibyte text;
the operator must review that exact model limit and its price conditions.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import ROUND_HALF_EVEN, ROUND_UP, Decimal

from .records import Record
from .formatting import money, utc_timestamp
from .json_validation import MAX_SAFE_INTEGER

SEMANTICS = "openai.responses.text.cache.v2"
CONTRACT = "openai.responses.implicit-cache.v1"
NANO = Decimal("0.000000001")
MAX_COUNT = MAX_SAFE_INTEGER
RATE_KEYS = {"input_uncached", "input_cache_read", "input_cache_write_30m", "output_text"}


def validate_contract(value: object, model_id: str, rates: object) -> Record:
    """Validate an operator-reviewed, exact-model financial contract at publish time."""
    fields = {
        "version",
        "requested_model",
        "returned_models",
        "cache_mode",
        "input_token_ceiling",
        "max_output_tokens",
        "input_bound_basis",
        "temperature_zero_supported",
        "price_conditions",
        "price_source_url",
        "observed_on",
    }
    if type(value) is not dict or set(value) != fields:
        raise ValueError("incomplete provider accounting contract")
    if (
        value["version"] != CONTRACT
        or value["requested_model"] != model_id
        or value["cache_mode"] != "implicit_default_30m"
        or value["input_bound_basis"] != "provider_enforced_context_window"
        or value["price_conditions"] != "single_tier_no_modifiers"
        or value["temperature_zero_supported"] is not True
        or type(value["returned_models"]) is not list
        or value["returned_models"] != [model_id]
    ):
        raise ValueError("unsupported model or request contract")
    for field in ("input_token_ceiling", "max_output_tokens"):
        if type(value[field]) is not int or not 1 <= value[field] <= 1000000:
            raise ValueError("invalid model token ceiling")
    if value["max_output_tokens"] > 4096:
        raise ValueError("unsupported output ceiling")
    if (
        type(value["price_source_url"]) is not str
        or not value["price_source_url"].startswith("https://")
        or len(value["price_source_url"]) > 512
    ):
        raise ValueError("invalid price source")
    if type(value["observed_on"]) is not str or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}", value["observed_on"]
    ):
        raise ValueError("invalid observation date")
    try:
        date.fromisoformat(value["observed_on"])
    except ValueError as exc:
        raise ValueError("invalid observation date") from exc
    if type(rates) is not dict or set(rates) != RATE_KEYS:
        raise ValueError("incomplete cache-aware rates")
    # The limits are assertions in a reviewed contract, never inferred from
    # an inventory/display label. Unknown tier or surcharge means no publish.
    return dict(value)


def exposure_bound(schedule, output_limit):
    """Upper bound for disjoint input buckets and total output, rounded up."""
    contract = schedule["contract"]
    if (
        schedule["usage_semantics_version"] != SEMANTICS
        or type(output_limit) is not int
        or not 1 <= output_limit <= contract["max_output_tokens"]
    ):
        raise ValueError("unsupported output setting")
    input_rate = max(
        Decimal(schedule["rates"][key]) for key in RATE_KEYS if key.startswith("input_")
    )
    raw = (
        Decimal(contract["input_token_ceiling"]) * input_rate
        + Decimal(output_limit) * Decimal(schedule["rates"]["output_text"])
    ) / Decimal(schedule["unit_denominator"])
    return raw.quantize(NANO, rounding=ROUND_UP)


def _quantity(container, field):
    if type(container) is not dict or field not in container:
        return {"state": "absent"}
    value = container[field]
    if value is None:
        return {"state": "null"}
    if type(value) is int and 0 <= value <= MAX_COUNT:
        return {"state": "known", "count": value}
    return {"state": "invalid"}


def cache_usage_revision(attempt_id, report, schedule, expected_model, reported_model):
    """Price only complete, consistent billed buckets; preserve absence facts."""
    from datetime import datetime, timezone

    input_details = report.get("input_tokens_details") if type(report) is dict else None
    output_details = report.get("output_tokens_details") if type(report) is dict else None
    write_details = (
        input_details.get("cache_write_tokens_details") if type(input_details) is dict else None
    )
    observed = {
        "input_total": _quantity(report, "input_tokens"),
        "output_total": _quantity(report, "output_tokens"),
        "reported_total": _quantity(report, "total_tokens"),
        "input_cache_read": _quantity(input_details, "cached_tokens"),
        "input_cache_write": _quantity(input_details, "cache_write_tokens"),
        "input_cache_write_30m": _quantity(write_details, "ttl_30m_tokens"),
        "input_cache_write_12h": _quantity(write_details, "ttl_12h_tokens"),
        "output_reasoning": _quantity(output_details, "reasoning_tokens"),
    }
    normalized = dict(observed)
    normalized["input_uncached"] = {"state": "unknown"}
    normalized["output_text"] = {"state": "unknown"}
    normalized["other_billable"] = [
        {"component": "unclassified", "unit": "units", "knowledge": {"state": "unknown"}}
    ]
    cost = {"status": "unknown", "currency": schedule["currency"]}
    total, out, reported_total, read, write = (
        observed[key]
        for key in (
            "input_total",
            "output_total",
            "reported_total",
            "input_cache_read",
            "input_cache_write",
        )
    )
    valid = all(item["state"] == "known" for item in (total, out, reported_total, read, write))
    if valid:
        input_count, output_count = total["count"], out["count"]
        read_count, write_count = read["count"], write["count"]
        thirty, twelve = observed["input_cache_write_30m"], observed["input_cache_write_12h"]
        valid = (
            reported_total["count"] == input_count + output_count
            and set(input_details)
            <= {"cached_tokens", "cache_write_tokens", "cache_write_tokens_details"}
            and type(write_details) is dict
            and set(write_details) == {"ttl_30m_tokens", "ttl_12h_tokens"}
            and (type(output_details) is not dict or set(output_details) <= {"reasoning_tokens"})
            and read_count + write_count <= input_count
            and all(item["state"] == "known" for item in (thirty, twelve))
            and thirty.get("count", -1) == write_count
            and twelve.get("count", -1) == 0
            and input_count <= schedule["contract"]["input_token_ceiling"]
            and output_count <= schedule["contract"]["max_output_tokens"]
            and reported_model in schedule["contract"]["returned_models"]
            and expected_model == schedule["contract"]["requested_model"]
        )
        if valid:
            ordinary = input_count - read_count - write_count
            normalized["input_uncached"] = {"state": "known", "count": ordinary}
            reason = observed["output_reasoning"]
            if reason["state"] == "known":
                if reason["count"] > output_count:
                    valid = False
                else:
                    normalized["output_text"] = {
                        "state": "known",
                        "count": output_count - reason["count"],
                    }
            elif reason["state"] == "invalid":
                valid = False
            if valid:
                rates = schedule["rates"]
                raw = (
                    Decimal(ordinary) * Decimal(rates["input_uncached"])
                    + Decimal(read_count) * Decimal(rates["input_cache_read"])
                    + Decimal(write_count) * Decimal(rates["input_cache_write_30m"])
                    + Decimal(output_count) * Decimal(rates["output_text"])
                ) / Decimal(schedule["unit_denominator"])
                amount = raw.quantize(NANO, rounding=ROUND_HALF_EVEN)
                if amount != 0 or raw == 0:
                    normalized["other_billable"] = []
                    cost = {
                        "status": "calculated",
                        "currency": schedule["currency"],
                        "amount_decimal": money(amount),
                        "source_ref": schedule["price_version"],
                    }
                    if amount == 0:
                        cost["zero_basis"] = (
                            "provider_reported_free"
                            if input_count == output_count == 0
                            else "contract_free"
                        )
    return {
        "attempt_id": attempt_id,
        "usage_observation": "reported"
        if cost["status"] == "calculated"
        else "partial"
        if any(x["state"] == "known" for x in observed.values())
        else "unknown",
        "normalized_usage": normalized,
        "reported_usage": observed,
        "usage_semantics_version": SEMANTICS,
        "contract_version": schedule["contract"]["version"],
        "price_version": schedule["price_version"],
        "cost": cost,
        "recorded_at": utc_timestamp(datetime.now(timezone.utc)),
    }
