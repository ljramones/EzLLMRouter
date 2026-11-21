"""Registry prices operations; caller owns the existing authority context."""

from __future__ import annotations

from ..errors import RegistryConflict
from ..repositories import registry as _queries
from ..cache_accounting import SEMANTICS as CACHE_SEMANTICS
from ..cache_accounting import validate_contract
from ..store import encode
from ..registry_values import RATE_CATEGORIES, timestamp, identifier, exact_rate


def _apply_price(self, db, actor, action, subject, expected, data):
    model = self._load_for_update(db, "registry_models", "ref", subject, expected)
    if model.get("kind") == "real_catalogue":
        raise ValueError("public reference is not an executable price schedule")
    if model["status"] == "revoked":
        raise RegistryConflict("retired model cannot be repriced")
    base_fields = {
        "price_version",
        "currency",
        "rates",
        "source",
        "usage_semantics_version",
    }
    if set(data) not in (base_fields, base_fields | {"contract"}):
        raise ValueError("invalid price")
    version = identifier(data["price_version"])
    if db.execute(_queries.APPLY_SELECT_REGISTRY_PRICES, (subject, version)).fetchone():
        raise RegistryConflict("price version exists")
    provider_schedule = model.get("kind") == "provider_deployment"
    allowed_source = (
        "operator-approved provider schedule" if provider_schedule else "synthetic fixture"
    )
    allowed_semantics = (
        ("openai.responses.text.v1", CACHE_SEMANTICS)
        if provider_schedule
        else ("synthetic.text.v1", "synthetic.tool.v1")
    )
    if (
        data["currency"] != "USD"
        or data["source"] != allowed_source
        or data["usage_semantics_version"] not in allowed_semantics
    ):
        raise ValueError("unsupported price semantics")
    rates = data["rates"]
    if data["usage_semantics_version"] == CACHE_SEMANTICS:
        contract = validate_contract(data.get("contract"), model["destination"]["model"], rates)
    else:
        if (
            "contract" in data
            or type(rates) is not dict
            or set(rates) != {"input_uncached", "output_text"}
        ):
            raise ValueError("unsupported rate categories")
        contract = None
    record = {
        "configuration_ref": subject,
        "price_version": version,
        "currency": "USD",
        "rates": {key: exact_rate(rates[key]) for key in rates},
        "unit_denominator": 1000000,
        "usage_semantics_version": data["usage_semantics_version"],
        "source": allowed_source,
        "recorded_at": timestamp(),
        "effective_at": timestamp(),
        "approved_by": actor,
        "revision": model["revision"] + 1,
        "unsupported_categories": [x for x in RATE_CATEGORIES if x not in rates],
    }
    if contract is not None:
        record["contract"] = contract
    db.execute(_queries.APPLY_INSERT_REGISTRY_PRICES, (subject, version, encode(record)))
    model["revision"] += 1
    model["price_version"] = version
    db.execute(_queries.APPLY_UPDATE_REGISTRY_MODELS, (encode(model), subject))
    return {**record, "revision": model["revision"]}
