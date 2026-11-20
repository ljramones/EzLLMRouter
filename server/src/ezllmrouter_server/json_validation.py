"""One restricted JSON engine with explicit wire-version policies."""

import json
from dataclasses import dataclass
from typing import NoReturn, TypeVar, cast

from .errors import RequestError

MAX_SAFE_INTEGER = 9007199254740991
type JSONValue = str | int | bool | None | list[JSONValue] | dict[str, JSONValue]
T = TypeVar("T")


class JSONValidationError(RequestError):
    pass


@dataclass(frozen=True)
class JSONPolicy:
    max_bytes: int
    max_depth: int
    allow_null: bool
    reject_controls: bool
    reject_negative_zero: bool
    exact_types: bool
    max_members: int | None = None


WORK_V02 = JSONPolicy(65536, 16, False, False, True, False, 1024)
WORK_V03 = JSONPolicy(262144, 32, True, True, False, True)


def unique_pairs(items: list[tuple[str, T]]) -> dict[str, T]:
    result: dict[str, T] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def reject_number(_value: str) -> NoReturn:
    raise ValueError("unsupported JSON number")


def validate_json(value: object, policy: JSONPolicy, depth: int = 0) -> None:
    if depth > policy.max_depth:
        raise JSONValidationError("LIMIT_EXCEEDED", 413)
    if type(value) is str or (not policy.exact_types and isinstance(value, str)):
        if any(
            0xD800 <= ord(c) <= 0xDFFF
            or (policy.reject_controls and (ord(c) < 32 or ord(c) == 127))
            for c in value
        ):
            raise JSONValidationError("MALFORMED_JSON", 400)
    elif type(value) is int:
        if abs(value) > MAX_SAFE_INTEGER:
            raise JSONValidationError("MALFORMED_JSON", 400)
    elif type(value) is bool or (value is None and policy.allow_null):
        return
    elif type(value) is list or (not policy.exact_types and isinstance(value, list)):
        for item in value:
            validate_json(item, policy, depth + 1)
    elif type(value) is dict or (not policy.exact_types and isinstance(value, dict)):
        if policy.max_members is not None and len(value) > policy.max_members:
            raise JSONValidationError("LIMIT_EXCEEDED", 413)
        for key, item in value.items():
            if not policy.exact_types and not isinstance(key, str):
                raise JSONValidationError("MALFORMED_JSON", 400)
            validate_json(key, policy, depth + 1)
            validate_json(item, policy, depth + 1)
    else:
        raise JSONValidationError("MALFORMED_JSON", 400)


def decode_json(data: bytes, policy: JSONPolicy) -> JSONValue:
    if policy.exact_types and type(data) is not bytes:
        raise JSONValidationError("MALFORMED_JSON", 400)
    if len(data) > policy.max_bytes:
        raise JSONValidationError("LIMIT_EXCEEDED", 413)

    def integer(raw: str) -> int:
        value = int(raw)
        if (policy.reject_negative_zero and raw == "-0") or abs(value) > MAX_SAFE_INTEGER:
            raise ValueError("unsafe integer")
        return value

    try:
        value = json.loads(
            data.decode("utf-8", "strict"),
            object_pairs_hook=unique_pairs,
            parse_int=integer,
            parse_float=reject_number,
            parse_constant=reject_number,
        )
        validate_json(value, policy)
        return cast(JSONValue, value)
    except JSONValidationError:
        raise
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise JSONValidationError("MALFORMED_JSON", 400) from exc


def canonical_json(
    value: object, *, utf16_keys: bool = False, allow_null: bool = False, exact_types: bool = False
) -> str:
    def emit(item: object) -> str:
        return canonical_json(
            item, utf16_keys=utf16_keys, allow_null=allow_null, exact_types=exact_types
        )

    if type(value) is str or (not exact_types and isinstance(value, str)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        if abs(value) > MAX_SAFE_INTEGER:
            raise ValueError("unsafe canonical integer")
        return str(value)
    if type(value) is list or (not exact_types and isinstance(value, list)):
        return "[" + ",".join(emit(item) for item in value) + "]"
    if type(value) is dict or (not exact_types and isinstance(value, dict)):
        keys = sorted(value, key=(lambda key: key.encode("utf-16-be")) if utf16_keys else None)
        return "{" + ",".join(emit(key) + ":" + emit(value[key]) for key in keys) + "}"
    if value is None and allow_null:
        return "null"
    raise TypeError("unsupported canonical value")
