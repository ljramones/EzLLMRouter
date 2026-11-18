"""Isolated external observations through registry, normal HTTP and durable SQLite."""
import csv
from decimal import Decimal
import http.client
import io
import json
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest import mock
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/src"))
from duranki_server.integration_accounting import IntegrationError
from duranki_server.registry import Registry
from duranki_server.store import SQLiteStore
from duranki_server.web import serve

EXAMPLES = json.loads((ROOT / "docs/contracts/integration-readiness-v1/examples.json").read_text())
DEST = {"configuration_ref": "cfg.demo", "service": "litellm.dev04", "endpoint": "127.0.0.1",
        "model": "model.demo", "model_version": "v1", "processing_region": "local"}
TRUSTED = {"principal_id": "svc.demo", "charging_owner_id": "team.demo"}


class Authority:
    def __init__(self):
        self.gate = threading.RLock()
        self.epoch = 0


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = SQLiteStore(Path(self.tmp.name) / "integration.sqlite")
        self.addCleanup(self.store.close)
        self.registry = Registry(self.store, Authority(), legacy_destination=DEST,
            legacy_token="synthetic-legacy-service-token-000000000000",
            legacy_trusted=TRUSTED)
        self.registry.mutate("owner.local", {"operation_id": "op.integration.principal",
            "action": "create_principal", "subject": "svc.integration", "expected_revision": 0,
            "data": {"display_name": "Synthetic integration", "kind": "service",
                     "owner": "owner.local", "role": "ordinary"}})
        _, self.ingest_token = self.registry.provision_credential(
            "owner.local", "svc.integration", 1, "op.integration.credential")
        self.registry.mutate("owner.local", {"operation_id": "op.integration.activate",
            "action": "principal_state", "subject": "svc.integration", "expected_revision": 2,
            "data": {"status": "active", "reason": "isolated test"}})
        self.admin_token = self.registry.issue_local_operator_token("owner.local")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.http = serve("127.0.0.1", self.port, SimpleNamespace(registry=self.registry))
        self.thread = threading.Thread(target=self.http.serve_forever)
        self.thread.start()
        self.addCleanup(self._stop)
        self.dataset = {**EXAMPLES["dataset"], "ingest_principal_id": "svc.integration"}
        self.account = EXAMPLES["account"]

    def _stop(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=3)

    def request(self, method, path, body=None, *, admin=False, token=None, version="1"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Authorization": "Bearer " + (token or (self.admin_token if admin else self.ingest_token)),
                   "Duranki-Integration-Version": version}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body, separators=(",", ":"))
        try:
            conn.request(method, path, data, headers)
            response = conn.getresponse()
            raw = response.read()
            return response.status, (raw.decode() if response.getheader("Content-Type").startswith("text/csv")
                                     else json.loads(raw))
        finally:
            conn.close()

    def create(self):
        self.assertEqual(self.request("POST", "/integration/v1/datasets", self.dataset, admin=True)[0], 201)
        self.assertEqual(self.request("POST", "/integration/v1/accounts", self.account, admin=True)[0], 201)

    def event(self, value):
        return self.request("POST", "/integration/v1/events", value)

    @mock.patch("duranki_server.integration_accounting._time", return_value="2026-11-03T00:00:00Z")
    def test_local_real_cohort_expiry_at_t0_boundary(self, clock):
        owner = {"principal_id": "owner.local", "owner": "owner.local", "role": "registry_admin"}
        accounting = self.registry.integration
        accounting.accounting_retention_days = 1
        did = "dataset.local.real.retention.controlled"
        real = {**self.dataset, "dataset_id": did, "activated_at": "2026-11-03T00:00:00Z"}
        synthetic = {**self.dataset, "dataset_id": "dataset.synthetic.retention.controlled",
                     "activated_at": "2026-11-03T00:00:00Z"}
        accounting.create_dataset(owner, real)
        accounting.create_dataset(owner, synthetic)
        account = {**self.account, "dataset_id": did, "account_id": "account.local.real.retention"}
        accounting.create_account(owner, account)
        self.assertEqual(accounting._dataset(did)["dataset_id"], did)
        clock.return_value = "2026-11-03T23:59:59Z"
        self.assertEqual(accounting.expire_datasets(), 0)
        self.assertIsNotNone(self.store.db.execute(
            "SELECT 1 FROM integration_accounts WHERE dataset_id=?", (did,)).fetchone())
        restarted = Registry(self.store, Authority())
        self.assertEqual(restarted.integration.expire_datasets(), 0)
        clock.return_value = "2026-11-04T00:00:00Z"
        self.assertEqual(restarted.integration.expire_datasets(), 1)
        self.assertIsNone(self.store.db.execute(
            "SELECT 1 FROM integration_accounts WHERE dataset_id=?", (did,)).fetchone())
        self.assertIsNone(self.store.db.execute(
            "SELECT 1 FROM integration_account_history WHERE id=?", (account["account_id"],)).fetchone())
        with self.assertRaisesRegex(IntegrationError, "NOT_FOUND_OR_FORBIDDEN"):
            accounting._dataset(did)
        self.assertEqual(accounting._dataset(synthetic["dataset_id"])["dataset_id"],
                         synthetic["dataset_id"])
        with self.assertRaisesRegex(IntegrationError, "DATASET_EXPIRED"):
            accounting.create_dataset(owner, real)

    @mock.patch("duranki_server.integration_accounting._time", return_value="2099-01-01T00:00:00Z")
    def test_v3_speech_opt_in_and_model_scope(self, _clock):
        def api(method, path, body=None, admin=False):
            return self.request(method, "/integration/v3" + path, body, admin=admin, version="3")
        did = "dataset.speech.v3"
        dataset = {**self.dataset, "dataset_id": did}
        self.assertEqual(api("POST", "/datasets", dataset, True)[0], 201)
        account = {**self.account, "dataset_id": did, "account_id": "account.speech.v3",
                   "allowed_models": ["model.allowed"], "allowed_operations": []}
        self.assertEqual(api("POST", "/accounts", account, True)[0], 201)
        selector = f"/accounts/{account['account_id']}/eligibility?dataset_id={did}&operation_family=speech_input&capability=transcription&selection_kind=not_applicable"
        status, denied = api("GET", selector)
        self.assertEqual(status, 200)
        self.assertEqual((denied["usable"], denied["reason"]), (False, "operation_not_permitted"))
        _clock.return_value = "2099-01-01T00:00:01Z"
        self.assertEqual(api("POST", f"/accounts/{account['account_id']}/permissions",
            {"dataset_id": did, "expected_revision": 1, "allowed_models": ["model.allowed"],
             "allowed_operations": ["speech_input"]}, True)[0], 200)
        _clock.return_value = "2099-01-01T00:00:02Z"
        status, allowed = api("GET", selector)
        self.assertEqual((status, allowed["usable"], allowed["account_revision"]), (200, True, 2))
        self.assertEqual(allowed["provider_id"], account["provider_id"])
        self.assertEqual(allowed["credential_ref"], account["credential_ref"])
        self.assertEqual(api("GET", selector.replace("speech_input&capability=transcription",
            "speech_output&capability=synthesis"))[1]["reason"], "operation_not_permitted")
        known = selector.replace("selection_kind=not_applicable", "selection_kind=known_model&model_id=model.denied")
        self.assertEqual(api("GET", known)[1]["reason"], "model_not_permitted")
        self.assertEqual(api("GET", selector.replace("capability=transcription", "capability=synthesis"))[0], 400)
        self.assertEqual(api("GET", selector.replace("selection_kind=not_applicable", "selection_kind=known_model"))[0], 400)
        self.assertEqual(api("GET", selector.replace(did, "dataset.other"))[0], 404)
        self.assertEqual(api("GET", selector.replace(account["account_id"], "account.other"))[0], 404)
        old = {**self.account, "dataset_id": did, "account_id": "account.legacy.v3"}
        self.assertEqual(self.request("POST", "/integration/v2/accounts", old, admin=True, version="2")[0], 201)
        self.assertEqual(api("GET", selector.replace(account["account_id"], old["account_id"]))[1]["reason"],
                         "operation_not_permitted")
        empty = {**account, "account_id": "account.empty.v3", "allowed_models": [],
                 "allowed_operations": []}
        self.assertEqual(api("POST", "/accounts", empty, True)[0], 201)
        self.assertEqual(api("GET", selector.replace(account["account_id"], empty["account_id"]))[1]["reason"],
                         "operation_not_permitted")
        _clock.return_value = "2099-01-01T00:00:04Z"
        self.assertEqual(api("POST", f"/accounts/{account['account_id']}/state",
            {"dataset_id": did, "expected_revision": 2, "state": "disabled"}, True)[0], 200)
        self.assertEqual(api("GET", selector)[1]["reason"], "account_disabled")
        at = "2099-01-01T00:00:03Z"
        aid = "attempt.speech.v3"
        evidence = {"status": "verified", "eligibility_id": allowed["eligibility_id"]}
        action = {"selected_account_id": account["account_id"], "operation_family": "speech_input",
                  "capability": "transcription", "selection_kind": "not_applicable",
                  "policy_version": "policy.synthetic.v3", "eligibility_evidence": evidence}
        snapshot = {"integration_version": "3", "dataset_id": did, "attempt_id": aid,
                    "schema_version": "1", "producer_version": "synthetic.test.v3",
                    "provenance": "synthetic", "source_at": "2099-01-01T00:00:02Z",
                    "available_at": "2099-01-01T00:00:02Z", "classification": "low",
                    "retention_until": "2099-01-02T00:00:00Z"}
        self.assertEqual(api("POST", "/snapshots", {**snapshot, "snapshot_id": "feature.speech.v3",
            "snapshot_kind": "feature", "status": "not_collected"})[0], 201)
        self.assertEqual(api("POST", "/snapshots", {**snapshot, "snapshot_id": "decision.speech.v3",
            "snapshot_kind": "decision", "status": "captured", "selected_action": action})[0], 201)
        decision = {"integration_version": "3", "event_id": "event.speech.decision", "dataset_id": did,
                    "kind": "decision", "occurred_at": at, "attempt_id": aid,
                    "decision_ref": "decision.speech.v3", **action}
        self.assertEqual(api("POST", "/events", decision)[0], 201)
        self.assertEqual(api("POST", "/events", decision)[0], 200)
        self.assertEqual(api("POST", "/events", {**decision, "event_id": "event.speech.wrong",
            "operation_family": "speech_output", "capability": "synthesis"})[0], 409)
        self.assertEqual(api("POST", "/events", {**decision, "event_id": "event.speech.other",
            "attempt_id": "attempt.speech.other", "decision_ref": "decision.speech.other",
            "operation_family": "speech_output", "capability": "synthesis"})[0], 409)
        start = {"integration_version": "3", "event_id": "event.speech.start", "dataset_id": did,
                 "kind": "attempt_started", "occurred_at": at, "started_at": at,
                 "attempt_id": aid, "task_id": "task.speech.v3", "step_id": "step.speech.v3",
                 "run_id": "run.speech.v3", "root_run_id": "run.speech.v3",
                 "actor_kind": "service", "actor_id": "service.voice.synthetic",
                 "provider_account_id": account["account_id"], "context_ref": "feature.speech.v3",
                 "operation_family_version": "1", "operation_family": "speech_input",
                 "model_identity_state": "not_applicable", "logical_operation_id": "operation.speech.v3",
                 "attempt_role": "initial"}
        self.assertEqual(api("POST", "/events", start)[0], 201)
        result = {"integration_version": "3", "event_id": "event.speech.result", "dataset_id": did,
                  "kind": "result", "occurred_at": "2099-01-01T00:00:05Z", "attempt_id": aid,
                  "result_state": "completed"}
        usage = {"integration_version": "3", "event_id": "event.speech.usage", "dataset_id": did,
                 "kind": "usage", "occurred_at": "2099-01-01T00:00:05Z", "attempt_id": aid,
                 "usage_revision": 1, "usage_state": "known", "cost_state": "unknown",
                 "native_units": [{"unit": "bytes", "quantity_decimal": "17"}],
                 "usage_provenance": "provider_reported"}
        self.assertEqual(api("POST", "/events", result)[0], 201)
        self.assertEqual(api("POST", "/events", usage)[0], 201)
        status, report = api("GET", f"/reports/usage?dataset_id={did}", admin=True)
        self.assertEqual(status, 200, report)
        self.assertEqual((report["attempt_count"], report["unknown_cost_attempts"]), (1, 1))
        self.assertEqual(report["attempts"][0]["eligibility_assessment"], "verified")
        export = api("GET", f"/reports/dataset?dataset_id={did}", admin=True)[1]
        self.assertEqual((len(export["attempts"]), len(export["eligibility_reads"])), (1, 1))

    def correction02_fixture(self, suffix):
        did = "dataset.c02." + suffix
        dataset = {**self.dataset, "dataset_id": did}
        account = {**self.account, "dataset_id": did, "account_id": "account.c02." + suffix}
        api = lambda method, path, body=None, admin=False: self.request(
            method, "/integration/v2" + path, body, admin=admin, version="2")
        self.assertEqual(api("POST", "/datasets", dataset, True)[0], 201)
        self.assertEqual(api("POST", "/accounts", account, True)[0], 201)
        start = {**EXAMPLES["events"][2], "integration_version": "2", "dataset_id": did,
            "event_id": "event.base", "attempt_id": "attempt.base", "started_at": "2099-01-01T00:00:10Z",
            "occurred_at": "2099-01-01T00:00:10Z", "run_id": "run.c02", "root_run_id": "run.c02",
            "task_id": "task.c02", "provider_account_id": account["account_id"],
            "context_ref": "feature.base", "operation_family_version": "1", "operation_family": "generation",
            "model_identity_state": "known", "logical_operation_id": "logical.c02", "attempt_role": "initial"}
        start.pop("parent_run_id")
        return api, did, account, start

    @mock.patch("duranki_server.integration_accounting._time", return_value="2099-01-01T00:00:00Z")
    def test_correction02_lineage_both_orders_and_historical_conflict(self, _clock):
        api, did, _, base = self.correction02_fixture("lineage")
        link = {"integration_version": "2", "event_id": "event.link.orphan", "dataset_id": did,
            "kind": "lineage", "occurred_at": "2099-01-01T00:00:11Z",
            "attempt_id": "attempt.orphan", "logical_operation_id": "logical.c02",
            "attempt_role": "fallback", "predecessor_attempt_id": "attempt.future"}
        self.assertEqual(api("POST", "/events", link)[0], 201)
        orphan = {**base, "event_id": "event.orphan", "attempt_id": "attempt.orphan",
            "context_ref": "feature.orphan", "attempt_role": "unknown"}
        self.assertEqual(api("POST", "/events", {**orphan, "logical_operation_id": "logical.wrong"})[0], 409)
        self.assertEqual(api("POST", "/events", {**orphan, "attempt_role": "initial"})[0], 409)
        self.assertEqual(api("POST", "/events", orphan)[0], 201)
        self.assertEqual(api("POST", "/events", {**base, "event_id": "event.future",
            "attempt_id": "attempt.future", "context_ref": "feature.future",
            "logical_operation_id": "logical.wrong"})[0], 409)
        self.assertEqual(api("POST", "/events", {**base, "event_id": "event.future.task",
            "attempt_id": "attempt.future", "context_ref": "feature.future",
            "task_id": "task.wrong"})[0], 409)
        future = {**base, "event_id": "event.future", "attempt_id": "attempt.future",
                  "context_ref": "feature.future"}
        self.assertEqual(api("POST", "/events", future)[0], 201)
        self.assertEqual(api("POST", "/events", future)[0], 200)
        self.assertEqual(api("POST", "/events", base)[0], 201)
        self.assertEqual(api("POST", "/events", {**link, "event_id": "event.link.base",
            "attempt_id": "attempt.base", "predecessor_attempt_id": "attempt.future"})[0], 409)
        late = {**base, "event_id": "event.late", "attempt_id": "attempt.late",
                "context_ref": "feature.late", "attempt_role": "unknown"}
        self.assertEqual(api("POST", "/events", late)[0], 201)
        late_link = {**link, "event_id": "event.link.late", "attempt_id": "attempt.late",
                     "predecessor_attempt_id": "attempt.future"}
        self.assertEqual(api("POST", "/events", late_link)[0], 201)
        self.assertEqual(api("POST", "/events", late_link)[0], 200)
        self.assertEqual(api("POST", "/events", {**late_link, "event_id": "event.link.cycle",
            "attempt_id": "attempt.future", "predecessor_attempt_id": "attempt.late"})[0], 409)
        usage = {"integration_version": "2", "event_id": "event.usage.orphan", "dataset_id": did,
            "kind": "usage", "occurred_at": "2099-01-01T00:00:20Z", "attempt_id": "attempt.orphan",
            "usage_revision": 1, "usage_state": "unknown", "cost_state": "known", "currency": "USD",
            "amount_decimal": "0.010000000", "cost_basis": "provider_reported",
            "price_ref": "tariff.synthetic", "price_version": "v1"}
        self.assertEqual(api("POST", "/events", usage)[0], 201)
        self.assertEqual(api("POST", "/events", usage)[0], 200)
        report = api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]
        by_id = {row["attempt_id"]: row for row in report["attempts"]}
        self.assertEqual(by_id["attempt.orphan"]["lineage_status"], "linked")
        self.assertEqual(by_id["attempt.late"]["lineage_status"], "linked")
        self.assertEqual(report["known_total_by_currency"], {"USD": "0.010000000"})
        # An older accepted contradiction remains readable but is not a trusted link.
        with self.store._lock:
            row = self.store.db.execute("SELECT record FROM integration_attempts WHERE dataset_id=? AND attempt_id=?",
                                        (did, "attempt.orphan")).fetchone()
            corrupted = {**json.loads(row[0]), "logical_operation_id": "logical.wrong"}
            self.store.db.execute("UPDATE integration_attempts SET record=? WHERE dataset_id=? AND attempt_id=?",
                                  (json.dumps(corrupted), did, "attempt.orphan"))
        report = api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]
        self.assertEqual(next(row for row in report["attempts"] if row["attempt_id"] == "attempt.orphan")
                         ["lineage_status"], "binding_conflict")
        self.assertEqual(report["known_total_by_currency"], {"USD": "0.010000000"})
        unrelated = {**base, "event_id": "event.unrelated.after.conflict",
            "attempt_id": "attempt.unrelated.after.conflict", "context_ref": "feature.unrelated",
            "task_id": "task.unrelated", "run_id": "run.unrelated",
            "root_run_id": "run.unrelated", "logical_operation_id": "logical.unrelated"}
        self.assertEqual(api("POST", "/events", unrelated)[0], 201)
        self.assertEqual(api("POST", "/events", unrelated)[0], 200)
        self.assertEqual(api("POST", "/events", {**unrelated,
            "event_id": "event.related.to.conflict", "attempt_id": "attempt.related.to.conflict",
            "context_ref": "feature.related", "task_id": "task.c02",
            "run_id": "run.c02", "root_run_id": "run.c02",
            "logical_operation_id": "logical.c02", "attempt_role": "fallback",
            "predecessor_attempt_id": "attempt.orphan"})[0], 409)
        after = api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]
        self.assertEqual(after["attempt_count"], report["attempt_count"] + 1)
        self.assertEqual(after["known_total_by_currency"], {"USD": "0.010000000"})
        self.assertEqual(next(row for row in after["attempts"] if row["attempt_id"] == "attempt.orphan")
                         ["lineage_status"], "binding_conflict")

    @mock.patch("duranki_server.integration_accounting._time", return_value="2099-01-01T00:00:00Z")
    def test_correction03_mixed_version_lineage_orders_and_unrelated_work(self, _clock):
        def old_start(did, account, event_id):
            start = {**EXAMPLES["events"][2], "dataset_id": did,
                "event_id": event_id, "attempt_id": "attempt.legacy",
                "occurred_at": "2099-01-01T00:00:10Z", "started_at": "2099-01-01T00:00:10Z",
                "task_id": "task.legacy", "run_id": "run.legacy",
                "root_run_id": "run.legacy", "provider_account_id": account["account_id"]}
            start.pop("parent_run_id")
            return start

        def link(did):
            return {"integration_version": "2", "event_id": "event.link.legacy",
                "dataset_id": did, "kind": "lineage", "occurred_at": "2099-01-01T00:00:11Z",
                "attempt_id": "attempt.legacy", "logical_operation_id": "logical.legacy",
                "attempt_role": "fallback", "predecessor_attempt_id": "attempt.pending"}

        def unrelated(base, label):
            return {**base, "event_id": "event.unrelated." + label,
                "attempt_id": "attempt.unrelated." + label,
                "context_ref": "feature.unrelated." + label,
                "task_id": "task.unrelated." + label,
                "run_id": "run.unrelated." + label,
                "root_run_id": "run.unrelated." + label,
                "logical_operation_id": "logical.unrelated." + label}

        api, did, account, base = self.correction02_fixture("mixed.link.first")
        legacy = old_start(did, account, "event.legacy")
        orphan = link(did)
        v1 = lambda value: self.request("POST", "/integration/v1/events", value, version="1")
        first_link = api("POST", "/events", orphan)
        self.assertEqual(first_link[0], 201)
        self.assertEqual(v1(legacy)[0], 409)
        self.assertEqual(api("POST", "/events", orphan), (200, first_link[1]))
        self.assertEqual(api("GET", "/events/event.link.legacy/receipt?dataset_id=" + did)[1], first_link[1])
        clean = unrelated(base, "after.rejected.start")
        self.assertEqual(api("POST", "/events", clean)[0], 201)
        self.assertEqual(api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]["attempt_count"], 1)

        api, did, account, base = self.correction02_fixture("mixed.start.first")
        legacy = old_start(did, account, "event.legacy.second")
        orphan = link(did)
        accepted = v1(legacy)
        self.assertEqual(accepted[0], 201)
        self.assertEqual(api("POST", "/events", orphan)[0], 409)
        self.assertEqual(v1(legacy), (200, accepted[1]))
        self.assertEqual(self.request("GET", "/integration/v1/events/event.legacy.second/receipt?dataset_id=" + did,
                                      version="1")[1], accepted[1])
        self.assertEqual(api("POST", "/events", unrelated(base, "after.rejected.link"))[0], 201)
        report = api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]
        self.assertEqual(report["attempt_count"], 2)
        self.assertEqual(next(row for row in report["attempts"] if row["attempt_id"] == "attempt.legacy")
                         ["lineage_status"], "legacy_absent")
        self.assertEqual(report["known_total_by_currency"], {})

        api, did, _, base = self.correction02_fixture("pure.v2.control")
        self.assertEqual(api("POST", "/events", base)[0], 201)
        self.assertEqual(api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]["attempt_count"], 1)

    @mock.patch("duranki_server.integration_accounting._time", return_value="2099-01-01T00:00:00Z")
    def test_correction03_previously_accepted_mixed_conflict_projection(self, _clock):
        api, did, account, base = self.correction02_fixture("old.mixed")
        link = {"integration_version": "2", "event_id": "event.old.link", "dataset_id": did,
            "kind": "lineage", "occurred_at": "2099-01-01T00:00:11Z",
            "attempt_id": "attempt.old.legacy", "logical_operation_id": "logical.old",
            "attempt_role": "fallback", "predecessor_attempt_id": "attempt.old.pending"}
        self.assertEqual(api("POST", "/events", link)[0], 201)
        legacy = {**EXAMPLES["events"][2], "dataset_id": did,
            "event_id": "event.old.legacy", "attempt_id": "attempt.old.legacy",
            "occurred_at": "2099-01-01T00:00:10Z", "started_at": "2099-01-01T00:00:10Z",
            "task_id": "task.old", "run_id": "run.old", "root_run_id": "run.old",
            "provider_account_id": account["account_id"]}
        legacy.pop("parent_run_id")
        # Reproduce the predecessor's v1 admission gap through normal HTTP.
        with mock.patch.object(self.registry.integration, "_check_lineage"):
            accepted = self.request("POST", "/integration/v1/events", legacy, version="1")
        self.assertEqual(accepted[0], 201)
        before = list(self.store.db.execute("SELECT event_id,digest,record FROM integration_events "
                                            "WHERE dataset_id=? ORDER BY event_id", (did,)))
        report = api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]
        self.assertEqual(report["attempts"][0]["lineage_status"], "binding_conflict")
        unrelated = {**base, "event_id": "event.new.unrelated",
            "attempt_id": "attempt.new.unrelated", "context_ref": "feature.new.unrelated",
            "task_id": "task.new", "run_id": "run.new", "root_run_id": "run.new",
            "logical_operation_id": "logical.new"}
        self.assertEqual(api("POST", "/events", unrelated)[0], 201)
        self.assertEqual(api("POST", "/events", unrelated)[0], 200)
        report = api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]
        self.assertEqual(report["attempt_count"], 2)
        self.assertEqual(next(row for row in report["attempts"] if row["attempt_id"] == "attempt.old.legacy")
                         ["lineage_status"], "binding_conflict")
        export = api("GET", "/reports/dataset?dataset_id=" + did, admin=True)[1]
        self.assertEqual(len(export["attempts"]), 2)
        after = list(self.store.db.execute("SELECT event_id,digest,record FROM integration_events "
                                           "WHERE dataset_id=? AND event_id IN ('event.old.link','event.old.legacy') "
                                           "ORDER BY event_id", (did,)))
        self.assertEqual(before, after)

    def test_correction02_eligibility_same_second_and_unambiguous(self):
        with mock.patch("duranki_server.integration_accounting._time", return_value="2099-01-01T00:00:00Z"):
            api, did, account, base = self.correction02_fixture("eligibility")
            answer = api("GET", "/accounts/" + account["account_id"] +
                "/eligibility?dataset_id=" + did + "&model_id=model.synthetic")[1]
            first = {**base, "event_id": "event.first", "attempt_id": "attempt.first",
                     "context_ref": "feature.first", "started_at": "2099-01-01T00:00:01Z",
                     "occurred_at": "2099-01-01T00:00:01Z"}
            second = {**first, "event_id": "event.second", "attempt_id": "attempt.second",
                      "context_ref": "feature.second"}
            for item in (first, second):
                self.assertEqual(api("POST", "/events", item)[0], 201)
            decision = {"integration_version": "2", "event_id": "event.decision.first",
                "dataset_id": did, "kind": "decision", "occurred_at": "2099-01-01T00:00:00Z",
                "attempt_id": "attempt.first", "decision_ref": "decision.first",
                "selected_account_id": account["account_id"], "selected_model_id": "model.synthetic",
                "policy_version": "policy.synthetic", "eligibility_evidence":
                {"status": "verified", "eligibility_id": answer["eligibility_id"]}}
            self.assertEqual(api("POST", "/events", decision)[0], 201)
            self.assertEqual(api("POST", "/accounts/" + account["account_id"] + "/state",
                {"dataset_id": did, "expected_revision": 1, "state": "disabled"}, True)[0], 200)
            delayed = {**decision, "event_id": "event.decision.second", "attempt_id": "attempt.second",
                       "decision_ref": "decision.second"}
            self.assertEqual(api("POST", "/events", delayed)[0], 201)
            self.assertEqual(api("POST", "/events", delayed)[0], 200)
            self.assertEqual(api("GET", "/events/event.decision.second/receipt?dataset_id=" + did)[0], 200)
            report = api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]
            self.assertEqual({row["eligibility_assessment"] for row in report["attempts"]},
                             {"indeterminate"})
            self.assertEqual({row["eligibility_evidence_status"] for row in report["attempts"]},
                             {"verified"})
            exported = api("GET", "/reports/dataset?dataset_id=" + did, admin=True)[1]
            self.assertEqual({row["assessment"] for row in exported["eligibility_assessments"]},
                             {"indeterminate"})
            self.assertEqual(len(exported["eligibility_reads"]), 1)
            csv_rows = list(csv.DictReader(io.StringIO(api("GET",
                "/reports/usage?dataset_id=" + did + "&export=csv", admin=True)[1])))
            self.assertEqual({row["eligibility_assessment"] for row in csv_rows}, {"indeterminate"})
        with mock.patch("duranki_server.integration_accounting._time", return_value="2099-01-01T00:00:01Z"):
            denied = api("GET", "/accounts/" + account["account_id"] +
                "/eligibility?dataset_id=" + did + "&model_id=model.synthetic")[1]
        stale_start = {**first, "event_id": "event.stale", "attempt_id": "attempt.stale",
                       "context_ref": "feature.stale", "started_at": "2099-01-01T00:00:03Z",
                       "occurred_at": "2099-01-01T00:00:03Z"}
        self.assertEqual(api("POST", "/events", stale_start)[0], 201)
        stale = {**decision, "event_id": "event.decision.stale", "attempt_id": "attempt.stale",
                 "decision_ref": "decision.stale", "occurred_at": "2099-01-01T00:00:02Z",
                 "eligibility_evidence": {"status": "stale", "eligibility_id": answer["eligibility_id"]}}
        self.assertEqual(api("POST", "/events", stale)[0], 201)
        false_start = {**stale_start, "event_id": "event.false.start", "attempt_id": "attempt.false",
                       "context_ref": "feature.false"}
        self.assertEqual(api("POST", "/events", false_start)[0], 201)
        self.assertEqual(api("POST", "/events", {**stale, "event_id": "event.false.verified",
            "attempt_id": "attempt.false", "decision_ref": "decision.false",
            "eligibility_evidence": {"status": "verified", "eligibility_id": answer["eligibility_id"]}})[0], 400)
        self.assertEqual(api("POST", "/events", {**stale, "event_id": "event.false.model",
            "attempt_id": "attempt.false", "decision_ref": "decision.false",
            "selected_model_id": "model.other"})[0], 409)
        denied_start = {**stale_start, "event_id": "event.denied", "attempt_id": "attempt.denied",
                        "context_ref": "feature.denied"}
        self.assertEqual(api("POST", "/events", denied_start)[0], 201)
        denial = {**stale, "event_id": "event.decision.denied", "attempt_id": "attempt.denied",
                  "decision_ref": "decision.denied", "eligibility_evidence":
                  {"status": "denied", "eligibility_id": denied["eligibility_id"]}}
        self.assertEqual(api("POST", "/events", denial)[0], 201)
        report = api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]
        assessments = {row["attempt_id"]: row["eligibility_assessment"] for row in report["attempts"]}
        self.assertEqual(assessments["attempt.stale"], "stale")
        self.assertEqual(assessments["attempt.denied"], "denied")

    @mock.patch("duranki_server.integration_accounting._time", return_value="2099-01-01T00:00:00Z")
    def test_correction02_snapshot_binding_both_orders_and_old_mismatches(self, clock):
        api, did, account, base = self.correction02_fixture("snapshots")
        self.assertEqual(api("POST", "/events", base)[0], 201)
        feature = {"integration_version": "2", "snapshot_id": "feature.base", "dataset_id": did,
            "attempt_id": "attempt.base", "snapshot_kind": "feature", "status": "captured",
            "schema_version": "1", "producer_version": "producer.synthetic.1", "provenance": "synthetic",
            "source_at": "2099-01-01T00:00:01Z", "available_at": "2099-01-01T00:00:02Z",
            "classification": "low", "retention_until": "2099-01-02T00:00:00Z",
            "source_expires_at": "2099-01-02T00:00:00Z", "features": {"task_category": "briefing"}}
        self.assertEqual(api("POST", "/snapshots", feature)[0], 201)
        self.assertEqual(api("POST", "/snapshots", feature)[0], 200)
        self.assertEqual(api("POST", "/snapshots", {**feature, "features":
            {"task_category": "different"}})[0], 409)
        other = {**base, "event_id": "event.other", "attempt_id": "attempt.other",
                 "context_ref": "feature.base"}
        self.assertEqual(api("POST", "/events", other)[0], 409)
        other["context_ref"] = "feature.pending"
        self.assertEqual(api("POST", "/events", other)[0], 201)
        self.assertEqual(api("POST", "/snapshots", {**feature, "snapshot_id": "feature.pending",
            "attempt_id": "attempt.foreign"})[0], 409)
        decision = {"integration_version": "2", "event_id": "event.decision.other", "dataset_id": did,
            "kind": "decision", "occurred_at": "2099-01-01T00:00:09Z",
            "attempt_id": "attempt.other", "decision_ref": "feature.base",
            "selected_account_id": account["account_id"], "selected_model_id": "model.synthetic",
            "policy_version": "policy.synthetic", "eligibility_evidence": {"status": "unavailable"}}
        self.assertEqual(api("POST", "/events", decision)[0], 409)
        decision["decision_ref"] = "decision.pending"
        self.assertEqual(api("POST", "/events", decision)[0], 201)
        late = {**feature, "snapshot_id": "decision.pending", "attempt_id": "attempt.foreign",
                "snapshot_kind": "decision", "selected_action": {key: decision[key] for key in
                ("selected_account_id", "selected_model_id", "policy_version", "eligibility_evidence")}}
        late.pop("features")
        self.assertEqual(api("POST", "/snapshots", late)[0], 409)
        late["attempt_id"] = "attempt.other"
        self.assertEqual(api("POST", "/snapshots", late)[0], 201)
        self.assertEqual(api("POST", "/snapshots", {**feature, "snapshot_id": "feature.pending",
            "attempt_id": "attempt.other"})[0], 201)
        wrong_kind_start = {**base, "event_id": "event.kind", "attempt_id": "attempt.kind",
                            "context_ref": "feature.kind"}
        self.assertEqual(api("POST", "/events", wrong_kind_start)[0], 201)
        self.assertEqual(api("POST", "/snapshots", {**feature, "snapshot_id": "feature.kind",
            "attempt_id": "attempt.kind"})[0], 201)
        self.assertEqual(api("POST", "/events", {**decision, "event_id": "event.kind.decision",
            "attempt_id": "attempt.kind", "decision_ref": "feature.kind"})[0], 409)
        before_start = {**late, "snapshot_id": "feature.wrong.kind", "attempt_id": "attempt.future"}
        self.assertEqual(api("POST", "/snapshots", before_start)[0], 201)
        self.assertEqual(api("POST", "/events", {**base, "event_id": "event.future",
            "attempt_id": "attempt.future", "context_ref": "feature.wrong.kind"})[0], 409)
        report = api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]
        rows = {row["attempt_id"]: row for row in report["attempts"]}
        self.assertEqual(rows["attempt.other"]["decision_snapshot_status"], "captured")
        self.assertEqual(rows["attempt.other"]["feature_snapshot_status"], "captured")
        # Model an immutable mismatch accepted by the predecessor build.
        with self.store._lock:
            raw = self.store.db.execute("SELECT record FROM integration_attempts WHERE dataset_id=? AND attempt_id=?",
                                        (did, "attempt.other")).fetchone()[0]
            old = {**json.loads(raw), "context_ref": "feature.base"}
            self.store.db.execute("UPDATE integration_attempts SET record=? WHERE dataset_id=? AND attempt_id=?",
                                  (json.dumps(old), did, "attempt.other"))
            raw = self.store.db.execute("SELECT record FROM integration_events WHERE dataset_id=? AND event_id=?",
                                        (did, "event.decision.other")).fetchone()[0]
            old_decision = {**json.loads(raw), "decision_ref": "feature.base"}
            self.store.db.execute("UPDATE integration_events SET record=? WHERE dataset_id=? AND event_id=?",
                                  (json.dumps(old_decision), did, "event.decision.other"))
        report = api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]
        row = next(row for row in report["attempts"] if row["attempt_id"] == "attempt.other")
        self.assertEqual(row["feature_snapshot_status"], "binding_conflict")
        self.assertEqual(row["decision_snapshot_status"], "binding_conflict")
        self.assertIsNone(row["feature_snapshot_digest"])
        self.assertIsNone(row["decision_snapshot_digest"])
        csv_rows = list(csv.DictReader(io.StringIO(api("GET",
            "/reports/usage?dataset_id=" + did + "&export=csv", admin=True)[1])))
        self.assertEqual(next(row for row in csv_rows if row["attempt_id"] == "attempt.other")
                         ["decision_snapshot_status"], "binding_conflict")
        exported = api("GET", "/reports/dataset?dataset_id=" + did, admin=True)[1]
        self.assertEqual({item["status"] for item in exported["snapshot_reference_assessments"]
                          if item["attempt_id"] == "attempt.other"}, {"binding_conflict"})
        clock.return_value = "2099-01-03T00:00:00Z"
        report = api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]
        self.assertEqual(next(row for row in report["attempts"] if row["attempt_id"] == "attempt.base")
                         ["feature_snapshot_status"], "expired")

    @mock.patch("duranki_server.integration_accounting._time", return_value="2099-01-01T00:00:00Z")
    def test_correction02_usage_state_json_csv_and_export(self, _clock):
        api, did, _, base = self.correction02_fixture("usage")
        for suffix in ("both", "units", "cost", "unknown", "absent"):
            item = {**base, "event_id": "event.start." + suffix,
                    "attempt_id": "attempt." + suffix, "context_ref": "feature." + suffix}
            self.assertEqual(api("POST", "/events", item)[0], 201)
        template = {"integration_version": "2", "dataset_id": did, "kind": "usage",
            "occurred_at": "2099-01-01T00:00:20Z", "usage_revision": 1}
        units = {"usage_state": "known", "native_units":
            [{"unit": "input_tokens", "quantity_decimal": "8"}],
            "usage_provenance": "provider_reported"}
        cost = {"cost_state": "known", "currency": "USD", "amount_decimal": "0.010000000",
            "cost_basis": "provider_reported", "price_ref": "tariff.synthetic", "price_version": "v1"}
        for suffix, fields in (("both", {**units, **cost}),
                               ("units", {**units, "cost_state": "unknown"}),
                               ("cost", {"usage_state": "unknown", **cost}),
                               ("unknown", {"usage_state": "unknown", "cost_state": "unknown"})):
            event = {**template, "event_id": "event.usage." + suffix,
                     "attempt_id": "attempt." + suffix, **fields}
            self.assertEqual(api("POST", "/events", event)[0], 201)
            self.assertEqual(api("POST", "/events", event)[0], 200)
        report = api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]
        rows = {row["attempt_id"]: row for row in report["attempts"]}
        self.assertEqual({aid: row["usage_state"] for aid, row in rows.items()},
            {"attempt.both": "known", "attempt.units": "known", "attempt.cost": "unknown",
             "attempt.unknown": "unknown", "attempt.absent": "not_observed"})
        self.assertEqual({aid: row["cost_status"] for aid, row in rows.items()},
            {"attempt.both": "known", "attempt.units": "unknown", "attempt.cost": "known",
             "attempt.unknown": "unknown", "attempt.absent": "not_observed"})
        self.assertEqual(report["known_total_by_currency"], {"USD": "0.020000000"})
        self.assertEqual(report["unknown_cost_attempts"], 3)
        self.assertEqual(rows["attempt.units"]["native_units"], units["native_units"])
        self.assertEqual(rows["attempt.units"]["usage_observed_at"], "2099-01-01T00:00:20Z")
        self.assertIsNone(rows["attempt.absent"]["usage_observed_at"])
        csv_rows = {row["attempt_id"]: row for row in csv.DictReader(io.StringIO(api("GET",
            "/reports/usage?dataset_id=" + did + "&export=csv", admin=True)[1]))}
        self.assertEqual({aid: row["usage_state"] for aid, row in csv_rows.items()},
                         {aid: row["usage_state"] for aid, row in rows.items()})
        self.assertEqual(csv_rows["attempt.units"]["usage_observed_at"], "2099-01-01T00:00:20Z")
        self.assertEqual(sum((Decimal(row["amount_decimal"]) for row in csv_rows.values()
                              if row["amount_decimal"]), Decimal(0)), Decimal("0.020000000"))
        exported = api("GET", "/reports/dataset?dataset_id=" + did, admin=True)[1]
        effective = {e["attempt_id"]: e["usage_state"] for e in exported["events"] if e["kind"] == "usage"}
        self.assertEqual(effective, {aid: row["usage_state"] for aid, row in rows.items()
                                     if row["usage_state"] != "not_observed"})

    def test_http_duplicate_conflict_late_revision_and_disabled_account(self):
        self.create()
        base = "/integration/v1/accounts/account.synthetic.01/eligibility?dataset_id=dataset.local.vega.01&model_id=model.synthetic"
        self.assertTrue(self.request("GET", base)[1]["usable"])
        self.assertEqual(self.request("POST", "/integration/v1/datasets", self.dataset)[0], 403)
        events = EXAMPLES["events"]
        # Out-of-order completion and revision 2 retain receipts without cost.
        for item in (events[6], events[5], events[3], events[2], events[0], events[1]):
            self.assertEqual(self.event(item)[0], 201)
        status, report = self.request("GET", "/integration/v1/reports/usage?dataset_id=dataset.local.vega.01", admin=True)
        self.assertEqual(status, 200)
        self.assertEqual(report["attempt_count"], 1)
        self.assertEqual(report["unknown_cost_attempts"], 1)
        self.assertEqual(report["known_total_by_currency"], {})
        self.assertEqual(self.event(events[4])[0], 201)
        status, report = self.request("GET", "/integration/v1/reports/usage?dataset_id=dataset.local.vega.01", admin=True)
        self.assertEqual(report["known_total_by_currency"], {"USD": "0.030000000"})
        self.assertEqual(report["attempts"][0]["result_state"], "unknown")
        self.assertEqual(self.event(events[4])[0], 200)
        self.assertEqual(self.event({**events[4], "usage_state": "known"})[0], 400)  # invalid known shape
        self.assertEqual(self.event({**events[4], "occurred_at": "2026-10-27T00:00:22Z"})[0], 409)
        self.assertEqual(self.request("GET", "/integration/v1/events/event.usage.1.1/receipt?dataset_id=dataset.local.vega.01")[0], 200)
        self.assertEqual(self.request("POST", "/integration/v1/accounts/account.synthetic.01/state",
            {"dataset_id": self.dataset["dataset_id"], "expected_revision": 1, "state": "disabled"}, admin=True)[0], 200)
        self.assertEqual(self.request("GET", base)[1]["reason"], "account_disabled")
        self.assertEqual(self.request("POST", "/integration/v1/accounts", self.account, admin=True)[1]["revision"], 1)
        for item in (events[7], events[8]):
            self.assertEqual(self.event(item)[0], 201)  # late accounting remains allowed
        report = self.request("GET", "/integration/v1/reports/usage?dataset_id=dataset.local.vega.01", admin=True)[1]
        self.assertEqual(report["known_total_by_currency"], {"USD": "0.050000000"})
        self.assertEqual(report["by_root_workflow"]["run.root"]["USD"], "0.050000000")
        self.assertEqual(report["by_run_including_descendants"]["run.child"]["USD"], "0.050000000")
        self.assertEqual(report["attempt_count"], 2)
        csv_data = self.request("GET", "/integration/v1/reports/usage?dataset_id=dataset.local.vega.01&export=csv", admin=True)[1]
        csv_rows = list(csv.DictReader(io.StringIO(csv_data)))
        self.assertEqual(sum((Decimal(row["amount_decimal"]) for row in csv_rows), Decimal(0)), Decimal("0.05"))
        self.assertEqual(len(csv_rows), report["attempt_count"])
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0], 0)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM dev12_submissions").fetchone()[0], 0)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM dev12_send_ownership").fetchone()[0], 0)

    def test_membership_scope_zero_and_noncontiguous_usage(self):
        self.create()
        early = {**EXAMPLES["events"][2], "event_id": "event.early", "attempt_id": "attempt.early",
                 "started_at": "2026-10-26T23:59:59Z", "occurred_at": "2026-10-26T23:59:59Z"}
        self.assertEqual(self.event(early)[1]["membership_at_receipt"], "excluded_before_activation")
        late_usage = {**EXAMPLES["events"][6], "event_id": "event.early.usage",
                      "attempt_id": "attempt.early"}
        self.assertEqual(self.event(late_usage)[0], 201)
        second_only = {**EXAMPLES["events"][6], "event_id": "event.gap.usage",
                       "attempt_id": "attempt.gap"}
        self.assertEqual(self.event(second_only)[0], 201)
        started = {**EXAMPLES["events"][2], "event_id": "event.gap.start", "attempt_id": "attempt.gap"}
        self.assertEqual(self.event(started)[0], 201)
        report = self.request("GET", "/integration/v1/reports/usage?dataset_id=dataset.local.vega.01", admin=True)[1]
        self.assertEqual(report["attempt_count"], 1)
        self.assertEqual(report["known_total_by_currency"], {})
        self.assertEqual(report["unknown_cost_attempts"], 1)
        first = {**EXAMPLES["events"][4], "event_id": "event.gap.first", "attempt_id": "attempt.gap"}
        self.assertEqual(self.event(first)[0], 201)
        report = self.request("GET", "/integration/v1/reports/usage?dataset_id=dataset.local.vega.01", admin=True)[1]
        self.assertEqual(report["known_total_by_currency"], {"USD": "0.030000000"})
        self.assertEqual(self.request("GET", "/integration/v1/reports/usage?dataset_id=dataset.local.vega.01")[0], 404)
        self.assertEqual(self.event({**EXAMPLES["events"][6], "event_id": "event.bad.zero",
            "attempt_id": "attempt.gap", "usage_revision": 3, "amount_decimal": "0"})[0], 400)
        self.assertEqual(self.event({**EXAMPLES["events"][6], "event_id": "event.good.zero",
            "attempt_id": "attempt.gap", "usage_revision": 3, "amount_decimal": "0",
            "zero_basis": "provider.reported.free"})[0], 201)
        report = self.request("GET", "/integration/v1/reports/usage?dataset_id=dataset.local.vega.01", admin=True)[1]
        self.assertEqual(report["known_total_by_currency"], {"USD": "0.000000000"})
        self.assertEqual(report["attempts"][0]["usage_revision"], 3)

    def test_restart_backup_and_concurrent_duplicate(self):
        self.create()
        event = EXAMPLES["events"][2]
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.event(event))) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(status for status, _ in results), [200, 200, 200, 201])
        self.assertEqual(len({reply["event_digest"] for _, reply in results}), 1)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM integration_events").fetchone()[0], 1)
        backup = Path(self.tmp.name) / "backup.sqlite"
        with self.store._lock, sqlite3.connect(backup) as dest:
            self.store.db.backup(dest)
        copy = SQLiteStore(backup)
        self.addCleanup(copy.close)
        restored = Registry(copy, Authority())
        self.assertEqual(restored.integration.receipt(
            restored.principal("svc.integration"), self.dataset["dataset_id"], event["event_id"]),
            results[0][1])
        self.assertEqual(restored.integration.report(restored.principal("owner.local"),
            self.dataset["dataset_id"])["attempt_count"], 1)

    def test_long_usage_history_and_attribution_conflict(self):
        self.create()
        examples = EXAMPLES["events"]
        self.assertEqual(self.event(examples[3])[1]["membership_at_receipt"], "pending_start")
        self.assertEqual(self.event(examples[0])[0], 201)
        self.assertEqual(self.event(examples[1])[0], 201)
        wrong = {**examples[1], "event_id": "event.wrong.parent", "root_run_id": "run.other"}
        self.assertEqual(self.event(wrong)[0], 409)
        self.assertEqual(self.event(examples[2])[0], 201)
        with self.assertRaises(IntegrationError):
            self.registry.integration.append_event(self.registry.principal("svc.demo"), examples[4])
        for revision in range(1, 34):
            item = {**examples[6], "event_id": f"event.long.{revision}",
                    "usage_revision": revision, "amount_decimal": f"0.{revision:09d}"}
            self.assertEqual(self.event(item)[0], 201)
        report = self.request("GET", "/integration/v1/reports/usage?dataset_id=dataset.local.vega.01", admin=True)[1]
        self.assertEqual(report["attempts"][0]["usage_revision"], 33)
        self.assertEqual(report["known_total_by_currency"], {"USD": "0.000000033"})
        self.assertEqual(self.store.db.execute(
            "SELECT COUNT(*) FROM integration_events WHERE kind='usage'").fetchone()[0], 33)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM dev12_usage_revisions").fetchone()[0], 0)

    def test_owner_read_only_reporting_without_administration(self):
        self.create()
        self.registry.mutate("owner.local", {"operation_id": "op.integration.reader.create",
            "action": "create_principal", "subject": "user.integration.reader", "expected_revision": 0,
            "data": {"display_name": "Synthetic reader", "kind": "human",
                     "owner": "owner.local", "role": "ordinary"}})
        _, credential = self.registry.provision_credential(
            "owner.local", "user.integration.reader", 1, "op.integration.reader.credential")
        self.registry.mutate("owner.local", {"operation_id": "op.integration.reader.activate",
            "action": "principal_state", "subject": "user.integration.reader", "expected_revision": 2,
            "data": {"status": "active", "reason": "isolated reporting test"}})
        self.registry.mutate("owner.local", {"operation_id": "op.integration.reader.role",
            "action": "set_role", "subject": "user.integration.reader", "expected_revision": 3,
            "data": {"role": "read_only_operator"}})
        path = "/integration/v1/reports/usage?dataset_id=" + self.dataset["dataset_id"]
        self.assertEqual(self.request("GET", path, token=credential)[0], 200)
        self.assertEqual(self.request("POST", "/integration/v1/accounts", self.account,
                                      token=credential)[0], 404)

    def test_correction_ids_timestamps_and_legacy_missing_outcome(self):
        self.create()
        event = {**EXAMPLES["events"][0], "event_id": "event.TimeZ"}
        self.assertEqual(self.event(event)[0], 201)
        invalid = {**event, "event_id": "event.invalid.time", "occurred_at": "2026-02-30T00:00:00Z"}
        self.assertEqual(self.event(invalid)[0], 400)
        account = {**self.account, "account_id": "account:review:01"}
        self.assertEqual(self.request("POST", "/integration/v1/accounts", account, admin=True)[0], 201)
        self.assertEqual(self.request("GET", "/integration/v1/accounts/account%3Areview%3A01/eligibility"
            "?dataset_id=dataset.local.vega.01&model_id=model.synthetic")[0], 200)
        self.assertEqual(self.request("POST", "/integration/v1/accounts/account%3Areview%3A01/state",
            {"dataset_id": self.dataset["dataset_id"], "expected_revision": 1, "state": "disabled"}, admin=True)[0], 200)
        self.assertEqual(self.request("GET", "/integration/v1/events/event%2ETimeZ/receipt"
            "?dataset_id=dataset.local.vega.01")[0], 200)
        for path in ("/integration/v1/events/event%GG/receipt", "/integration/v1/events/event%2Fbad/receipt",
                     "/integration/v1/events/event%252Fbad/receipt"):
            self.assertEqual(self.request("GET", path + "?dataset_id=dataset.local.vega.01")[0], 400)
        start = EXAMPLES["events"][2]
        self.assertEqual(self.event(start)[0], 201)
        missing = {**EXAMPLES["events"][10], "event_id": "event.legacy.missing.outcome"}
        missing.pop("outcome")
        self.assertEqual(self.event(missing)[0], 201)
        status, report = self.request("GET", "/integration/v1/reports/usage?dataset_id=dataset.local.vega.01", admin=True)
        self.assertEqual(status, 200)
        self.assertEqual(report["attempts"][0]["task_outcome"], "not_observed")
        status, csv_data = self.request("GET", "/integration/v1/reports/usage?dataset_id=dataset.local.vega.01&export=csv", admin=True)
        self.assertEqual(status, 200)
        self.assertEqual(list(csv.DictReader(io.StringIO(csv_data)))[0]["task_outcome"], "not_observed")
        v2_report = self.request("GET", "/integration/v2/reports/usage?dataset_id=dataset.local.vega.01",
                                 admin=True, version="2")[1]
        self.assertEqual(v2_report["attempts"][0]["usage_state"], "legacy_absent")

    @mock.patch("duranki_server.integration_accounting._time", return_value="2099-01-01T00:00:00Z")
    def test_correction_v2_accounting_lineage_snapshots_and_export(self, _clock):
        dataset = {**self.dataset, "dataset_id": "dataset.correction.01"}
        account = {**self.account, "dataset_id": dataset["dataset_id"], "account_id": "account:correct:01"}
        did = dataset["dataset_id"]
        api = lambda method, path, body=None, admin=False: self.request(method, "/integration/v2" + path,
            body, admin=admin, version="2")
        self.assertEqual(api("POST", "/datasets", dataset, True)[0], 201)
        self.assertEqual(api("POST", "/accounts", account, True)[0], 201)
        eligibility = api("GET", "/accounts/account%3Acorrect%3A01/eligibility?dataset_id=" + did +
            "&model_id=model.synthetic")[1]
        self.assertTrue(eligibility["usable"])
        self.assertEqual(api("GET", "/accounts/account%3Acorrect%3A01/eligibility?dataset_id=" + did +
            "&model_id=model.synthetic")[0], 200)
        start = {**EXAMPLES["events"][2], "integration_version": "2", "dataset_id": did,
            "event_id": "event.TimeZ", "attempt_id": "attempt.base", "started_at": "2099-01-01T00:00:10Z",
            "occurred_at": "2099-01-01T00:00:10Z", "run_id": "run.correction", "root_run_id": "run.correction",
            "task_id": "task.correction", "context_ref": "feature.base", "provider_account_id": account["account_id"],
            "operation_family_version": "1", "operation_family": "generation", "model_identity_state": "known",
            "logical_operation_id": "logical.one", "attempt_role": "initial"}
        start.pop("parent_run_id")
        self.assertEqual(api("POST", "/events", start)[0], 201)
        feature = {"integration_version": "2", "snapshot_id": "feature.base", "dataset_id": did,
            "attempt_id": "attempt.base", "snapshot_kind": "feature", "status": "captured", "schema_version": "1",
            "producer_version": "producer.synthetic.1", "provenance": "synthetic", "source_at": "2099-01-01T00:00:01Z",
            "available_at": "2099-01-01T00:00:02Z", "classification": "low",
            "retention_until": "2099-12-31T00:00:00Z", "source_expires_at": "2099-12-31T00:00:00Z",
            "features": {"task_category": "briefing", "modalities": ["text"],
                         "input_size": {"unit": "tokens", "quantity_decimal": "10", "provenance": "estimated"}}}
        self.assertEqual(api("POST", "/snapshots", feature)[0], 201)
        self.assertEqual(api("POST", "/snapshots", feature)[0], 200)
        self.assertEqual(api("GET", "/snapshots/feature.base?dataset_id=" + did)[1]["features"], feature["features"])
        self.assertEqual(api("POST", "/snapshots", {**feature, "snapshot_id": "feature.bad",
            "features": {"raw_prompt": "secret"}})[0], 400)
        decision = {"integration_version": "2", "event_id": "event.decision.base", "dataset_id": did,
            "kind": "decision", "occurred_at": "2099-01-01T00:00:09Z", "attempt_id": "attempt.base",
            "decision_ref": "decision.base", "selected_account_id": account["account_id"],
            "selected_model_id": "model.synthetic", "policy_version": "policy.synthetic",
            "eligibility_evidence": {"status": "verified", "eligibility_id": eligibility["eligibility_id"]}}
        self.assertEqual(api("POST", "/events", decision)[0], 201)
        decision_snapshot = {**feature, "snapshot_id": "decision.base", "snapshot_kind": "decision",
            "available_at": "2099-01-01T00:00:09Z", "selected_action": {key: decision[key] for key in
                ("selected_account_id", "selected_model_id", "policy_version", "eligibility_evidence")}}
        decision_snapshot.pop("features")
        self.assertEqual(api("POST", "/snapshots", decision_snapshot)[0], 201)
        usage = {"integration_version": "2", "event_id": "event.usage.base.1", "dataset_id": did,
            "kind": "usage", "occurred_at": "2099-01-01T00:00:20Z", "attempt_id": "attempt.base",
            "usage_revision": 1, "usage_state": "known", "cost_state": "unknown",
            "native_units": [{"unit": "input_tokens", "quantity_decimal": "10"}],
            "usage_provenance": "provider_reported"}
        self.assertEqual(api("POST", "/events", usage)[0], 201)
        report = api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]
        self.assertEqual(report["attempts"][0]["native_units"], usage["native_units"])
        self.assertEqual(report["unknown_cost_attempts"], 1)
        self.assertIsNone(report["attempts"][0]["amount_decimal"])
        second = {**usage, "event_id": "event.usage.base.2", "usage_revision": 2,
            "cost_state": "known", "currency": "USD", "amount_decimal": "0.020000000",
            "cost_basis": "provider_reported", "price_ref": "tariff.synthetic", "price_version": "v1"}
        self.assertEqual(api("POST", "/events", second)[0], 201)
        self.assertEqual(api("POST", "/events", second)[0], 200)
        self.assertEqual(api("POST", "/events", {**second, "event_id": "event.gap", "usage_revision": 4})[0], 201)
        report = api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]
        self.assertEqual(report["known_total_by_currency"], {"USD": "0.020000000"})
        self.assertEqual(report["attempts"][0]["usage_revision"], 2)
        self.assertEqual(report["attempts"][0]["eligibility_record"]["eligibility_id"], eligibility["eligibility_id"])
        self.assertEqual(report["attempts"][0]["feature_snapshot_status"], "captured")
        self.assertEqual(report["attempts"][0]["decision_snapshot_status"], "captured")
        retry = {**start, "event_id": "event.retry", "attempt_id": "attempt.retry", "context_ref": "feature.retry",
                 "started_at": "2099-01-01T00:00:11Z", "attempt_role": "retry",
                 "predecessor_attempt_id": "attempt.base"}
        self.assertEqual(api("POST", "/events", retry)[0], 201)
        self.assertEqual(api("POST", "/events", {**retry, "event_id": "event.self",
            "attempt_id": "attempt.self", "predecessor_attempt_id": "attempt.self"})[0], 400)
        unresolved = {**start, "event_id": "event.unresolved", "attempt_id": "attempt.unresolved",
            "provider_account_id": "account.unregistered", "model_identity_state": "not_applicable",
            "operation_family": "search", "logical_operation_id": "logical.other", "attempt_role": "fanout",
            "context_ref": "feature.unavailable"}
        unresolved.pop("model_id")
        self.assertEqual(api("POST", "/events", unresolved)[0], 201)
        unpriced = {**usage, "event_id": "event.unresolved.usage", "attempt_id": "attempt.unresolved",
            "usage_state": "unknown", "cost_state": "known", "currency": "USD", "amount_decimal": "0.010000000",
            "cost_basis": "provider_reported", "price_ref": "tariff.synthetic", "price_version": "v1"}
        unpriced.pop("native_units")
        unpriced.pop("usage_provenance")
        self.assertEqual(api("POST", "/events", unpriced)[0], 201)
        report = api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]
        self.assertEqual(report["known_total_by_currency"], {"USD": "0.030000000"})
        self.assertEqual(next(x for x in report["attempts"] if x["attempt_id"] == "attempt.unresolved")
                         ["account_resolution_status"], "unresolved")
        self.assertEqual(next(x for x in report["attempts"] if x["attempt_id"] == "attempt.retry")
                         ["lineage_status"], "linked")
        exported = api("GET", "/reports/dataset?dataset_id=" + did, admin=True)[1]
        self.assertEqual(len(exported["attempts"]), 3)
        self.assertEqual(len(exported["eligibility_reads"]), 1)
        self.assertEqual(len(exported["snapshots"]), 2)
        status, csv_data = api("GET", "/reports/usage?dataset_id=" + did + "&export=csv", admin=True)
        self.assertEqual(status, 200)
        csv_rows = list(csv.DictReader(io.StringIO(csv_data)))
        self.assertEqual(sum((Decimal(x["amount_decimal"]) for x in csv_rows if x["amount_decimal"]), Decimal(0)),
                         Decimal("0.03"))

    @mock.patch("duranki_server.integration_accounting._time", return_value="2099-01-01T00:00:00Z")
    def test_correction_v2_negative_policy_lineage_and_expiry(self, clock):
        did = "dataset.correction.negative"
        dataset = {**self.dataset, "dataset_id": did}
        api = lambda method, path, body=None, admin=False: self.request(method, "/integration/v2" + path,
            body, admin=admin, version="2")
        self.assertEqual(api("POST", "/datasets", dataset, True)[0], 201)
        account = {**self.account, "dataset_id": did, "account_id": "account:negative"}
        self.assertEqual(api("POST", "/accounts", account, True)[0], 201)
        invalid_date = {**EXAMPLES["events"][0], "integration_version": "2", "dataset_id": did,
                        "event_id": "event.invalid.date", "occurred_at": "2099-02-30T00:00:00Z"}
        self.assertEqual(api("POST", "/events", invalid_date)[0], 400)
        missing_outcome = {**invalid_date, "occurred_at": "2099-01-01T00:00:05Z", "activity_kind": "outcome"}
        self.assertEqual(api("POST", "/events", missing_outcome)[0], 400)
        start = {**EXAMPLES["events"][2], "integration_version": "2", "dataset_id": did,
            "event_id": "event.start.base", "attempt_id": "attempt.base", "started_at": "2099-01-01T00:00:10Z",
            "occurred_at": "2099-01-01T00:00:10Z", "run_id": "run.negative", "root_run_id": "run.negative",
            "task_id": "task.negative", "provider_account_id": account["account_id"], "context_ref": "feature.base",
            "operation_family_version": "1", "operation_family": "embedding", "model_identity_state": "known",
            "logical_operation_id": "logical.negative", "attempt_role": "initial"}
        start.pop("parent_run_id")
        self.assertEqual(api("POST", "/events", start)[0], 201)
        for family in ("speech_input", "speech_output", "search", "realtime", "rerank", "other", "unknown"):
            item = {**start, "event_id": "event." + family, "attempt_id": "attempt." + family,
                    "context_ref": "feature." + family, "operation_family": family,
                    "logical_operation_id": "logical." + family, "model_identity_state": "not_applicable",
                    "attempt_role": "fanout"}
            item.pop("model_id")
            self.assertEqual(api("POST", "/events", item)[0], 201)
        zero = {"integration_version": "2", "event_id": "event.zero", "dataset_id": did,
            "kind": "usage", "occurred_at": "2099-01-01T00:00:21Z", "attempt_id": "attempt.rerank",
            "usage_revision": 1, "usage_state": "unknown", "cost_state": "known", "currency": "USD",
            "amount_decimal": "0", "cost_basis": "provider_reported", "price_ref": "tariff.synthetic",
            "price_version": "v1"}
        self.assertEqual(api("POST", "/events", zero)[0], 400)
        self.assertEqual(api("POST", "/events", {**zero, "zero_basis": "provider.reported.free"})[0], 201)
        self.assertEqual(api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]
                         ["known_total_by_currency"], {"USD": "0.000000000"})
        unknown = {**start, "event_id": "event.late", "attempt_id": "attempt.late",
                   "context_ref": "feature.late", "attempt_role": "unknown"}
        self.assertEqual(api("POST", "/events", unknown)[0], 201)
        late_link = {"integration_version": "2", "event_id": "event.link.late", "dataset_id": did,
            "kind": "lineage", "occurred_at": "2099-01-01T00:00:30Z", "attempt_id": "attempt.late",
            "logical_operation_id": "logical.negative", "attempt_role": "retry",
            "predecessor_attempt_id": "attempt.base"}
        self.assertEqual(api("POST", "/events", late_link)[0], 201)
        self.assertEqual(api("POST", "/events", {**late_link, "event_id": "event.duplicate.link"})[0], 409)
        self.assertEqual(api("POST", "/events", {**late_link, "event_id": "event.cross.logical",
            "attempt_id": "attempt.search", "logical_operation_id": "logical.search"})[0], 409)
        pending = {**start, "event_id": "event.pending", "attempt_id": "attempt.pending",
                   "context_ref": "feature.pending", "attempt_role": "retry",
                   "predecessor_attempt_id": "attempt.future"}
        self.assertEqual(api("POST", "/events", pending)[0], 201)
        self.assertEqual(api("POST", "/events", {**pending, "event_id": "event.future",
            "attempt_id": "attempt.future", "predecessor_attempt_id": "attempt.pending"})[0], 400)
        other_dataset = {**dataset, "dataset_id": "dataset.other.owner"}
        self.assertEqual(api("POST", "/datasets", other_dataset, True)[0], 201)
        foreign = {**start, "dataset_id": other_dataset["dataset_id"], "event_id": "event.foreign",
                   "attempt_id": "attempt.foreign", "context_ref": "feature.foreign"}
        self.assertEqual(api("POST", "/events", foreign)[0], 201)
        self.assertEqual(api("POST", "/events", {**pending, "event_id": "event.cross.dataset",
            "attempt_id": "attempt.cross", "predecessor_attempt_id": "attempt.foreign"})[0], 409)
        foreign_account = {**account, "dataset_id": other_dataset["dataset_id"],
                           "account_id": "account.other.dataset"}
        self.assertEqual(api("POST", "/accounts", foreign_account, True)[0], 201)
        foreign_start = {**start, "event_id": "event.foreign.account", "attempt_id": "attempt.foreign.account",
                         "provider_account_id": foreign_account["account_id"],
                         "context_ref": "feature.foreign.account"}
        self.assertEqual(api("POST", "/events", foreign_start)[0], 201)
        self.assertEqual(api("POST", "/events", {"integration_version": "2", "event_id": "event.false.resolve",
            "dataset_id": did, "kind": "account_resolution", "occurred_at": "2099-01-01T00:00:31Z",
            "attempt_id": "attempt.foreign.account", "resolved_account_id": foreign_account["account_id"]})[0], 409)
        with self.assertRaises(IntegrationError):
            self.registry.integration.report({"principal_id": "owner.other", "owner": "owner.other",
                                              "role": "registry_admin"}, did, version="2")
        denied = api("GET", "/accounts/account%3Anegative/eligibility?dataset_id=" + did +
            "&model_id=model.disallowed")[1]
        self.assertEqual(denied["reason"], "model_not_permitted")
        denied_start = {**start, "event_id": "event.denied.start", "attempt_id": "attempt.denied",
            "model_id": "model.disallowed", "context_ref": "feature.denied"}
        self.assertEqual(api("POST", "/events", denied_start)[0], 201)
        denied_decision = {"integration_version": "2", "event_id": "event.denied.decision", "dataset_id": did,
            "kind": "decision", "occurred_at": "2099-01-01T00:00:09Z", "attempt_id": "attempt.denied",
            "decision_ref": "decision.denied", "selected_account_id": account["account_id"],
            "selected_model_id": "model.disallowed", "policy_version": "policy.synthetic",
            "eligibility_evidence": {"status": "denied", "eligibility_id": denied["eligibility_id"]}}
        self.assertEqual(api("POST", "/events", denied_decision)[0], 201)
        self.assertEqual(api("POST", "/events", {**denied_decision, "event_id": "event.forged",
            "attempt_id": "attempt.base", "eligibility_evidence": {"status": "verified",
                "eligibility_id": denied["eligibility_id"]}})[0], 409)
        self.assertEqual(api("POST", "/accounts/account%3Anegative/state",
            {"dataset_id": did, "expected_revision": 1, "state": "disabled"}, True)[0], 200)
        report = api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]
        self.assertEqual(next(x for x in report["attempts"] if x["attempt_id"] == "attempt.denied")
                         ["eligibility_evidence_status"], "denied")
        self.assertEqual(next(x for x in report["attempts"] if x["attempt_id"] == "attempt.pending")
                         ["lineage_status"], "pending_predecessor")
        self.assertEqual(api("GET", "/reports/dataset?dataset_id=" + did)[0], 404)
        feature = {"integration_version": "2", "snapshot_id": "feature.base", "dataset_id": did,
            "attempt_id": "attempt.base", "snapshot_kind": "feature", "status": "captured", "schema_version": "1",
            "producer_version": "producer.synthetic.1", "provenance": "synthetic", "source_at": "2099-01-01T00:00:01Z",
            "available_at": "2099-01-01T00:00:02Z", "classification": "low",
            "retention_until": "2099-01-02T00:00:00Z", "source_expires_at": "2099-01-02T00:00:00Z",
            "features": {"task_category": "briefing"}}
        self.assertEqual(api("POST", "/snapshots", feature)[0], 201)
        self.assertEqual(api("POST", "/snapshots", {**feature, "snapshot_id": "feature.long",
            "retention_until": "2101-01-01T00:00:00Z", "source_expires_at": "2101-01-01T00:00:00Z"})[0], 403)
        self.assertEqual(api("POST", "/snapshots", {**feature, "snapshot_id": "feature.real",
            "provenance": "platform"})[0], 403)
        backup = Path(self.tmp.name) / "before-expiry.sqlite"
        with self.store._lock, sqlite3.connect(backup) as destination:
            self.store.db.backup(destination)
        with mock.patch("duranki_server.integration_accounting._time", return_value="2099-01-03T00:00:00Z"):
            expired = api("GET", "/snapshots/feature.base?dataset_id=" + did)[1]
            self.assertEqual(expired["status"], "expired")
            self.assertNotIn("features", expired)
            self.assertEqual(api("GET", "/reports/usage?dataset_id=" + did, admin=True)[1]
                             ["attempts"][0]["feature_snapshot_status"], "expired")
            copied = SQLiteStore(backup)
            self.addCleanup(copied.close)
            restored = Registry(copied, Authority())
            self.assertEqual(restored.integration.snapshot(restored.principal("owner.local"), did,
                             "feature.base")["status"], "expired")
            self.assertIsNone(copied.db.execute("SELECT content FROM integration_snapshots "
                "WHERE dataset_id=? AND snapshot_id='feature.base'", (did,)).fetchone()[0])


if __name__ == "__main__":
    unittest.main()
