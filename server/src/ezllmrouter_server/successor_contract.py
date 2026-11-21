"""Product-side wire-0.3 synthetic retrieval contract and exact native tariffs.

The JSON inputs are byte copies of the adopted A1 candidate-04 registries. This
module intentionally does not import its offline JavaScript reference checker.
"""

from __future__ import annotations

import json
import re
from decimal import ROUND_CEILING, ROUND_HALF_EVEN, Decimal, InvalidOperation
from hashlib import sha256
from importlib.resources import files
from typing import Any, cast
from .records import Record
from .json_validation import JSONValue

from .canonical import ContractError
from .formatting import is_utc_second, money
from .json_validation import (
    MAX_SAFE_INTEGER,
    WORK_V03,
    JSONValidationError,
    canonical_json,
    decode_json,
    validate_json,
)

SAFE = MAX_SAFE_INTEGER
SCHEMAS = json.loads(files("ezllmrouter_server").joinpath("retrieval/schemas.json").read_text())
REGISTRATIONS = json.loads(
    files("ezllmrouter_server").joinpath("retrieval/registrations.json").read_text()
)
TARIFFS = json.loads(files("ezllmrouter_server").joinpath("retrieval/tariffs.json").read_text())
QUANTUM = Decimal(TARIFFS["quantum"])


def strict_decode(data: bytes) -> JSONValue:
    try:
        return decode_json(data, WORK_V03)
    except JSONValidationError as exc:
        raise ContractError(exc.code, exc.status) from exc


def _restricted(value: object, depth: int = 0) -> None:
    try:
        validate_json(value, WORK_V03, depth)
    except JSONValidationError as exc:
        raise ContractError(exc.code, exc.status) from exc


def schema_valid(value: object, schema: Record, bundle: Record = SCHEMAS) -> bool:
    if "$ref" in schema:
        match = re.fullmatch(r"#/\$defs/([A-Za-z][A-Za-z0-9]*)", schema["$ref"])
        if not match or match[1] not in bundle["$defs"]:
            raise ValueError("unresolved local schema reference")
        return schema_valid(value, bundle["$defs"][match[1]], bundle)
    if "oneOf" in schema:
        return sum(schema_valid(value, part, bundle) for part in schema["oneOf"]) == 1
    if "const" in schema and (type(value) is not type(schema["const"]) or value != schema["const"]):
        return False
    if "enum" in schema and not any(
        type(value) is type(item) and value == item for item in schema["enum"]
    ):
        return False
    kind = schema.get("type")
    if kind == "object":
        if type(value) is not dict or any(key not in value for key in schema.get("required", ())):
            return False
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key not in properties:
                if schema.get("additionalProperties") is False:
                    return False
            elif not schema_valid(item, properties[key], bundle):
                return False
    elif kind == "array":
        if (
            type(value) is not list
            or len(value) < schema.get("minItems", 0)
            or len(value) > schema.get("maxItems", float("inf"))
        ):
            return False
        return all(schema_valid(item, schema["items"], bundle) for item in value)
    elif kind == "string":
        if type(value) is not str or any(
            ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value
        ):
            return False
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get(
            "maxLength", float("inf")
        ):
            return False
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            return False
    elif kind == "integer":
        if (
            type(value) is not int
            or abs(value) > SAFE
            or value < schema.get("minimum", -float("inf"))
            or value > schema.get("maximum", float("inf"))
        ):
            return False
    elif kind == "boolean" and type(value) is not bool:
        return False
    return True


def canonical(value: JSONValue) -> str:
    """A1's ASCII-key-order canonical JSON for its restricted value domain."""
    return canonical_json(value, allow_null=True, exact_types=True)


def domain_digest(prefix: str, value: JSONValue) -> str:
    return "sha256:" + sha256((prefix + canonical(value)).encode("utf-8")).hexdigest()


def work_projection(request: Record, trusted: Record) -> Record:
    return {
        "schema_id": "ezllmrouter-work-v0.3",
        "profile": request["capability_profile"],
        "work_key": {
            "principal_id": trusted["identity"]["principal_id"],
            **request["work_selector"],
        },
        "operation": request["operation"],
        "input": request["input"],
        "metadata": request["metadata"],
        "trusted": trusted["identity"],
        "purpose": request["purpose"],
        "task_class": request["task_class"],
        "requested_configuration_ref": request["requested_configuration_ref"],
        "deadline": request["deadline"],
        "handling_profile": request["handling_profile"],
    }


def work_digest(work: Record) -> str:
    op = work["operation"]
    return domain_digest(f"ezllmrouter-work-v0.3\n{op['type']}@{op['version']}\n", work)


def valid_utc_second(value: object) -> bool:
    return type(value) is str and is_utc_second(value)


def public_text_digest(text: str) -> str:
    return "sha256:" + sha256(("ezllmrouter-public-text-v1\n" + text).encode()).hexdigest()


def content_digest(candidate: Record) -> str:
    text = "ezllmrouter-content-v1\n" + candidate["content_version"] + "\n" + candidate["text"]
    return "sha256:" + sha256(text.encode()).hexdigest()


def config_for(request: Record, registry: Record = REGISTRATIONS) -> Record | None:
    return next(
        (
            item
            for item in cast(list[Record], registry["configurations"])
            if item["configuration_ref"] == request["requested_configuration_ref"]
        ),
        None,
    )


def price_for(request: Record, registry: Record = REGISTRATIONS) -> Record | None:
    config = config_for(request, registry)
    if not config:
        return None
    ref = (
        config["price_ref"]
        if request["operation"]["type"] == "rerank"
        else config["role_price_refs"].get(request["input"]["role"])
    )
    return next(
        (
            item
            for item in cast(list[Record], registry["price_contracts"])
            if item["price_ref"] == ref
        ),
        None,
    )


def semantic_request(
    request: Record, trusted: Record, registry: Record = REGISTRATIONS, *, fresh: bool = True
) -> bool:
    metadata, identity = request["metadata"], trusted["identity"]
    config = config_for(request, registry)
    if not all(
        valid_utc_second(item)
        for item in (request["deadline"], trusted["authenticated_at"], trusted["expires_at"])
    ):
        return False
    if fresh and not trusted["authenticated_at"] < request["deadline"] <= trusted["expires_at"]:
        return False
    if (
        request["handling_profile"] != registry["handling_profile"]
        or not config
        or canonical(config["operation"]) != canonical(request["operation"])
    ):
        return False
    if (
        metadata["root_workflow_id"] != trusted["allowed_root_workflow_id"]
        or metadata["run_id"] != trusted["authenticated_current_run_id"]
        or (
            "initiating_user_id" in metadata
            and metadata["initiating_user_id"] != trusted.get("allowed_initiating_user_id")
        )
    ):
        return False
    mode = metadata["invocation_mode"]
    if mode == "direct_human" and (
        identity["actor_kind"] != "human"
        or identity["actor_id"] != metadata.get("initiating_user_id")
    ):
        return False
    if mode == "autonomous_service" and (
        identity["actor_kind"] != "service" or "initiating_user_id" in metadata
    ):
        return False
    if mode == "delegated_agent":
        links = metadata["delegation"]
        if (
            identity["actor_kind"] != "agent"
            or not links
            or links[0]["from_actor_id"] != metadata.get("initiating_user_id")
        ):
            return False
        last = links[-1]
        if (
            last["to_actor_id"] != identity["actor_id"]
            or last["to_run_id"] != metadata["run_id"]
            or last["from_run_id"] != metadata.get("parent_run_id")
        ):
            return False
        seen = {links[0]["from_actor_id"]}
        for index, link in enumerate(links):
            if index and (
                link["from_actor_id"] != links[index - 1]["to_actor_id"]
                or link["from_run_id"] != links[index - 1]["to_run_id"]
            ):
                return False
            if link["to_actor_id"] in seen:
                return False
            seen.add(link["to_actor_id"])
    allowed = set(registry["allowed_public_text_sha256"])
    if request["operation"]["type"] == "embedding.create":
        data = request["input"]
        if (
            canonical(data["profile"]) != canonical(config["embedding_profile"])
            or (data["role"] == "query" and len(data["items"]) != 1)
            or len({item["item_id"] for item in data["items"]}) != len(data["items"])
        ):
            return False
        if any(public_text_digest(item["text"]) not in allowed for item in data["items"]):
            return False
    elif request["operation"]["type"] == "rerank":
        data = request["input"]
        if (
            data["ranking_profile_id"] != config["ranking_profile_id"]
            or data["corpus_version"] != config["corpus_version"]
            or data["index_version"] != config["index_version"]
            or data["top_k"] > len(data["candidates"])
            or len({item["candidate_id"] for item in data["candidates"]}) != len(data["candidates"])
            or public_text_digest(data["query"]) not in allowed
        ):
            return False
        if any(
            public_text_digest(item["text"]) not in allowed
            or item["content_digest"] != content_digest(item)
            for item in data["candidates"]
        ):
            return False
    else:
        return False
    return price_for(request, registry) is not None


def classify_request(
    request: object, trusted: Record, registry: Record = REGISTRATIONS, *, fresh: bool = True
) -> str:
    if not schema_valid(request, SCHEMAS["$defs"]["RequestEnvelope"]):
        return "SCHEMA_INVALID"
    request = cast(Record, request)
    if request["contract_version"] != "0.3":
        return "UNSUPPORTED_VERSION"
    op = request["operation"]
    if (
        request["capability_profile"] != "retrieval-synthetic@1"
        or op["type"] not in ("embedding.create", "rerank")
        or op["version"] != 1
    ):
        return "CAPABILITY_UNSUPPORTED"
    if not schema_valid(request, SCHEMAS["$defs"]["SubmitRequest"]):
        return "SCHEMA_INVALID"
    return (
        "ACCEPT"
        if semantic_request(request, trusted, registry, fresh=fresh)
        else "SEMANTIC_INVALID"
    )


_DECIMAL = re.compile(r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]{1,3})?$")


def decimal_valid(value: object, score: bool = False) -> bool:
    if type(value) is not str or _DECIMAL.fullmatch(value) is None:
        return False
    try:
        number = Decimal(value)
    except InvalidOperation:
        return False
    if number.is_zero() and number.is_signed():
        return False
    mantissa, _, exponent = value.lower().partition("e")
    if (
        len(mantissa.replace("-", "").replace(".", "").lstrip("0")) > 17
        or abs(int(exponent or "0")) > 100
        or abs(number) > 1000000
    ):
        return False
    return not score or 0 <= number <= 1


def result_valid(
    result: object, request: Record, attempt_id: str, registry: Record = REGISTRATIONS
) -> bool:
    if (
        not schema_valid(result, SCHEMAS["$defs"]["Result"])
        or cast(Record, result)["attempt_id"] != attempt_id
        or canonical(cast(Record, result)["operation"]) != canonical(request["operation"])
    ):
        return False
    result = cast(Record, result)
    config = config_for(request, registry)
    if not config:
        return False
    if result["operation"]["type"] == "embedding.create":
        profile = config["embedding_profile"]
        if (
            result["profile_id"] != profile["profile_id"]
            or result["model_ref"] != profile["model_ref"]
            or result["dimensions"] != profile["dimensions"]
            or len(result["vectors"]) != len(request["input"]["items"])
        ):
            return False
        return all(
            vector["input_index"] == index
            and vector["item_id"] == item["item_id"]
            and len(vector["values"]) == profile["dimensions"]
            and all(decimal_valid(value) for value in vector["values"])
            for index, (vector, item) in enumerate(
                zip(result["vectors"], request["input"]["items"], strict=True)
            )
        )
    if (
        result["ranking_profile_id"] != config["ranking_profile_id"]
        or len(result["results"]) != request["input"]["top_k"]
    ):
        return False
    seen = set()
    previous = None
    for index, row in enumerate(result["results"]):
        input_index = row["input_index"]
        if (
            row["rank"] != index + 1
            or input_index >= len(request["input"]["candidates"])
            or row["candidate_id"] != request["input"]["candidates"][input_index]["candidate_id"]
            or row["candidate_id"] in seen
            or not decimal_valid(row["score"], True)
        ):
            return False
        if previous is not None:
            previous_score = Decimal(previous["score"])
            score = Decimal(row["score"])
            if previous_score < score or (
                previous_score == score and previous["input_index"] > input_index
            ):
                return False
        seen.add(row["candidate_id"])
        previous = row
    return True


def tariff(request: Record, price: Record) -> Record:
    count = len(
        request["input"]["candidates"]
        if request["operation"]["type"] == "rerank"
        else request["input"]["items"]
    )
    kind = price["schedule_kind"]
    sections = {
        "tariff_a": "schedule_a",
        "tariff_b": "schedule_b",
        "embedding_document": "embedding_document",
        "embedding_query": "embedding_query",
    }
    if kind not in sections:
        raise ValueError("unregistered tariff")
    schedule = TARIFFS[sections[kind]]
    if (
        price["price_ref"] != schedule["id"]
        or price["component"] != schedule["unit"]
        or price["currency"] != TARIFFS["currency"]
        or price["maximum_bound_decimal"] != schedule["maximum_domain_bound_usd"]
    ):
        raise ValueError("tariff registration mismatch")
    minimum, maximum = (
        (TARIFFS["domain"][key] for key in ("minimum_documents", "maximum_documents"))
        if kind in {"tariff_a", "tariff_b"}
        else (schedule["minimum_items"], schedule["maximum_items"])
    )
    if (minimum, maximum) != (price["minimum_items"], price["maximum_items"]):
        raise ValueError("tariff registration domain mismatch")
    if not minimum <= count <= maximum:
        raise ValueError("tariff cardinality outside registered domain")

    def rate(key: str) -> Decimal:
        if type(schedule[key]) is not str:
            raise ValueError("invalid tariff rate")
        try:
            value = Decimal(schedule[key])
        except InvalidOperation as exc:
            raise ValueError("invalid tariff rate") from exc
        if not value.is_finite() or value < 0:
            raise ValueError("invalid tariff rate")
        return value

    if kind == "tariff_a":
        # This is the registered tariff formula, never an evaluated expression.
        match = re.fullmatch(r"ceil\(documents/([1-9][0-9]*)\)", schedule["units_formula"])
        if not match:
            raise ValueError("unsupported tariff formula")
        divisor = int(match[1])
        quantity = (count + divisor - 1) // divisor
        raw = max(rate("minimum_per_attempt_usd"), rate("per_unit_usd") * quantity)
    elif kind == "tariff_b":
        quantity = count
        raw = Decimal(count) * rate(
            "whole_request_tier_le_10_usd" if count <= 10 else "whole_request_tier_ge_11_usd"
        )
    else:
        quantity = count
        raw = Decimal(count) * rate("per_item_usd")
    if raw.quantize(QUANTUM, rounding=ROUND_CEILING) > Decimal(price["maximum_bound_decimal"]):
        raise ValueError("tariff exceeds registered maximum")
    return {
        "quantity": quantity,
        "settled": money(raw.quantize(QUANTUM, rounding=ROUND_HALF_EVEN)),
        "bound": money(raw.quantize(QUANTUM, rounding=ROUND_CEILING)),
    }


def usage_valid(
    row: dict[str, Any],
    request: dict[str, Any],
    attempt_id: str,
    price_ref: str,
    usage_ref: str,
    max_exposure_decimal: str,
) -> bool:
    """Validate a complete native row against independently admitted request/price scope."""
    if (
        not schema_valid(row, SCHEMAS["$defs"]["UsageRevision"])
        or row["attempt_id"] != attempt_id
        or row["price_ref"] != price_ref
        or row["usage_semantics_ref"] != usage_ref
    ):
        return False
    price = price_for(request)
    if not price or price["price_ref"] != price_ref or price["usage_ref"] != usage_ref:
        return False
    component = row["components"][0]
    if component["component"] != price["component"]:
        return False
    expected = tariff(request, price)
    reported = (
        component["presence"] == "known"
        and component["evidence"] == "reported"
        and component["quantity"] == expected["quantity"]
    )
    if row["cost_status"] == "unknown":
        return "amount_decimal" not in row and not reported
    if not reported or row["amount_decimal"] != expected["settled"]:
        return False
    over = Decimal(row["amount_decimal"]) > Decimal(max_exposure_decimal)
    return cast(bool, row["cost_status"] == ("over_bound" if over else "calculated"))


def native_usage_row(
    request: Record,
    attempt_id: str,
    revision: int,
    component: Record,
    max_exposure_decimal: str,
    previous_revision: int | None = None,
) -> Record:
    """Project actual receiver evidence; absent/insufficient evidence stays unknown."""
    price = price_for(request)
    if price is None or component.get("component") != price["component"]:
        raise ValueError("unregistered native component")
    row = {
        "attempt_id": attempt_id,
        "revision": revision,
        "usage_semantics_ref": price["usage_ref"],
        "price_ref": price["price_ref"],
        "components": [component],
    }
    if previous_revision is not None:
        row["previous_revision"] = previous_revision
    expected = tariff(request, price)
    if (
        component.get("presence") == "known"
        and component.get("evidence") == "reported"
        and component.get("quantity") == expected["quantity"]
    ):
        row["amount_decimal"] = expected["settled"]
        row["cost_status"] = (
            "over_bound"
            if Decimal(expected["settled"]) > Decimal(max_exposure_decimal)
            else "calculated"
        )
    else:
        row["cost_status"] = "unknown"
    if not usage_valid(
        row, request, attempt_id, price["price_ref"], price["usage_ref"], max_exposure_decimal
    ):
        raise ValueError("invalid native usage evidence")
    return row
