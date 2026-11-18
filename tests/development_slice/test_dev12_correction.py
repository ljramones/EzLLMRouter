"""Focused correction checks for shared identity, recovery and authority scope."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from itertools import product
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
from threading import Barrier, Event, Thread
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/src"))
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from duranki_server.canonical import ContractError  # noqa: E402
from duranki_server.store import SQLiteStore  # noqa: E402
from duranki_server.successor_authority import SyntheticSuccessorAuthority  # noqa: E402
from duranki_server.successor_campaign import FiniteSuccessorCampaign  # noqa: E402
from duranki_server.successor_service import SuccessorService  # noqa: E402
from duranki_server.successor_plan import execution_eligible, mint_plan  # noqa: E402
from duranki_server.successor_contract import native_usage_row  # noqa: E402

VECTORS = json.loads((ROOT / "docs/contracts/dev12-successor-01/vectors.json").read_text())


class ObservedExecutor:
    def execute(self, record, _authority, store, campaign):
        receipt = {"attempt_id": record["attempt_id"],
                   "plan_id": record["signed_plan"]["plan_id"],
                   "work_digest": record["work_digest"]}
        store.successor_guard_commit(record["submission_id"], record["attempt_id"],
                                     receipt, record["created_at"], campaign)
        result = deepcopy(next(row["value"] for row in VECTORS["result_examples"]
                               if row["id"] == "EMBEDDING_RESULT"))
        result["attempt_id"] = record["attempt_id"]
        return {"state": "observed", "result": result,
                "usage_component": {"component": "document_units", "presence": "known",
                                    "quantity": len(record["request"]["input"]["items"]),
                                    "evidence": "reported", "source_ref": "receiver.test"}}


class FailedDeliveryExecutor:
    def execute(self, record, _authority, store, campaign):
        store.successor_guard_commit(record["submission_id"], record["attempt_id"],
            {"attempt_id": record["attempt_id"], "plan_id": record["signed_plan"]["plan_id"],
             "work_digest": record["work_digest"]}, record["created_at"], campaign)
        component = ({"component": "document_units", "presence": "known", "quantity": 3,
                      "evidence": "reported", "source_ref": "receiver.test"}
                     if record["work_key"]["step_id"] == "step.failure.known" else
                     {"component": "document_units", "presence": "absent"})
        return {"state": "observed", "result": None, "http_status": 502,
                "usage_component": component}


class ComponentExecutor:
    def __init__(self, component, *, failed=False):
        self.component = component
        self.failed = failed

    def execute(self, record, _authority, store, campaign):
        store.successor_guard_commit(record["submission_id"], record["attempt_id"],
            {"attempt_id": record["attempt_id"], "plan_id": record["signed_plan"]["plan_id"],
             "work_digest": record["work_digest"]}, record["created_at"], campaign)
        result = deepcopy(next(row["value"] for row in VECTORS["result_examples"]
                               if row["id"] == "EMBEDDING_RESULT"))
        result["attempt_id"] = record["attempt_id"]
        outcome = {"state": "observed", "result": None if self.failed else result,
                   "http_status": 502 if self.failed else 200}
        if self.component is not ...:
            outcome["usage_component"] = self.component
        return outcome


class CorrectionTests(unittest.TestCase):
    def test_one_transactional_work_key_owner_in_both_orders_and_race(self):
        key = {"principal_id": "user.demo", "task_id": "task.demo", "step_id": "step.same",
               "step_revision": 1, "execution_generation": "gen.1"}
        legacy = {"submission_id": "submission.legacy", "attempt_id": "attempt.legacy",
                  "principal_id": "user.demo", "task_id": "task.demo",
                  "work_key": key, "work_digest": "sha256:legacy"}
        modern = {"submission_id": "submission.modern", "attempt_id": "attempt.modern",
                  "work_key": key, "work_digest": "sha256:modern"}
        for first in ("0.2", "0.3"):
            with self.subTest(first=first), TemporaryDirectory() as temporary:
                store = SQLiteStore(Path(temporary) / "ledger.sqlite")
                if first == "0.2":
                    store.create(legacy)
                    with self.assertRaises(sqlite3.IntegrityError):
                        store.successor_create(modern)
                else:
                    store.successor_create(modern)
                    with self.assertRaises(sqlite3.IntegrityError):
                        store.create(legacy)
                self.assertEqual(store.work_owner(key)["contract_version"], first)
                self.assertEqual(sum(store.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                                     for table in ("submissions", "dev12_submissions")), 1)
                store.close()
        with TemporaryDirectory() as temporary:
            store = SQLiteStore(Path(temporary) / "race.sqlite")
            barrier = Barrier(2)
            outcomes = []
            def enter(version):
                barrier.wait()
                try:
                    (store.create(legacy) if version == "0.2" else store.successor_create(modern))
                    outcomes.append("accepted")
                except sqlite3.IntegrityError:
                    outcomes.append("conflict")
            threads = [Thread(target=enter, args=(version,)) for version in ("0.2", "0.3")]
            for thread in threads: thread.start()
            for thread in threads: thread.join(5)
            self.assertEqual(sorted(outcomes), ["accepted", "conflict"])
            self.assertIsNotNone(store.work_owner(key))
            store.close()

    def test_expired_duplicate_is_query_first_and_never_reexecutes(self):
        example = next(row for row in VECTORS["examples"] if row["id"] == "DIRECT_DOCUMENT")
        clock = [datetime(2030, 1, 1, 0, 0, 10, tzinfo=timezone.utc)]
        fmt = lambda instant: instant.strftime("%Y-%m-%dT%H:%M:%SZ")
        context = deepcopy(example["trusted_context"])
        context["authenticated_at"] = fmt(clock[0] - timedelta(seconds=10))
        context["expires_at"] = fmt(clock[0] + timedelta(days=10))
        request = deepcopy(example["request"])
        request["deadline"] = fmt(clock[0] + timedelta(minutes=30))
        trusted = {**context["identity"], "task_id": request["work_selector"]["task_id"]}
        token = "test.dev12.recovery." + "x" * 32
        with TemporaryDirectory() as temporary:
            store = SQLiteStore(Path(temporary) / "recovery.sqlite")
            authority = SyntheticSuccessorAuthority(store, Ed25519PrivateKey.generate(), "key.test", "v1")
            campaign = FiniteSuccessorCampaign(store, "campaign.recovery", "budget.recovery",
                                               wall_clock=lambda: clock[0])
            campaign.start({}, [], max_attempts=2)
            authority.set_historical_access(context["identity"], read=True, write=True,
                resume=True, observed_at=fmt(clock[0]))
            permitted = lambda current, record: current["principal_id"] == record["work_key"]["principal_id"]
            service = SuccessorService(store, {token: context}, authority, ObservedExecutor(), campaign,
                clock=lambda: fmt(clock[0]), read_allowed=permitted, usage_write_allowed=permitted)
            try:
                status_code, reply = service.submit(request, trusted, 5000, credential=token)
                self.assertEqual(status_code, 200)
                sid = reply["handle"]["submission_id"]
                original = store.successor_get(sid)
                clock[0] += timedelta(days=7) - timedelta(seconds=1)
                context["authenticated_at"] = fmt(clock[0] - timedelta(minutes=1))
                self.assertEqual(service.submit(request, trusted, 0, credential=token)[0], 200)
                clock[0] += timedelta(seconds=1)
                with self.assertRaises(ContractError) as error:
                    service.submit(request, trusted, 0, credential=token)
                self.assertEqual((error.exception.code, error.exception.status,
                                  error.exception.retry_guidance),
                                 ("POLICY_DENIED", 403, "query_first"))
                for status in (service.status(sid, trusted),
                               service.status_by_work(original["work_key"], trusted)):
                    self.assertEqual(status["submission_state"], "completed")
                    self.assertEqual(status["candidate_access"], "expired")
                    self.assertNotIn("result", status["attempts"][0])
                self.assertEqual(campaign.inspect()["attempt_count"], 1)
                self.assertEqual(campaign.inspect()["possible_send_count"], 1)
                self.assertEqual(store.successor_get(sid)["attempt_id"], original["attempt_id"])
            finally:
                service.pool.shutdown(wait=True)
                store.close()

    def test_financial_scope_mismatch_has_no_admission(self):
        with TemporaryDirectory() as temporary:
            store = SQLiteStore(Path(temporary) / "scope.sqlite")
            proper = FiniteSuccessorCampaign(store, "campaign.scope", "budget.scope",
                                             financial_owner_id="team.scope")
            proper.start({}, [], max_attempts=2)
            wrong = FiniteSuccessorCampaign(store, "campaign.scope", "budget.other",
                                            financial_owner_id="team.scope")
            with self.assertRaises(PermissionError):
                wrong.inspect()
            record = {"submission_id": "submission.scope", "attempt_id": "attempt.scope",
                "work_key": {"principal_id": "user.demo", "task_id": "task.demo", "step_id": "step.scope",
                             "step_revision": 1, "execution_generation": "gen.1"},
                "work_digest": "sha256:scope",
                "reservation": {"budget_account_id": "budget.other", "financial_owner_id": "team.scope",
                                "currency": "USD", "max_exposure_decimal": "0.000100000"}}
            with self.assertRaises(PermissionError):
                store.successor_create(record, reserve=proper.reserve)
            self.assertEqual(proper.inspect()["attempt_count"], 0)
            self.assertIsNone(store.work_owner(record["work_key"]))
            store.close()

    def test_bound_key_rotation_activation_and_definite_rollback(self):
        example = next(row for row in VECTORS["examples"] if row["id"] == "DELEGATED_RERANK")
        with TemporaryDirectory() as temporary:
            store = SQLiteStore(Path(temporary) / "authority.sqlite")
            original_key = Ed25519PrivateKey.generate()
            authority = SyntheticSuccessorAuthority(store, original_key, "key.test", "v1")
            revisions, activation, key_id, key_version, signer = authority.minting_snapshot()
            plan = mint_plan(example["request"], example["work_digest"],
                example["admission_snapshot_digest"], "submission.test", "attempt.test",
                "team.demo", "budget.test", revisions, activation, key_id, key_version, signer)
            record = {"signed_plan": plan, "submission_id": "submission.test",
                "attempt_id": "attempt.test", "work_digest": example["work_digest"],
                "admission_snapshot_digest": example["admission_snapshot_digest"],
                "trusted_identity": example["trusted_context"]["identity"],
                "reservation": plan["reservation"]}
            valid = lambda: execution_eligible(plan, example["request"],
                example["canonical_work"], example["admission_snapshot"],
                authority.current_context(record, "2030-01-01T00:00:10Z"))
            self.assertTrue(valid())
            authority.rotate_minting_key(Ed25519PrivateKey.generate(), "key.test", "v2",
                                          "2030-01-01T00:00:11Z")
            self.assertTrue(valid())
            authority.revoke_key_version("key.test", "v2", "2030-01-01T00:00:12Z")
            self.assertTrue(valid())
            old_epoch = authority.epoch
            with self.assertRaises(TypeError):
                authority.update(lambda state: state["revisions"].update(policy=2),
                                 {"unserializable": object()})
            self.assertEqual(authority.epoch, old_epoch)
            self.assertFalse(authority.revoked)
            self.assertTrue(valid())
            authority.update(lambda state: state.update(activation={"state": "tagged_fixture",
                "epoch": "epoch.changed"}), {"kind": "activation", "at": "2030-01-01T00:00:13Z"})
            self.assertFalse(valid())
            authority.update(lambda state: state.update(activation=activation),
                             {"kind": "activation_restore", "at": "2030-01-01T00:00:14Z"})
            self.assertTrue(valid())
            authority.revoke_key_version("key.test", "v1", "2030-01-01T00:00:15Z")
            self.assertFalse(valid())
            store.close()

    def test_failed_delivery_retains_known_usage_and_unknown_pauses(self):
        example = next(row for row in VECTORS["examples"] if row["id"] == "DIRECT_DOCUMENT")
        now = datetime.now(timezone.utc).replace(microsecond=0)
        fmt = lambda instant: instant.strftime("%Y-%m-%dT%H:%M:%SZ")
        context = deepcopy(example["trusted_context"])
        context["authenticated_at"] = fmt(now - timedelta(minutes=1))
        context["expires_at"] = fmt(now + timedelta(hours=1))
        trusted = {**context["identity"], "task_id": "task.demo"}
        token = "test.dev12.failure." + "x" * 32
        with TemporaryDirectory() as temporary:
            store = SQLiteStore(Path(temporary) / "failure.sqlite")
            authority = SyntheticSuccessorAuthority(store, Ed25519PrivateKey.generate(), "key.test", "v1")
            campaign = FiniteSuccessorCampaign(store, "campaign.failure", "budget.failure")
            campaign.start({}, [], max_attempts=3)
            authority.set_historical_access(context["identity"], read=True, write=True,
                resume=True, observed_at=fmt(now))
            permitted = lambda current, record: current["principal_id"] == record["work_key"]["principal_id"]
            service = SuccessorService(store, {token: context}, authority, FailedDeliveryExecutor(), campaign,
                                       read_allowed=permitted, usage_write_allowed=permitted)
            try:
                for step, cost, paused in (("step.failure.known", "calculated", False),
                                           ("step.failure.absent", "unknown", True)):
                    request = deepcopy(example["request"])
                    request["deadline"] = fmt(now + timedelta(minutes=30))
                    request["work_selector"]["step_id"] = step
                    _code, reply = service.submit(request, trusted, 5000, credential=token)
                    status = service.status(reply["handle"]["submission_id"], trusted)
                    self.assertEqual(status["submission_state"], "failed")
                    self.assertEqual(status["attempts"][0]["usage_revision"]["cost_status"], cost)
                    self.assertEqual(campaign.inspect()["paused"], paused)
                self.assertEqual(campaign.inspect()["attempt_count"], 2)
            finally:
                service.pool.shutdown(wait=True)
                store.close()

    def test_non_object_native_evidence_preserves_delivery_and_unknown_cost(self):
        example = next(row for row in VECTORS["examples"] if row["id"] == "DIRECT_DOCUMENT")
        now = datetime.now(timezone.utc).replace(microsecond=0)
        fmt = lambda value: value.strftime("%Y-%m-%dT%H:%M:%SZ")
        cases = ((..., "absent"), (None, "null"), ([], "invalid"), (1, "invalid"),
                 ("bad", "invalid"), (True, "invalid"),
                 ({"component": "document_units", "presence": "known",
                   "quantity": chr(0xD800)}, "invalid"),
                 ({"component": "document_units", "presence": "known", "quantity": 1,
                   "evidence": "derived", "source_ref": "receiver.test"}, "known"))
        for (component, expected_presence), failed in product(cases, (False, True)):
            with self.subTest(component=repr(component), failed=failed), TemporaryDirectory() as temporary:
                store = SQLiteStore(Path(temporary) / "native.sqlite")
                authority = SyntheticSuccessorAuthority(store, Ed25519PrivateKey.generate(), "key.test", "v1")
                campaign = FiniteSuccessorCampaign(store, "campaign.native", "budget.native")
                campaign.start({}, [], max_attempts=1)
                request, context = deepcopy(example["request"]), deepcopy(example["trusted_context"])
                request["deadline"] = fmt(now + timedelta(minutes=30))
                context["authenticated_at"] = fmt(now - timedelta(minutes=1))
                context["expires_at"] = fmt(now + timedelta(hours=1))
                authority.set_historical_access(context["identity"], read=True, write=True,
                    resume=True, observed_at=fmt(now))
                trusted = {**context["identity"], "task_id": request["work_selector"]["task_id"]}
                token = "test.native." + "x" * 32
                permitted = lambda current, record: current["principal_id"] == record["work_key"]["principal_id"]
                service = SuccessorService(store, {token: context}, authority,
                    ComponentExecutor(component, failed=failed), campaign, read_allowed=permitted,
                    usage_write_allowed=permitted)
                try:
                    _code, reply = service.submit(request, trusted, 5000, credential=token)
                    status = service.status(reply["handle"]["submission_id"], trusted)
                    usage = status["attempts"][0]["usage_revision"]
                    self.assertEqual(status["submission_state"], "failed" if failed else "completed")
                    self.assertEqual((usage["cost_status"], usage["components"][0]["presence"]),
                                     ("unknown", expected_presence))
                    if isinstance(component, dict) and component.get("quantity") == chr(0xD800):
                        expected = sha256(b'{"component":"document_units","presence":"known",'
                                          b'"quantity":"\\ud800"}').hexdigest()
                        self.assertEqual(usage["components"][0]["raw_digest"], "sha256:" + expected)
                    self.assertTrue(campaign.inspect()["paused"])
                    self.assertEqual(campaign.inspect()["possible_send_count"], 1)
                finally:
                    service.pool.shutdown(wait=True)
                    store.close()

    def test_historical_usage_mutates_only_its_admitted_campaign(self):
        example = next(row for row in VECTORS["examples"] if row["id"] == "DIRECT_DOCUMENT")
        now = datetime.now(timezone.utc).replace(microsecond=0)
        fmt = lambda value: value.strftime("%Y-%m-%dT%H:%M:%SZ")
        request, context = deepcopy(example["request"]), deepcopy(example["trusted_context"])
        request["deadline"] = fmt(now + timedelta(minutes=30))
        context["authenticated_at"] = fmt(now - timedelta(minutes=1))
        context["expires_at"] = fmt(now + timedelta(hours=1))
        context["identity"]["charging_owner_id"] = "team.admitted"
        trusted = {**context["identity"], "task_id": request["work_selector"]["task_id"]}
        token = "test.campaign.binding." + "x" * 32
        with TemporaryDirectory() as temporary:
            store = SQLiteStore(Path(temporary) / "campaign-binding.sqlite")
            authority = SyntheticSuccessorAuthority(store, Ed25519PrivateKey.generate(), "key.test", "v1")
            admitted = FiniteSuccessorCampaign(store, "campaign.admitted", "budget.admitted",
                                               financial_owner_id="team.admitted")
            foreign = FiniteSuccessorCampaign(store, "campaign.foreign", "budget.foreign",
                                              financial_owner_id="team.foreign")
            admitted.start({}, [], max_attempts=2)
            foreign.start({}, [], max_attempts=2)
            authority.set_historical_access(context["identity"], read=True, write=True,
                resume=True, observed_at=fmt(now))
            permitted = lambda current, record: current["principal_id"] == record["work_key"]["principal_id"]
            services = [SuccessorService(store, {token: context}, authority, ComponentExecutor(None), allowance,
                read_allowed=permitted, usage_write_allowed=permitted)
                for allowance in (admitted, foreign)]
            try:
                _, reply = services[0].submit(request, trusted, 5000, credential=token)
                sid, aid = reply["handle"]["submission_id"], reply["attempt_id"]
                row = store.successor_get(sid)
                self.assertEqual(row["campaign_id"], admitted.campaign_id)
                known = {"component": "document_units", "presence": "known", "quantity": 1,
                         "evidence": "reported", "source_ref": "receiver.test"}
                usage = native_usage_row(request, aid, 2, known,
                    row["reservation"]["max_exposure_decimal"], previous_revision=1)
                prior = (store.successor_get(sid), store.successor_latest_usage(aid),
                         admitted.inspect(), foreign.inspect())
                with self.assertRaises(PermissionError):
                    services[1].ingest_usage_revision(sid, usage, trusted)
                self.assertEqual(prior, (store.successor_get(sid), store.successor_latest_usage(aid),
                                         admitted.inspect(), foreign.inspect()))
                self.assertEqual(services[0].ingest_usage_revision(sid, usage, trusted), "accepted")
                self.assertEqual(store.successor_latest_usage(aid)["revision"], 2)
                self.assertEqual(foreign.inspect(), prior[3])
            finally:
                for service in services:
                    service.pool.shutdown(wait=True)
                store.close()

    def test_late_write_rechecks_permission_after_gate_wait(self):
        example = next(row for row in VECTORS["examples"] if row["id"] == "DIRECT_DOCUMENT")
        now = datetime.now(timezone.utc).replace(microsecond=0)
        fmt = lambda value: value.strftime("%Y-%m-%dT%H:%M:%SZ")
        with TemporaryDirectory() as temporary:
            store = SQLiteStore(Path(temporary) / "late.sqlite")
            authority = SyntheticSuccessorAuthority(store, Ed25519PrivateKey.generate(), "key.test", "v1")
            campaign = FiniteSuccessorCampaign(store, "campaign.late", "budget.late")
            campaign.start({}, [], max_attempts=1)
            request, context = deepcopy(example["request"]), deepcopy(example["trusted_context"])
            request["deadline"] = fmt(now + timedelta(minutes=30))
            context["authenticated_at"] = fmt(now - timedelta(minutes=1))
            context["expires_at"] = fmt(now + timedelta(hours=1))
            authority.set_historical_access(context["identity"], read=True, write=True,
                resume=True, observed_at=fmt(now))
            trusted = {**context["identity"], "task_id": request["work_selector"]["task_id"]}
            token = "test.late." + "x" * 32
            checked = Event()
            def write_allowed(_current, _record):
                checked.set()
                return True
            permitted = lambda current, record: current["principal_id"] == record["work_key"]["principal_id"]
            service = SuccessorService(store, {token: context}, authority,
                ComponentExecutor(None), campaign, read_allowed=permitted,
                usage_write_allowed=write_allowed)
            try:
                _code, reply = service.submit(request, trusted, 5000, credential=token)
                sid, aid = reply["handle"]["submission_id"], reply["attempt_id"]
                original = store.successor_get(sid)
                known = {"component": "document_units", "presence": "known", "quantity": 1,
                         "evidence": "reported", "source_ref": "receiver.late"}
                usage = native_usage_row(request, aid, 2, known,
                    original["reservation"]["max_exposure_decimal"], previous_revision=1)
                checked.clear()
                failures = []
                with authority.gate:
                    def append():
                        try:
                            service.ingest_usage_revision(sid, usage, trusted)
                        except PermissionError as exc:
                            failures.append(type(exc).__name__)
                    thread = Thread(target=append)
                    thread.start()
                    self.assertFalse(checked.wait(.2), "permission sampled before gate")
                    authority.set_historical_access(context["identity"], read=True, write=False,
                        resume=True, observed_at=fmt(now))
                thread.join(2)
                self.assertFalse(thread.is_alive())
                self.assertEqual(failures, ["PermissionError"])
                self.assertEqual(store.successor_latest_usage(aid)["revision"], 1)
                self.assertEqual(store.successor_get(sid)["settlement_state"], "unknown")
                self.assertEqual(campaign.inspect()["attempt_count"], 1)
                self.assertEqual(campaign.inspect()["possible_send_count"], 1)
                authority.set_historical_access(context["identity"], read=True, write=True,
                    resume=True, observed_at=fmt(now))
                authority.revoke_key_version("key.test", "v1", fmt(now))
                self.assertEqual(service.ingest_usage_revision(sid, usage, trusted), "accepted")
                self.assertEqual(store.successor_latest_usage(aid)["revision"], 2)
            finally:
                service.pool.shutdown(wait=True)
                store.close()


if __name__ == "__main__":
    unittest.main()
