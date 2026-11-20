"""Internal IDs shared by admission, registry, catalogue and reporting."""

import re
from typing import TypeGuard

MAX_IDENTIFIER_LENGTH = 160
IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}\Z")


def valid_identifier(value: object) -> TypeGuard[str]:
    return type(value) is str and IDENTIFIER_RE.fullmatch(value) is not None


def require_identifier(value: object) -> str:
    if not valid_identifier(value):
        raise ValueError("invalid identifier")
    return value
