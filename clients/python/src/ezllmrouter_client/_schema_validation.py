"""Shared supported JSON Schema subset; protocol text policy stays explicit."""

from datetime import datetime, timezone
import json
import re
from typing import Any


def _pattern_matches(pattern: str, value: str) -> bool:
    # JSON Schema permits substring patterns. An unescaped terminal dollar
    # still means the end of the value, including after a final newline.
    backslashes = len(pattern[:-1]) - len(pattern[:-1].rstrip("\\"))
    if pattern.endswith("$") and backslashes % 2 == 0:
        pattern = pattern[:-1] + r"\Z"
    return re.search(pattern, value) is not None


def validate(
    value: Any,
    shape: dict[str, Any],
    definitions: dict[str, Any],
    *,
    public_text: bool = False,
) -> bool:
    def check(item: Any, rule: dict[str, Any]) -> bool:
        return validate(item, rule, definitions, public_text=public_text)

    if "$ref" in shape:
        reference = shape["$ref"]
        if not reference.startswith("#/$defs/") or reference[8:] not in definitions:
            raise ValueError("unresolved schema reference")
        name = reference[8:]
        if name == "utc":
            if (
                type(value) is not str
                or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value) is None
            ):
                return False
            try:
                datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            except ValueError:
                return False
        return check(value, definitions[name])
    if "oneOf" in shape and sum(check(value, part) for part in shape["oneOf"]) != 1:
        return False
    if "const" in shape and (type(value) is not type(shape["const"]) or value != shape["const"]):
        return False
    if "enum" in shape and not any(
        type(value) is type(item) and value == item for item in shape["enum"]
    ):
        return False
    kind = shape.get("type")
    if kind == "object":
        if type(value) is not dict or not set(shape.get("required", ())) <= value.keys():
            return False
        properties = shape.get("properties", {})
        return all(
            check(item, properties[key])
            if key in properties
            else shape.get("additionalProperties") is not False
            for key, item in value.items()
        )
    if kind == "array":
        return (
            type(value) is list
            and shape.get("minItems", 0) <= len(value) <= shape.get("maxItems", float("inf"))
            and all(check(item, shape["items"]) for item in value)
            and (
                not shape.get("uniqueItems")
                or len({json.dumps(item, sort_keys=True) for item in value}) == len(value)
            )
        )
    if kind == "string":
        return (
            type(value) is str
            and shape.get("minLength", 0) <= len(value) <= shape.get("maxLength", float("inf"))
            and not any(char == "\0" or 0xD800 <= ord(char) <= 0xDFFF for char in value)
            and (not public_text or all(ord(char) >= 32 and ord(char) != 127 for char in value))
            and ("pattern" not in shape or _pattern_matches(shape["pattern"], value))
        )
    if kind == "integer":
        return (
            type(value) is int
            and abs(value) <= 9007199254740991
            and shape.get("minimum", -float("inf")) <= value <= shape.get("maximum", float("inf"))
        )
    if kind == "boolean":
        return type(value) is bool
    if kind is None:
        return True
    raise ValueError("unsupported schema type")
