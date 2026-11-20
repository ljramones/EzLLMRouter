"""Independent read-only reconciliation of legacy and successor target rows.

The legacy synthetic prewrite failure has an admitted owner and intent but no
native price/usage row. Count its admission and conservatively allocate one
possible send; leave its financial upper bound unknown and future release
fail-closed. This does not alter the original campaign counters.
"""

from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import sys


def audit(export: Path):
    ledger_path = export / "ledger.json"
    ledger = json.loads(ledger_path.read_text())
    needed = (
        "submissions",
        "intents",
        "guard_dispatches",
        "usage_revisions",
        "work_key_owners",
        "dev12_submissions",
        "dev12_send_ownership",
        "dev12_usage_revisions",
        "dev12_campaigns",
    )
    assert all(
        name in ledger and "schema" in ledger[name] and "columns" in ledger[name] for name in needed
    )
    legacy = [json.loads(row["record"]) for row in ledger["submissions"]["rows"]]
    successor = [json.loads(row["record"]) for row in ledger["dev12_submissions"]["rows"]]
    intents = ledger["intents"]["rows"]
    owners = ledger["work_key_owners"]["rows"]
    guards = ledger["guard_dispatches"]["rows"]
    legacy_usage = ledger["usage_revisions"]["rows"]
    successor_guards = ledger["dev12_send_ownership"]["rows"]
    campaign = json.loads(ledger["dev12_campaigns"]["rows"][0]["record"])
    assert len({row["submission_id"] for row in legacy + successor}) == len(legacy) + len(successor)
    assert len({row["submission_id"] for row in owners}) == len(owners)
    assert len(owners) == len(legacy) + len(successor)
    by_id = {row["submission_id"]: row for row in legacy + successor}
    legacy_ids = {row["submission_id"] for row in legacy}
    for owner in owners:
        row = by_id[owner["submission_id"]]
        assert json.loads(owner["work_key"]) == row["work_key"]
        assert owner["contract_version"] == (
            "0.2" if owner["submission_id"] in legacy_ids else "0.3"
        )
    assert len(legacy) == len(intents) == 1
    assert not guards and not legacy_usage
    old = legacy[0]
    intent = json.loads(intents[0]["intent"])
    assert intents[0]["submission_id"] == old["submission_id"]
    assert intents[0]["attempt_id"] == old["attempt_id"] == intent["attempt_id"]
    assert old["submission_state"] == "failed_before_transmit"
    assert old["dispatch_state"] == "failed_before_dispatch"
    assert old["settlement_state"] == "unsettled"
    assert old["terminal_failure"]["code"] == "INTENT_PERSIST_FAILED"
    assert old["work_digest"] == intent["work_digest"]
    case_path = export / "target/cases/case.ct02_workkey.wire02_first.continuation4.json"
    case = json.loads(case_path.read_text())
    value = case["payload"]
    assert (value["legacy_before"], value["legacy_after"]) == (0, 1)
    assert value["first"]["reply"]["handle"]["submission_id"] == old["submission_id"]
    assert value["first"]["reply"]["attempt_id"] == old["attempt_id"]
    assert value["owner"] == {"contract_version": "0.2", "submission_id": old["submission_id"]}
    assert value["before"]["campaign"] == value["after"]["campaign"]
    assert campaign["attempt_count"] == len(successor)
    assert campaign["possible_send_count"] == len(successor_guards)
    assert len(successor) + len(legacy) <= campaign["max_attempts"]
    # Intent is counted as possible-send capacity even though no legacy
    # guard/receiver record was observed. This is a conservative upper count.
    legacy_possible = {row["attempt_id"] for row in intents + guards}
    send_upper = len(successor_guards) + len(legacy_possible)
    assert send_upper <= campaign["max_attempts"]
    successor_bound = Decimal(campaign["cumulative_reserved_decimal"])
    assert successor_bound <= Decimal(campaign["ceiling_decimal"])
    journal = export / "target/case-journal.jsonl"
    observed = [json.loads(line) for line in journal.read_text().splitlines()]
    assert any(
        row.get("case_id") == case["case_id"] and row.get("status") == "PASS" for row in observed
    )
    return {
        "kind": "dev12_completion02_mixed_immutable_reconciliation_v1",
        "status": "MIXED_COUNTS_RECONCILED_FINANCIAL_HEADROOM_UNRESOLVED",
        "source_database_sha256": json.loads((export / "AUDIT.json").read_text())[
            "source_database_sha256"
        ],
        "logical_ledger_sha256": sha256(ledger_path.read_bytes()).hexdigest(),
        "journal_sha256": sha256(journal.read_bytes()).hexdigest(),
        "legacy_case_sha256": sha256(case_path.read_bytes()).hexdigest(),
        "successor_admissions": len(successor),
        "legacy_admissions": len(legacy),
        "mixed_admissions": len(successor) + len(legacy),
        "successor_guarded_possible_sends": len(successor_guards),
        "legacy_committed_intents": len(intents),
        "legacy_guard_dispatches": len(guards),
        "mixed_possible_send_conservative_upper_count": send_upper,
        "successor_cumulative_reserved_usd": format(successor_bound, ".9f"),
        "legacy_admitted_finite_reservation": None,
        "legacy_observed_cost": None,
        "mixed_financial_upper_bound": None,
        "legacy_status": {
            "submission_id": old["submission_id"],
            "attempt_id": old["attempt_id"],
            "state": old["submission_state"],
            "settlement": old["settlement_state"],
        },
        "campaign_paused": campaign["paused"],
        "campaign_pause_reasons": campaign["pause_reasons"],
        "held_successor_reservations": sum(
            json.loads(row["record"])["exposure_state"] == "outstanding"
            for row in ledger["dev12_submissions"]["rows"]
        ),
        "new_release_eligible": False,
        "new_release_blockers": ["authority_pause", "legacy_financial_upper_bound_unestablished"],
        "interpretation": "The legacy intent is booked against admission and possible-send capacity. Its absent native usage and finite reservation are unknown, not a zero-dollar observation. No new send is released until a supported finite mixed financial bound is established under independent authority.",
    }


if __name__ == "__main__":
    print(json.dumps(audit(Path(sys.argv[1])), sort_keys=True, indent=2))
