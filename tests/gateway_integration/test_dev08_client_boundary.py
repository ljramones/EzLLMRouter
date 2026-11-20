"""Exercise the DEV-08 disposable registry through the unchanged installed-client wire."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import threading
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/src"))
sys.path.insert(
    0, os.environ.get("EZLLMROUTER_TEST_CLIENT_WHEEL", str(ROOT / "clients/python/src"))
)
sys.path.insert(0, str(ROOT / "tests/gateway_integration"))

from ezllmrouter_client import EzLLMRouterClient, _validation as validation
from ezllmrouter_server.core import Coordinator
from ezllmrouter_server.plans import PlanAuthority
from ezllmrouter_server.web import serve
from ezllmrouter_server.provider_vault import ProviderVault
from ezllmrouter_server.personal_campaign import PersonalCampaign
from ezllmrouter_server.registry import Registry
from ezllmrouter_server.canonical import ContractError
from dev08_integrated import TEST_TOKEN, certificate, fixture_paths, prepare_registry
from ezllmrouter_server.gateway.proxy_recipe import (
    GatewayProxyRecipe,
    proxy_policy,
    public_destination,
)
from test_provider_plan import Adapter


class ClientBoundaryTests(unittest.TestCase):
    def test_commonjs_client_uses_campaign_on_normal_wire(self):
        fixture_path, request_path = fixture_paths()
        fixture = json.loads(fixture_path.read_text())
        request = json.loads(request_path.read_text())
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            cert, _ = certificate(root)
            store, authority, registry, config = prepare_registry(
                root,
                fixture,
                "https://localhost:8766",
                cert.read_text(),
                funding_kind="personal_testing",
            )
            adapter = Adapter()
            adapter.return_details = True
            registry.controlled_provider_proof = False
            registry.mutate(
                "owner.local",
                {
                    "operation_id": "op.dev10.js.grant",
                    "action": "set_grant",
                    "subject": "owner.local",
                    "expected_revision": 0,
                    "data": {
                        "configuration_ref": config["configuration_ref"],
                        "status": "active",
                        "purposes": ["execution"],
                        "task_classes": ["class.demo"],
                    },
                },
            )
            campaign = PersonalCampaign(store, registry)
            registry.personal_campaign = campaign
            campaign.configure(
                "owner.local",
                {
                    "connection_id": "conn.dev08-controlled",
                    "configuration_ref": config["configuration_ref"],
                    "principal_id": "owner.local",
                    "currency": "USD",
                    "allowance_decimal": "0.02",
                    "per_request_decimal": "0.01",
                    "max_requests": 1,
                    "max_input_bytes": 4096,
                    "max_output_tokens": 32,
                    "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1))
                    .isoformat()
                    .replace("+00:00", "Z"),
                },
            )
            campaign.transition("owner.local", "active")
            token = registry.issue_local_operator_token("owner.local")
            coordinator = Coordinator(
                store,
                {TEST_TOKEN: fixture["trusted_context"]},
                public_destination(fixture),
                fixture["prompt_blocks"],
                fixture["allowed_lineages"],
                PlanAuthority(Ed25519PrivateKey.generate(), proxy_policy(fixture), registry),
                adapter,
                fixture["retention"],
                fixture["classification"],
                GatewayProxyRecipe(controlled_provider_proof=True),
                trusted_source_labels=fixture["trusted_source_labels"],
                registry=registry,
            )
            wire = serve("127.0.0.1", 0, coordinator)
            try:
                threading.Thread(target=wire.serve_forever, daemon=True).start()
                request["requested_configuration_ref"] = config["configuration_ref"]
                request["step_id"] = "step.dev10.js.personal"
                request["execution_generation"] = "gen.dev10.js.personal"
                script = """const {EzLLMRouterClient}=require(process.argv[1]);
                    let input='';process.stdin.on('data',x=>input+=x);
                    process.stdin.on('end',async()=>{const v=JSON.parse(input);
                      const c=new EzLLMRouterClient({baseUrl:v.url,token:v.token});
                      try{const r=await c.submit(v.request,{wait_ms:10000});
                        process.stdout.write(JSON.stringify({state:r.state,cost:r.candidate.usage.revision.cost}));}
                      catch(e){process.stderr.write(e.code||String(e));process.exitCode=1;}});"""
                result = subprocess.run(
                    ["node", "-e", script, str(ROOT / "clients/js/index.cjs")],
                    input=json.dumps(
                        {
                            "url": "http://127.0.0.1:" + str(wire.server_port),
                            "token": token,
                            "request": request,
                        }
                    ),
                    text=True,
                    capture_output=True,
                    timeout=20,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                answer = json.loads(result.stdout)
                self.assertEqual(answer["state"], "delivered")
                self.assertEqual(answer["cost"]["amount_decimal"], "0.000009000")
                self.assertEqual(campaign.summary()["request_count"], 1)
                self.assertEqual(len(adapter.sent), 1)
            finally:
                wire.shutdown()
                wire.server_close()
                coordinator.pool.shutdown(wait=True)
                store.close()

    def test_source_permission_is_exact_and_revokes_queued_plan(self):
        fixture = json.loads(fixture_paths()[0].read_text())
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            cert, _ = certificate(root)
            store, authority, registry, config = prepare_registry(
                root, fixture, "https://localhost:8766", cert.read_text()
            )
            try:
                ref = config["configuration_ref"]
                _, decision = registry.admit("svc.demo", ref, "execution", "class.demo")
                self.assertTrue(
                    registry.source_model_allowed("conn.dev08-controlled", "test-response-model")
                )
                new = registry.mutate(
                    "owner.local",
                    {
                        "operation_id": "op.source.second",
                        "action": "create_connection",
                        "subject": "conn.same-model-other-source",
                        "expected_revision": 0,
                        "data": {
                            "display_name": "Separate source",
                            "adapter_id": "openai.responses.v1",
                            "settings": {
                                "origin": "https://localhost:8766",
                                "location": "commercial",
                                "site": "Another account",
                                "ca_pem": cert.read_text(),
                            },
                            "owner": "owner.local",
                        },
                    },
                )
                self.assertEqual(new["record"]["status"], "draft")
                registry.mutate(
                    "owner.local",
                    {
                        "operation_id": "op.source.second.associate",
                        "action": "associate_deployment",
                        "subject": "conn.same-model-other-source",
                        "expected_revision": 1,
                        "data": {
                            "deployment_id": "deployment.second-source",
                            "model_ref": "catalogue.operator.dev08-controlled",
                            "serving_id": "test-response-model",
                            "site": "Another account",
                            "status": "catalogued",
                        },
                    },
                )
                self.assertFalse(
                    registry.source_model_allowed(
                        "conn.same-model-other-source", "test-response-model"
                    )
                )
                with self.assertRaises(PermissionError):
                    registry.mutate(
                        "svc.demo",
                        {
                            "operation_id": "op.source.unauthorized",
                            "action": "set_source_permissions",
                            "subject": "conn.dev08-controlled",
                            "expected_revision": 0,
                            "data": {
                                "allowed": False,
                                "items": [
                                    {"serving_id": "test-response-model", "expected_revision": 1}
                                ],
                            },
                        },
                    )
                first = registry.mutate(
                    "owner.local",
                    {
                        "operation_id": "op.source.disallow",
                        "action": "set_source_permissions",
                        "subject": "conn.dev08-controlled",
                        "expected_revision": 0,
                        "data": {
                            "allowed": False,
                            "items": [
                                {"serving_id": "test-response-model", "expected_revision": 1}
                            ],
                        },
                    },
                )
                self.assertEqual(first["record"]["items"][0]["revision"], 2)
                self.assertEqual(
                    registry.explain("svc.demo", ref, "execution", "class.demo")["reason"],
                    "SOURCE_MODEL_DISALLOWED",
                )
                with self.assertRaisesRegex(ValueError, "source model disallowed"):
                    registry.mutate(
                        "owner.local",
                        {
                            "operation_id": "op.source.denied.grant",
                            "action": "set_grant",
                            "subject": "svc.demo",
                            "expected_revision": 1,
                            "data": {
                                "configuration_ref": ref,
                                "status": "active",
                                "purposes": ["execution"],
                                "task_classes": ["class.demo"],
                            },
                        },
                    )
                with self.assertRaises(ContractError):
                    registry.check_current("svc.demo", ref, "execution", "class.demo", decision)
                registry.mutate(
                    "owner.local",
                    {
                        "operation_id": "op.source.allow.other",
                        "action": "set_source_permissions",
                        "subject": "conn.same-model-other-source",
                        "expected_revision": 0,
                        "data": {
                            "allowed": True,
                            "items": [
                                {"serving_id": "test-response-model", "expected_revision": 0}
                            ],
                        },
                    },
                )
                self.assertTrue(
                    registry.source_model_allowed(
                        "conn.same-model-other-source", "test-response-model"
                    )
                )
                self.assertFalse(
                    registry.source_model_allowed("conn.dev08-controlled", "test-response-model")
                )
                reopened = Registry(
                    store,
                    authority,
                    provider_vault=ProviderVault(root / "vault"),
                    provider_execution_ready=True,
                    controlled_provider_proof=True,
                )
                self.assertFalse(
                    reopened.source_model_allowed("conn.dev08-controlled", "test-response-model")
                )
                self.assertEqual(
                    reopened.source_inventory("conn.dev08-controlled")["items"][0]["allowed"], False
                )
                self.assertEqual(
                    store.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0], 0
                )
            finally:
                store.close()

    def test_real_wire_with_controlled_provider_fixture(self):
        fixture_path, request_path = fixture_paths()
        fixture = json.loads(fixture_path.read_text())
        request = json.loads(request_path.read_text())
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            cert, _ = certificate(root)
            store, authority, registry, config = prepare_registry(
                root, fixture, "https://localhost:8766", cert.read_text()
            )
            adapter = Adapter()
            adapter.return_details = True
            coordinator = Coordinator(
                store,
                {TEST_TOKEN: fixture["trusted_context"]},
                public_destination(fixture),
                fixture["prompt_blocks"],
                fixture["allowed_lineages"],
                PlanAuthority(Ed25519PrivateKey.generate(), proxy_policy(fixture), registry),
                adapter,
                fixture["retention"],
                fixture["classification"],
                GatewayProxyRecipe(controlled_provider_proof=True),
                trusted_source_labels=fixture["trusted_source_labels"],
                registry=registry,
            )
            wire = serve("127.0.0.1", 0, coordinator)
            try:
                thread = threading.Thread(target=wire.serve_forever, daemon=True)
                thread.start()
                request["requested_configuration_ref"] = config["configuration_ref"]
                request["step_id"] = "step.dev08.integrated"
                request["execution_generation"] = "gen.dev08.integrated"
                request["generation_settings"]["total_timeout_ms"] = 10000
                with EzLLMRouterClient(
                    "http://127.0.0.1:" + str(wire.server_port), TEST_TOKEN
                ) as client:
                    reply = client.submit(request, {"wait_ms": 10000})
                    self.assertEqual(reply["state"], "delivered")
                    served = reply["candidate"]["served_destination"]
                    self.assertTrue(validation.destination(served))
                    self.assertEqual(served["endpoint"], "deployment.dev08-controlled")
                    self.assertEqual(served["processing_region"].split(".", 1)[0], "site")
                    self.assertNotIn("https://localhost", json.dumps(served))
                    self.assertNotIn("connection_id", served)
                    status = client.getStatus({"submission_id": reply["handle"]["submission_id"]})
                    self.assertEqual(status["submission_state"], "completed")
                    self.assertEqual(status["candidate"]["served_destination"], served)
                    self.assertEqual(
                        reply["candidate"]["usage"]["revision"]["cost"]["status"], "calculated"
                    )
                    self.assertEqual(
                        reply["candidate"]["usage"]["revision"]["cost"]["amount_decimal"],
                        "0.000009000",
                    )
                intent = json.loads(
                    store.db.execute(
                        "SELECT intent FROM intents WHERE submission_id=?",
                        (reply["handle"]["submission_id"],),
                    ).fetchone()[0]
                )
                self.assertEqual(intent["destination"]["endpoint"], "https://localhost:8766")
                self.assertEqual(intent["destination"]["connection_id"], "conn.dev08-controlled")
                self.assertEqual(len(adapter.sent), 1)
            finally:
                wire.shutdown()
                wire.server_close()
                coordinator.pool.shutdown(wait=True)
                store.close()


if __name__ == "__main__":
    unittest.main()
