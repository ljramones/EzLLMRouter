"""Recompute the DEV-12 synthetic target census from the portable safe export.

This reads only ledger.json, receiver.jsonl and the public fixed tariff registry.
It has no database, credential, socket or provider dependency.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal, ROUND_HALF_EVEN
from hashlib import sha256
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dev12_completion_mixed_audit import audit as mixed_audit


NANO = Decimal("0.000000001")
QUALIFIED_SUPPLEMENT = {
    "case.ct02_workkey.wire02_first.continuation4",
    "case.ct02_workkey.wire03_first.continuation5",
    "case.ct02_workkey.http_contention.continuation5",
    "case.ct02_recovery.wheel.continuation9",
    "case.ct02_recovery.tarball",
    "case.ct02_realized_guard.method_host_route",
    "case.ct02_realized_guard.headers_body",
    "case.ct02_realized_guard.timeout_matrix",
    "case.ct02_authority_wait.activation_pause_expiry",
    "case.ct02_failed_unknown.failed_then_corrected",
    "case.ct02_revision33.accepted_history",
    "case.ct02_historical_auth.read_write_resume",
    "case.ct02_reporting.csv_overbound",
    "case.ct02_transport.would_block_revoke",
    "case.ct02_transport.partial_unknown",
    "case.ct02_authority_atomic.rollback_stall_unpublished_restart",
}


def tariff(price_ref, component, quantity):
    if type(quantity) is not int or quantity < 0:
        raise AssertionError("invalid reported native quantity")
    if price_ref == "tariff.synthetic.a@1":
        assert component == "search_units"
        raw = max(Decimal("0.005"), Decimal("0.003") * quantity)
    elif price_ref == "tariff.synthetic.b@1":
        assert component == "document_units"
        raw = Decimal(quantity) * Decimal("0.0003000005" if quantity <= 10 else "0.0004000005")
    elif price_ref in {"tariff.synthetic.embed-doc@1", "tariff.synthetic.embed-query@1"}:
        assert component == ("query_units" if "embed-query" in price_ref else "document_units")
        raw = Decimal("0.000200000") * quantity
    else:
        raise AssertionError("unregistered synthetic price reference")
    return raw.quantize(NANO, rounding=ROUND_HALF_EVEN)


def rows(ledger, table):
    return ledger[table]["rows"]


def audit(packet: Path, registry_path: Path):
    ledger = json.loads((packet / "ledger.json").read_text())
    registry = json.loads(registry_path.read_text())
    contracts = {row["price_ref"]: row for row in registry["price_contracts"]}
    assert len(contracts) == 4
    campaigns = rows(ledger, "dev12_campaigns")
    assert len(campaigns) == 1
    campaign = json.loads(campaigns[0]["record"])
    attempts = rows(ledger, "dev12_campaign_attempts")
    submissions = [json.loads(row["record"]) for row in rows(ledger, "dev12_submissions")]
    ownership = rows(ledger, "dev12_send_ownership")
    usage_rows = rows(ledger, "dev12_usage_revisions")
    campaign_id = campaign["campaign_id"]
    by_attempt = {r["attempt_id"]: r for r in submissions}
    assert len(by_attempt) == len(submissions) == len(attempts)
    assert {r["attempt_id"] for r in attempts} == set(by_attempt)
    assert len({r["attempt_id"] for r in ownership}) == len(ownership)
    assert all(r["campaign_id"] == campaign_id for r in submissions + attempts)
    assert campaign["attempt_count"] == len(attempts)
    assert campaign["possible_send_count"] == len(ownership)
    assert campaign["inflight_count"] == 0
    assert len(attempts) <= campaign["max_attempts"]
    assert len(ownership) <= campaign["max_attempts"]
    reserved = sum((Decimal(r["reservation_decimal"]) for r in attempts), Decimal(0))
    assert reserved == Decimal(campaign["cumulative_reserved_decimal"])
    assert reserved <= Decimal(campaign["ceiling_decimal"])
    for row in submissions:
        reservation = row["reservation"]
        assert reservation == row["signed_plan"]["reservation"]
        assert reservation["budget_account_id"] == campaign["budget_account_id"]
        assert reservation["financial_owner_id"] == campaign["financial_owner_id"]
        assert row["signed_plan"]["submission_id"] == row["submission_id"]
        assert row["signed_plan"]["attempt_id"] == row["attempt_id"]
        assert row["work_key"] == row["canonical_work"]["work_key"]
        assert row["signed_plan"]["work_digest"] == row["work_digest"]
        assert reservation["price_ref"] in contracts
        attempt_row = next(r for r in attempts if r["attempt_id"] == row["attempt_id"])
        assert Decimal(attempt_row["reservation_decimal"]) == Decimal(
            reservation["max_exposure_decimal"]
        )
    for own in ownership:
        submission = by_attempt[own["attempt_id"]]
        receipt = json.loads(own["guard_receipt"])
        assert own["submission_id"] == submission["submission_id"]
        assert receipt["attempt_id"] == own["attempt_id"]
        assert receipt["plan_id"] == submission["signed_plan"]["plan_id"]
    arrivals = [
        json.loads(line) for line in (packet / "target" / "receiver.jsonl").read_text().splitlines()
    ]
    by_arrival = {row["attempt_id"]: row for row in arrivals}
    assert len(by_arrival) == len(arrivals)
    by_ownership = {row["attempt_id"]: json.loads(row["guard_receipt"]) for row in ownership}
    for attempt_id, arrival in by_arrival.items():
        assert attempt_id in by_ownership
        guard = by_ownership[attempt_id]
        assert arrival["request_valid"] is True
        assert arrival["body_sha256"] == guard["body_sha256"]
        assert arrival["body_bytes"] == guard["body_bytes"]
    receiver_receipts = [
        json.loads(line)
        for line in (packet / "target" / "receiver-receipts.jsonl").read_text().splitlines()
    ]
    assert len(receiver_receipts) == len(arrivals)
    assert {row["attempt_id"] for row in receiver_receipts} == set(by_arrival)
    for receipt in receiver_receipts:
        arrival = by_arrival[receipt["attempt_id"]]
        assert receipt["body_sha256"] == arrival["body_sha256"]
        assert receipt["body_bytes"] == arrival["body_bytes"]
    histories = defaultdict(list)
    for row in usage_rows:
        usage = json.loads(row["usage"])
        attempt_id = row["attempt_id"]
        assert attempt_id in by_attempt
        assert row["submission_id"] == by_attempt[attempt_id]["submission_id"]
        assert usage["attempt_id"] == attempt_id
        assert usage["revision"] == row["revision"]
        assert usage["price_ref"] == by_attempt[attempt_id]["reservation"]["price_ref"]
        histories[attempt_id].append(usage)
    known = Decimal(0)
    cost_states = Counter()
    over_bound = 0
    for attempt_id, history in histories.items():
        history.sort(key=lambda r: r["revision"])
        assert [r["revision"] for r in history] == list(range(1, len(history) + 1))
        for index, row in enumerate(history):
            if index:
                assert row["previous_revision"] == index
            else:
                assert "previous_revision" not in row
        latest = history[-1]
        assert by_attempt[attempt_id]["effective_usage_revision"] == latest["revision"]
        status = latest["cost_status"]
        cost_states[status] += 1
        if status in {"calculated", "over_bound"}:
            assert len(latest["components"]) == 1
            component = latest["components"][0]
            assert component["presence"] == "known" and component["evidence"] == "reported"
            amount = tariff(latest["price_ref"], component["component"], component["quantity"])
            assert Decimal(latest["amount_decimal"]) == amount
            bound = Decimal(by_attempt[attempt_id]["reservation"]["max_exposure_decimal"])
            assert (status == "over_bound") == (amount > bound)
            over_bound += status == "over_bound"
            known += amount
        elif status == "unknown":
            assert "amount_decimal" not in latest
        else:
            raise AssertionError(f"unsupported cost state {status}")
    assert all(
        (row.get("effective_usage_revision") is None) == (row["attempt_id"] not in histories)
        for row in submissions
    )
    journal = [
        json.loads(line)
        for line in (packet / "target" / "case-journal.jsonl").read_text().splitlines()
    ]
    plans = {}
    for path in (packet / "target").glob("plan*.json"):
        value = json.loads(path.read_text())
        plans[sha256(path.read_bytes()).hexdigest()] = value
        if path.name == "plan.json":
            compact = (
                json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
            ).encode()
            plans[sha256(compact).hexdigest()] = value
    releases = [
        json.loads(line)
        for line in (packet / "target" / "release-identity.jsonl").read_text().splitlines()
    ]
    for release in releases:
        assert release["campaign_id"] == campaign_id
        assert release["real_provider_calls"] == 0
        assert release["plan_sha256"] in plans
        assert release["source_tree"] == plans[release["plan_sha256"]]["source_tree"]
        if "original_start_at" in release:
            assert release["original_start_at"] == campaign["start_at"]
            assert release["original_expires_at"] == campaign["expires_at"]
    assert (
        releases[-1]["plan_sha256"]
        == sha256((packet / "target" / "plan.supplement9.json").read_bytes()).hexdigest()
    )
    for entry in journal:
        if entry.get("kind") == "supplement_case_begin":
            assert entry["plan_sha256"] in plans
    # Every claimed passing case must have an available case document with its exact hash.
    original_pass = set()
    supplement_pass = set()
    failed = []
    for entry in journal:
        if entry.get("kind") not in {
            "case_end",
            "supplement_case_end",
            "supplement_case_reconciled",
        }:
            continue
        case_id = entry["case_id"]
        if entry["status"] != "PASS":
            failed.append(case_id)
            continue
        for assertion in entry["result"]["assertions"]:
            assert assertion["executed"] and assertion["passed"]
            for relative in assertion["evidence_paths"]:
                source = packet / "target" / relative
                assert source.is_file(), relative
                recorded = [
                    ob for ob in entry["result"]["observations"] if ob["evidence_path"] == relative
                ]
                assert recorded and all(
                    ob["sha256"] == sha256(source.read_bytes()).hexdigest() for ob in recorded
                )
        if entry["kind"] == "case_end":
            original_pass.add(case_id)
        else:
            supplement_pass.add(case_id)
    assert len(original_pass) == 80
    assert QUALIFIED_SUPPLEMENT <= supplement_pass
    assert "case.ct02_workkey.wire03_first" in supplement_pass  # retained weak pass
    campaign_audits = [json.loads(row["record"]) for row in rows(ledger, "dev12_campaign_audit")]
    audit_decisions = Counter(row.get("decision", row.get("kind")) for row in campaign_audits)
    assert campaign["paused"] and campaign["pause_reasons"] == ["authority"]
    held = [row for row in submissions if row["exposure_state"] == "outstanding"]
    held_amount = sum(
        (Decimal(row["reservation"]["max_exposure_decimal"]) for row in held), Decimal(0)
    )
    historical = json.loads((packet / "historical-underbound-ledger.json").read_text())
    htables = historical["tables"]
    assert len(htables["dev12_submissions"]["rows"]) == 1
    assert len(htables["dev12_usage_revisions"]["rows"]) == 1
    assert not htables["dev12_send_ownership"]["rows"]
    hrecord = json.loads(htables["dev12_submissions"]["rows"][0]["record"])
    husage = json.loads(htables["dev12_usage_revisions"]["rows"][0]["usage"])
    hcampaign = json.loads(htables["dev12_campaigns"]["rows"][0]["record"])
    hcomponent = husage["components"][0]
    hamount = tariff(husage["price_ref"], hcomponent["component"], hcomponent["quantity"])
    assert hrecord["attempt_id"] == husage["attempt_id"]
    assert husage["cost_status"] == "over_bound"
    assert Decimal(husage["amount_decimal"]) == hamount
    assert hamount > Decimal(hrecord["reservation"]["max_exposure_decimal"])
    assert hcampaign["paused"] and hcampaign["attempt_count"] == 0
    assert hcampaign["possible_send_count"] == 0
    outcome = {
        "status": "PASS",
        "campaign_id": campaign_id,
        "admissions": len(submissions),
        "possible_sends": len(ownership),
        "receiver_arrivals": len(arrivals),
        "usage_revision_rows": len(usage_rows),
        "effective_usage_attempts": len(histories),
        "effective_known_usd": format(known, ".9f"),
        "effective_cost_states": dict(cost_states),
        "over_bound_attempts": over_bound,
        "cumulative_reserved_usd": format(reserved, ".9f"),
        "held_reservations": len(held),
        "held_reservation_usd": format(held_amount, ".9f"),
        "exposure_states": dict(Counter(row["exposure_state"] for row in submissions)),
        "campaign_paused": campaign["paused"],
        "campaign_pause_reasons": campaign["pause_reasons"],
        "campaign_start_at": campaign["start_at"],
        "campaign_expires_at": campaign["expires_at"],
        "original_pass_pairs": len(original_pass),
        "qualified_supplement_pairs": len(QUALIFIED_SUPPLEMENT),
        "retained_weak_supplement_pass_excluded": 1,
        "retained_failed_stops": len(failed),
        "campaign_audit_decisions": dict(audit_decisions),
        "separate_historical_overbound_usd": format(hamount, ".9f"),
        "separate_historical_overbound_zero_send": True,
        "receiver_sha256": sha256((packet / "target" / "receiver.jsonl").read_bytes()).hexdigest(),
    }
    mixed = mixed_audit(packet)
    assert mixed["mixed_admissions"] == len(submissions) + mixed["legacy_admissions"]
    assert (
        mixed["mixed_possible_send_conservative_upper_count"]
        == len(ownership) + mixed["legacy_committed_intents"]
    )
    assert mixed["successor_cumulative_reserved_usd"] == outcome["cumulative_reserved_usd"]
    assert mixed["held_successor_reservations"] == outcome["held_reservations"]
    assert mixed["campaign_paused"] and mixed["mixed_financial_upper_bound"] is None
    outcome["mixed"] = mixed
    return outcome


if __name__ == "__main__":
    print(json.dumps(audit(Path(sys.argv[1]), Path(sys.argv[2])), sort_keys=True, indent=2))
