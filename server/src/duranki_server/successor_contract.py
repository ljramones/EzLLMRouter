"""Product-side wire-0.3 synthetic retrieval contract and exact native tariffs.

The JSON inputs are byte copies of the adopted A1 candidate-04 registries. This
module intentionally does not import its offline JavaScript reference checker.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_EVEN
from hashlib import sha256
from importlib.resources import files
import json
import re

from .canonical import ContractError

SAFE = 9007199254740991
QUANTUM = Decimal("0.000000001")
SCHEMAS = json.loads(files("duranki_server").joinpath("dev12/schemas.json").read_text())
REGISTRATIONS = json.loads(files("duranki_server").joinpath("dev12/registrations.json").read_text())
TARIFFS = json.loads(files("duranki_server").joinpath("dev12/tariffs.json").read_text())


def strict_decode(data: bytes):
    if type(data) is not bytes:
        raise ContractError("MALFORMED_JSON", 400)
    if len(data) > 262144:
        raise ContractError("LIMIT_EXCEEDED", 413)
    try:
        text = data.decode("utf-8", "strict")

        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError("duplicate decoded key")
                result[key] = value
            return result

        def integer(raw):
            value = int(raw)
            if abs(value) > SAFE:
                raise ValueError("unsafe integer")
            return value

        def reject(_raw):
            raise ValueError("unsupported JSON number")

        value = json.loads(text, object_pairs_hook=pairs, parse_int=integer,
                           parse_float=reject, parse_constant=reject)
        _restricted(value)
        return value
    except (UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, ContractError):
            raise
        raise ContractError("MALFORMED_JSON", 400) from exc


def _restricted(value, depth=0):
    if depth > 32:
        raise ContractError("LIMIT_EXCEEDED", 413)
    if type(value) is str:
        if any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
            raise ContractError("MALFORMED_JSON", 400)
    elif type(value) is int:
        if abs(value) > SAFE:
            raise ContractError("MALFORMED_JSON", 400)
    elif type(value) is bool or value is None:
        return
    elif type(value) is list:
        for item in value:
            _restricted(item, depth + 1)
    elif type(value) is dict:
        for key, item in value.items():
            _restricted(key, depth + 1)
            _restricted(item, depth + 1)
    else:
        raise ContractError("MALFORMED_JSON", 400)


def schema_valid(value, schema, bundle=SCHEMAS):
    if "$ref" in schema:
        match = re.fullmatch(r"#/\$defs/([A-Za-z][A-Za-z0-9]*)", schema["$ref"])
        if not match or match[1] not in bundle["$defs"]:
            raise ValueError("unresolved local schema reference")
        return schema_valid(value, bundle["$defs"][match[1]], bundle)
    if "oneOf" in schema:
        return sum(schema_valid(value, part, bundle) for part in schema["oneOf"]) == 1
    if "const" in schema and (type(value) is not type(schema["const"]) or value != schema["const"]):
        return False
    if "enum" in schema and not any(type(value) is type(item) and value == item for item in schema["enum"]):
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
        if (type(value) is not list or len(value) < schema.get("minItems", 0) or
                len(value) > schema.get("maxItems", float("inf"))):
            return False
        return all(schema_valid(item, schema["items"], bundle) for item in value)
    elif kind == "string":
        if type(value) is not str or any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
            return False
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", float("inf")):
            return False
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            return False
    elif kind == "integer":
        if (type(value) is not int or abs(value) > SAFE or value < schema.get("minimum", -float("inf")) or
                value > schema.get("maximum", float("inf"))):
            return False
    elif kind == "boolean" and type(value) is not bool:
        return False
    return True


def canonical(value):
    """A1's ASCII-key-order canonical JSON for its restricted value domain."""
    if type(value) is dict:
        return "{" + ",".join(canonical(key) + ":" + canonical(value[key]) for key in sorted(value)) + "}"
    if type(value) is list:
        return "[" + ",".join(canonical(item) for item in value) + "]"
    if type(value) is str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if type(value) is int:
        if abs(value) > SAFE:
            raise ValueError("unsafe canonical integer")
        return str(value)
    if type(value) is bool:
        return "true" if value else "false"
    if value is None:
        return "null"
    raise TypeError("unsupported canonical value")


def digest(prefix: str, value) -> str:
    return "sha256:" + sha256((prefix + canonical(value)).encode("utf-8")).hexdigest()


def work_projection(request, trusted):
    return {"schema_id": "duranki-work-v0.3", "profile": request["capability_profile"],
            "work_key": {"principal_id": trusted["identity"]["principal_id"], **request["work_selector"]},
            "operation": request["operation"], "input": request["input"],
            "metadata": request["metadata"], "trusted": trusted["identity"],
            "purpose": request["purpose"], "task_class": request["task_class"],
            "requested_configuration_ref": request["requested_configuration_ref"],
            "deadline": request["deadline"], "handling_profile": request["handling_profile"]}


def work_digest(work):
    op = work["operation"]
    return digest(f"duranki-work-v0.3\n{op['type']}@{op['version']}\n", work)


def utc_second(value):
    if type(value) is not str or re.fullmatch(
            r"[0-9]{4}-(0[1-9]|1[0-2])-([0-2][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]Z", value) is None:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") == value
    except ValueError:
        return False


def public_text_digest(text):
    return "sha256:" + sha256(("duranki-public-text-v1\n" + text).encode()).hexdigest()


def content_digest(candidate):
    text = "duranki-content-v1\n" + candidate["content_version"] + "\n" + candidate["text"]
    return "sha256:" + sha256(text.encode()).hexdigest()


def config_for(request, registry=REGISTRATIONS):
    return next((item for item in registry["configurations"]
                 if item["configuration_ref"] == request["requested_configuration_ref"]), None)


def price_for(request, registry=REGISTRATIONS):
    config = config_for(request, registry)
    if not config:
        return None
    ref = (config["price_ref"] if request["operation"]["type"] == "rerank" else
           config["role_price_refs"].get(request["input"]["role"]))
    return next((item for item in registry["price_contracts"] if item["price_ref"] == ref), None)


def semantic_request(request, trusted, registry=REGISTRATIONS, *, fresh=True):
    metadata, identity = request["metadata"], trusted["identity"]
    config = config_for(request, registry)
    if not all(utc_second(item) for item in (request["deadline"], trusted["authenticated_at"], trusted["expires_at"])):
        return False
    if fresh and not trusted["authenticated_at"] < request["deadline"] <= trusted["expires_at"]:
        return False
    if (request["handling_profile"] != registry["handling_profile"] or not config or
            canonical(config["operation"]) != canonical(request["operation"])):
        return False
    if (metadata["root_workflow_id"] != trusted["allowed_root_workflow_id"] or
            metadata["run_id"] != trusted["authenticated_current_run_id"] or
            ("initiating_user_id" in metadata and metadata["initiating_user_id"] != trusted.get("allowed_initiating_user_id"))):
        return False
    mode = metadata["invocation_mode"]
    if mode == "direct_human" and (identity["actor_kind"] != "human" or
                                   identity["actor_id"] != metadata.get("initiating_user_id")):
        return False
    if mode == "autonomous_service" and (identity["actor_kind"] != "service" or
                                          "initiating_user_id" in metadata):
        return False
    if mode == "delegated_agent":
        links = metadata["delegation"]
        if (identity["actor_kind"] != "agent" or not links or
                links[0]["from_actor_id"] != metadata.get("initiating_user_id")):
            return False
        last = links[-1]
        if (last["to_actor_id"] != identity["actor_id"] or last["to_run_id"] != metadata["run_id"] or
                last["from_run_id"] != metadata.get("parent_run_id")):
            return False
        seen = {links[0]["from_actor_id"]}
        for index, link in enumerate(links):
            if index and (link["from_actor_id"] != links[index - 1]["to_actor_id"] or
                          link["from_run_id"] != links[index - 1]["to_run_id"]):
                return False
            if link["to_actor_id"] in seen:
                return False
            seen.add(link["to_actor_id"])
    allowed = set(registry["allowed_public_text_sha256"])
    if request["operation"]["type"] == "embedding.create":
        data = request["input"]
        if (canonical(data["profile"]) != canonical(config["embedding_profile"]) or
                (data["role"] == "query" and len(data["items"]) != 1) or
                len({item["item_id"] for item in data["items"]}) != len(data["items"])):
            return False
        if any(public_text_digest(item["text"]) not in allowed for item in data["items"]):
            return False
    elif request["operation"]["type"] == "rerank":
        data = request["input"]
        if (data["ranking_profile_id"] != config["ranking_profile_id"] or
                data["corpus_version"] != config["corpus_version"] or
                data["index_version"] != config["index_version"] or
                data["top_k"] > len(data["candidates"]) or
                len({item["candidate_id"] for item in data["candidates"]}) != len(data["candidates"]) or
                public_text_digest(data["query"]) not in allowed):
            return False
        if any(public_text_digest(item["text"]) not in allowed or
               item["content_digest"] != content_digest(item) for item in data["candidates"]):
            return False
    else:
        return False
    return price_for(request, registry) is not None


def classify_request(request, trusted, registry=REGISTRATIONS, *, fresh=True):
    if not schema_valid(request, SCHEMAS["$defs"]["RequestEnvelope"]):
        return "SCHEMA_INVALID"
    if request["contract_version"] != "0.3":
        return "UNSUPPORTED_VERSION"
    op = request["operation"]
    if (request["capability_profile"] != "retrieval-synthetic@1" or
            op["type"] not in ("embedding.create", "rerank") or op["version"] != 1):
        return "CAPABILITY_UNSUPPORTED"
    if not schema_valid(request, SCHEMAS["$defs"]["SubmitRequest"]):
        return "SCHEMA_INVALID"
    return "ACCEPT" if semantic_request(request, trusted, registry, fresh=fresh) else "SEMANTIC_INVALID"


_DECIMAL = re.compile(r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]{1,3})?$")


def decimal_valid(value, score=False):
    if type(value) is not str or _DECIMAL.fullmatch(value) is None:
        return False
    try:
        number = Decimal(value)
    except Exception:
        return False
    if number.is_zero() and number.is_signed():
        return False
    mantissa, _, exponent = value.lower().partition("e")
    if (len(mantissa.replace("-", "").replace(".", "").lstrip("0")) > 17 or
            abs(int(exponent or "0")) > 100 or abs(number) > 1000000):
        return False
    return not score or 0 <= number <= 1


def result_valid(result, request, attempt_id, registry=REGISTRATIONS):
    if (not schema_valid(result, SCHEMAS["$defs"]["Result"]) or
            result["attempt_id"] != attempt_id or
            canonical(result["operation"]) != canonical(request["operation"])):
        return False
    config = config_for(request, registry)
    if not config:
        return False
    if result["operation"]["type"] == "embedding.create":
        profile = config["embedding_profile"]
        if (result["profile_id"] != profile["profile_id"] or
                result["model_ref"] != profile["model_ref"] or
                result["dimensions"] != profile["dimensions"] or
                len(result["vectors"]) != len(request["input"]["items"])):
            return False
        return all(vector["input_index"] == index and vector["item_id"] == item["item_id"] and
                   len(vector["values"]) == profile["dimensions"] and
                   all(decimal_valid(value) for value in vector["values"])
                   for index, (vector, item) in enumerate(zip(result["vectors"], request["input"]["items"])))
    if (result["ranking_profile_id"] != config["ranking_profile_id"] or
            len(result["results"]) != request["input"]["top_k"]):
        return False
    seen = set()
    previous = None
    for index, row in enumerate(result["results"]):
        input_index = row["input_index"]
        if (row["rank"] != index + 1 or input_index >= len(request["input"]["candidates"]) or
                row["candidate_id"] != request["input"]["candidates"][input_index]["candidate_id"] or
                row["candidate_id"] in seen or not decimal_valid(row["score"], True)):
            return False
        if previous is not None:
            previous_score = Decimal(previous["score"])
            score = Decimal(row["score"])
            if previous_score < score or (previous_score == score and previous["input_index"] > input_index):
                return False
        seen.add(row["candidate_id"])
        previous = row
    return True


def tariff(request, price):
    count = len(request["input"]["candidates"] if request["operation"]["type"] == "rerank"
                else request["input"]["items"])
    kind = price["schedule_kind"]
    if kind == "tariff_a":
        quantity = (count + 9) // 10
        raw = max(Decimal("0.005"), Decimal("0.003") * quantity)
    elif kind == "tariff_b":
        quantity = count
        raw = Decimal(count) * Decimal("0.0003000005" if count <= 10 else "0.0004000005")
    elif kind in ("embedding_document", "embedding_query"):
        quantity = count
        raw = Decimal(count) * Decimal("0.000200000")
    else:
        raise ValueError("unregistered tariff")
    return {"quantity": quantity,
            "settled": str(raw.quantize(QUANTUM, rounding=ROUND_HALF_EVEN)),
            "bound": str(raw.quantize(QUANTUM, rounding=ROUND_CEILING))}


def usage_valid(row, request, attempt_id, price_ref, usage_ref, max_exposure_decimal):
    """Validate a complete native row against independently admitted request/price scope."""
    if (not schema_valid(row, SCHEMAS["$defs"]["UsageRevision"]) or
            row["attempt_id"] != attempt_id or row["price_ref"] != price_ref or
            row["usage_semantics_ref"] != usage_ref):
        return False
    price = price_for(request)
    if not price or price["price_ref"] != price_ref or price["usage_ref"] != usage_ref:
        return False
    component = row["components"][0]
    if component["component"] != price["component"]:
        return False
    expected = tariff(request, price)
    reported = (component["presence"] == "known" and component["evidence"] == "reported" and
                component["quantity"] == expected["quantity"])
    if row["cost_status"] == "unknown":
        return "amount_decimal" not in row and not reported
    if not reported or row["amount_decimal"] != expected["settled"]:
        return False
    over = Decimal(row["amount_decimal"]) > Decimal(max_exposure_decimal)
    return row["cost_status"] == ("over_bound" if over else "calculated")


def native_usage_row(request, attempt_id, revision, component, max_exposure_decimal,
                     previous_revision=None):
    """Project actual receiver evidence; absent/insufficient evidence stays unknown."""
    price = price_for(request)
    if price is None or component.get("component") != price["component"]:
        raise ValueError("unregistered native component")
    row = {"attempt_id": attempt_id, "revision": revision,
           "usage_semantics_ref": price["usage_ref"], "price_ref": price["price_ref"],
           "components": [component]}
    if previous_revision is not None:
        row["previous_revision"] = previous_revision
    expected = tariff(request, price)
    if (component.get("presence") == "known" and component.get("evidence") == "reported" and
            component.get("quantity") == expected["quantity"]):
        row["amount_decimal"] = expected["settled"]
        row["cost_status"] = ("over_bound" if Decimal(expected["settled"]) >
                              Decimal(max_exposure_decimal) else "calculated")
    else:
        row["cost_status"] = "unknown"
    if not usage_valid(row, request, attempt_id, price["price_ref"], price["usage_ref"], max_exposure_decimal):
        raise ValueError("invalid native usage evidence")
    return row
