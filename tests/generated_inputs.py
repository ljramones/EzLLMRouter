"""Bounded deterministic inputs; failures report the seed and case index for replay."""

import json
import os
import random

DEFAULT_SEED = 20261120


def settings(default=128):
    seed = int(os.environ.get("EZLLMROUTER_TEST_SEED", str(DEFAULT_SEED)), 0)
    count = int(os.environ.get("EZLLMROUTER_TEST_EXAMPLES", str(default)))
    if not 1 <= count <= 10000:
        raise ValueError("generated example budget must be between 1 and 10000")
    return seed, count


def json_value(rng, depth=0):
    scalars = [
        None,
        True,
        False,
        0,
        1,
        -1,
        9007199254740991,
        -9007199254740991,
        "",
        "é",
        "😀",
        "plain.text",
        1.0,
        -0.0,
        1.25,
        'line\nquote"slash\\',
        "\0\t\r\x7f",
    ]
    if depth >= 4 or rng.randrange(3) == 0:
        return rng.choice(scalars)
    if rng.randrange(2):
        return [json_value(rng, depth + 1) for _ in range(rng.randrange(5))]
    keys = rng.sample(("", "key.0", "é", "😀", "\ue000", "\n", '"', "\\"), rng.randrange(5))
    return {key: json_value(rng, depth + 1) for key in keys}


# Literal tokens in UTF-16 order. Expected canonical bytes are constructed before
# decoding; neither the runtime canonicalizer nor a second serializer is an oracle.
CANONICAL_KEYS = (
    '""',
    '"\\u0000"',
    '"\\n"',
    '"\\""',
    '"0"',
    '"10"',
    '"2"',
    '"\\\\"',
    '"a"',
    '"é"',
    '"z"',
    '"é"',
    '"𐀀"',
    '"😀"',
    '"\ue000"',
)
CANONICAL_SCALARS = (
    "true",
    "false",
    "0",
    "1",
    "-1",
    "9007199254740991",
    "-9007199254740991",
    *CANONICAL_KEYS,
)


def canonical_case(rng, depth=0):
    def literal(level):
        if level >= 4 or rng.randrange(3) == 0:
            return rng.choice(CANONICAL_SCALARS)
        if rng.randrange(2):
            return "[" + ",".join(literal(level + 1) for _ in range(rng.randrange(5))) + "]"
        ranks = sorted(rng.sample(range(len(CANONICAL_KEYS)), rng.randrange(5)))
        return "{" + ",".join(CANONICAL_KEYS[i] + ":" + literal(level + 1) for i in ranks) + "}"

    raw = literal(depth).encode()
    value = json.loads(raw)
    if isinstance(value, dict):
        items = list(value.items())
        rng.shuffle(items)
        value = dict(items)
    return value, raw


def json_cases(seed, count):
    rng = random.Random(seed)
    corpus = [
        b"",
        b"{}",
        b"[]",
        b"null",
        b"true",
        b"-0",
        b"1.0",
        b"1e2",
        b"NaN",
        b"Infinity",
        b"9007199254740992",
        b'{"x":1,"x":2}',
        b'{"x":"\\ud800"}',
        b'"\\u0000"',
        b'"\\n"',
        b"\xef\xbb\xbf{}",
        b"\xff{}",
        b"[" * 33 + b"0" + b"]" * 33,
        b'{"__proto__":{"polluted":true},"constructor":0}',
    ]
    for index in range(count):
        if index < len(corpus):
            yield corpus[index]
            continue
        raw = json.dumps(json_value(rng), ensure_ascii=False, separators=(",", ":")).encode()
        operation = rng.randrange(5)
        offset = rng.randrange(len(raw) + 1)
        if operation == 1:
            raw = raw[:offset]
        elif operation == 2:
            raw = raw[:offset] + bytes([rng.randrange(256)]) + raw[offset:]
        elif operation == 3:
            raw = raw[:offset] + raw[offset + 1 :]
        elif operation == 4:
            raw = b" \r\n" + raw + b"\t "
        yield raw
