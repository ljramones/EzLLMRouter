"""Validate public model references without creating a runtime destination."""

from datetime import date
from decimal import Decimal, InvalidOperation
import re
from urllib.parse import urlsplit


from .identity import DEFAULT_IDENTITY
from .identifiers import require_identifier

RATE = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,12})?\Z")


def _text(value, limit=500):
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > limit
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError("invalid catalogue text")
    return value


def _key(value):
    return require_identifier(value)


def operator_source(url, title, recorded_at, snapshot):
    _text(url)
    _text(title, 160)
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or any(ord(char) < 33 for char in url)
    ):
        raise ValueError("invalid source URL")
    return {
        "id": _key("operator.source." + snapshot),
        "title": title,
        "url": url,
        "checked_on": None,
        "type": "operator-entered reference",
        "recorded_at": recorded_at,
    }


def operator_reference_price(data, recorded_at):
    """Validate explicit reference rates without claiming publisher verification."""
    if type(data) is not dict or set(data) != {
        "snapshot_id",
        "bands",
        "source_url",
        "source_title",
    }:
        raise ValueError("invalid operator reference price")
    snapshot = _key(data["snapshot_id"])
    source = operator_source(data["source_url"], data["source_title"], recorded_at, snapshot)
    bands = data["bands"]
    if type(bands) is not list or not 1 <= len(bands) <= 4:
        raise ValueError("invalid reference bands")
    allowed = {
        "prompt_tokens_lte",
        "prompt_tokens_gt",
        "input_tokens_lte",
        "input_tokens_gt",
        "rate_period",
        "weekday_intervals",
        "exclude",
        "definition",
        "publisher_date_through",
        "cutover_timezone",
        "calendar_and_exact_interval_boundary_resolution",
        "days",
        "timezone",
    }
    normalized = []
    for band in bands:
        required = {"label", "conditions", "rates_usd_per_1000000_tokens"}
        if (
            type(band) is not dict
            or not required <= set(band)
            or set(band) - required - {"additional_rates", "calculation_basis"}
        ):
            raise ValueError("invalid reference band")
        conditions = band["conditions"]
        if type(conditions) is not dict or set(conditions) - allowed or len(str(conditions)) > 2000:
            raise ValueError("invalid reference conditions")
        for value in conditions.values():
            if type(value) not in (str, int, bool, list) or (
                type(value) is list
                and (len(value) > 20 or any(type(item) is not str for item in value))
            ):
                raise ValueError("invalid reference conditions")
        rates = band["rates_usd_per_1000000_tokens"]
        primary = {"input_uncached", "output", "input_cached"}
        extra = {"cache_write_5m", "cache_write_1h", "cache_write_30m", "cache_write_12h"}
        if type(rates) is not dict or not primary <= set(rates) or set(rates) - primary - extra:
            raise ValueError("invalid reference rates")
        clean = {}
        for key, value in rates.items():
            if value is None:
                clean[key] = None
            elif (
                type(value) is str
                and RATE.fullmatch(value)
                and Decimal(value) <= Decimal("1000000")
            ):
                clean[key] = value
            else:
                raise ValueError("invalid reference rate")
        if all(clean[key] is None for key in primary):
            raise ValueError("at least one primary reference rate is required")
        item = {
            "label": _text(band["label"], 160),
            "conditions": conditions,
            "rates_usd_per_1000000_tokens": clean,
        }
        if "additional_rates" in band:
            additional = band["additional_rates"]
            if type(additional) is not dict or set(additional) != {
                "context_storage_usd_per_1000000_token_hours"
            }:
                raise ValueError("invalid additional reference rate")
            value = additional["context_storage_usd_per_1000000_token_hours"]
            if value is not None and (
                type(value) is not str
                or not RATE.fullmatch(value)
                or Decimal(value) > Decimal("1000000")
            ):
                raise ValueError("invalid additional reference rate")
            item["additional_rates"] = additional
        if "calculation_basis" in band:
            item["calculation_basis"] = _text(band["calculation_basis"], 500)
        normalized.append(item)
    return (
        {
            "snapshot_id": snapshot,
            "verified_on": None,
            "operator_recorded_at": recorded_at,
            "publisher_effective_from": None,
            "currency": "USD",
            "basis": "operator-entered reference",
            "rates_are_reference_data_not_an_active_EzLLMRouter_billing_schedule": True,
            "bands": normalized,
        },
        source,
    )


def validate_catalogue(subject, data, *, owner_id=DEFAULT_IDENTITY.owner_id):
    """Return a reference-only registry record from one researched seed entry."""
    if type(data) is not dict or set(data) != {"entry", "sources"}:
        raise ValueError("invalid catalogue import")
    entry, sources = data["entry"], data["sources"]
    if type(entry) is not dict or type(sources) is not list or not sources:
        raise ValueError("invalid catalogue import")
    _key(subject)
    if subject != "catalogue." + _key(entry.get("catalogue_key")):
        raise ValueError("catalogue key mismatch")
    for key in (
        "display_name",
        "vendor",
        "family",
        "provider_route_basis",
        "identifier_pin_status",
    ):
        _text(entry.get(key))
    _key(entry.get("published_api_model_id"))
    registration = entry.get("ezllmrouter_registration")
    if (
        type(registration) is not dict
        or registration.get("catalogued") is not True
        or any(
            registration.get(key) is not False for key in ("execution_approved", "runtime_ready")
        )
        or any(
            registration.get(key) is not None for key in ("runtime_binding", "credential_reference")
        )
        or registration.get("automatic_grants") != []
    ):
        raise ValueError("catalogue cannot carry runtime authority")
    price = entry.get("price_reference")
    if (
        type(price) is not dict
        or price.get("currency") != "USD"
        or price.get("rates_are_reference_data_not_an_active_EzLLMRouter_billing_schedule")
        is not True
    ):
        raise ValueError("invalid reference price")
    _key(price.get("snapshot_id"))
    if price.get("publisher_effective_from") is not None:
        raise ValueError("invented effective date")
    try:
        date.fromisoformat(price["verified_on"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid checked date") from exc
    bands = price.get("bands")
    if type(bands) is not list or not bands or len(bands) > 4:
        raise ValueError("invalid price bands")
    for band in bands:
        if type(band) is not dict or type(band.get("conditions")) is not dict:
            raise ValueError("invalid price condition")
        _text(band.get("label"))
        rates = band.get("rates_usd_per_1000000_tokens")
        if type(rates) is not dict or not {"input_uncached", "output", "input_cached"} <= set(
            rates
        ):
            raise ValueError("missing reference rates")
        for value in rates.values():
            if type(value) is not str or not RATE.fullmatch(value):
                raise ValueError("invalid reference rate")
            try:
                if Decimal(value) > Decimal("1000000"):
                    raise ValueError("invalid reference rate")
            except InvalidOperation as exc:
                raise ValueError("invalid reference rate") from exc
    refs = entry.get("source_refs")
    if type(refs) is not list or not refs or len(refs) != len(sources):
        raise ValueError("invalid source references")
    if {source.get("id") for source in sources if type(source) is dict} != set(refs):
        raise ValueError("source mismatch")
    for source in sources:
        if (
            type(source) is not dict
            or type(source.get("url")) is not str
            or not source["url"].startswith("https://")
        ):
            raise ValueError("invalid source")
        _key(source.get("id"))
        _text(source.get("title"))
        if source.get("checked_on") != price["verified_on"]:
            raise ValueError("source check date mismatch")
    return {
        "configuration_ref": subject,
        "kind": "real_catalogue",
        "display_name": entry["display_name"],
        "status": "catalogued",
        "revision": 1,
        "destination": None,
        "owner": owner_id,
        "capabilities": [],
        "purposes": [],
        "task_classes": [],
        "handling": [],
        "approved_by": None,
        "approved_at": None,
        "legacy_unpriced": False,
        "catalogue": entry,
        "source_links": sources,
        "price_version": price["snapshot_id"],
    }
