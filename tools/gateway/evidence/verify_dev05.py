"""Strict DEV-05 client/tool evidence checks; stdout files are single JSON documents."""

if not __package__:
    import sys
    from pathlib import Path

    for _parent in Path(__file__).resolve().parents:
        if (_parent / "tools/gateway/__init__.py").is_file():
            sys.path.insert(0, str(_parent))
            break
        if (_parent / "server/tools/gateway/__init__.py").is_file():
            sys.path.insert(0, str(_parent / "server"))
            break


import json
from pathlib import Path
import sys


def one(run, name):
    return json.loads((run / (name + ".stdout")).read_text())


def rows(run, name):
    return [
        json.loads(line) for line in (run / (name + ".stdout")).read_text().splitlines() if line
    ]


def public_destination(value):
    assert (
        value["configuration_ref"],
        value["service"],
        value["endpoint"],
        value["model"],
        value["model_version"],
        value["processing_region"],
    ) == ("cfg.demo", "litellm.dev04", "127.0.0.1", "model.demo", "v1", "local")


def checkpoint(run):
    assert one(run, "d05-readiness") == 200
    assert one(run, "d05-python-package")["version"] == "0.0.3"
    assert one(run, "d05-js-package")["version"] == "0.0.2"
    worker = one(run, "d05-worker-identities")
    isolation = one(run, "d05-worker-isolation")
    assert worker["selected_transport"] == "RelayTransport"
    assert isolation["network_mode"] == "none" and isolation["default_route"] is False
    assert isolation["trusted_code_mounted"] is False
    assert isolation["trusted_credentials_in_environment"] is False
    assert isolation["direct_receiver_connect_errno"] != 0
    js = one(run, "d05-js-text")
    py = one(run, "d05-python-cross-text")
    cross_text = one(run, "d05-js-cross-text")
    assert (js["receiver_delta"], py["receiver_delta"]) == (1, 1)
    assert py["cross_read"] == js["submission_id"]
    assert py["cross_candidate_id"] == js["candidate_id"]
    assert py["cross_attempt_id"] == js["attempt_id"]
    assert cross_text["cross_read"] == py["submission_id"]
    assert cross_text["candidate_id"] == py["candidate_id"]
    assert cross_text["attempt_id"] == py["attempt_id"]
    assert cross_text["provider_sends_delta"] == cross_text["caller_tool_executions"] == 0
    assert cross_text["usage_state"] == "available"
    public_destination(js["served_destination"])
    public_destination(py["served_destination"])
    for name, expected, step in (
        ("d05-python-by-work-js-text", js, "step.dev04.js.text"),
        ("d05-js-by-work-python-text", py, "step.dev04.python.text"),
    ):
        by_work = one(run, name)
        assert by_work["by_work"]["step_id"] == step
        assert by_work["by_work"]["execution_generation"] == "gen.1"
        assert (by_work["submission_id"], by_work["candidate_id"], by_work["attempt_id"]) == (
            expected["submission_id"],
            expected["candidate_id"],
            expected["attempt_id"],
        )
        assert by_work["provider_sends_delta"] == by_work["caller_tool_executions"] == 0
    cycles = [one(run, name) for name in ("d05-python-cycle", "d05-js-cycle")]
    assert [row["result_kind"] for row in cycles] == ["result_value", "result_text"]
    for row in cycles:
        assert row["provider_sends_delta"] == 2 and row["caller_tool_executions"] == 1
        assert row["first_submission_id"] != row["second_submission_id"]
        assert row["first_attempt_id"] != row["second_attempt_id"]
        assert row["first_candidate_id"] != row["second_candidate_id"]
        assert row["call_id"] == "call.lookup.1"
        assert len(row["destinations"]) == 2
        for value in row["destinations"]:
            public_destination(value)
        assert all(item["state"] == "available" for item in row["usage"])
    for name, cycle in (
        ("d05-js-cross-python-tool", cycles[0]),
        ("d05-python-cross-js-tool", cycles[1]),
    ):
        cross = one(run, name)
        assert cross["cross_read"] == cycle["first_submission_id"]
        assert cross["candidate_id"] == cycle["first_candidate_id"]
        assert cross["attempt_id"] == cycle["first_attempt_id"]
        assert cross["usage_state"] == "available"
        assert cross["provider_sends_delta"] == cross["caller_tool_executions"] == 0
    for name, cycle, step in (
        ("d05-js-by-work-python-tool", cycles[0], "step.dev03.python"),
        ("d05-python-by-work-js-tool", cycles[1], "step.dev03.js"),
    ):
        by_work = one(run, name)
        assert by_work["by_work"]["step_id"] == step
        assert by_work["by_work"]["execution_generation"] == "gen.1"
        assert (by_work["submission_id"], by_work["candidate_id"], by_work["attempt_id"]) == (
            cycle["first_submission_id"],
            cycle["first_candidate_id"],
            cycle["first_attempt_id"],
        )
        assert by_work["provider_sends_delta"] == by_work["caller_tool_executions"] == 0
    arrivals = rows(run, "d05-checkpoint-receiver")
    receipts = rows(run, "d05-checkpoint-receipts")
    assert len(arrivals) == len(receipts) == 6
    assert len({item["attempt_id"] for item in arrivals}) == 6
    assert [item["message_roles"] for item in arrivals] == [
        ["system", "user"],
        ["system", "user"],
        ["system", "user"],
        ["system", "user", "assistant", "tool"],
        ["system", "user"],
        ["system", "user", "assistant", "tool"],
    ]
    assert [item["tool_call_ids"] for item in arrivals] == [
        [],
        [],
        [],
        ["call.lookup.1"],
        [],
        ["call.lookup.1"],
    ]
    by_attempt = {item["attempt_id"]: item["receipt"] for item in receipts}
    assert len(by_attempt) == 6
    for arrival in arrivals:
        receipt = by_attempt[arrival["attempt_id"]]
        assert (receipt["method"], receipt["body_sha256"], receipt["body_bytes"]) == (
            arrival["method"],
            arrival["body_sha256"],
            arrival["body_bytes"],
        )
        assert receipt["timeout_seconds"] and all(
            0 < value <= 5 for value in receipt["timeout_seconds"].values()
        )
    return {
        "checkpoint": "D05-01/02",
        "provider_arrivals": 6,
        "caller_lookups": 2,
        "cross_read_sends": 0,
    }


def full(run):
    result = checkpoint(run)
    no_store = [one(run, name) for name in ("d05-python-no-store", "d05-js-no-store")]
    for row in no_store:
        assert row["variant"] == "live_no_store"
        assert row["provider_sends_delta"] == 2 and row["caller_tool_executions"] == 1
        assert row["forged_source_rejected"] is True
        assert row["negative_stable_ms"] >= 5000
        assert row["candidate_access"] == ["not_retained", "not_retained"]
        assert len(row["destinations"]) == 2
        for value in row["destinations"]:
            public_destination(value)
    for mode, expected in (("503", "failed_after_transmit"), ("close", "outcome_unknown")):
        actor = one(run, "d05-" + mode)
        cross = one(run, "d05-js-cross-" + mode)
        assert actor["receiver_delta"] == 1 and actor["submission_state"] == expected
        assert actor["usage_state"] == "not_recorded"
        assert cross["cross_read"] == actor["submission_id"]
        assert cross["attempt_id"] == actor["attempt_id"]
        assert cross["submission_state"] == expected and cross["usage_state"] == "not_recorded"
        assert cross["provider_sends_delta"] == cross["caller_tool_executions"] == 0
        if mode == "503":
            assert (actor["public_code"], actor["http_status"]) == ("REMOTE_EXECUTION_FAILED", 502)
        assert one(run, "d05-" + mode + "-drain")["submission_state"] == expected
        assert int((run / ("d05-" + mode + "-horizon.stdout")).read_text()) >= 5000
        assert (run / ("d05-" + mode + "-before-horizon.stdout")).read_bytes() == (
            run / ("d05-" + mode + "-after-horizon.stdout")
        ).read_bytes()
    mutation = one(run, "d05-tool-mutation")
    assert mutation["failure"] == "FDC_REJECTED" and mutation["provider_sends_delta"] == 0
    assert mutation["caller_tool_executions"] == 0 and mutation["negative_stable_ms"] >= 5000
    assert (run / "d05-mutation-before.stdout").read_bytes() == (
        run / "d05-mutation-after.stdout"
    ).read_bytes()
    assert one(run, "d05-raw-probe")["error_type"] in ("ConnectError", "ConnectTimeout")
    assert one(run, "d05-forged-attempt") == {
        "probe": "forged_sender_attempt",
        "rejected": True,
        "error_type": "ValueError",
    }
    assert int((run / "d05-probes-horizon.stdout").read_text()) >= 5000
    assert (run / "d05-probes-before.stdout").read_bytes() == (
        run / "d05-receiver.stdout"
    ).read_bytes()
    assert one(run, "d05-probes-health") == 200
    arrivals = rows(run, "d05-receiver")
    receipts = rows(run, "d05-receipts")
    events = rows(run, "d05-guard-events")
    sends = rows(run, "d05-send-events")
    relay_counts = one(run, "d05-worker-attempts")["relay_attempt_counts"]
    store = rows(run, "d05-store-metadata")
    authority = rows(run, "d05-authority-chain")
    assert len(arrivals) == len(receipts) == 12
    assert len(store) == 13
    assert len(authority) == 13
    assert {row["attempt_id"] for row in authority} == {row["attempt_id"] for row in store}
    assert sorted(row["usage_revisions"] for row in authority) == [0] * 3 + [1] * 10
    for row in authority:
        intent = row["intent"]
        assert intent is not None
        assert intent["attempt_id"] == row["attempt_id"]
        assert intent["work_digest"] == row["work_digest"]
        assert intent["plan_id"].startswith("plan.")
        assert intent["prepared_request_digest"].startswith("sha256:")
        if row["step_id"] == "step.dev03.mutation":
            assert row["receipt_plan_id"] is None and row["receipt_work_digest"] is None
        else:
            assert row["receipt_plan_id"] == intent["plan_id"]
            assert row["receipt_work_digest"] == row["work_digest"]
    assert set(relay_counts) == {row["attempt_id"] for row in store}
    assert all(count == 1 for count in relay_counts.values())
    assert len({row["attempt_id"] for row in arrivals}) == 12
    assert [row["message_roles"] for row in arrivals[6:]] == [
        ["system", "user"],
        ["system", "user", "assistant", "tool"],
        ["system", "user"],
        ["system", "user", "assistant", "tool"],
        ["system", "user"],
        ["system", "user"],
    ]
    assert [row["tool_call_ids"] for row in arrivals[6:]] == [
        [],
        ["call.lookup.1"],
        [],
        ["call.lookup.1"],
        [],
        [],
    ]
    by_receipt = {row["attempt_id"]: row["receipt"] for row in receipts}
    assert len(by_receipt) == 12
    for arrival in arrivals:
        receipt = by_receipt[arrival["attempt_id"]]
        assert (receipt["method"], receipt["body_sha256"], receipt["body_bytes"]) == (
            arrival["method"],
            arrival["body_sha256"],
            arrival["body_bytes"],
        )
        assert receipt["timeout_seconds"] and all(
            0 < value <= 5 for value in receipt["timeout_seconds"].values()
        )
        stages = [row["stage"] for row in events if row["attempt_id"] == arrival["attempt_id"]]
        assert stages[:3] == ["entered", "commit_acknowledged", "released_to_lower_transport"]
        assert stages.count("entered") == 1
    assert len(sends) == 13
    assert {row["attempt_id"] for row in sends} == (
        {row["attempt_id"] for row in arrivals}
        | {next(row["attempt_id"] for row in store if row["step_id"] == "step.dev03.mutation")}
    )
    assert all(
        row["first_acceptance_events"] == 1
        for row in sends
        if row["attempt_id"] in {arrival["attempt_id"] for arrival in arrivals}
    )
    assert all(
        row["first_bytes_accepted_by_local_socket"] is True
        for row in sends
        if row["attempt_id"] in {arrival["attempt_id"] for arrival in arrivals}
    )
    mutation_attempt = next(
        row["attempt_id"] for row in store if row["step_id"] == "step.dev03.mutation"
    )
    mutations = rows(run, "d05-tool-mutation-events")
    assert len(mutations) == 1 and mutations[0]["attempt_id"] == mutation_attempt
    assert mutations[0]["field"] == "tools[0].function.description"
    assert mutations[0]["bound_sha256"] != mutations[0]["mutated_sha256"]
    assert mutations[0]["same_length"] is True
    assert (
        next(row for row in sends if row["attempt_id"] == mutation_attempt)[
            "first_acceptance_events"
        ]
        == 0
    )
    assert (
        next(row for row in sends if row["attempt_id"] == mutation_attempt)[
            "first_bytes_accepted_by_local_socket"
        ]
        is False
    )
    assert mutation_attempt not in by_receipt
    assert [
        (row["stage"], row["code"]) for row in events if row["attempt_id"] == mutation_attempt
    ] == [("entered", None), ("blocked", "FDC_REJECTED")]
    no_store_rows = [
        row for row in store if row["step_id"] in ("step.dev03.no_store", "step.dev03.js.no_store")
    ]
    assert len(no_store_rows) == 4
    assert all(
        row["content_store_allowed"] is False
        and row["candidate_present"] is False
        and row["candidate_access"] == "not_retained"
        for row in no_store_rows
    )
    assert all(row["usage_state"] == "available" for row in no_store_rows)
    storage = one(run, "d05-no-store-storage")
    assert storage["no_store_submissions"] == 4
    assert storage["candidate_or_prompt_literals_present"] is False
    assert storage["checked_rows"] == {
        "submissions": 4,
        "intents": 4,
        "guard_dispatches": 4,
        "usage_revisions": 4,
    }
    assert one(run, "d05-log-scan")["log_scan"] == "PASS"
    assert all(row["model"] == "model.demo" for row in arrivals)
    result.update(
        {
            "matrix": "DEV05_SEPARATED_CLIENT_TOOL_CHECKPOINT_OBSERVED",
            "provider_arrivals": 12,
            "caller_lookups": 4,
            "retained_text": 2,
            "retained_tool_rounds": 4,
            "no_store_tool_rounds": 4,
            "failure_requests": 2,
            "blocked_before_send": 1,
        }
    )
    return result


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("checkpoint", "full"):
        raise SystemExit("usage: verify_dev05.py checkpoint|full RUN_DIR")
    run = Path(sys.argv[2])
    result = checkpoint(run) if sys.argv[1] == "checkpoint" else full(run)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
