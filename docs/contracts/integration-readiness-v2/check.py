"""Independent dependency-free v2 schema and arithmetic examples; no service import."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
import re

ROOT = Path(__file__).parent
schema = json.loads((ROOT / "schema.json").read_text())["$defs"]
examples = json.loads((ROOT / "examples.json").read_text())


def valid(value, shape):
    if "$ref" in shape:
        name = shape["$ref"].rsplit("/", 1)[1]
        if name == "utc":
            if type(value) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
                return False
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return False
        return valid(value, schema[name])
    if "oneOf" in shape:
        return sum(valid(value, item) for item in shape["oneOf"]) == 1
    if "const" in shape and value != shape["const"] or "enum" in shape and value not in shape["enum"]:
        return False
    kind = shape.get("type")
    if kind == "object":
        return (type(value) is dict and set(shape.get("required", ())) <= set(value) and
                (shape.get("additionalProperties") is not False or set(value) <= set(shape["properties"])) and
                all(valid(v, shape["properties"][k]) for k, v in value.items() if k in shape["properties"]))
    if kind == "array":
        return (type(value) is list and shape.get("minItems", 0) <= len(value) <= shape.get("maxItems", 10**9)
                and (not shape.get("uniqueItems") or len({json.dumps(v, sort_keys=True) for v in value}) == len(value))
                and all(valid(v, shape["items"]) for v in value))
    if kind == "integer":
        return type(value) is int and shape.get("minimum", -10**30) <= value <= shape.get("maximum", 10**30)
    if kind == "string":
        return type(value) is str and ("pattern" not in shape or re.fullmatch(shape["pattern"], value) is not None)
    return True


def semantic(e):
    if e["kind"] == "attempt_started":
        return ((e["model_identity_state"] == "known") == ("model_id" in e) and
                (e["attempt_role"] in ("retry", "fallback")) == ("predecessor_attempt_id" in e))
    if e["kind"] == "usage":
        units = e.get("native_units", ())
        cost = ("currency", "amount_decimal", "cost_basis", "price_ref", "price_version")
        return (len({x["unit"] for x in units}) == len(units) and
                (e["usage_state"] == "known") == ("native_units" in e and "usage_provenance" in e) and
                (e["cost_state"] == "known") == all(k in e for k in cost) and
                (e["cost_state"] == "known" or not any(k in e for k in cost + ("zero_basis",))) and
                (e["cost_state"] != "known" or (Decimal(e["amount_decimal"]) == 0) == ("zero_basis" in e)))
    return True


def run():
    assert valid(examples["dataset"], schema["dataset"])
    assert valid(examples["account"], schema["account"])
    events = examples["events"]
    assert len({e["event_id"] for e in events}) == len(events)
    assert all(valid(e, schema["event"]) and semantic(e) for e in events)
    assert all(valid(s, schema["snapshot"]) for s in examples["snapshots"])
    response_shapes = {"usage_state": "report_usage_state",
                       "eligibility_assessment": "report_eligibility_assessment",
                       "feature_snapshot_status": "report_snapshot_status",
                       "lineage_status": "report_lineage_status"}
    assert all(all(valid(row[key], schema[definition]) for key, definition in response_shapes.items()) and
               row["cost_status"] in ("known", "unknown", "not_observed")
               for row in examples["response_states"])
    assert {row["usage_state"] for row in examples["response_states"]} == \
        {"known", "unknown", "not_observed", "legacy_absent"}
    usage = {e["attempt_id"]: e for e in events if e["kind"] == "usage"}
    assert sum((Decimal(e["amount_decimal"]) for e in usage.values() if e["cost_state"] == "known"),
               Decimal(0)) == Decimal("0.030000000")
    negatives = []
    bad = deepcopy(events[0]); bad["event_id"] = "event/bad"; negatives.append(bad)
    bad = deepcopy(events[0]); bad["started_at"] = "2026-02-30T00:00:00Z"; negatives.append(bad)
    bad = deepcopy(events[0]); bad["model_identity_state"] = "not_applicable"; negatives.append(bad)
    bad = deepcopy(events[1]); bad["amount_decimal"] = "0"; negatives.append(bad)
    bad = deepcopy(events[2]); bad["amount_decimal"] = "0"; negatives.append(bad)
    bad = deepcopy(events[2]); bad["native_units"].append(bad["native_units"][0]); negatives.append(bad)
    assert all(not (valid(e, schema["event"]) and semantic(e)) for e in negatives)
    print(f"integration-v2 contract PASS: {len(events)} positive events, {len(examples['snapshots'])} snapshots, "
          f"{len(negatives)} negative cases, {len(examples['response_states'])} response states, "
          "independent effective USD 0.030000000")


if __name__ == "__main__":
    run()
