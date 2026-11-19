"""Trusted run, delegation and outcome authority in a disposable registry."""
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from ezllmrouter_server.canonical import ContractError
from ezllmrouter_server.registry import Registry, RegistryConflict
from ezllmrouter_server.store import SQLiteStore


DEST = {"configuration_ref": "cfg.demo", "service": "litellm.dev04", "endpoint": "127.0.0.1",
        "model": "model.demo", "model_version": "v1", "processing_region": "local"}
TRUSTED = {"principal_id": "svc.demo", "charging_owner_id": "team.demo"}


class Authority:
    def __init__(self):
        self.gate = threading.RLock()
        self.epoch = 0


class AttributionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = SQLiteStore(Path(temp.name) / "metadata.sqlite")
        self.addCleanup(self.store.close)
        self.registry = Registry(self.store, Authority(), legacy_destination=DEST,
            legacy_token="synthetic-service-token-for-agent-tests-000000", legacy_trusted=TRUSTED)
        self.ledger = self.registry.attribution
        self.change("create_principal", "user.test", 0, {"display_name": "Synthetic user",
            "kind": "human", "owner": "team.demo", "role": "ordinary"})
        self.registry.provision_credential("owner.local", "user.test", 1, "op.user.test.credential")
        self.change("principal_state", "user.test", 2, {"status": "active", "reason": "Test activation"})
        self.change("set_grant", "user.test", 0, {"configuration_ref": "cfg.demo", "status": "active",
            "purposes": ["execution"], "task_classes": ["class.demo"]})
        for agent in ("agent.alpha", "agent.beta", "agent.idle"):
            self.change("register_agent", agent, 0, {"display_name": agent,
                "owner": "team.demo", "versions": ["v1"]})
        for index, agent in enumerate(("agent.alpha", "agent.beta")):
            for user in (None, "user.test"):
                data = {"caller_principal_id": "svc.demo", "agent_id": agent,
                    "charging_owner_id": "team.demo", "task_classes": ["class.demo"], "status": "active"}
                if user:
                    data["initiating_user_id"] = user
                self.change("set_agent_permission", f"permission.{index}.{'user' if user else 'autonomous'}", 0, data)

    def change(self, action, subject, revision, data):
        self.registry.mutate("owner.local", {"operation_id": f"op.{action}.{subject}.{revision}",
            "action": action, "subject": subject, "expected_revision": revision, "data": data})

    def start(self, run_id, mode, **fields):
        return self.ledger.start_run(TRUSTED, {"version": "1", "run_id": run_id, "task_id": "task.demo",
            "task_class": "class.demo", "evaluation_ref": "rubric.synthetic.v1", "mode": mode, **fields})

    def test_direct_delegated_nested_and_immutable_scope(self):
        direct = self.ledger.start_run({"principal_id": "user.test", "charging_owner_id": "team.demo"},
            {"version": "1", "run_id": "run.direct", "task_id": "task.demo", "task_class": "class.demo",
             "evaluation_ref": "rubric.synthetic.v1", "mode": "direct_human"})
        self.assertEqual(direct["initiating_user_id"], "user.test")
        root = self.start("run.root", "user_delegated_agent", agent_id="agent.alpha",
            agent_version="v1", initiating_user_id="user.test")
        child = self.start("run.child", "nested_agent", agent_id="agent.beta", agent_version="v1",
            parent_run_id="run.root")
        repeated = self.start("run.repeated", "nested_agent", agent_id="agent.alpha", agent_version="v1",
            parent_run_id="run.child")
        self.assertEqual(repeated["root_run_id"], root["run_id"])
        self.assertEqual(child["initiating_user_id"], "user.test")
        request = {"task_id": "task.demo", "task_class": "class.demo",
            "requested_configuration_ref": "cfg.demo", "purpose": "execution", "requested_features": ["text"]}
        self.assertEqual(self.ledger.bind(TRUSTED, request, "run.child")["agent_id"], "agent.beta")
        with self.assertRaises(ContractError):
            self.ledger.bind({"principal_id": "svc.demo", "charging_owner_id": "other.team"}, request, "run.child")
        with self.assertRaises(ContractError):
            self.start("run.forged", "user_delegated_agent", agent_id="agent.alpha",
                agent_version="v1", initiating_user_id="owner.local")
        with self.assertRaises(ContractError):
            self.start("run.bad-parent", "nested_agent", agent_id="agent.beta", agent_version="v1",
                parent_run_id="run.bad-parent")
        with self.assertRaises(ContractError):
            self.start("run.root", "autonomous_agent", agent_id="agent.alpha", agent_version="v1")
        self.assertEqual(len(self.ledger.agents()), 3)
        with self.assertRaises(RegistryConflict):
            self.change("set_agent_permission", "permission.duplicate", 0, {
                "caller_principal_id": "svc.demo", "agent_id": "agent.alpha",
                "charging_owner_id": "team.demo", "task_classes": ["class.demo"], "status": "active"})

    def test_outcome_authority_revision_replay_and_read_only_receipt(self):
        run = self.start("run.outcome", "autonomous_agent", agent_id="agent.alpha", agent_version="v1")
        event = {"version": "1", "event_id": "event.accepted", "run_id": run["run_id"],
            "kind": "task_outcome", "subject_revision": 1, "verdict": "accepted",
            "evaluator_version": "rubric.v1", "evidence_ref": "evidence.synthetic"}
        with self.assertRaises(ContractError):
            self.ledger.append_outcome(TRUSTED, event)
        self.change("set_outcome_authority", "svc.demo", 0,
            {"status": "active", "task_classes": ["class.demo"]})
        receipt = self.ledger.append_outcome(TRUSTED, event)
        self.assertEqual(self.ledger.append_outcome(TRUSTED, event), receipt)
        self.assertEqual(self.ledger.outcome_receipt(TRUSTED, "event.accepted"), receipt)
        with self.assertRaises(ContractError) as conflict:
            self.ledger.append_outcome(TRUSTED, {**event, "verdict": "rejected"})
        self.assertEqual(conflict.exception.code, "EVENT_CONFLICT")
        with self.assertRaises(ContractError) as stale:
            self.ledger.append_outcome(TRUSTED, {**event, "event_id": "event.stale"})
        self.assertEqual(stale.exception.code, "STALE_REVISION")
        revised = self.ledger.append_outcome(TRUSTED,
            {**event, "event_id": "event.revised", "subject_revision": 2, "verdict": "rejected"})
        self.assertEqual(revised["subject_revision"], 2)
        self.assertEqual(self.ledger.run("run.outcome")["status"], "rejected")
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0], 0)

    def test_disposable_backup_migration_and_reopen_preserves_authority(self):
        run = self.start("run.backup", "autonomous_agent", agent_id="agent.alpha", agent_version="v1")
        self.change("set_outcome_authority", "svc.demo", 0,
            {"status": "active", "task_classes": ["class.demo"]})
        event = {"version": "1", "event_id": "event.backup", "run_id": run["run_id"],
            "kind": "task_outcome", "subject_revision": 1, "verdict": "rejected",
            "evaluator_version": "rubric.synthetic.v1", "evidence_ref": "evidence.backup"}
        receipt = self.ledger.append_outcome(TRUSTED, event)
        copy = Path(self.store.path).parent / "consistent-backup.sqlite"
        with self.store._lock, sqlite3.connect(copy) as target:
            self.store.db.backup(target)
        reopened = SQLiteStore(copy)
        self.addCleanup(reopened.close)
        migrated = Registry(reopened, Authority())
        self.assertEqual(migrated.attribution.run("run.backup"), self.ledger.run("run.backup"))
        self.assertEqual(migrated.attribution.outcome_receipt(TRUSTED, "event.backup"), receipt)
        self.assertEqual(migrated.attribution.permission("svc.demo", "agent.alpha", None)["status"], "active")
        self.assertEqual(migrated.attribution.agent("agent.idle")["instrumentation_status"], "not_instrumented")
        migrated.mutate("owner.local", {"operation_id": "op.disposable.revoke", "action": "agent_state",
            "subject": "agent.alpha", "expected_revision": 1,
            "data": {"status": "archived", "reason": "Disposable backup only"}})
        self.assertEqual(migrated.attribution.agent("agent.alpha")["status"], "archived")
        self.assertEqual(self.ledger.agent("agent.alpha")["status"], "active")


if __name__ == "__main__":
    unittest.main()
