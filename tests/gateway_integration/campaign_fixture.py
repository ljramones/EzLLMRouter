"""Current personal allowance layered onto the retained controlled TLS fixture."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from ezllmrouter_server.personal_campaign import PersonalCampaign
from tools.gateway.evidence.dev08_integrated import certificate, prepare_registry


@contextmanager
def campaign_registry(root, fixture):
    cert, _ = certificate(root)
    store, authority, registry, config = prepare_registry(
        root,
        fixture,
        "https://localhost:8766",
        cert.read_text(),
        funding_kind="personal_testing",
    )
    try:
        ref = config["configuration_ref"]
        registry.mutate(
            "owner.local",
            {
                "operation_id": "op.dev10.js.price",
                "action": "publish_price",
                "subject": ref,
                "expected_revision": config["revision"],
                "data": {
                    "price_version": "test.dev10.js.price.v2",
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
            },
        )
        registry.controlled_provider_proof = False
        registry.mutate(
            "owner.local",
            {
                "operation_id": "op.dev10.js.grant",
                "action": "set_grant",
                "subject": "owner.local",
                "expected_revision": 0,
                "data": {
                    "configuration_ref": ref,
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
                "configuration_ref": ref,
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
        yield store, authority, registry, registry.model(ref)
    finally:
        store.close()
