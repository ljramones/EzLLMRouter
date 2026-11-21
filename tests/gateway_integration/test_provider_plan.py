"""DEV-08 selected provider binding through Coordinator and signed plan before target TLS."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[2]


from ezllmrouter_server.canonical import ContractError
from ezllmrouter_server.core import Coordinator, usage_revision
from ezllmrouter_server.plans import PlanAuthority
from ezllmrouter_server.provider_vault import ProviderVault
from ezllmrouter_server.personal_campaign import PersonalCampaign
from ezllmrouter_server.registry import Registry
from ezllmrouter_server.reporting import usage_costs
from ezllmrouter_server.store import SQLiteStore
from ezllmrouter_server.gateway.proxy_recipe import (
    GatewayProxyRecipe,
    proxy_policy,
    public_destination,
)
from tests.gateway_integration.campaign_fixture import campaign_registry
from tools.gateway.evidence.dev08_integrated import TEST_TOKEN, fixture_paths


class Authority:
    def __init__(self):
        self.gate = threading.RLock()
        self.epoch = 0


class Adapter:
    def __init__(self):
        self.sent = []
        self.return_details = False

    @staticmethod
    def prepare(body):
        return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()

    @staticmethod
    def describe(prepared, timeout_ms, destination):
        return {
            "method": "POST",
            "url": "http://127.0.0.1:8767/v1/responses",
            "content_type": "application/json",
            "content_length": len(prepared),
            "body_sha256": hashlib.sha256(prepared).hexdigest(),
            "timeout_ms": timeout_ms,
            "processing_region": destination["processing_region"],
        }

    def send(self, prepared, _timeout_ms, _expected):
        self.sent.append(json.loads(prepared))
        usage = {"input_tokens": 5, "output_tokens": 2, "total_tokens": 7}
        if self.return_details:
            usage.update(
                input_tokens_details={
                    "cached_tokens": 0,
                    "cache_write_tokens": 0,
                    "cache_write_tokens_details": {"ttl_30m_tokens": 0, "ttl_12h_tokens": 0},
                },
                output_tokens_details={"reasoning_tokens": 0},
            )
        return {
            "status": 200,
            "body": {
                "text": "Controlled result.",
                "served_model": "test-response-model",
                "usage": usage,
            },
        }


class ProviderPlanTests(unittest.TestCase):
    def test_responses_nested_usage_categories_are_counted_once(self):
        schedule = {
            "price_version": "rate.test",
            "currency": "USD",
            "usage_semantics_version": "openai.responses.text.v1",
            "unit_denominator": 1000000,
            "rates": {"input_uncached": "1", "output_text": "2"},
        }
        revision = usage_revision(
            "attempt.test",
            {
                "input_tokens": 12,
                "output_tokens": 7,
                "input_tokens_details": {"cached_tokens": 0},
                "output_tokens_details": {"reasoning_tokens": 3},
            },
            decision={
                "price_schedule": schedule,
                "price_version": "rate.test",
                "usage_semantics_version": "openai.responses.text.v1",
                "provider_model": "test-model",
            },
            reported_model="test-model",
        )
        self.assertEqual(revision["normalized_usage"]["output_text"]["count"], 4)
        self.assertEqual(revision["normalized_usage"]["output_reasoning"]["count"], 3)
        self.assertEqual(revision["cost"]["amount_decimal"], "0.000026000")

    def test_exact_provider_deployment_uses_existing_admission_and_signed_plan(self):
        fixture = json.loads((ROOT / "tools/gateway/evidence/dev05_fixture.json").read_text())
        request = json.loads((ROOT / "tests/development_slice/request.json").read_text())
        token = "test-service-provider-token-000000000000000000"
        with tempfile.TemporaryDirectory() as scratch:
            store = SQLiteStore(Path(scratch) / "store.sqlite")
            authority = Authority()
            registry = Registry(
                store,
                authority,
                legacy_destination=public_destination(fixture),
                legacy_token=token,
                legacy_trusted=fixture["trusted_context"],
                provider_vault=ProviderVault(Path(scratch) / "vault"),
                provider_execution_ready=True,
            )
            index = 0

            def change(action, subject, expected, data):
                nonlocal index
                index += 1
                return registry.mutate(
                    "owner.local",
                    {
                        "operation_id": f"op.provider.plan.{index}",
                        "action": action,
                        "subject": subject,
                        "expected_revision": expected,
                        "data": data,
                    },
                )["record"]

            try:
                _configure_provider_plan_route(change, registry, self)
                adapter = Adapter()
                coordinator = Coordinator(
                    store,
                    identity={token: fixture["trusted_context"]},
                    config=public_destination(fixture),
                    prompt_blocks=fixture["prompt_blocks"],
                    allowed_lineages=fixture["allowed_lineages"],
                    authority=PlanAuthority(
                        Ed25519PrivateKey.generate(), proxy_policy(fixture), registry
                    ),
                    adapter=adapter,
                    retention=fixture["retention"],
                    classification=fixture["classification"],
                    recipe=GatewayProxyRecipe(),
                    trusted_source_labels=fixture["trusted_source_labels"],
                    registry=registry,
                )
                try:
                    work = deepcopy(request)
                    work["requested_configuration_ref"] = "cfg.provider.plan"
                    work["step_id"] = "step.provider.plan"
                    caller = coordinator.authenticate(token)
                    with self.assertRaises(ContractError) as denied:
                        coordinator.submit(work, caller, credential=token, wait_ms=3000)
                    self.assertEqual(denied.exception.code, "POLICY_DENIED")
                    self.assertEqual(adapter.sent, [])
                    change(
                        "set_grant",
                        "svc.demo",
                        0,
                        {
                            "configuration_ref": "cfg.provider.plan",
                            "status": "active",
                            "purposes": ["execution"],
                            "task_classes": ["class.demo"],
                        },
                    )
                    with self.assertRaises(ContractError) as no_allowance:
                        coordinator.submit(work, caller, credential=token, wait_ms=3000)
                    self.assertEqual(no_allowance.exception.code, "FINANCIAL_AUTH_REQUIRED")
                    self.assertEqual(adapter.sent, [])
                    registry.controlled_provider_proof = True  # Mock adapter; no external send.
                    status, reply = coordinator.submit(work, caller, credential=token, wait_ms=3000)
                    self.assertEqual(status, 200, reply)
                    self.assertEqual(reply["state"], "delivered")
                    self.assertEqual(adapter.sent[0]["model"], "openai/test-response-model")
                    self.assertEqual(adapter.sent[0]["store"], False)
                    self.assertEqual(
                        store.get(reply["handle"]["submission_id"])["registry_decision"][
                            "price_version"
                        ],
                        "plan.rate.v1",
                    )
                    self.assertEqual(
                        reply["candidate"]["usage"]["revision"]["cost"]["status"], "unknown"
                    )
                    self.assertEqual(
                        registry.deployments("conn.plan")[0]["execution_approved"], True
                    )
                    # The authenticated owner uses the same Coordinator route,
                    # with a server-only short-lived wire credential.
                    _check_personal_provider_campaign(
                        adapter, change, coordinator, registry, self, store, work
                    )
                finally:
                    coordinator.pool.shutdown(wait=True)
            finally:
                store.close()


class ClientCampaignFixtureTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        fixture_path, request_path = fixture_paths()
        self.fixture = json.loads(fixture_path.read_text())
        self.request = json.loads(request_path.read_text())
        self.store, self.authority, self.registry, self.config = self.enterContext(
            campaign_registry(root, self.fixture)
        )

    def test_client_campaign_fixture_settles_through_normal_admission(self):
        fixture = self.fixture
        adapter = Adapter()
        adapter.return_details = True
        coordinator = Coordinator(
            self.store,
            identity={TEST_TOKEN: fixture["trusted_context"]},
            config=public_destination(fixture),
            prompt_blocks=fixture["prompt_blocks"],
            allowed_lineages=fixture["allowed_lineages"],
            authority=PlanAuthority(
                Ed25519PrivateKey.generate(), proxy_policy(fixture), self.registry
            ),
            adapter=adapter,
            retention=fixture["retention"],
            classification=fixture["classification"],
            recipe=GatewayProxyRecipe(controlled_provider_proof=True),
            trusted_source_labels=fixture["trusted_source_labels"],
            registry=self.registry,
        )
        self.addCleanup(coordinator.close)
        self.assertFalse(self.registry.controlled_provider_proof)
        token = self.registry.issue_local_operator_token("owner.local")
        self.request["requested_configuration_ref"] = self.config["configuration_ref"]
        self.request["step_id"] = "step.dev10.js.personal"
        self.request["execution_generation"] = "gen.dev10.js.personal"
        _, reply = coordinator.submit(
            self.request, coordinator.authenticate(token), credential=token, wait_ms=10000
        )
        self.assertEqual(reply["state"], "delivered")
        cost = reply["candidate"]["usage"]["revision"]["cost"]
        self.assertEqual(cost["status"], "calculated")
        self.assertEqual(cost["amount_decimal"], "0.000009000")
        self.assertEqual(cost["source_ref"], "test.dev10.js.price.v2")
        summary = self.registry.personal_campaign.summary()
        self.assertEqual(summary["request_count"], 1)
        self.assertEqual(summary["incurred_decimal"], "0.000009000")
        self.assertEqual(summary["outstanding_decimal"], "0")
        self.assertEqual(len(adapter.sent), 1)

    def test_client_campaign_fixture_rejects_rotated_authority(self):
        campaign = self.registry.personal_campaign
        campaign.transition("owner.local", "paused")
        connection = self.registry.connection("conn.dev08-controlled")
        self.registry.set_provider_credential(
            "owner.local",
            connection["connection_id"],
            connection["revision"],
            "op.dev10.js.rotate",
            "replace",
            "test-provider-key-rotated",
        )
        with self.assertRaisesRegex(ValueError, "campaign authority is stale"):
            campaign.transition("owner.local", "active")


def _configure_provider_plan_route(change, registry, self):
    model = change(
        "register_catalogue",
        "catalogue.operator.plan",
        0,
        {
            "display_name": "Test-only response model",
            "vendor": "Test only",
            "family": "Responses",
            "api_model_id": "test-response-model",
            "model_version": "test-v1",
            "owner": "owner.local",
            "capabilities": ["text"],
            "context_window": None,
            "max_output": None,
            "notes": "Controlled component",
            "price": {
                "snapshot_id": "test.reference.v1",
                "source_title": "Test reference",
                "source_url": "https://example.org/test",
                "bands": [
                    {
                        "label": "Test",
                        "conditions": {},
                        "rates_usd_per_1000000_tokens": {
                            "input_uncached": "1",
                            "output": "2",
                            "input_cached": None,
                        },
                    }
                ],
            },
        },
    )
    change(
        "create_connection",
        "conn.plan",
        0,
        {
            "display_name": "Controlled Responses",
            "adapter_id": "openai.responses.v1",
            "settings": {
                "origin": "https://api.openai.com",
                "location": "commercial",
                "site": "Test scope",
            },
            "owner": "owner.local",
            "funding_kind": "personal_testing",
        },
    )
    registry.set_provider_credential(
        "owner.local",
        "conn.plan",
        1,
        "op.provider.plan.credential",
        "replace",
        "test-provider-key-123456",
    )["record"]
    change(
        "connection_state",
        "conn.plan",
        2,
        {"status": "active", "reason": "Explicit controlled component"},
    )
    change(
        "associate_deployment",
        "conn.plan",
        3,
        {
            "deployment_id": "deployment.plan",
            "model_ref": model["configuration_ref"],
            "serving_id": "test-response-model",
            "site": "Test scope",
            "status": "catalogued",
        },
    )
    config = change(
        "create_provider_configuration",
        "cfg.provider.plan",
        0,
        {
            "display_name": "Controlled Responses route",
            "deployment_id": "deployment.plan",
            "owner": "owner.local",
            "purposes": ["execution"],
            "task_classes": ["class.demo"],
        },
    )
    self.assertEqual(config["destination"]["connection_revision"], 4)
    config = change(
        "publish_price",
        "cfg.provider.plan",
        1,
        {
            "price_version": "plan.rate.v1",
            "currency": "USD",
            "rates": {
                "input_uncached": "1",
                "input_cache_read": "0.1",
                "input_cache_write_30m": "1.25",
                "output_text": "2",
            },
            "source": "operator-approved provider schedule",
            "usage_semantics_version": "openai.responses.text.cache.v2",
            "contract": {
                "version": "openai.responses.implicit-cache.v1",
                "requested_model": "test-response-model",
                "returned_models": ["test-response-model"],
                "cache_mode": "implicit_default_30m",
                "input_token_ceiling": 1000,
                "max_output_tokens": 32,
                "input_bound_basis": "provider_enforced_context_window",
                "temperature_zero_supported": True,
                "price_conditions": "single_tier_no_modifiers",
                "price_source_url": "https://example.test/fictional-rates",
                "observed_on": "2026-10-25",
            },
        },
    )
    change(
        "set_source_permissions",
        "conn.plan",
        0,
        {
            "allowed": True,
            "items": [{"serving_id": "test-response-model", "expected_revision": 0}],
        },
    )
    registry.provider_execution_ready = False
    with self.assertRaisesRegex(ValueError, "execution path not validated"):
        change(
            "model_state",
            "cfg.provider.plan",
            2,
            {"status": "enabled", "reason": "Premature target activation"},
        )
    self.assertEqual(registry.model("cfg.provider.plan")["status"], "draft")
    registry.provider_execution_ready = True
    config = change(
        "model_state",
        "cfg.provider.plan",
        2,
        {"status": "enabled", "reason": "Explicit controlled component"},
    )


def _check_personal_provider_campaign(adapter, change, coordinator, registry, self, store, work):
    change(
        "set_grant",
        "owner.local",
        0,
        {
            "configuration_ref": "cfg.provider.plan",
            "status": "active",
            "purposes": ["execution"],
            "task_classes": ["class.demo"],
        },
    )
    registry.controlled_provider_proof = False
    registry.personal_campaign = PersonalCampaign(store, registry)
    campaign = registry.personal_campaign
    campaign.configure(
        "owner.local",
        {
            "connection_id": "conn.plan",
            "configuration_ref": "cfg.provider.plan",
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
    owner_token = registry.issue_local_operator_token("owner.local")
    owner_work = deepcopy(work)
    owner_work["step_id"] = "step.provider.personal"
    owner_work["execution_generation"] = "gen.provider.personal"
    adapter.return_details = True
    owner_status, owner_reply = coordinator.submit(
        owner_work,
        coordinator.authenticate(owner_token),
        credential=owner_token,
        wait_ms=3000,
    )
    self.assertEqual(owner_status, 200, owner_reply)
    self.assertEqual(
        owner_reply["candidate"]["usage"]["revision"]["cost"]["amount_decimal"],
        "0.000009000",
    )
    self.assertEqual(campaign.summary()["incurred_decimal"], "0.000009000")
    self.assertEqual(campaign.summary()["request_count"], 1)
    report = usage_costs(
        registry,
        {"role": "registry_admin", "principal_id": "owner.local"},
        {"environment": "live_personal_test"},
    )
    self.assertEqual(report["total"]["known_subtotals"], {"USD": "0.000009"})
    self.assertEqual(report["attempts"][0]["charging_owner_id"], "owner.local")
    self.assertEqual(report["attempts"][0]["initiating_user_id"], "owner.local")
    self.assertEqual(report["attempts"][0]["agent_id"], "__direct_human__")
    with self.assertRaises(ContractError):
        coordinator.submit(
            {**owner_work, "step_id": "step.provider.personal.2"},
            coordinator.authenticate(owner_token),
            credential=owner_token,
            wait_ms=3000,
        )
    self.assertEqual(len(adapter.sent), 2)
    registry.revoke_local_operator_token(owner_token)
    change(
        "connection_state",
        "conn.plan",
        4,
        {"status": "disabled", "reason": "Test queued revocation"},
    )
    self.assertEqual(
        registry.readiness(registry.model("cfg.provider.plan")),
        "provider_connection_stale",
    )


if __name__ == "__main__":
    unittest.main()
