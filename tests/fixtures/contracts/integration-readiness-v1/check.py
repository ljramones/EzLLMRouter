"""Executable, dependency-free schema and semantic examples for integration v1."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import json
import re

HERE = Path(__file__).resolve().parent
SCHEMA = json.loads((HERE / "schema.json").read_text())
EXAMPLES = json.loads((HERE / "examples.json").read_text())


def valid(value, shape):
    if "$ref" in shape:
        return valid(value, SCHEMA["$defs"][shape["$ref"].rsplit("/", 1)[1]])
    if "oneOf" in shape:
        return sum(valid(value, item) for item in shape["oneOf"]) == 1
    if "const" in shape and value != shape["const"]:
        return False
    if "enum" in shape and value not in shape["enum"]:
        return False
    kind = shape.get("type")
    if kind == "object":
        return (type(value) is dict and set(shape.get("required", ())) <= set(value) and
                (shape.get("additionalProperties") is not False or set(value) <= set(shape["properties"])) and
                all(valid(item, shape["properties"][key]) for key, item in value.items()
                    if key in shape["properties"]))
    if kind == "array":
        return (type(value) is list and shape.get("minItems", 0) <= len(value) <= shape.get("maxItems", 10**9)
                and (not shape.get("uniqueItems") or len({json.dumps(x, sort_keys=True) for x in value}) == len(value))
                and all(valid(item, shape["items"]) for item in value))
    if kind == "integer":
        return type(value) is int and shape.get("minimum", -10**30) <= value <= shape.get("maximum", 10**30)
    if kind == "string":
        return type(value) is str and ("pattern" not in shape or re.fullmatch(shape["pattern"], value) is not None)
    return True


def semantic(event):
    if event["kind"] in ("activity", "attempt_started"):
        if ("parent_run_id" in event) == (event["root_run_id"] == event["run_id"]):
            return False
        if event.get("parent_run_id") == event["run_id"]:
            return False
    if event["kind"] == "usage" and event["usage_state"] == "known":
        if len({item["unit"] for item in event["native_units"]}) != len(event["native_units"]):
            return False
        if Decimal(event["amount_decimal"]) == 0 and "zero_basis" not in event:
            return False
    return True


def run():
    assert valid(EXAMPLES["dataset"], SCHEMA["$defs"]["dataset"])
    assert valid(EXAMPLES["account"], SCHEMA["$defs"]["account"])
    events = EXAMPLES["events"]
    assert len({event["event_id"] for event in events}) == len(events)
    assert all(valid(event, SCHEMA["$defs"]["event"]) and semantic(event) for event in events)
    assert events[2]["started_at"] >= EXAMPLES["dataset"]["activated_at"]
    assert sum((Decimal(e["amount_decimal"]) for e in events if e["kind"] == "usage" and
                e["usage_state"] == "known"), Decimal(0)) == Decimal("0.050000000")
    # A revision replaces its predecessor; the two known rows belong to distinct attempts.
    by_attempt = {}
    for e in events:
        if e["kind"] == "usage":
            by_attempt.setdefault(e["attempt_id"], {})[e["usage_revision"]] = e
    assert sum((Decimal(rows[max(rows)]["amount_decimal"]) for rows in by_attempt.values()
                if rows[max(rows)]["usage_state"] == "known"), Decimal(0)) == Decimal("0.050000000")
    invalid = []
    changed = deepcopy(events[2]); changed["attempt_id"] = "bad/id"; invalid.append(changed)
    changed = deepcopy(events[6]); changed["amount_decimal"] = "0.0000000000"; invalid.append(changed)
    changed = deepcopy(events[6]); changed["native_units"].append(changed["native_units"][0]); invalid.append(changed)
    changed = deepcopy(events[6]); changed["amount_decimal"] = "0"; invalid.append(changed)
    changed = deepcopy(events[2]); changed["parent_run_id"] = "run.child"; invalid.append(changed)
    changed = deepcopy(events[4]); changed["currency"] = "USD"; invalid.append(changed)
    assert all(not (valid(e, SCHEMA["$defs"]["event"]) and semantic(e)) for e in invalid)
    print(f"integration-v1 contract PASS: {len(events)} positive event shapes, {len(invalid)} negative cases, exact USD 0.050000000 example")


if __name__ == "__main__":
    run()
