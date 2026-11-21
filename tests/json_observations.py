"""Typed JSON observations survive serialization without Python numeric coercion."""

import struct


def observe(value):
    if value is None:
        return ["null"]
    if type(value) is bool:
        return ["boolean", "true" if value else "false"]
    if type(value) is int:
        return ["integer", str(value)]
    if type(value) is float:
        return ["float", struct.pack("!d", value).hex()]
    if isinstance(value, str):
        return ["string", value]
    if isinstance(value, list):
        return ["array", [observe(child) for child in value]]
    return [
        "object",
        [[key, observe(value[key])] for key in sorted(value, key=lambda k: k.encode("utf-16-be"))],
    ]
