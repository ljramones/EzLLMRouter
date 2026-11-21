"""Restricted ezllmrouter-work-v0.2 canonicalization for the development slice."""

from __future__ import annotations
import hashlib
import re
from decimal import Decimal, InvalidOperation
from typing import cast
from collections.abc import Collection
from .records import Record
from .execution_policy import MAX_ATTEMPT_TIMEOUT_MS as MAX_ATTEMPT_TIMEOUT_MS
from .json_validation import JSONValue
from .errors import RequestError
from .formatting import parse_utc_second, utc_timestamp
from .identifiers import valid_identifier
from .json_validation import (
    MAX_SAFE_INTEGER,
    WORK_V02,
    JSONValidationError,
    canonical_json,
    decode_json,
    validate_json,
)

PREFIX = b"ezllmrouter-work-v0.2\n"
SAFE = MAX_SAFE_INTEGER
MAX_OUTPUT_TOKENS = 32768
_DECIMAL = re.compile("^(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?$")


class ContractError(RequestError):
    def __init__(self, code: str, status: int = 422):
        super().__init__(code)
        self.code, self.status = (code, status)


def strict_loads(data: bytes) -> JSONValue:
    try:
        return decode_json(data, WORK_V02)
    except JSONValidationError as exc:
        raise ContractError(exc.code, exc.status) from exc


def restricted(value: object, depth: int = 0) -> None:
    try:
        validate_json(value, WORK_V02, depth)
    except JSONValidationError as exc:
        raise ContractError(exc.code, exc.status) from exc


def jcs(value: object) -> bytes:
    """The contract's UTF-16-sorted, safe-integer, no-null JCS profile."""
    restricted(value)
    return canonical_json(value, utf16_keys=True).encode("utf-8")


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def decimal_lexical(value: str) -> str:
    if not isinstance(value, str) or not _DECIMAL.fullmatch(value):
        raise ContractError("SCHEMA_INVALID", 400)
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ContractError("SCHEMA_INVALID", 400) from exc
    if not number.is_finite() or number < 0:
        raise ContractError("SCHEMA_INVALID", 400)
    return value.rstrip("0").rstrip(".") if "." in value else value


def utc_second(value: str) -> str:
    try:
        return utc_timestamp(parse_utc_second(value, allow_offset=True))
    except ValueError as exc:
        raise ContractError("SCHEMA_INVALID", 400) from exc


def ident(value: object) -> str:
    if not valid_identifier(value):
        raise ContractError("SCHEMA_INVALID", 400)
    return value


def exact_keys(obj: object, required: Collection[str], optional: Collection[str] = ()) -> Record:
    if (
        not isinstance(obj, dict)
        or not set(required) <= set(obj)
        or set(obj) - set(required) - set(optional)
    ):
        raise ContractError("SCHEMA_INVALID", 400)
    return cast(Record, obj)


def _labels(labels: object) -> Record:
    labels = exact_keys(labels, ("lineage_ids", "sensitivity", "restrictions"))
    if labels["sensitivity"] not in ("public", "internal", "confidential", "restricted"):
        raise ContractError("SCHEMA_INVALID", 400)
    result = dict(labels)
    for key in ("lineage_ids", "restrictions"):
        values = labels[key]
        if (
            not isinstance(values, list)
            or (key == "lineage_ids" and (not values))
            or (not all((isinstance(v, str) for v in values)))
        ):
            raise ContractError("SCHEMA_INVALID", 400)
        if len(values) != len(set(values)):
            raise ContractError("SCHEMA_INVALID", 400)
        result[key] = sorted((ident(v) for v in values), key=lambda x: x.encode("utf-16-be"))
    return result


def _tool_schema_shape(value: object, depth: int = 0) -> None:
    if depth > 16:
        raise ContractError("LIMIT_EXCEEDED", 413)
    value = exact_keys(
        value,
        ("type",),
        (
            "properties",
            "required",
            "items",
            "enum",
            "minLength",
            "maxLength",
            "pattern",
            "minimum",
            "maximum",
        ),
    )
    if value["type"] not in ("object", "array", "string", "integer", "boolean"):
        raise ContractError("SCHEMA_INVALID", 400)
    if "properties" in value:
        if not isinstance(value["properties"], dict):
            raise ContractError("SCHEMA_INVALID", 400)
        for key, child in value["properties"].items():
            if not isinstance(key, str):
                raise ContractError("SCHEMA_INVALID", 400)
            _tool_schema_shape(child, depth + 1)
    if "items" in value:
        _tool_schema_shape(value["items"], depth + 1)
    if "required" in value:
        names = value["required"]
        if (
            not isinstance(names, list)
            or not all((isinstance(x, str) for x in names))
            or len(names) != len(set(names))
        ):
            raise ContractError("SCHEMA_INVALID", 400)
    if "enum" in value and (not isinstance(value["enum"], list) or not value["enum"]):
        raise ContractError("SCHEMA_INVALID", 400)
    for key in ("minLength", "maxLength"):
        if key in value and (type(value[key]) is not int or not 0 <= value[key] <= SAFE):
            raise ContractError("SCHEMA_INVALID", 400)
    for key in ("minimum", "maximum"):
        if key in value and (type(value[key]) is not int or abs(value[key]) > SAFE):
            raise ContractError("SCHEMA_INVALID", 400)
    if "pattern" in value and (not isinstance(value["pattern"], str)):
        raise ContractError("SCHEMA_INVALID", 400)


def validate_text_request(
    req: object,
    trusted: Record,
    config: Record,
    prompt_blocks: list[Record],
    allowed_lineages: Collection[str],
) -> tuple[list[Record], Record, str, str]:
    """Resolve trusted prompt and the pinned, caller-owned lookup subset."""
    from .request_validation import validate_text_request as validate

    return validate(req, trusted, config, prompt_blocks, allowed_lineages)


def projection(
    req: Record,
    trusted: Record,
    config: Record,
    messages: list[Record],
    settings: Record,
    deadline: str,
    prompt_digest: str,
) -> Record:
    prompt = req["resolved_prompt"]
    work = {
        "task_id": req["task_id"],
        "task_class": req["task_class"],
        "step_class": req["step_class"],
        "step_id": req["step_id"],
        "step_revision": req["step_revision"],
        "execution_generation": req["execution_generation"],
        "purpose": req["purpose"],
        "destination_config_id": req["requested_configuration_ref"],
        "requested_features": sorted(
            req["requested_features"], key=lambda x: x.encode("utf-16-be")
        ),
        "resolved_prompt": {
            "prompt_id": prompt["prompt_id"],
            "prompt_version": prompt["prompt_version"],
            "block_ids": prompt["block_ids"],
            "resolved_digest": prompt_digest,
        },
        "messages": messages,
        "tool_definitions": req.get("tool_definitions", []),
        "tool_choice": req.get("tool_choice", "none"),
        "generation_settings": settings,
        "deadline": deadline,
    }
    return {
        "projection_version": "ezllmrouter-work-v0.2",
        "trusted": {
            k: trusted[k]
            for k in ("principal_id", "charging_owner_id", "source_authority_id", "context_id")
        },
        "work": work,
        "destination": config,
    }


def work_digest(value: object) -> str:
    return digest(PREFIX + jcs(value))
