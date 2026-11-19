"""Offline product reduction for retained receiver evidence and audited resume."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/src"))
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from duranki_server.store import SQLiteStore  # noqa: E402
from duranki_server.successor_authority import SyntheticSuccessorAuthority  # noqa: E402
from duranki_server.successor_campaign import FiniteSuccessorCampaign  # noqa: E402
from duranki_server.successor_receiver_evidence import DurableReceiverReceipts  # noqa: E402
from duranki_server.successor_service import SuccessorService  # noqa: E402
from duranki_server.canonical import ContractError  # noqa: E402

VECTORS = json.loads((ROOT / "tests/fixtures/contracts/dev12-successor-01/vectors.json").read_text())


class UnknownAfterGuard:
    def execute(self, record, _authority, store, campaign):
        body = b"independently observed synthetic request bytes"
        store.successor_guard_commit(record["submission_id"], record["attempt_id"],
            {"attempt_id": record["attempt_id"], "plan_id": record["signed_plan"]["plan_id"],
             "work_digest": record["work_digest"], "body_sha256": sha256(body).hexdigest(),
             "body_bytes": len(body)}, record["created_at"], campaign)
        return {"state": "unknown"}


class RejectedBeforeFirstWriteThenUnknown:
    def __init__(self):
        self.calls = 0

    def execute(self, record, authority, store, campaign):
        self.calls += 1
        if self.calls == 2:
            raise ContractError("PLAN_INVALID_OR_STALE", 409)
        if self.calls != 1:
            return UnknownAfterGuard().execute(record, authority, store, campaign)
        sid, aid = record["submission_id"], record["attempt_id"]
        store.successor_guard_commit(sid, aid,
            {"attempt_id": aid, "plan_id": record["signed_plan"]["plan_id"],
             "work_digest": record["work_digest"], "body_sha256": "0" * 64,
             "body_bytes": 1}, record["created_at"], campaign)
        store.successor_append_evidence(sid, "sender_outcome", record["created_at"],
            {"error_type": "GuardRejected", "guard_committed": True,
             "first_bytes_accepted": False, "response_received": False})
        raise ContractError("FDC_REJECTED", 409)


class LateEvidenceTests(unittest.TestCase):
    def test_audited_resume_releases_only_proven_no_send(self):
        example = next(row for row in VECTORS["examples"] if row["id"] == "DIRECT_DOCUMENT")
        now = datetime.now(timezone.utc).replace(microsecond=0)
        fmt = lambda value: value.strftime("%Y-%m-%dT%H:%M:%SZ")
        request, context = deepcopy(example["request"]), deepcopy(example["trusted_context"])
        request["deadline"] = fmt(now + timedelta(minutes=30))
        context["authenticated_at"] = fmt(now - timedelta(minutes=1))
        context["expires_at"] = fmt(now + timedelta(hours=1))
        trusted = {**context["identity"], "task_id": request["work_selector"]["task_id"]}
        token = "test.no.send." + "x" * 32
        with TemporaryDirectory() as temporary:
            store = SQLiteStore(Path(temporary) / "ledger.sqlite")
            authority = SyntheticSuccessorAuthority(store, Ed25519PrivateKey.generate(),
                                                     "key.no.send", "v1")
            campaign = FiniteSuccessorCampaign(store, "campaign.no.send", "budget.no.send")
            campaign.start({}, [], max_attempts=4)
            authority.set_historical_access(context["identity"], read=True, write=True,
                resume=True, observed_at=fmt(now))
            permitted = lambda current, original: current["principal_id"] == original["work_key"]["principal_id"]
            executor = RejectedBeforeFirstWriteThenUnknown()
            service = SuccessorService(store, {token: context}, authority, executor, campaign,
                read_allowed=permitted, usage_write_allowed=permitted)
            try:
                code, first = service.submit(request, trusted, 5000, credential=token)
                self.assertEqual((code, first["state"]), (409, "failed"))
                sid, aid = first["handle"]["submission_id"], first["attempt_id"]
                self.assertEqual(store.successor_get(sid)["exposure_state"], "outstanding")
                second_request = deepcopy(request)
                second_request["work_selector"]["execution_generation"] = "gen.2"
                code, second = service.submit(second_request, trusted, 5000, credential=token)
                self.assertEqual((code, second["state"]), (409, "failed"))
                third_request = deepcopy(request)
                third_request["work_selector"]["execution_generation"] = "gen.3"
                code, third = service.submit(third_request, trusted, 5000, credential=token)
                self.assertEqual((code, third["state"]), (202, "outcome_unknown"))
                before = campaign.inspect()
                refused = service.resume_campaign(sid, trusted, "sender definitely rejected")
                self.assertEqual(refused["decision"], "refused")
                self.assertEqual(set(refused["definite_no_send_reconciled"]),
                                 {aid, second["attempt_id"]})
                self.assertEqual(store.successor_get(sid)["exposure_state"], "not_sent")
                self.assertEqual(store.successor_get(second["handle"]["submission_id"])[
                    "exposure_state"], "not_sent")
                self.assertIn("unresolved_unknown_outcome:" + third["attempt_id"],
                              refused["blockers"])
                self.assertNotIn("unresolved_exposure:" + aid, refused["blockers"])
                again = service.resume_campaign(sid, trusted, "still awaiting receiver")
                self.assertEqual(again["definite_no_send_reconciled"], [])
                self.assertEqual(store.db.execute("SELECT COUNT(*) FROM dev12_evidence_events "
                    "WHERE submission_id=? AND event_kind='definite_no_send_reconciled'",
                    (sid,)).fetchone()[0], 1)
                after = campaign.inspect()
                for name in ("attempt_count", "possible_send_count",
                             "cumulative_reserved_decimal", "expires_at"):
                    self.assertEqual(after[name], before[name])
            finally:
                service.pool.shutdown(wait=True)
                store.close()

    def test_same_attempt_receiver_collection_and_audited_resume(self):
        example = next(row for row in VECTORS["examples"] if row["id"] == "DIRECT_DOCUMENT")
        now = datetime.now(timezone.utc).replace(microsecond=0)
        fmt = lambda value: value.strftime("%Y-%m-%dT%H:%M:%SZ")
        request, context = deepcopy(example["request"]), deepcopy(example["trusted_context"])
        request["deadline"] = fmt(now + timedelta(minutes=30))
        context["authenticated_at"] = fmt(now - timedelta(minutes=1))
        context["expires_at"] = fmt(now + timedelta(hours=1))
        trusted = {**context["identity"], "task_id": request["work_selector"]["task_id"]}
        token = "test.late.receiver." + "x" * 32
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipts = root / "receiver-receipts.jsonl"
            store = SQLiteStore(root / "ledger.sqlite")
            key = Ed25519PrivateKey.generate()
            authority = SyntheticSuccessorAuthority(store, key, "key.late", "v1")
            campaign = FiniteSuccessorCampaign(store, "campaign.late", "budget.late")
            campaign.start({}, [], max_attempts=3)
            authority.set_historical_access(context["identity"], read=True, write=True,
                resume=True, observed_at=fmt(now))
            permitted = lambda current, record: current["principal_id"] == record["work_key"]["principal_id"]
            service = SuccessorService(store, {token: context}, authority, UnknownAfterGuard(), campaign,
                read_allowed=permitted, usage_write_allowed=permitted,
                receiver_receipts=DurableReceiverReceipts(receipts))
            try:
                code, reply = service.submit(request, trusted, 5000, credential=token)
                self.assertEqual((code, reply["state"]), (202, "outcome_unknown"))
                sid, aid = reply["handle"]["submission_id"], reply["attempt_id"]
                before = campaign.inspect()
                self.assertTrue(before["paused"])
                self.assertEqual((before["attempt_count"], before["possible_send_count"]), (1, 1))
                refused = service.resume_campaign(sid, trusted, "await independent receipt")
                self.assertEqual(refused["decision"], "refused")
                self.assertIn("unresolved_exposure:" + aid, refused["blockers"])
                authority.set_historical_access(context["identity"], read=True, write=False,
                    resume=True, observed_at=fmt(now))
                body = b"independently observed synthetic request bytes"
                retained = {"kind": "native_usage_receipt", "attempt_id": aid,
                    "path": service.store.successor_get(sid)["signed_plan"]["execution_descriptor"]["route"],
                    "body_sha256": sha256(body).hexdigest(), "body_bytes": len(body),
                    "received_at_ns": 123456789,
                    "usage_component": {"component": "document_units", "presence": "known",
                        "evidence": "reported", "quantity": len(request["input"]["items"]),
                        "source_ref": "receiver.synthetic.dev12"}}
                wrong = {**retained, "body_sha256": "0" * 64}
                receipts.write_text(json.dumps(wrong, sort_keys=True) + "\n")
                authority.set_historical_access(context["identity"], read=True, write=True,
                    resume=True, observed_at=fmt(now))
                with self.assertRaises(ValueError):
                    service.collect_receiver_receipt(sid, trusted)
                authority.set_historical_access(context["identity"], read=True, write=False,
                    resume=True, observed_at=fmt(now))
                receipts.write_text(json.dumps(retained, sort_keys=True) + "\n")
                with self.assertRaises(PermissionError):
                    service.collect_receiver_receipt(sid, trusted)
                self.assertIsNone(store.successor_latest_usage(aid))
                authority.set_historical_access(context["identity"], read=True, write=True,
                    resume=True, observed_at=fmt(now))
                self.assertEqual(service.collect_receiver_receipt(sid, trusted), "accepted")
                self.assertEqual(service.collect_receiver_receipt(sid, trusted), "duplicate")
                status = service.status(sid, trusted)
                self.assertEqual(status["submission_state"], "unknown")
                self.assertEqual(status["attempts"][0]["usage_revision"]["cost_status"], "calculated")
                self.assertEqual(store.successor_get(sid)["exposure_state"], "settled")
                resumed = service.resume_campaign(sid, trusted, "receiver usage verified")
                self.assertEqual(resumed["decision"], "resumed")
                self.assertEqual(len(resumed["resolved_evidence"]), 1)
                after = campaign.inspect()
                self.assertFalse(after["paused"])
                for name in ("attempt_count", "possible_send_count", "cumulative_reserved_decimal",
                             "expires_at"):
                    self.assertEqual(after[name], before[name])
                with authority.gate:
                    store.database.transaction(lambda: campaign.pause_in_transaction(store.database, "manual"))
                denied = service.resume_campaign(sid, trusted, "financial receipt alone")
                self.assertEqual(denied["decision"], "refused")
                self.assertIn("unresolved_manual", denied["blockers"])
                self.assertEqual(store.db.execute(
                    "SELECT COUNT(*) FROM dev12_campaign_audit").fetchone()[0], 3)
            finally:
                service.pool.shutdown(wait=True)
                store.close()
            reopened = SQLiteStore(root / "ledger.sqlite")
            restarted_authority = SyntheticSuccessorAuthority(reopened, key, "key.late", "v1")
            restarted_campaign = FiniteSuccessorCampaign(reopened, "campaign.late", "budget.late")
            self.assertTrue(restarted_authority.historical_allowed(trusted,
                reopened.successor_get(sid), "write"))
            self.assertEqual(restarted_campaign.inspect()["pause_reasons"], ["manual"])
            self.assertEqual(reopened.successor_latest_usage(aid)["revision"], 1)
            reopened.close()


if __name__ == "__main__":
    unittest.main()
