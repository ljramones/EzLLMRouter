"""Bounded shape and correlation checks for explicitly selected wire 0.3."""

from importlib.resources import files
from decimal import Decimal, InvalidOperation
import json
import re

SCHEMAS = json.loads(files("ezllmrouter_client").joinpath("dev12_schemas.json").read_text())


def schema(value, shape):
    if "$ref" in shape:
        match = re.fullmatch(r"#/\$defs/([A-Za-z][A-Za-z0-9]*)", shape["$ref"])
        if not match or match[1] not in SCHEMAS["$defs"]:
            raise ValueError("unresolved successor schema")
        return schema(value, SCHEMAS["$defs"][match[1]])
    if "oneOf" in shape:
        return sum(schema(value, part) for part in shape["oneOf"]) == 1
    if "const" in shape and (type(value) is not type(shape["const"]) or value != shape["const"]):
        return False
    if "enum" in shape and not any(
        type(value) is type(item) and value == item for item in shape["enum"]
    ):
        return False
    kind = shape.get("type")
    if kind == "object":
        if type(value) is not dict or any(key not in value for key in shape.get("required", ())):
            return False
        properties = shape.get("properties", {})
        return all(
            (key in properties and schema(item, properties[key]))
            or (key not in properties and shape.get("additionalProperties") is not False)
            for key, item in value.items()
        )
    if kind == "array":
        return (
            type(value) is list
            and shape.get("minItems", 0) <= len(value) <= shape.get("maxItems", float("inf"))
            and all(schema(item, shape["items"]) for item in value)
        )
    if kind == "string":
        return (
            type(value) is str
            and shape.get("minLength", 0) <= len(value) <= shape.get("maxLength", float("inf"))
            and all(
                ord(c) >= 32 and ord(c) != 127 and not 0xD800 <= ord(c) <= 0xDFFF for c in value
            )
            and ("pattern" not in shape or re.search(shape["pattern"], value) is not None)
        )
    if kind == "integer":
        return (
            type(value) is int
            and abs(value) <= 9007199254740991
            and shape.get("minimum", -float("inf")) <= value <= shape.get("maximum", float("inf"))
        )
    if kind == "boolean":
        return type(value) is bool
    return True


def named_shape(value, name):
    return schema(value, SCHEMAS["$defs"][name])


def matches_selector(handle, selector):
    if not named_shape(handle, "Handle"):
        return False
    if "submission_id" in selector:
        return handle["submission_id"] == selector["submission_id"]
    return all(
        handle["work_key"][key] == selector[key]
        for key in ("task_id", "step_id", "step_revision", "execution_generation")
    )


_DECIMAL = re.compile(r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]{1,3})?$")


def decimal_value(value, *, score=False):
    if type(value) is not str or _DECIMAL.fullmatch(value) is None:
        return None
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    mantissa, _, exponent = value.lower().partition("e")
    if (
        number.is_signed()
        and number.is_zero()
        or len(mantissa.replace("-", "").replace(".", "").lstrip("0")) > 17
        or abs(int(exponent or "0")) > 100
        or abs(number) > 1000000
        or score
        and not 0 <= number <= 1
    ):
        return None
    return number


def result_valid(result, attempt_id, request=None):
    if (
        not named_shape(result, "Result")
        or result["attempt_id"] != attempt_id
        or request is not None
        and result["operation"] != request["operation"]
    ):
        return False
    operation = result["operation"]["type"]
    if operation == "embedding.create":
        vectors = result["vectors"]
        if any(
            vector["input_index"] != index
            or vector["values"] is None
            or len(vector["values"]) != result["dimensions"]
            or any(decimal_value(value) is None for value in vector["values"])
            for index, vector in enumerate(vectors)
        ):
            return False
        if request is None:
            return True
        profile = request["input"]["profile"]
        return bool(
            result["profile_id"] == profile["profile_id"]
            and result["model_ref"] == profile["model_ref"]
            and result["dimensions"] == profile["dimensions"]
            and len(vectors) == len(request["input"]["items"])
            and all(
                vector["item_id"] == request["input"]["items"][index]["item_id"]
                for index, vector in enumerate(vectors)
            )
        )
    ranking = result["results"]
    if any(
        item["rank"] != index + 1 or decimal_value(item["score"], score=True) is None
        for index, item in enumerate(ranking)
    ):
        return False
    if any(
        (
            decimal_value(ranking[index - 1]["score"]) < decimal_value(item["score"])
            or decimal_value(ranking[index - 1]["score"]) == decimal_value(item["score"])
            and ranking[index - 1]["input_index"] > item["input_index"]
        )
        for index, item in enumerate(ranking)
        if index
    ):
        return False
    if request is None:
        return len({item["candidate_id"] for item in ranking}) == len(ranking)
    candidates = request["input"]["candidates"]
    return bool(
        result["ranking_profile_id"] == request["input"]["ranking_profile_id"]
        and len(ranking) == request["input"]["top_k"]
        and len({item["candidate_id"] for item in ranking}) == len(ranking)
        and all(
            item["input_index"] < len(candidates)
            and item["candidate_id"] == candidates[item["input_index"]]["candidate_id"]
            for item in ranking
        )
    )


ERROR_HTTP = {
    "UNSUPPORTED_VERSION": 426,
    "MALFORMED_JSON": 400,
    "SCHEMA_INVALID": 400,
    "LIMIT_EXCEEDED": 413,
    "SEMANTIC_INVALID": 422,
    "CAPABILITY_UNSUPPORTED": 422,
    "WORK_CONFLICT": 409,
    "WORK_VERSION_CONFLICT": 409,
    "NOT_FOUND_OR_FORBIDDEN": 404,
    "POLICY_DENIED": 403,
    "FINANCIAL_AUTH_REQUIRED": 403,
    "PLAN_INVALID_OR_STALE": 409,
    "FDC_REJECTED": 409,
    "INTENT_PERSIST_FAILED": 503,
    "RESULT_INVALID": 502,
    "USAGE_UNKNOWN": 502,
}


def error_valid(value, http_status, kind):
    if not named_shape(value, "ErrorResponse"):
        return False
    if http_status == 401:
        return value["code"] == "POLICY_DENIED" and value["retry_guidance"] == "never"
    if ERROR_HTTP.get(value["code"]) != http_status:
        return False
    if value["code"] == "INTENT_PERSIST_FAILED":
        return value["retry_guidance"] == "query_first"
    if value["code"] in ("WORK_CONFLICT", "WORK_VERSION_CONFLICT"):
        return value["retry_guidance"] == "never"
    if value["code"] == "POLICY_DENIED" and value["retry_guidance"] == "query_first":
        return kind == "submit"
    return True


def native_usage_valid(usage):
    component = usage["components"][0]
    if usage["cost_status"] == "unknown":
        return "amount_decimal" not in usage
    return (
        component["presence"] == "known"
        and component["evidence"] == "reported"
        and type(component["quantity"]) is int
        and component["quantity"] > 0
        and "amount_decimal" in usage
    )


def failed_status(value):
    code = value["error"]["code"]
    if value["failure_stage"] == "before_send":
        if code == "INTENT_PERSIST_FAILED":
            return 503
        return 409 if code in ("FDC_REJECTED", "PLAN_INVALID_OR_STALE") else None
    return 502 if code in ("RESULT_INVALID", "USAGE_UNKNOWN") else None


def response_valid(value, name, http_status, selector, request=None):
    if not named_shape(value, name) or not matches_selector(value["handle"], selector):
        return False
    if name == "SubmitReply":
        state = value["state"]
        if http_status != (
            {"completed": 200, "pending": 202, "outcome_unknown": 202}.get(
                state, failed_status(value) if state == "failed" else None
            )
        ):
            return False
        return (
            state != "completed" or result_valid(value["result"], value["attempt_id"], request)
        ) and (state != "failed" or error_valid(value["error"], http_status, "submit"))
    if http_status != 200 or len(value["attempts"]) != 1:
        return False
    item = value["attempts"][0]
    usage = item.get("usage_revision")
    if (
        usage
        and (
            usage["attempt_id"] != item["attempt_id"]
            or item["settlement_state"] != usage["cost_status"]
            or not native_usage_valid(usage)
        )
        or not usage
        and item["settlement_state"] != "pending"
    ):
        return False
    if "result" in item and not result_valid(item["result"], item["attempt_id"]):
        return False
    state, access = value["submission_state"], value["candidate_access"]
    if state == "completed":
        return item["delivery_state"] == "valid" and (
            access == "present" and "result" in item or access == "expired" and "result" not in item
        )
    if state == "failed":
        return (
            access == "unavailable_due_failure"
            and "failure" in item
            and "result" not in item
            and item["delivery_state"] in ("invalid", "pending")
        )
    if state == "unknown":
        return (
            access == "unknown_outcome"
            and item["dispatch_state"] == "possible_send"
            and item["delivery_state"] == "unknown"
            and "result" not in item
        )
    return (
        access == "not_yet_available"
        and item["delivery_state"] == "pending"
        and "result" not in item
    )
