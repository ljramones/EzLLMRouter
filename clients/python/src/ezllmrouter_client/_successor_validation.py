"""Bounded shape and correlation checks for explicitly selected wire 0.3."""

from importlib.resources import files
from decimal import Decimal, InvalidOperation
import json
import re
from typing import Any

from ._schema_validation import validate

SCHEMAS = json.loads(files("ezllmrouter_client").joinpath("dev12_schemas.json").read_text())


def schema(value: Any, shape: dict[str, Any]) -> bool:
    return bool(validate(value, shape, SCHEMAS["$defs"], public_text=True))


def named_shape(value: Any, name: Any) -> bool:
    return bool(schema(value, SCHEMAS["$defs"][name]))


def matches_selector(handle: Any, selector: Any) -> bool:
    if not named_shape(handle, "Handle"):
        return False
    if "submission_id" in selector:
        return bool(handle["submission_id"] == selector["submission_id"])
    return bool(
        all(
            handle["work_key"][key] == selector[key]
            for key in ("task_id", "step_id", "step_revision", "execution_generation")
        )
    )


_DECIMAL = re.compile(r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]{1,3})?$")


def decimal_value(value: Any, *, score: Any = False) -> Decimal | None:
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


def result_valid(result: Any, attempt_id: Any, request: Any = None) -> bool:
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
    scores: list[Decimal] = []
    for index, item in enumerate(ranking):
        score = decimal_value(item["score"], score=True)
        if item["rank"] != index + 1 or score is None:
            return False
        if scores and (
            scores[-1] < score
            or scores[-1] == score
            and ranking[index - 1]["input_index"] > item["input_index"]
        ):
            return False
        scores.append(score)
    if request is None:
        return bool(len({item["candidate_id"] for item in ranking}) == len(ranking))
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


def error_valid(value: Any, http_status: Any, kind: Any) -> bool:
    if not named_shape(value, "ErrorResponse"):
        return False
    if http_status == 401:
        return bool(value["code"] == "POLICY_DENIED" and value["retry_guidance"] == "never")
    if ERROR_HTTP.get(value["code"]) != http_status:
        return False
    if value["code"] == "INTENT_PERSIST_FAILED":
        return bool(value["retry_guidance"] == "query_first")
    if value["code"] in ("WORK_CONFLICT", "WORK_VERSION_CONFLICT"):
        return bool(value["retry_guidance"] == "never")
    if value["code"] == "POLICY_DENIED" and value["retry_guidance"] == "query_first":
        return bool(kind == "submit")
    return True


def native_usage_valid(usage: Any) -> bool:
    component = usage["components"][0]
    if usage["cost_status"] == "unknown":
        return bool("amount_decimal" not in usage)
    return bool(
        component["presence"] == "known"
        and component["evidence"] == "reported"
        and type(component["quantity"]) is int
        and component["quantity"] > 0
        and "amount_decimal" in usage
    )


def failed_status(value: Any) -> int | None:
    code = value["error"]["code"]
    if value["failure_stage"] == "before_send":
        if code == "INTENT_PERSIST_FAILED":
            return 503
        return 409 if code in ("FDC_REJECTED", "PLAN_INVALID_OR_STALE") else None
    return 502 if code in ("RESULT_INVALID", "USAGE_UNKNOWN") else None


def response_valid(
    value: Any, name: Any, http_status: Any, selector: Any, request: Any = None
) -> bool:
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
        return bool(
            (state != "completed" or result_valid(value["result"], value["attempt_id"], request))
            and (state != "failed" or error_valid(value["error"], http_status, "submit"))
        )
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
        return bool(
            item["delivery_state"] == "valid"
            and (
                access == "present"
                and "result" in item
                or access == "expired"
                and "result" not in item
            )
        )
    if state == "failed":
        return bool(
            access == "unavailable_due_failure"
            and "failure" in item
            and "result" not in item
            and item["delivery_state"] in ("invalid", "pending")
        )
    if state == "unknown":
        return bool(
            access == "unknown_outcome"
            and item["dispatch_state"] == "possible_send"
            and item["delivery_state"] == "unknown"
            and "result" not in item
        )
    return bool(
        access == "not_yet_available"
        and item["delivery_state"] == "pending"
        and "result" not in item
    )
