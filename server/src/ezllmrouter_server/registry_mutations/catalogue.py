"""Registry catalogue operations; caller owns the existing authority context."""

from __future__ import annotations

from ..errors import RegistryConflict
from ..identifiers import require_text as nonempty
from ..repositories import registry as _queries
from ..catalogue import operator_reference_price, validate_catalogue
from ..store import encode
from ..registry_values import timestamp, identifier


def _apply_import_catalogue(self, db, actor, action, subject, expected, data):
    if expected != 0:
        raise RegistryConflict("catalogue creation requires revision zero")
    record = validate_catalogue(subject, data, owner_id=self.identity.owner_id)
    db.execute(_queries.APPLY_INSERT_REGISTRY_MODELS, (subject, encode(record)))
    return record


def _apply_register_catalogue(self, db, actor, action, subject, expected, data):
    required = {
        "display_name",
        "vendor",
        "family",
        "api_model_id",
        "model_version",
        "owner",
        "capabilities",
        "context_window",
        "max_output",
        "notes",
        "price",
    }
    if expected or set(data) != required or not subject.startswith("catalogue.operator."):
        raise ValueError("invalid manual catalogue registration")
    if db.execute(_queries.APPLY_SELECT_REGISTRY_MODELS, (subject,)).fetchone():
        raise RegistryConflict("model exists")
    capabilities = data["capabilities"]
    if type(capabilities) is not list or any(
        item not in ("text", "tools", "vision", "audio", "reasoning") for item in capabilities
    ):
        raise ValueError("invalid descriptive capabilities")
    for field in ("context_window", "max_output"):
        value = data[field]
        if value is not None and (type(value) is not int or not 1 <= value <= 100000000):
            raise ValueError("invalid advertised limit")
    at = timestamp()
    price, source = operator_reference_price(data["price"], at)
    name = nonempty(data["display_name"])
    catalogue = {
        "catalogue_key": subject[len("catalogue.") :],
        "display_name": name,
        "short_name": name,
        "vendor": nonempty(data["vendor"]),
        "family": nonempty(data["family"]),
        "published_api_model_id": identifier(data["api_model_id"]),
        "observed_serving_version": identifier(data["model_version"]),
        "provider_route_basis": "operator-entered metadata; no connection",
        "identifier_pin_status": "operator-entered; unverified",
        "provider_published_limits": {
            "context_window_advertised": data["context_window"],
            "max_output_advertised": data["max_output"],
        },
        "provider_published_capabilities": sorted(set(capabilities)),
        "ezllmrouter_registration": {
            "catalogued": True,
            "execution_approved": False,
            "runtime_ready": False,
            "runtime_binding": None,
            "credential_reference": None,
            "automatic_grants": [],
        },
        "price_reference": price,
        "source_refs": [source["id"]],
        "notes": [nonempty(data["notes"], 500)],
    }
    record = {
        "configuration_ref": subject,
        "kind": "real_catalogue",
        "display_name": name,
        "status": "catalogued",
        "revision": 1,
        "destination": None,
        "owner": identifier(data["owner"]),
        "capabilities": [],
        "purposes": [],
        "task_classes": [],
        "handling": [],
        "approved_by": None,
        "approved_at": None,
        "legacy_unpriced": False,
        "catalogue": catalogue,
        "source_links": [source],
        "reference_price_history": [],
        "price_version": price["snapshot_id"],
        "record_origin": "operator_entered",
    }
    db.execute(_queries.APPLY_INSERT_REGISTRY_MODELS, (subject, encode(record)))
    return record
