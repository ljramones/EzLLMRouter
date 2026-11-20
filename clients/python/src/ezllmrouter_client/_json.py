"""Strict response JSON shared by the synchronous client protocols."""

from __future__ import annotations

import json
from typing import Any, NoReturn


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in items:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _reject_number(_text: str) -> NoReturn:
    raise ValueError("unsupported JSON number")


def strict_reply(data: bytes) -> Any:
    if data.startswith(b"\xef\xbb\xbf"):
        raise ValueError("unexpected UTF-8 BOM")
    value = json.loads(
        data.decode("utf-8", "strict"),
        object_pairs_hook=_pairs,
        parse_float=_reject_number,
        parse_constant=_reject_number,
    )

    def check(item: Any, depth: int = 0) -> None:
        if depth > 32:
            raise ValueError("response nesting limit")
        if type(item) is int and abs(item) > 9007199254740991:
            raise ValueError("unsafe response integer")
        if type(item) is str and any(
            char == "\0" or 0xD800 <= ord(char) <= 0xDFFF for char in item
        ):
            raise ValueError("invalid response scalar")
        if type(item) is dict:
            for key, child in item.items():
                check(key, depth + 1)
                check(child, depth + 1)
        elif type(item) is list:
            for child in item:
                check(child, depth + 1)

    check(value)
    return value


def encode_request(value: Any) -> bytes:
    active: set[int] = set()

    def check(item: Any, depth: int = 0) -> None:
        if depth > 32:
            raise ValueError("request nesting limit")
        if item is None or type(item) is bool:
            return
        if type(item) is int and abs(item) <= 9007199254740991:
            return
        if type(item) is str:
            if "\0" in item:
                raise ValueError("invalid request text")
            item.encode("utf-8", "strict")
            return
        if type(item) not in (list, dict) or id(item) in active:
            raise ValueError("invalid JSON request value")
        active.add(id(item))
        try:
            if type(item) is dict:
                for key, child in item.items():
                    if type(key) is not str:
                        raise ValueError("non-string request key")
                    check(key, depth + 1)
                    check(child, depth + 1)
            else:
                for child in item:
                    check(child, depth + 1)
        finally:
            active.remove(id(item))

    check(value)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
        "utf-8"
    )
