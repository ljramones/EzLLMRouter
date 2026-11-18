"""Check bounded DEV-04 boundary records without masking a demonstrated limit."""
import json
from pathlib import Path
import sys


def rows(run, name):
    return [json.loads(line) for line in (run / (name + ".stdout")).read_text().splitlines() if line]


def one(run, name):
    values = rows(run, name)
    assert len(values) == 1, name
    return values[0]


def matched(arrivals, receipts):
    by_attempt = {row["attempt_id"]: row["receipt"] for row in receipts}
    assert len(by_attempt) == len(receipts)
    for arrival in arrivals:
        receipt = by_attempt.get(arrival.get("attempt_id"))
        if receipt is None:
            continue
        assert (receipt["body_sha256"], receipt["body_bytes"], receipt["method"]) == (
            arrival["body_sha256"], arrival["body_bytes"], arrival["method"])
    return by_attempt


def errors(run):
    arrivals = rows(run, "d04-4-receiver")
    receipts = rows(run, "d04-4-receipts")
    events = rows(run, "d04-4-events")
    sdk = rows(run, "d04-4-sdk")
    store = rows(run, "d04-4-store")
    assert len(arrivals) == len(receipts) == len(sdk) == 7
    assert len({row["attempt_id"] for row in arrivals}) == 7
    assert set(row["attempt_id"] for row in arrivals) == set(matched(arrivals, receipts))
    assert all(row["matched_sdk_clients"] == 1 and row["effective_max_retries"] == 0
               and row["selected_pool_requests_at_send_end"] == 0 for row in sdk)
    for attempt in {row["attempt_id"] for row in arrivals}:
        stages = [row["stage"] for row in events if row["attempt_id"] == attempt]
        assert stages[:3] == ["entered", "commit_acknowledged", "released_to_lower_transport"]
        assert stages.count("entered") == 1 and "blocked" not in stages
    records = {row["step_id"]: row for row in store if "step_id" in row}
    assert len(records) == 7 and store[-1] == {"usage_revisions": 4}
    for mode in ("422", "503", "close"):
        actor = one(run, "d04-4-" + mode)
        assert actor["receiver_delta"] == 1
        record = records["step.dev04.boundary." + mode]
        if mode == "close":
            assert (actor["submission_state"], actor["usage_state"]) == ("outcome_unknown", "not_recorded")
            assert record["submission_state"] == "outcome_unknown" and record["terminal_code"] is None
        else:
            assert (actor["public_code"], actor["http_status"]) == ("REMOTE_EXECUTION_FAILED", 502)
            assert (record["submission_state"], record["terminal_code"]) == (
                "failed_after_transmit", "REMOTE_EXECUTION_FAILED")
        assert int((run / ("d04-4-" + mode + "-horizon.stdout")).read_text()) >= 5000
        assert (run / ("d04-4-" + mode + "-before-horizon.stdout")).read_bytes() == (
            run / ("d04-4-" + mode + "-after-horizon.stdout")).read_bytes()
    assert any(row["stage"] == "lower_error" for row in events)
    return {"case": "D04-4", "observed_provider_arrivals": 7,
            "controlled_negatives": ["422", "503", "close"],
            "known_remote_errors": 2, "unknown_outcomes": 1,
            "guard_entries_per_attempt": 1, "effective_sdk_retries": 0,
            "selected_pool_requests_at_send_end": 0,
            "complete_proxy_task_drain": "not_established"}


def wait(run):
    queued = one(run, "d04-5-real-pool-queued")["attempt_id"]
    events = rows(run, "d04-5-events")
    pool = rows(run, "d04-5-pool")
    trace = rows(run, "d04-5-lower-trace")
    authority = rows(run, "d04-5-authority-events")
    receiver = rows(run, "d04-5-receiver")
    mixed = rows(run, "d04-5-receipts")
    receipts = [row for row in mixed if "receipt" in row]
    records = [row for row in mixed if "context_id" in row]
    sdk = rows(run, "d04-5-sdk")
    matched(receiver, receipts)
    stages = {row["stage"]: row for row in events if row["attempt_id"] == queued}
    queue = next(row for row in pool if row["attempt_id"] == queued and
                 row["event"] == "queued_in_selected_httpcore_pool")
    revoked = next(row for row in authority if row["event"] == "authority_revoked_after_pool_queue")
    assert stages["entered"]["monotonic_ns"] < stages["commit_acknowledged"]["monotonic_ns"]
    assert stages["commit_acknowledged"]["monotonic_ns"] < stages["released_to_lower_transport"]["monotonic_ns"]
    assert stages["released_to_lower_transport"]["monotonic_ns"] < queue["monotonic_ns"] < revoked["monotonic_ns"]
    first_write = [row for row in trace if row["attempt_id"] == queued and
                   row["event"].endswith("send_request_headers.started")]
    arrival = [row for row in receiver if row.get("attempt_id") == queued]
    if first_write:
        assert first_write[0]["monotonic_ns"] > revoked["monotonic_ns"]
        assert first_write[0]["authority_state"] == "revoked"
    assert bool(first_write) == bool(arrival)
    overlap = one(run, "d04-5-overlap-contexts")
    assert overlap["receiver_delta"] == 2
    overlap_ids = {row["attempt_id"] for row in overlap["contexts"]}
    overlap_contexts = {row["context_id"] for row in records if row["attempt_id"] in overlap_ids}
    assert len(overlap_ids) == len(overlap_contexts) == 2
    assert overlap_ids <= {row["attempt_id"] for row in receiver}
    assert one(run, "d04-5-swapped-context")["receiver_delta"] == 0
    assert any(row["code"] == "SECOND_SEND_REJECTED" for row in events if row["stage"] == "blocked")
    swapped_records = [row for row in records if row["step_id"] == "step.dev04.wait.swapped"]
    assert len(swapped_records) == 1
    assert swapped_records[0]["submission_state"] == "failed_before_transmit"
    assert swapped_records[0]["attempt_id"] not in {row["attempt_id"] for row in receipts}
    assert all(row["effective_max_retries"] == 0 for row in sdk)
    assert int((run / "d04-5-stale-horizon.stdout").read_text()) >= 5000
    assert (run / "d04-5-stale-before-horizon.stdout").read_bytes() == (
        run / "d04-5-stale-after-horizon.stdout").read_bytes()
    assert int((run / "d04-5-swap-horizon.stdout").read_text()) >= 5000
    assert (run / "d04-5-swap-before-horizon.stdout").read_bytes() == (
        run / "d04-5-swap-after-horizon.stdout").read_bytes()
    for name in ("d04-5-positive-before", "d04-5-positive-after-stale", "d04-5-positive-after-swap"):
        assert one(run, name)["state"] == "delivered"
    return {"case": "D04-5", "queued_attempt_id": queued,
            "guard_commit_before_real_pool_queue": True,
            "authority_changed_while_queued": True,
            "first_request_write_after_change": bool(first_write),
            "stale_provider_arrival": bool(arrival),
            "disposition": "BOUNDARY_LIMIT_FOUND" if arrival else "NO_STALE_SEND_OBSERVED",
            "distinct_overlap_contexts": 2, "swapped_context_receiver_delta": 0,
            "pool_assignment_instant": "not_directly_timestamped"}


def bypass(run):
    probes = json.loads((run / "d04-6-probes.stdout").read_text())
    assert len(probes) == 4
    by_name = {row["probe"]: row for row in probes}
    raw = by_name["deliberate_arbitrary_raw_client"]
    arrivals = rows(run, "d04-6-receiver")
    assert raw["attempt_id"] == "probe.raw.dev04" and raw["receiver_delta"] == 1
    assert raw["status"] == 400
    assert sum(row.get("attempt_id") == "probe.raw.dev04" for row in arrivals) == 1
    assert one(run, "d04-6-positive-before")["state"] == "delivered"
    assert one(run, "d04-6-positive-after")["state"] == "delivered"
    assert one(run, "d04-6-alt-handler-startup")["alternate_handler_startup"] == "rejected"
    assert int((run / "d04-6-horizon.stdout").read_text()) >= 5000
    assert (run / "d04-6-before-horizon.stdout").read_bytes() == (
        run / "d04-6-after-horizon.stdout").read_bytes()
    selected = [row for row in probes if row["probe"] != "deliberate_arbitrary_raw_client"]
    return {"case": "D04-6", "selected_handler_probes": selected,
            "deliberate_raw_client_arrivals": 1, "receiver_rejected_raw_payload": True,
            "selected_handler_bypass_observed": any(row["receiver_delta"] for row in selected),
            "alternate_handler_startup": "rejected",
            "disposition": "BOUNDARY_LIMIT_FOUND"}


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("errors", "wait", "bypass"):
        raise SystemExit("usage: verify_boundary.py errors|wait|bypass RUN_DIR")
    run = Path(sys.argv[2])
    result = {"errors": errors, "wait": wait, "bypass": bypass}[sys.argv[1]](run)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
