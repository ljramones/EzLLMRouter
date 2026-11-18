"""Real SQLite projection tests: no content export, revision replacement and launcher custody."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, os.environ.get("DURANKI_OPERATOR_SOURCE_ROOT", str(ROOT / "server/src")))
from duranki_server.operator_projection import OperatorProjection
from duranki_server.store import SQLiteStore


def record(sid, aid, step, *, no_store=False, state="admitted"):
    return {"submission_id": sid, "attempt_id": aid, "principal_id": "svc.demo", "task_id": "task.demo",
        "work_key": {"principal_id": "svc.demo", "task_id": "task.demo", "step_id": step,
                     "step_revision": 1, "execution_generation": "gen.1"},
        "work_digest": "sha256:" + "1" * 64, "submission_state": state,
        "dispatch_state": "prepared", "candidate_access": "not_retained" if no_store else "present",
        "content_store_allowed": not no_store, "updated_at": "2026-10-21T00:00:00Z",
        "status_revision": 1, "candidate": {"output_blocks": [{"text": "DO_NOT_EXPORT"}]},
        "terminal_failure": {"code": "REMOTE_EXECUTION_FAILED", "message": "DO_NOT_EXPORT"}}


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SQLiteStore(Path(self.tmp.name) / "state.sqlite")
        self.store.create(record("submission.a", "attempt.a", "step.a"))
        self.store.create(record("submission.b", "attempt.b", "step.b", no_store=True))
        self.store.create({**record("submission.hidden", "attempt.hidden", "step.hidden"),
                           "principal_id": "other.principal"})
        intent = {"attempt_id": "attempt.a", "plan_id": "plan.a", "work_digest": "sha256:" + "1" * 64,
                  "committed_at": "2026-10-21T00:00:00Z",
                  "destination": {"configuration_ref": "cfg.demo", "service": "synthetic",
                                  "endpoint": "receiver", "model": "model.demo", "model_version": "v1",
                                  "processing_region": "local"}}
        self.store.intent("submission.a", "attempt.a", intent)
        self.store.guard_commit("submission.a", "attempt.a", {"attempt_id": "attempt.a",
            "plan_id": "plan.a", "work_digest": "sha256:" + "1" * 64,
            "body_sha256": "a" * 64, "body_bytes": 123, "committed_at": "2026-10-21T00:00:01Z"})
        for revision, count in ((1, 5), (2, 8)):
            usage = {"revision": revision, "normalized_usage": {
                "input_uncached": {"state": "known", "count": count},
                "output_text": {"state": "unknown"}}, "cost": {"status": "unknown"}}
            self.store.db.execute("INSERT INTO usage_revisions VALUES (?,?,?,?)",
                                  ("attempt.a", revision, "submission.a", json.dumps(usage)))
        self.projection = OperatorProjection(self.store, "svc.demo")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_allowlisted_activity_and_detail(self):
        page = self.projection.activity(page=1, limit=1)
        self.assertEqual(page["total"], 2)
        self.assertEqual(len(page["items"]), 1)
        detail = self.projection.detail("submission.a")
        self.assertEqual(detail["usage"]["counts"]["input_uncached"], 8)
        self.assertIsNone(detail["usage"]["counts"]["output_text"])
        self.assertTrue(detail["dispatch_receipt"]["present"])
        self.assertEqual(detail["selected_configuration"]["model"], "model.demo")
        self.assertNotIn("DO_NOT_EXPORT", json.dumps(detail))
        self.assertNotIn("DO_NOT_EXPORT", json.dumps(self.projection.activity()))
        self.assertIsNone(self.projection.detail("submission.hidden"))
        self.assertEqual(self.projection.detail("submission.b")["candidate_access"], "not_retained")

    def test_latest_usage_is_replacement_not_sum(self):
        usage = self.projection.usage()
        self.assertEqual((usage["attempts"], usage["dispatched"], usage["usage_available"]), (2, 1, 1))
        self.assertEqual((usage["intents_persisted"], usage["final_requests_committed"],
                          usage["transmission_started_observed"], usage["write_observation_unknown"]),
                         (1, 1, 0, 2))
        by_step = {x["step_id"]: x for x in usage["by_step"]}
        self.assertEqual(by_step["step.a"]["input_tokens_known"], 8)
        self.assertEqual(by_step["step.a"]["output_unknown"], 1)
        self.assertEqual(usage["cost"]["unknown_attempts"], usage["attempts"])
        self.assertEqual(usage["cost"]["known_subtotals"], {})

    def test_lower_pool_revocation_keeps_receipt_but_has_no_first_write(self):
        intent = {"attempt_id": "attempt.b", "plan_id": "plan.b", "work_digest": "sha256:" + "1" * 64,
                  "destination": {"configuration_ref": "cfg.demo"}}
        self.store.intent("submission.b", "attempt.b", intent)
        self.store.guard_commit("submission.b", "attempt.b", {"attempt_id": "attempt.b",
            "plan_id": "plan.b", "work_digest": "sha256:" + "1" * 64})
        self.store.update("submission.b", {"submission_state": "failed_before_transmit"})
        events = Path(self.tmp.name) / "send-events.jsonl"
        events.write_text(json.dumps({"attempt_id": "attempt.a",
            "first_bytes_accepted_by_local_socket": True, "first_acceptance_events": 1}) + "\n" +
            json.dumps({"attempt_id": "attempt.b",
            "first_bytes_accepted_by_local_socket": False, "first_acceptance_events": 0,
            "lower_error": "FDC_REJECTED"}) + "\n")
        projection = OperatorProjection(self.store, "svc.demo", events)
        usage = projection.usage()
        self.assertEqual((usage["attempts"], usage["intents_persisted"],
                          usage["final_requests_committed"], usage["dispatched"]), (2, 2, 2, 2))
        self.assertEqual((usage["transmission_started_observed"], usage["no_first_write_observed"],
                          usage["write_observation_unknown"]), (1, 1, 0))
        revoked = next(row for row in usage["by_step"] if row["step_id"] == "step.b")
        self.assertEqual((revoked["final_requests_committed"], revoked["transmission_started_observed"],
                          revoked["no_first_write_observed"]), (1, 0, 1))
        self.assertEqual(revoked["configuration_refs"], ["cfg.demo"])
        self.assertEqual(projection.activity()["items"][0]["configuration_ref"], "cfg.demo")
        events.write_text(events.read_text().splitlines()[0] + "\n")
        self.assertEqual(projection.usage()["write_observation_unknown"], 1)

    def test_explicit_principal_scope_keeps_ordinary_activity_private(self):
        self.assertEqual(self.projection.activity(principal_id="other.principal")["total"], 1)
        self.assertIsNone(self.projection.detail("submission.a", "other.principal"))
        self.assertEqual(self.projection.detail("submission.hidden", "other.principal")["submission_id"],
                         "submission.hidden")
        self.assertEqual(self.projection.overview_counts("other.principal")["submissions"], 1)
        self.assertEqual(self.projection.usage("other.principal")["attempts"], 1)
        self.assertEqual(self.projection.activity(principal_id="*")["total"], 3)

    def test_launcher_idempotency_and_restart_uncertainty(self):
        self.assertTrue(self.projection.begin_launch("operation.a", "text"))
        self.assertFalse(self.projection.begin_launch("operation.a", "text"))
        with self.assertRaisesRegex(ValueError, "another synthetic launcher"):
            self.projection.begin_launch("operation.b", "tool")
        with self.assertRaises(ValueError):
            self.projection.begin_launch("operation.a", "tool")
        self.projection.record_launch_submission("operation.a", "submission.a")
        self.projection.record_launch_submission("operation.a", "submission.a")
        self.assertEqual(self.projection.launch("operation.a")["submission_ids"], ["submission.a"])
        restarted = OperatorProjection(self.store, "svc.demo")
        self.assertEqual(restarted.launch("operation.a")["state"], "outcome_unknown")
        self.assertFalse(restarted.begin_launch("operation.a", "text"))

    def test_provider_validation_is_one_use_across_restart(self):
        args = ("op.provider.1", "conn.provider.1", 4, "cfg.provider.1", 3, 16)
        self.assertTrue(self.projection.begin_provider_validation(*args))
        self.assertFalse(self.projection.begin_provider_validation(*args))
        with self.assertRaises(ValueError):
            self.projection.begin_provider_validation(*args[:-1], 17)
        with self.assertRaises(ValueError):
            self.projection.begin_provider_validation("op.provider.2", "conn.provider.1", 4,
                                                      "cfg.provider.1", 3, 16)
        self.projection.record_provider_validation_submission("op.provider.1", "submission.a")
        restarted = OperatorProjection(self.store, "svc.demo")
        record = restarted.provider_validation("op.provider.1")
        self.assertEqual(record["state"], "outcome_unknown")
        self.assertEqual(record["submission_id"], "submission.a")
        self.assertFalse(restarted.begin_provider_validation(*args))

    def test_invalid_filters_fail_closed(self):
        with self.assertRaises(ValueError):
            self.projection.activity(page=0)
        with self.assertRaises(ValueError):
            self.projection.activity(state="not_a_state")
        with self.assertRaises(ValueError):
            self.projection.detail("../store.sqlite")

    def test_sqlite_reopen_retains_metadata_without_relaunch(self):
        self.projection.begin_launch("operation.restart", "text")
        path = Path(self.tmp.name) / "state.sqlite"
        self.store.close()
        self.store = SQLiteStore(path)
        restarted = OperatorProjection(self.store, "svc.demo")
        self.assertEqual(restarted.detail("submission.a")["usage"]["revision"], 2)
        self.assertEqual(restarted.detail("submission.b")["candidate_access"], "not_retained")
        self.assertEqual(restarted.launch("operation.restart")["state"], "outcome_unknown")
        self.assertFalse(restarted.begin_launch("operation.restart", "text"))


if __name__ == "__main__":
    unittest.main()
