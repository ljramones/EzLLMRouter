"""Independent standard-library A1 candidate-03 projection and Decimal check."""
import base64
import hashlib
import json
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_EVEN
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))

def canonical(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")

def sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()

def project(request, context):
    identity = context["identity"]
    selector = request["work_selector"]
    return {
        "schema_id": "ezllmrouter-work-v0.3",
        "profile": request["capability_profile"],
        "work_key": {"principal_id": identity["principal_id"],
                     "task_id": selector["task_id"], "step_id": selector["step_id"],
                     "step_revision": selector["step_revision"],
                     "execution_generation": selector["execution_generation"]},
        "operation": request["operation"], "input": request["input"],
        "metadata": request["metadata"], "trusted": identity,
        "purpose": request["purpose"], "task_class": request["task_class"],
        "requested_configuration_ref": request["requested_configuration_ref"],
        "deadline": request["deadline"], "handling_profile": request["handling_profile"],
    }

vectors, tariffs, registry = map(load, ("vectors.json", "tariffs.json", "registrations.json"))
assert vectors["schema_version"] == "dev12-a1-vectors@3"
assert len(vectors["examples"]) == 4
for ex in vectors["examples"]:
    work = project(ex["request"], ex["trusted_context"])
    assert work == ex["canonical_work"], ex["id"]
    raw = canonical(work)
    assert base64.b64decode(ex["canonical_bytes_base64"], validate=True) == raw, ex["id"]
    assert ex["canonical_byte_length"] == len(raw), ex["id"]
    op = work["operation"]
    prefix = f'ezllmrouter-work-v0.3\n{op["type"]}@{op["version"]}\n'.encode()
    assert sha(prefix + raw) == ex["work_digest"], ex["id"]
    admission = ex["admission_snapshot"]
    assert admission["work_digest"] == ex["work_digest"], ex["id"]
    assert sha(b"ezllmrouter-admission-v1\n" + canonical(admission)) == ex["admission_snapshot_digest"], ex["id"]
    for c in ex["request"]["input"].get("candidates", []):
        data = ("ezllmrouter-content-v1\n" + c["content_version"] + "\n" + c["text"]).encode()
        assert c["content_digest"] == sha(data)
assert "commission" not in vectors["examples"][0]["canonical_work"]["metadata"]
assert "commission" in vectors["examples"][3]["canonical_work"]["metadata"]
assert vectors["examples"][0]["work_digest"] != vectors["examples"][3]["work_digest"]

Q = Decimal("0.000000001")
assert tariffs["fictional"] is True and tariffs["currency"] == "USD"
assert Decimal(tariffs["quantum"]) == Q
assert len(tariffs["rows"]) == len(tariffs["embedding_document_rows"]) == 25
maximum = {"a": Decimal(0), "b": Decimal(0), "embedding": Decimal(0)}
for n, row in enumerate(tariffs["rows"], start=1):
    assert row["documents"] == n
    units_a = (n + 9) // 10
    raw_a = max(Decimal("0.005"), Decimal("0.003") * units_a)
    raw_b = Decimal(n) * (Decimal("0.0003000005") if n <= 10 else Decimal("0.0004000005"))
    for key, raw, units in (("a", raw_a, units_a), ("b", raw_b, n)):
        rec = row[f"tariff_{key}"]
        assert rec["search_units" if key == "a" else "document_units"] == units
        assert Decimal(rec["raw_usd"]) == raw
        settled = raw.quantize(Q, rounding=ROUND_HALF_EVEN)
        bound = raw.quantize(Q, rounding=ROUND_CEILING)
        assert Decimal(rec["settled_usd"]) == settled
        assert Decimal(rec["request_bound_usd"]) == bound
        maximum[key] = max(maximum[key], bound)
    embed = tariffs["embedding_document_rows"][n-1]
    raw = Decimal(n) * Decimal("0.000200000")
    assert embed["items"] == embed["document_units"] == n
    assert Decimal(embed["raw_usd"]) == raw
    assert Decimal(embed["settled_usd"]) == raw.quantize(Q, rounding=ROUND_HALF_EVEN)
    assert Decimal(embed["request_bound_usd"]) == raw.quantize(Q, rounding=ROUND_CEILING)
    maximum["embedding"] = max(maximum["embedding"], raw)
assert maximum["a"] == Decimal(tariffs["schedule_a"]["maximum_domain_bound_usd"])
assert maximum["b"] == Decimal(tariffs["schedule_b"]["maximum_domain_bound_usd"])
assert maximum["embedding"] == Decimal(tariffs["embedding_document"]["maximum_domain_bound_usd"])
query = tariffs["embedding_query_row"]
assert query["items"] == query["query_units"] == 1
assert Decimal(query["raw_usd"]) == Decimal(query["settled_usd"]) == Decimal(query["request_bound_usd"]) == Decimal("0.000200000")
assert 3 * Decimal("0.0003000005").quantize(Q, rounding=ROUND_HALF_EVEN) == Decimal("0.000900000")
assert (3 * Decimal("0.0003000005")).quantize(Q, rounding=ROUND_HALF_EVEN) == Decimal("0.000900002")
assert 3 * Decimal("0.0003000005").quantize(Q, rounding=ROUND_CEILING) == Decimal(tariffs["rounding_pair"]["separate_bounds_total_usd"])
assert (3 * Decimal("0.0003000005")).quantize(Q, rounding=ROUND_CEILING) == Decimal(tariffs["rounding_pair"]["batched_bound_usd"])
assert all(not isinstance(n, int) or isinstance(n, bool) or n < 1 or n > 25 for n in tariffs["negative_cardinalities"])
assert len(registry["configurations"]) == 3 and len(registry["price_contracts"]) == 4
plan = vectors["plan_fixture"]
unsigned = plan["unsigned_plan"]
message = b"ezllmrouter-plan-v1\n" + canonical(unsigned)
assert base64.b64decode(plan["signing_message_base64"], validate=True) == message
assert sha(message) == plan["signing_message_sha256"]
assert {k:v for k,v in plan["signed_plan"].items() if k != "signature"} == unsigned
signed = plan["signed_plan"]
authority = vectors["execution_eligibility_context"]
assert authority["expected_submission_id"] == signed["submission_id"]
assert authority["expected_attempt_id"] == signed["attempt_id"]
assert authority["expected_reservation"] == signed["reservation"]
assert authority["current_authority_revisions"] == signed["authority_revisions"]
assert datetime.fromisoformat(authority["evaluation_time"].replace("Z", "+00:00")) < datetime.fromisoformat(signed["expires_at"].replace("Z", "+00:00"))
tagged = vectors["activation_tagged_fixture"]
assert tagged["signed_plan"]["execution_context"] == tagged["execution_eligibility_context"]["expected_execution_context"]
assert tagged["signing_message_sha256"] == sha(b"ezllmrouter-plan-v1\n" + canonical({k: v for k, v in tagged["signed_plan"].items() if k != "signature"}))
slow = vectors["nonconforming_timeout_fixture"]
assert slow["signed_plan"]["execution_descriptor"]["timeout_ms"] == 30000
assert slow["signing_message_sha256"] == sha(b"ezllmrouter-plan-v1\n" + canonical({k: v for k, v in slow["signed_plan"].items() if k != "signature"}))
for name, history in vectors["historical_contexts"].items():
    assert history["stored_signed_plan_digest"] == sha(b"ezllmrouter-stored-plan-v1\n" + canonical(signed)), name
    assert history["expected_reservation"] == signed["reservation"], name
    for number, row in enumerate(history["accepted_revisions"], start=1):
        assert row["attempt_id"] == signed["attempt_id"] and row["revision"] == number, name
        assert ("previous_revision" not in row) if number == 1 else row["previous_revision"] == number - 1
under = vectors["historical_underbound"]
assert under["historical_context"]["stored_signed_plan_digest"] == sha(b"ezllmrouter-stored-plan-v1\n" + canonical(under["signed_plan"]))
assert Decimal(under["usage"]["amount_decimal"]) > Decimal(under["signed_plan"]["reservation"]["max_exposure_decimal"])
assert under["usage"]["cost_status"] == "over_bound"
retention = vectors["retention_context"]
origin = datetime.fromisoformat(retention["origin_at"].replace("Z", "+00:00"))
cutoff = origin + timedelta(seconds=signed["execution_descriptor"]["retention_seconds"])
assert cutoff.isoformat().replace("+00:00", "Z") == retention["cutoff_at"]
assert datetime.fromisoformat(retention["observed_at"].replace("Z", "+00:00")) >= cutoff
assert cutoff > datetime.fromisoformat(signed["expires_at"].replace("Z", "+00:00"))
latest = vectors["historical_contexts"]["CALCULATED_REVISION_2"]["accepted_revisions"][-1]
assert latest["revision"] == 2 and Decimal(latest["amount_decimal"]) == Decimal("0.000900002")
assert sum((Decimal(row["amount_decimal"]) for row in (latest, under["usage"])), Decimal(0)) == Decimal("0.001800004")
print("DEV-12/A1 Python offline cross-check PASS: 4 independent projections, 25 A/B and 25 embedding rows, query, split/batch, plan bytes, historical anchors and retention cutoff")
