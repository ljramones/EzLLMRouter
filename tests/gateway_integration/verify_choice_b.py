"""Check the first Choice B executable discriminator; freshness remains open."""
import json
from pathlib import Path
import sys


def rows(run, name):
    return [json.loads(line) for line in (run / (name + ".stdout")).read_text().splitlines() if line]


def one(run, name):
    return json.loads((run / (name + ".stdout")).read_text())


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_choice_b.py RUN_DIR")
    run = Path(sys.argv[1])
    isolation = one(run, "choice-b-worker-isolation")
    assert (isolation["network_mode"], isolation["default_route"],
            isolation["trusted_code_mounted"],
            isolation["trusted_credentials_in_environment"]) == ("none", False, False, False)
    assert isolation["direct_receiver_connect_errno"] != 0
    worker = one(run, "choice-b-worker-identities")
    assert worker["boundary"] == "network-disabled LiteLLM ASGI worker"
    assert worker["selected_transport"] == "RelayTransport"
    assert all(len(worker[name]["sha256"]) == 64 for name in
               ("litellm", "proxy", "openai_sdk", "httpx"))
    assert one(run, "choice-b-readiness") == 200
    assert one(run, "choice-b-raw-probe")["error_type"] in ("ConnectError", "ConnectTimeout")
    assert one(run, "choice-b-forged-attempt") == {
        "probe": "forged_sender_attempt", "rejected": True, "error_type": "ValueError"}
    for name in ("choice-b-positive-before", "choice-b-positive-after"):
        assert one(run, name)["state"] == "delivered"
        assert one(run, name)["receiver_delta"] == 1
    receiver = rows(run, "choice-b-receiver")
    receipts = rows(run, "choice-b-receipts")
    events = rows(run, "choice-b-guard-events")
    assert len(receiver) == len(receipts) == 2
    assert len({row["attempt_id"] for row in receiver}) == 2
    by_attempt = {row["attempt_id"]: row["receipt"] for row in receipts}
    assert set(by_attempt) == {row["attempt_id"] for row in receiver}
    for arrival in receiver:
        receipt = by_attempt[arrival["attempt_id"]]
        assert (receipt["method"], receipt["body_sha256"], receipt["body_bytes"]) == (
            arrival["method"], arrival["body_sha256"], arrival["body_bytes"])
        stages = [row["stage"] for row in events if row["attempt_id"] == arrival["attempt_id"]]
        assert stages[:3] == ["entered", "commit_acknowledged", "released_to_lower_transport"]
        assert stages.count("entered") == 1
    assert one(run, "choice-b-store") == {"submissions": 2,
        "preparatory_intents": 2, "guard_dispatches": 2, "usage_revisions": 2}
    modules = one(run, "choice-b-modules")
    assert modules["litellm_imported"] is False
    assert modules["provider_key_in_trusted_process"] is True
    for name in ("choice-b-receiver-before", "choice-b-receiver-after-negatives",
                 "choice-b-receiver-after-horizon"):
        assert (run / (name + ".stdout")).read_bytes() == (
            run / "choice-b-receiver-before.stdout").read_bytes()
    assert int((run / "choice-b-horizon.stdout").read_text()) >= 5000
    print(json.dumps({"status": "CHOICE_B_EGRESS_AND_SELECTED_POSITIVE_OBSERVED_FRESHNESS_OPEN",
        "selected_receiver_requests": 2, "matching_trusted_receipts": 2,
        "raw_worker_receiver_delta": 0, "forged_attempt_receiver_delta": 0,
        "freshness_after_sender_wait": "NOT_TESTED",
        "scope": "synthetic Unix-socket worker and trusted sender only"}, sort_keys=True))


if __name__ == "__main__":
    main()
