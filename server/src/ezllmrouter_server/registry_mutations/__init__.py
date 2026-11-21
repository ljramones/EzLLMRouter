"""Registry mutation families, invoked inside the facade publishing transaction."""

import hashlib
from ..records import Record
from ..registry_values import identifier
from ..store import encode


def mutation_request(request: Record) -> tuple[str, str, str, int, Record, str]:
    if type(request) is not dict or set(request) != {
        "operation_id",
        "action",
        "subject",
        "expected_revision",
        "data",
    }:
        raise ValueError("invalid management request")
    op = identifier(request["operation_id"])
    action_name = request["action"]
    subject = identifier(request["subject"])
    expected = request["expected_revision"]
    data = request["data"]
    if type(expected) is not int or expected < 0 or type(data) is not dict:
        raise ValueError("invalid management revision or data")
    request_hash = hashlib.sha256(encode(request).encode()).hexdigest()
    return op, action_name, subject, expected, data, request_hash
