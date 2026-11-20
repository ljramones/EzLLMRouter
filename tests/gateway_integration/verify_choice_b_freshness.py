"""Independently check the bounded Choice B first-write discriminator."""

import json
from pathlib import Path
import sys


def rows(run, name):
    return [
        json.loads(line)
        for line in (run / (name + ".stdout")).read_text().splitlines()
        if line.strip()
    ]


def one(run, name):
    return json.loads((run / (name + ".stdout")).read_text())


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_choice_b_freshness.py RUN_DIR")
    run = Path(sys.argv[1])
    hold_sid = (run / "choice-b-freshness-hold-sid.stdout").read_text().strip()
    queued_sid = (run / "choice-b-freshness-queued-sid.stdout").read_text().strip()
    hold = one(run, "choice-b-freshness-hold-status")
    queued = one(run, "choice-b-freshness-queued-status")
    held_attempt, queued_attempt = hold["attempt_id"], queued["attempt_id"]
    assert hold_sid and queued_sid and hold_sid != queued_sid
    assert hold["submission_id"] == hold_sid and queued["submission_id"] == queued_sid
    assert held_attempt != queued_attempt
    assert (hold["submission_state"], hold["candidate_access"]) == ("completed", "present"), (
        "held positive did not complete",
        hold,
    )
    assert (queued["submission_state"], queued["candidate_access"]) == (
        "failed_before_transmit",
        "unavailable_due_failure",
    )
    assert one(run, "choice-b-freshness-real-pool-queued") == {
        "attempt_id": queued_attempt,
        "pool_queued": True,
    }

    events = rows(run, "choice-b-freshness-guard-events")
    pool = rows(run, "choice-b-freshness-pool-observations")
    sends = rows(run, "choice-b-freshness-send-events")
    receipts = rows(run, "choice-b-freshness-receipts")
    arrivals = rows(run, "choice-b-freshness-receiver-final")
    controls = rows(run, "choice-b-freshness-receiver-controls")
    control_events = [row["event"] for row in controls]
    assert control_events == [
        "hold_entered_after_receiver_arrival",
        "hold_released",
        "hold_response_released",
    ]
    assert [row["at_ns"] for row in controls] == sorted(row["at_ns"] for row in controls)
    revoked = one(run, "choice-b-freshness-authority-revoked")
    restored = one(run, "choice-b-freshness-authority-restored")
    assert (revoked["authority_state"], revoked["epoch"]) == ("revoked", 1)
    assert (restored["authority_state"], restored["epoch"]) == ("active", 2)
    assert revoked["monotonic_ns"] < restored["monotonic_ns"]
    queue = [
        row
        for row in pool
        if row["attempt_id"] == queued_attempt and row["event"] == "queued_in_owned_httpcore_pool"
    ]
    assert len(queue) == 1
    assert queue[0]["monotonic_ns"] < revoked["monotonic_ns"]

    by_receipt = {row["attempt_id"]: row for row in receipts}
    by_send = {row["attempt_id"]: row for row in sends}
    assert len(receipts) == len(by_receipt) == 5
    assert len(sends) == len(by_send) == 5
    assert len(arrivals) == 4
    assert len({row["attempt_id"] for row in arrivals}) == 4
    assert set(by_receipt) == set(by_send)
    assert queued_attempt in by_receipt and queued_attempt not in {
        row["attempt_id"] for row in arrivals
    }
    assert by_send[queued_attempt]["first_bytes_accepted_by_local_socket"] is False
    assert by_send[queued_attempt]["first_acceptance_events"] == 0
    # The Coordinator's fresh callback raises ContractError; the local gate
    # raises GuardRejected. Require the same public before-send semantics.
    assert by_send[queued_attempt]["lower_error"] in ("GuardRejected", "ContractError")
    assert queued["dispatch_state"] == "failed_before_dispatch"
    assert queued["terminal_error_code"] == "FDC_REJECTED"
    assert queued["terminal_attempt_id"] == queued_attempt
    for attempt in (held_attempt, queued_attempt):
        assert by_receipt[attempt]["receipt"]["timeout_seconds"] == {
            "connect": 30.0,
            "read": 30.0,
            "write": 30.0,
            "pool": 30.0,
        }, ("selected SDK timeout differs from its 30-second work budget", attempt)
    for attempt in set(by_receipt) - {held_attempt, queued_attempt}:
        assert by_receipt[attempt]["receipt"]["timeout_seconds"] == {
            "connect": 1.0,
            "read": 1.0,
            "write": 1.0,
            "pool": 1.0,
        }, ("ordinary SDK timeout was widened", attempt)
    for row in arrivals:
        attempt = row["attempt_id"]
        receipt = by_receipt[attempt]["receipt"]
        assert (
            receipt["method"],
            receipt["url"],
            receipt["body_sha256"],
            receipt["body_bytes"],
        ) == (
            row["method"],
            "http://127.0.0.1:8766/v1/chat/completions",
            row["body_sha256"],
            row["body_bytes"],
        )
        assert by_send[attempt]["first_bytes_accepted_by_local_socket"] is True
        assert by_send[attempt]["first_acceptance_events"] == 1
        assert by_send[attempt]["lower_error"] is None

    for attempt in by_receipt:
        stages = [row for row in events if row["attempt_id"] == attempt]
        names = [row["stage"] for row in stages]
        assert names[:3] == ["entered", "commit_acknowledged", "released_to_lower_transport"]
        assert names.count("entered") == 1
        if attempt == queued_attempt:
            assert names.count("lower_error") == 1
            assert stages[2]["monotonic_ns"] < queue[0]["monotonic_ns"]
        else:
            assert "lower_error" not in names

    assert one(run, "choice-b-freshness-positive-after")["state"] == "delivered"
    assert one(run, "choice-b-freshness-positive-after")["receiver_delta"] == 1
    assert (run / "choice-b-freshness-receiver-before-horizon.stdout").read_bytes() == (
        run / "choice-b-freshness-receiver-after-horizon.stdout"
    ).read_bytes()
    assert int((run / "choice-b-freshness-horizon.stdout").read_text()) >= 5000
    assert one(run, "choice-b-freshness-store") == {
        "submissions": 5,
        "preparatory_intents": 5,
        "guard_dispatches": 5,
        "usage_revisions": 4,
    }
    print(
        json.dumps(
            {
                "status": "CHOICE_B_LOCAL_FIRST_WRITE_QUEUE_REVOCATION_OBSERVED",
                "queued_attempt_id": queued_attempt,
                "queued_after_guard_commit": True,
                "local_authority_revoked_before_resource_release": True,
                "queued_first_bytes_accepted_by_local_socket": False,
                "queued_receiver_arrivals": 0,
                "matching_positive_arrivals_and_receipts": 4,
                "scope": "fixed synthetic plaintext HTTP/1.1 local authority and socket.send acceptance only",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
