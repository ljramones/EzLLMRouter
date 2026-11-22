"""Independent, fixed-seed protocol JSON expectations for all six client decoders."""

import json
from pathlib import Path

from tests.generated_inputs import json_cases

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "tests/fixtures/contracts/transport-security/decoder_cases.json"


def reference(raw):
    def reject(_value):
        raise ValueError("integer JSON required")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def check(value, depth=0):
        if depth > 32:
            raise ValueError("depth")
        if isinstance(value, str):
            if "\0" in value or any(0xD800 <= ord(char) <= 0xDFFF for char in value):
                raise ValueError("scalar")
        elif type(value) is int and abs(value) > 9007199254740991:
            raise ValueError("integer")
        elif isinstance(value, dict):
            for key, child in value.items():
                check(key, depth + 1)
                check(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                check(child, depth + 1)

    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=pairs, parse_float=reject, parse_constant=reject
        )
        if type(value) is not dict:
            raise ValueError("object required")
        check(value)
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    except (ValueError, UnicodeError, RecursionError):
        return None


def corpus():
    known = [
        ("empty-object", b"{}", "{}"),
        ("negative-zero", b'{"n":-0}', '{"n":0}'),
        ("escaped-line", b'{"text":"one\\ntwo\\tthree"}', '{"text":"one\\ntwo\\tthree"}'),
        (
            "safe-integers",
            b'{"b":9007199254740991,"a":-9007199254740991}',
            '{"a":-9007199254740991,"b":9007199254740991}',
        ),
        ("escaped-duplicate", b'{"a":0,"\\u0061":1}', None),
        ("utf8-overlong", b'{"x":"\xc0\x80"}', None),
        ("raw-surrogate", b'{"x":"\xed\xa0\x80"}', None),
        ("bad-surrogate-pair", b'{"x":"\\ud800\\ud800"}', None),
        ("nul-key", b'{"\\u0000":1}', None),
        ("duplicate-null", b'{"x":null,"x":false}', None),
        ("valid-surrogate-pair", b'{"x":"\\ud83d\\ude00"}', '{"x":"😀"}'),
        ("bom", b"\xef\xbb\xbf{}", None),
        ("formfeed-whitespace", b"\x0c{}", None),
        ("trailing-data", b"{}{}", None),
        ("unsafe-negative", b'{"n":-9007199254740992}', None),
        ("fraction", b'{"n":1.0}', None),
        ("exponent", b'{"n":1e0}', None),
        (
            "proto-key",
            b'{"__proto__":{"x":1},"constructor":false}',
            '{"__proto__":{"x":1},"constructor":false}',
        ),
    ]
    rows = []
    for name, raw, expected in known:
        assert reference(raw) == expected, name
        rows.append({"id": name, "raw_hex": raw.hex(), "canonical": expected})
    for depth in (30, 31, 32, 33, 64, 129):
        raw = b'{"x":' + b"[" * depth + b"]" * depth + b"}"
        rows.append(
            {"id": "depth-" + str(depth), "raw_hex": raw.hex(), "canonical": reference(raw)}
        )
    for index, raw in enumerate(json_cases(20261122, 512)):
        rows.append(
            {"id": "generated-" + str(index), "raw_hex": raw.hex(), "canonical": reference(raw)}
        )
    return {"schema": "ezllmrouter.decoder-corpus.v1", "seed": 20261122, "cases": rows}


if __name__ == "__main__":
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    DESTINATION.write_text(json.dumps(corpus(), indent=2, ensure_ascii=False) + "\n")
