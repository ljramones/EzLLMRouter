"""Correlate available receiver tokens with main-service guard receipts on failure."""
from pathlib import Path
import json
import sys


def rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def main():
    report_unmatched = len(sys.argv) == 4 and sys.argv[3] == "--report-unmatched"
    if len(sys.argv) not in (3, 4) or (len(sys.argv) == 4 and not report_unmatched):
        raise SystemExit("usage: correlate_partial.py ARRIVALS RECEIPTS [--report-unmatched]")
    receiver, receipts = rows(sys.argv[1]), rows(sys.argv[2])
    by_attempt = {row["attempt_id"]: row for row in receipts}
    if len(by_attempt) != len(receipts):
        raise ValueError("duplicate guard receipt attempt")
    if any(row["receipt"].get("attempt_id") != row["attempt_id"] or
           not row.get("submission_id") for row in receipts):
        raise ValueError("guard table identity/receipt mismatch")
    matched = []
    unmatched = []
    for arrival in receiver:
        attempt = arrival.get("attempt_id")
        row = by_attempt.get(attempt)
        if not attempt or not row:
            if report_unmatched:
                unmatched.append({"attempt_id": attempt, "sequence": arrival.get("sequence"),
                                  "body_sha256": arrival.get("body_sha256")})
                continue
            raise ValueError("receiver attempt lacks main guard receipt")
        receipt = row["receipt"]
        if (receipt.get("body_sha256") != arrival.get("body_sha256") or
            receipt.get("body_bytes") != arrival.get("body_bytes") or
            receipt.get("method") != arrival.get("method")):
            raise ValueError("receiver/guard final request mismatch")
        matched.append({"attempt_id": attempt, "body_sha256": arrival["body_sha256"],
                        "body_bytes": arrival["body_bytes"]})
    print(json.dumps({"receiver_arrivals": len(receiver), "main_guard_receipts": len(receipts),
                      "matched_arrivals": matched, "unmatched_arrivals": unmatched}, sort_keys=True))


if __name__ == "__main__":
    main()
