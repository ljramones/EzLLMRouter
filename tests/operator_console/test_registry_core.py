"""Real Coordinator admission with persistent registry and controlled lower I/O.

Plan signing and the owned socket require the frozen target container and are
covered separately; this component test does not claim that target proof.
"""

from copy import deepcopy
import hashlib
import json
from importlib.resources import files
from pathlib import Path
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]


from ezllmrouter_server.canonical import ContractError
from ezllmrouter_server.core import Coordinator
from ezllmrouter_server.registry import Registry
from ezllmrouter_server.store import SQLiteStore
from ezllmrouter_server.gateway.synthetic_recipe import SyntheticTextRecipe

FIXTURE = json.loads(files("tools.gateway.evidence").joinpath("dev05_fixture.json").read_text())
REQUEST = json.loads((ROOT / "tests/development_slice/request.json").read_text())
TOKEN = "synthetic-dev07-coordinator-token-000000000000000000"


class SendAuthority:
    def __init__(self):
        self.gate = threading.RLock()
        self.epoch = 0


class PlanAuthority:
    policy = {
        "policy_version": "policy.dev01",
        "currency": "USD",
        "max_attempt_charge_decimal": "0.1",
    }

    def __init__(self, registry):
        self.registry = registry

    def issue(self, projection, digest, key, classification, retention, decision_record_ref=None):
        return {
            "plan_id": "plan.component",
            "work_digest": digest,
            "work_key": deepcopy(key),
            "destination": deepcopy(projection["destination"]),
            "classification_snapshot": deepcopy(classification),
            "effective_retention": deepcopy(retention),
            "deadline": projection["work"]["deadline"],
            "per_attempt_total_timeout_ms": projection["work"]["generation_settings"][
                "total_timeout_ms"
            ],
            "registry_version": "registry.local." + str(self.registry.version()),
            "decision_record_ref": decision_record_ref,
            "configuration_ref": projection["destination"]["configuration_ref"],
            "purpose": projection["work"]["purpose"],
            "task_class": projection["work"]["task_class"],
        }

    def verify(self, plan, digest, policy):
        if (
            plan["work_digest"] != digest
            or policy != self.policy["policy_version"]
            or plan["registry_version"] != "registry.local." + str(self.registry.version())
        ):
            raise ContractError("PLAN_INVALID_OR_STALE", 409)


class Adapter:
    def __init__(self):
        self.sent = []

    def prepare(self, body):
        return json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()

    def describe(self, prepared, timeout_ms, destination):
        return {
            "method": "POST",
            "url": "http://127.0.0.1:8766/v1/chat/completions",
            "content_type": "application/json",
            "content_length": len(prepared),
            "body_sha256": hashlib.sha256(prepared).hexdigest(),
            "timeout_ms": timeout_ms,
            "processing_region": destination["processing_region"],
        }

    def send(self, prepared, _timeout_ms, _expected):
        self.sent.append(json.loads(prepared))
        return {
            "status": 200,
            "body": {"text": "Hello.", "usage": {"input_tokens": 1000, "output_tokens": 100}},
        }


class RegistryCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = SQLiteStore(Path(self.tmp.name) / "store.sqlite")
        self.addCleanup(self.store.close)
        self.registry = Registry(
            self.store,
            SendAuthority(),
            legacy_destination={
                **FIXTURE["destination"],
                "service": "litellm.dev04",
                "endpoint": "127.0.0.1",
            },
            legacy_token=TOKEN,
            legacy_trusted=FIXTURE["trusted_context"],
        )
        self.adapter = Adapter()
        self.coordinator = Coordinator(
            self.store,
            {TOKEN: FIXTURE["trusted_context"]},
            FIXTURE["destination"],
            FIXTURE["prompt_blocks"],
            FIXTURE["allowed_lineages"],
            PlanAuthority(self.registry),
            self.adapter,
            FIXTURE["retention"],
            FIXTURE["classification"],
            SyntheticTextRecipe("127.0.0.1", 8766),
            trusted_source_labels=FIXTURE["trusted_source_labels"],
            registry=self.registry,
        )
        self.addCleanup(self.coordinator.pool.shutdown, wait=True)

    def change(self, index, action, subject, revision, data):
        return self.registry.mutate(
            "owner.local",
            {
                "operation_id": "op.component." + str(index),
                "action": action,
                "subject": subject,
                "expected_revision": revision,
                "data": data,
            },
        )

    def test_admission_uses_exact_registered_configuration_and_grant(self):
        self.change(
            1,
            "create_model",
            "cfg.alt",
            0,
            {
                "display_name": "Alternate",
                "model": "model.demo.alt",
                "model_version": "v1",
                "owner": "owner.local",
                "capabilities": ["text"],
                "purposes": ["execution"],
                "task_classes": ["class.demo"],
            },
        )
        self.change(
            2,
            "publish_price",
            "cfg.alt",
            1,
            {
                "price_version": "alt.v1",
                "currency": "USD",
                "rates": {"input_uncached": "2", "output_text": "8"},
                "source": "synthetic fixture",
                "usage_semantics_version": "synthetic.text.v1",
            },
        )
        self.change(
            3, "model_state", "cfg.alt", 2, {"status": "enabled", "reason": "Component test"}
        )
        self.change(
            4,
            "create_principal",
            "svc.alt",
            0,
            {"display_name": "Alternate caller", "kind": "service", "owner": "team.alt"},
        )
        _, secret = self.registry.provision_credential(
            "owner.local", "svc.alt", 1, "op.component.provision"
        )
        self.change(
            5, "principal_state", "svc.alt", 2, {"status": "active", "reason": "Component test"}
        )
        trusted = self.coordinator.authenticate(secret)
        denied = deepcopy(REQUEST)
        denied["requested_configuration_ref"] = "cfg.alt"
        with self.assertRaises(ContractError) as exc:
            self.coordinator.submit(denied, trusted, credential=secret)
        self.assertEqual(exc.exception.code, "POLICY_DENIED")
        self.assertEqual(self.adapter.sent, [])
        self.change(
            6,
            "set_grant",
            "svc.alt",
            0,
            {
                "configuration_ref": "cfg.alt",
                "status": "active",
                "purposes": ["execution"],
                "task_classes": ["class.demo"],
            },
        )
        status, reply = self.coordinator.submit(denied, trusted, wait_ms=3000, credential=secret)
        self.assertEqual(status, 200)
        self.assertEqual(reply["candidate"]["served_destination"]["model"], "model.demo.alt")
        self.assertEqual(
            reply["candidate"]["usage"]["revision"]["cost"]["amount_decimal"], "0.0028"
        )
        self.assertEqual(len(self.adapter.sent), 1)
        self.assertEqual(self.adapter.sent[0]["model"], "model.demo.alt")
        self.assertEqual(
            self.store.get(reply["handle"]["submission_id"])["registry_decision"]["price_version"],
            "alt.v1",
        )
        # The same credential cannot borrow the pre-existing demo grant.
        other = deepcopy(REQUEST)
        other["execution_generation"] = "gen.alt.other"
        with self.assertRaises(ContractError):
            self.coordinator.submit(other, trusted, credential=secret)
        self.assertEqual(len(self.adapter.sent), 1)

    def test_attributed_run_binds_signed_decision_and_rejects_reassignment(self):
        self.change(
            30,
            "register_agent",
            "agent.component",
            0,
            {"display_name": "Synthetic component agent", "owner": "team.demo", "versions": ["v1"]},
        )
        self.change(
            31,
            "set_agent_permission",
            "permission.component",
            0,
            {
                "caller_principal_id": "svc.demo",
                "agent_id": "agent.component",
                "charging_owner_id": "team.demo",
                "task_classes": ["class.demo"],
                "status": "active",
            },
        )
        request = deepcopy(REQUEST)
        run = {
            "version": "1",
            "run_id": "run.component",
            "task_id": request["task_id"],
            "task_class": request["task_class"],
            "evaluation_ref": "rubric.synthetic.v1",
            "mode": "autonomous_agent",
            "agent_id": "agent.component",
            "agent_version": "v1",
        }
        self.registry.attribution.start_run(FIXTURE["trusted_context"], run)
        status, reply = self.coordinator.submit(
            request,
            FIXTURE["trusted_context"],
            wait_ms=3000,
            credential=TOKEN,
            run_id="run.component",
        )
        self.assertEqual(status, 200)
        saved = self.store.get(reply["handle"]["submission_id"])
        self.assertEqual(saved["attribution"]["agent_id"], "agent.component")
        self.assertEqual(len(saved["attribution_digest"]), 64)
        self.assertEqual(
            self.store.guard_record(saved["attempt_id"]), None
        )  # Component adapter has no guard.
        intent = self.store.db.execute(
            "SELECT intent FROM intents WHERE attempt_id=?", (saved["attempt_id"],)
        ).fetchone()
        self.assertEqual(json.loads(intent[0])["attribution_digest"], saved["attribution_digest"])
        other = {**run, "run_id": "run.reassigned"}
        self.registry.attribution.start_run(FIXTURE["trusted_context"], other)
        with self.assertRaises(ContractError) as reassigned:
            self.coordinator.submit(
                request, FIXTURE["trusted_context"], credential=TOKEN, run_id="run.reassigned"
            )
        self.assertEqual(reassigned.exception.code, "WORK_CONFLICT")
        self.change(
            32,
            "set_agent_permission",
            "permission.component",
            1,
            {
                "caller_principal_id": "svc.demo",
                "agent_id": "agent.component",
                "charging_owner_id": "team.demo",
                "task_classes": ["class.demo"],
                "status": "revoked",
            },
        )
        later = deepcopy(request)
        later["execution_generation"] = "gen.attribution.later"
        with self.assertRaises(ContractError) as revoked:
            self.coordinator.submit(
                later, FIXTURE["trusted_context"], credential=TOKEN, run_id="run.component"
            )
        self.assertEqual(revoked.exception.code, "POLICY_DENIED")
        self.assertEqual(len(self.adapter.sent), 1)


if __name__ == "__main__":
    unittest.main()
