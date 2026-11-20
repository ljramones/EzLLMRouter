"""Independent exact-decimal audit of one disposable DEV-12 campaign."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal, ROUND_HALF_EVEN
import hashlib
import json
from pathlib import Path
import sqlite3
import sys


NANO = Decimal("0.000000001")


def expected(request):
    count = len(request["input"].get("items", request["input"].get("candidates", [])))
    config = request["requested_configuration_ref"]
    role = request["input"].get("role")
    if config == "cfg.rerank.synthetic.a":
        component, quantity = "search_units", (count + 9) // 10
        raw = max(Decimal("0.005"), Decimal("0.003") * quantity)
    elif config == "cfg.rerank.synthetic":
        component, quantity = "document_units", count
        raw = Decimal(count) * Decimal("0.0003000005" if count <= 10 else "0.0004000005")
    elif config == "cfg.embed.synthetic" and role in ("document", "query"):
        component, quantity = ("query_units" if role == "query" else "document_units"), count
        raw = Decimal(count) * Decimal("0.000200000")
    else:
        raise AssertionError("unregistered price input")
    return component, quantity, raw.quantize(NANO, rounding=ROUND_HALF_EVEN)


def audit(root):
    root = Path(root)
    database = sqlite3.connect(root / "campaign.sqlite")
    records = [
        json.loads(raw)
        for (raw,) in database.execute("SELECT record FROM dev12_submissions ORDER BY rowid")
    ]
    usage = {
        aid: json.loads(raw)
        for aid, raw in database.execute(
            "SELECT attempt_id,usage FROM dev12_usage_revisions ORDER BY revision"
        )
    }
    receipts = {
        aid: json.loads(raw)
        for aid, raw in database.execute(
            "SELECT attempt_id,guard_receipt FROM dev12_send_ownership"
        )
    }
    arrivals = [json.loads(line) for line in (root / "receiver.jsonl").read_text().splitlines()]
    campaign = json.loads(database.execute("SELECT record FROM dev12_campaigns").fetchone()[0])
    database.close()
    ids = [record["attempt_id"] for record in records]
    if len(ids) != len(set(ids)) or len(receipts) != campaign["possible_send_count"]:
        raise AssertionError("distinct attempt/send ownership counts differ")
    by_arrival = {row["attempt_id"]: row for row in arrivals}
    amount = Decimal(0)
    families = Counter()
    states = Counter()
    for record in records:
        aid = record["attempt_id"]
        state = record["submission_state"]
        states[state] += 1
        if aid in usage:
            row = usage[aid]
            component, quantity, cost = expected(record["request"])
            if row["cost_status"] in ("calculated", "over_bound"):
                actual = row["components"][0]
                if (
                    row["amount_decimal"] != format(cost, "f")
                    or actual["component"] != component
                    or actual["presence"] != "known"
                    or actual["evidence"] != "reported"
                    or actual["quantity"] != quantity
                ):
                    raise AssertionError("native usage or tariff differs: " + aid)
                amount += cost
            elif row["cost_status"] != "unknown" or "amount_decimal" in row:
                raise AssertionError("unknown native amount manufactured: " + aid)
        if state == "completed":
            if aid not in usage:
                raise AssertionError("completed attempt lacks usage row: " + aid)
            families[
                (
                    record["request"]["requested_configuration_ref"],
                    record["request"]["input"].get("role", "rerank"),
                )
            ] += 1
        elif state == "unknown":
            if record["exposure_state"] != "outstanding":
                raise AssertionError("unknown exposure incorrectly settled")
        elif state == "failed":
            if record["dispatch_state"] == "blocked" and aid in by_arrival:
                raise AssertionError("blocked failure arrived at receiver")
        else:
            raise AssertionError("unsettled campaign state: " + state)
        if aid in by_arrival and (
            aid not in receipts
            or not by_arrival[aid]["request_valid"]
            or receipts[aid]["body_sha256"] != by_arrival[aid]["body_sha256"]
            or receipts[aid]["body_bytes"] != by_arrival[aid]["body_bytes"]
        ):
            raise AssertionError("final-body/receiver correlation differs: " + aid)
        if state in ("completed", "unknown") and aid not in by_arrival:
            raise AssertionError("receiver arrival absent for observed/unknown path")
    if campaign["attempt_count"] != len(ids) or campaign["inflight_count"] != 0:
        raise AssertionError("finite campaign counters differ")
    if campaign["possible_send_count"] != len(receipts) or len(by_arrival) != len(arrivals):
        raise AssertionError("possible sends or receiver uniqueness differ")
    historical_report = root / "resume-result.json"
    if historical_report.exists():
        supplement = json.loads(historical_report.read_text())
        if Decimal(supplement["report_total"]["known_usd"]) > amount:
            raise AssertionError("historical operator amount exceeds later effective total")
    result = {
        "status": "PASS",
        "campaign_id": campaign["campaign_id"],
        "attempts": len(ids),
        "possible_sends": campaign["possible_send_count"],
        "receiver_arrivals": len(arrivals),
        "fictional_known_usd": format(amount, "f"),
        "states": dict(states),
        "paused": campaign["paused"],
        "families": [
            {"configuration_ref": key[0], "role": key[1], "attempts": count}
            for key, count in sorted(families.items())
        ],
        "real_provider_calls": 0,
        "receiver_log_sha256": hashlib.sha256((root / "receiver.jsonl").read_bytes()).hexdigest(),
    }
    (root / "audit.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    return result


if __name__ == "__main__":
    print(json.dumps(audit(sys.argv[1]), sort_keys=True))
