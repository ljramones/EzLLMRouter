"""Independent scoped synthetic reporting, revision cutoffs and content expiry."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/src"))
from duranki_server.store import SQLiteStore  # noqa: E402
from duranki_server.successor_contract import native_usage_row, price_for, work_projection, work_digest  # noqa: E402
from duranki_server.successor_reporting import usage_report  # noqa: E402

VECTORS = json.loads((ROOT / "tests/fixtures/contracts/dev12-successor-01/vectors.json").read_text())


class SyntheticReportingTests(unittest.TestCase):
    def test_unique_attempt_cutoff_scope_and_expired_content(self):
        with TemporaryDirectory() as temporary:
            store = SQLiteStore(Path(temporary) / "store.sqlite")
            cases = [next(row for row in VECTORS["examples"] if row["id"] == name)
                     for name in ("DIRECT_DOCUMENT", "DELEGATED_RERANK")]
            records = []
            for ordinal, case in enumerate(cases, 1):
                request = deepcopy(case["request"])
                work = work_projection(request, case["trusted_context"])
                price = price_for(request)
                record = {"contract_version": "0.3", "submission_id": f"submission.{ordinal}",
                          "attempt_id": f"attempt.{ordinal}", "work_key": work["work_key"],
                          "work_digest": work_digest(work), "request": request,
                          "trusted_identity": case["trusted_context"]["identity"],
                          "reservation": {"price_ref": price["price_ref"], "usage_ref": price["usage_ref"],
                                          "max_exposure_decimal": "0.010000013"},
                          "signed_plan": {"destination_ref": "destination.synthetic.v1"},
                          "created_at": f"2030-01-01T00:00:0{ordinal}Z",
                          "updated_at": f"2030-01-01T00:00:0{ordinal}Z",
                          "submission_state": "completed", "dispatch_state": "sent",
                          "delivery_state": "valid", "candidate_access": "present",
                          "result_available_at": "2030-01-01T00:00:10Z", "result": {"sample": True},
                          "exposure_state": "outstanding", "settlement_state": "pending",
                          "status_revision": 1}
                store.successor_create(record)
                records.append((record, price))
            first, price = records[0]
            absent = {"component": price["component"], "presence": "absent"}
            unknown = native_usage_row(first["request"], first["attempt_id"], 1, absent,
                                       first["reservation"]["max_exposure_decimal"])
            store.successor_append_usage(first["submission_id"], unknown,
                                         "2030-01-01T00:00:20Z", write_allowed=True)
            observed = {"component": price["component"], "presence": "known", "quantity": 3,
                        "evidence": "reported", "source_ref": "receiver.synthetic"}
            corrected = native_usage_row(first["request"], first["attempt_id"], 2, observed,
                                         first["reservation"]["max_exposure_decimal"], 1)
            store.successor_append_usage(first["submission_id"], corrected,
                                         "2030-01-01T00:00:40Z", write_allowed=True)
            second, second_price = records[1]
            count = len(second["request"]["input"]["candidates"])
            component = {"component": second_price["component"], "presence": "known",
                         "quantity": count, "evidence": "reported", "source_ref": "receiver.synthetic"}
            usage = native_usage_row(second["request"], second["attempt_id"], 1, component,
                                     second["reservation"]["max_exposure_decimal"])
            store.successor_append_usage(second["submission_id"], usage,
                                         "2030-01-01T00:00:30Z", write_allowed=True)
            admin = {"role": "registry_admin", "principal_id": "owner.local"}
            early = usage_report(store, admin, {"cutoff": "2030-01-01T00:00:35Z"})
            self.assertEqual(early["total"]["attempts"], 2)
            self.assertEqual(early["total"]["unknown_cost_attempts"], 1)
            late = usage_report(store, admin)
            self.assertEqual(late["total"]["attempts"], 2)
            self.assertEqual(late["total"]["unknown_cost_attempts"], 0)
            self.assertEqual(late["total"]["known_usd"], "0.001500002")
            self.assertEqual(len({item["attempt_id"] for item in late["attempts"]}), 2)
            selected = usage_report(store, admin,
                {"task_id": "task.demo", "environment": "standalone-synthetic"})
            self.assertEqual(selected["total"], late["total"])
            self.assertEqual(usage_report(store, admin, {"task_id": "task.other"})["total"]["attempts"], 0)
            self.assertEqual(usage_report(store, admin,
                {"environment": "operational"})["total"]["attempts"], 0)
            self.assertEqual(selected["groupings"]["environment"][0]["id"], "standalone-synthetic")
            root = next(run for run in late["workflows"] if run["run_id"] == "run.root")
            self.assertEqual(root["direct"]["attempts"], 0)
            self.assertEqual(root["total_including_delegated"]["known_usd"], "0.000900002")
            own = usage_report(store, {"role": "ordinary", "principal_id": "svc.vega"})
            self.assertEqual(own["total"]["attempts"], 1)
            self.assertEqual(usage_report(store, {"role": "ordinary", "principal_id": "stranger"})["total"]["attempts"], 0)
            self.assertEqual(store.successor_expire_results("2030-01-08T00:00:09Z"), [])
            self.assertEqual(len(store.successor_expire_results("2030-01-08T00:00:10Z")), 2)
            expired = store.successor_get(first["submission_id"])
            self.assertEqual(expired["candidate_access"], "expired")
            self.assertNotIn("result", expired)
            self.assertEqual(store.successor_latest_usage(first["attempt_id"])["revision"], 2)
            self.assertEqual(usage_report(store, admin)["total"]["known_usd"], "0.001500002")
            store.close()


if __name__ == "__main__":
    unittest.main()
