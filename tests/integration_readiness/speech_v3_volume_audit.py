"""Read-only independent reduction of a retained v3 volume export and CSV."""

import csv
from collections import defaultdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "deploy/local/.state/integration-v3-runs" / sys.argv[1]
if not sys.argv[1].startswith("volume-v3-"):
    raise SystemExit("volume-v3 run ID required")
exported = json.loads((RUN / "export.json").read_text())
report = json.loads((RUN / "report.json").read_text())
with (RUN / "report.csv").open(newline="") as source:
    rows = list(csv.DictReader(source))
starts = {row["attempt_id"]: row for row in exported["attempts"]}
assert len(starts) == len(exported["attempts"]) == 512
usage = defaultdict(list)
results = defaultdict(list)
decisions = defaultdict(list)
for event in exported["events"]:
    if event["kind"] == "usage":
        usage[event["attempt_id"]].append(event)
    elif event["kind"] == "result":
        results[event["attempt_id"]].append(event)
    elif event["kind"] == "decision":
        decisions[event["attempt_id"]].append(event)
assert set(usage) == set(results) == set(decisions) == set(starts)
snapshots = {row["snapshot_id"]: row for row in exported["snapshots"]}
assert len(snapshots) == 1024
report_rows = {row["attempt_id"]: row for row in report["attempts"]}
csv_rows = {row["attempt_id"]: row for row in rows}
assert len(report_rows) == len(csv_rows) == len(rows) == 512
assert set(starts) == set(report_rows) == set(csv_rows)
unknown = 0
new = 0
for attempt_id, start in starts.items():
    assert start["context_ref"] in snapshots
    assert len(results[attempt_id]) == len(decisions[attempt_id]) == 1
    assert decisions[attempt_id][0]["decision_ref"] in snapshots
    revisions = sorted(usage[attempt_id], key=lambda row: row["usage_revision"])
    assert [row["usage_revision"] for row in revisions] == list(range(1, len(revisions) + 1))
    effective = revisions[-1]
    projected = report_rows[attempt_id]
    csv_row = csv_rows[attempt_id]
    assert projected["usage_revision"] == effective["usage_revision"]
    assert int(csv_row["usage_revision"]) == effective["usage_revision"]
    assert projected["native_units"] == effective.get("native_units")
    csv_units = json.loads(csv_row["native_units"]) if csv_row["native_units"] else None
    assert csv_units == effective.get("native_units")
    assert projected["cost_status"] == csv_row["cost_status"] == effective["cost_state"]
    assert projected["amount_decimal"] is None and csv_row["amount_decimal"] == ""
    unknown += effective["cost_state"] == "unknown"
    if attempt_id.startswith("attempt.synthetic.volume."):
        new += 1
        assert start["operation_family"] == "speech_output"
        assert start["model_identity_state"] == "unknown"
        assert start["actor_id"] == "service.synthetic.volume"
        assert "initiating_user_id" not in start
        assert projected["account_resolution_status"] == "registered_at_start"
        assert projected["eligibility_evidence_status"] == "verified"
assert new == 501 and unknown == 512
assert report["attempt_count"] == report["unknown_cost_attempts"] == unknown
assert report["known_total_by_currency"] == {}
assert len(exported["eligibility_reads"]) == len(exported["eligibility_assessments"]) == 512
assert len(exported["events"]) == 2049
print(
    json.dumps(
        {
            "status": "PASS",
            "run_id": sys.argv[1],
            "raw_unique_attempts": len(starts),
            "new_v3_attempts": new,
            "effective_unknown_costs": unknown,
            "csv_rows": len(rows),
            "raw_events": len(exported["events"]),
        },
        sort_keys=True,
    )
)
