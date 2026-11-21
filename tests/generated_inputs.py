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
    ]
    if depth >= 4 or rng.randrange(3) == 0:
        return rng.choice(scalars)
    if rng.randrange(2):
        return [json_value(rng, depth + 1) for _ in range(rng.randrange(5))]
    return {"key." + str(i): json_value(rng, depth + 1) for i in range(rng.randrange(5))}


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
