"""Cross-check independent receiver arrivals with durable guard acknowledgments."""

from pathlib import Path
import json
import sys


def lines(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line]


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: verify_runtime.py ARRIVALS_JSONL GUARD_RECORDS_JSONL")
    arrivals, receipts = lines(sys.argv[1]), lines(sys.argv[2])
    if len(arrivals) != 7 or len(receipts) != 7:
        raise ValueError("expected seven provider arrivals and seven guard commits")
    by_attempt = {row["attempt_id"]: row for row in receipts}
    if len(by_attempt) != len(receipts) or any(not row.get("attempt_id") for row in arrivals):
        raise ValueError("duplicate or missing attempt identity")
    if {row["attempt_id"] for row in arrivals} != set(by_attempt):
        raise ValueError("receiver/guard attempt set differs")
    for arrival in arrivals:
        receipt = by_attempt[arrival["attempt_id"]]
        if (
            arrival["body_sha256"] != receipt["body_sha256"]
            or arrival["body_bytes"] != receipt["body_bytes"]
            or arrival["method"] != receipt["method"]
            or receipt["url"] != "http://127.0.0.1:8766/v1/chat/completions"
        ):
            raise ValueError("final request and receiver bytes differ")
    print(
        json.dumps(
            {
                "status": "SEVEN_CORRELATED_GUARD_COMMIT_AND_RECEIVER_ARRIVALS",
                "attempt_ids": sorted(by_attempt),
            }
        )
    )


if __name__ == "__main__":
    main()
