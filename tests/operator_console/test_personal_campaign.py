"""DEV-10 local allowance arithmetic and restart/race checks; no provider traffic."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import pathlib
import tempfile
import threading
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]

from ezllmrouter_server.canonical import ContractError
from ezllmrouter_server.personal_campaign import PersonalCampaign
from ezllmrouter_server.registry import Registry
from ezllmrouter_server.store import SQLiteStore, encode
from ezllmrouter_server.provider_vault import ProviderVault


class Authority:
    def __init__(self):
        self.gate = threading.RLock()
        self.epoch = 0


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = pathlib.Path(self.temp.name)
        self.store = SQLiteStore(root / "service.sqlite")
        self.addCleanup(self.store.close)
        self.vault = ProviderVault(root / "vault")
        self.registry = Registry(
            self.store,
            Authority(),
            legacy_destination={
                "configuration_ref": "cfg.demo",
                "service": "litellm.dev04",
                "endpoint": "127.0.0.1",
                "model": "model.demo",
                "model_version": "v1",
                "processing_region": "local",
            },
            legacy_token="synthetic-local-service-token-only-for-test-000001",
            legacy_trusted={"principal_id": "svc.demo", "charging_owner_id": "team.demo"},
            provider_vault=self.vault,
            provider_execution_ready=True,
        )
        self.connection = {
            "connection_id": "conn.personal",
            "funding_kind": "personal_testing",
            "owner": "owner.local",
            "adapter_id": "openai.responses.v1",
            "status": "active",
            "credential_state": "present",
            "credential_version": 1,
            "revision": 3,
        }
        self.model = {
            "configuration_ref": "cfg.personal",
            "kind": "provider_deployment",
            "status": "enabled",
            "revision": 5,
            "price_version": "rate.reviewed",
            "capabilities": ["text"],
            "purposes": ["execution"],
            "task_classes": ["class.demo"],
            "destination": {
                "configuration_ref": "cfg.personal",
                "service": "openai.responses.v1",
                "connection_id": "conn.personal",
                "connection_revision": 3,
                "credential_version": 1,
                "adapter_id": "openai.responses.v1",
                "model": "model-test",
            },
        }
        self.rate = {
            "price_version": "rate.reviewed",
            "currency": "USD",
            "usage_semantics_version": "openai.responses.text.cache.v2",
            "unit_denominator": 1000000,
            "rates": {
                "input_uncached": "1.2",
                "input_cache_read": "0.12",
                "input_cache_write_30m": "1.5",
                "output_text": "2.4",
            },
            "contract": {
                "version": "openai.responses.implicit-cache.v1",
                "requested_model": "model-test",
                "returned_models": ["model-test"],
                "cache_mode": "implicit_default_30m",
                "input_token_ceiling": 1000,
                "max_output_tokens": 16,
                "input_bound_basis": "provider_enforced_context_window",
                "temperature_zero_supported": True,
                "price_conditions": "single_tier_no_modifiers",
                "price_source_url": "https://example.test/fictional-rates",
                "observed_on": "2026-10-25",
            },
        }
        self.store._transaction(
            lambda: (
                self.store.db.execute(
                    "INSERT INTO registry_connections VALUES (?,?)",
                    ("conn.personal", encode(self.connection)),
                ),
                self.store.db.execute(
                    "INSERT INTO registry_models VALUES (?,?)", ("cfg.personal", encode(self.model))
                ),
                self.store.db.execute(
                    "INSERT INTO registry_prices VALUES (?,?,?)",
                    ("cfg.personal", "rate.reviewed", encode(self.rate)),
                ),
                self.store.db.execute(
                    "INSERT INTO registry_deployments VALUES (?,?)",
                    (
                        "deployment.personal",
                        encode(
                            {
                                "connection_id": "conn.personal",
                                "serving_id": "model-test",
                                "execution_approved": True,
                            }
                        ),
                    ),
                ),
                self.store.db.execute(
                    "INSERT INTO registry_grants VALUES (?,?,?)",
                    (
                        "owner.local",
                        "cfg.personal",
                        encode(
                            {
                                "principal_id": "owner.local",
                                "configuration_ref": "cfg.personal",
                                "status": "active",
                                "revision": 1,
                                "purposes": ["execution"],
                                "task_classes": ["class.demo"],
                            }
                        ),
                    ),
                ),
            )
        )
        self.campaign = PersonalCampaign(self.store, self.registry)
        self.registry.personal_campaign = self.campaign
        self.config = {
            "connection_id": "conn.personal",
            "configuration_ref": "cfg.personal",
            "principal_id": "owner.local",
            "currency": "USD",
            "allowance_decimal": "0.012",
            "per_request_decimal": "0.006",
            "max_requests": 2,
            "max_input_bytes": 200,
            "max_output_tokens": 16,
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1))
            .isoformat()
            .replace("+00:00", "Z"),
        }

    def _record(self, suffix):
        return {
            "submission_id": "submission." + suffix,
            "attempt_id": "attempt." + suffix,
            "principal_id": "owner.local",
            "task_id": "task.personal",
            "work_key": {
                "principal_id": "owner.local",
                "task_id": "task.personal",
                "step_id": "step." + suffix,
                "step_revision": 1,
                "execution_generation": "gen." + suffix,
            },
            "work_digest": "digest." + suffix,
            "selected_destination": self.model["destination"],
        }

    def _reserve(self, suffix):
        record = self._record(suffix)
        self.store.create(record, reserve=lambda db, item: self.campaign.reserve(db, item, 20, 16))
        return record

    def test_draft_atomic_race_known_settlement_and_restart(self):
        self.campaign.configure("owner.local", self.config)
        with self.assertRaises(ContractError):
            self._reserve("disabled")
        self.campaign.transition("owner.local", "active")
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda name: self._try_reserve(name), ("one", "two")))
        self.assertEqual(sorted(results), ["admitted", "denied"])
        active = self.campaign.summary()
        self.assertEqual(active["request_count"], 1)
        # Reviewed 1000-token provider ceiling at the highest input rate
        # plus 16 total output tokens bounds a cold write at 0.0015384.
        self.assertEqual(active["outstanding_decimal"], "0.001538400")
        self.assertEqual(active["available_decimal"], "0.010461600")
        aid = active["attempts"][0]["attempt_id"]
        reopened = PersonalCampaign(self.store, self.registry)
        self.assertEqual(reopened.summary()["outstanding_decimal"], active["outstanding_decimal"])
        self.assertEqual(reopened.summary()["state"], "paused")
        self.assertEqual(reopened.summary()["attempts"][0]["state"], "unknown")
        reopened.settle(
            aid, {"cost": {"status": "calculated", "amount_decimal": "0.0000192"}, "revision": 1}
        )
        self.assertEqual(reopened.summary()["incurred_decimal"], "0.0000192")
        reopened.transition("owner.local", "active")
        self._reserve("three")
        self.assertEqual(reopened.summary()["request_count"], 2)
        with self.assertRaises(ContractError):
            self._reserve("four")

    def _try_reserve(self, name):
        try:
            self._reserve(name)
            return "admitted"
        except ContractError:
            return "denied"

    def test_unknown_pauses_and_rotation_blocks_unsent(self):
        self.campaign.configure("owner.local", self.config)
        self.campaign.transition("owner.local", "active")
        first = self._reserve("unknown")
        self.campaign.settle(first["attempt_id"])
        summary = self.campaign.summary()
        self.assertEqual(summary["state"], "paused")
        self.assertEqual(summary["outstanding_decimal"], "0.001538400")
        with self.assertRaises(ValueError):
            self.campaign.transition("owner.local", "active")
        with self.assertRaises(ContractError):
            self._reserve("blocked")
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0], 1)

    def test_over_bound_charge_is_preserved_and_pauses_after_reopen(self):
        self.campaign.configure("owner.local", self.config)
        self.campaign.transition("owner.local", "active")
        attempt = self._reserve("over-bound")
        self.campaign.settle(
            attempt["attempt_id"],
            {
                "revision": 1,
                "cost": {"status": "calculated", "currency": "USD", "amount_decimal": "0.002"},
            },
        )
        summary = self.campaign.summary()
        self.assertEqual(summary["state"], "paused")
        self.assertEqual(summary["attempts"][0]["state"], "over_bound")
        self.assertEqual(summary["incurred_decimal"], "0.002")
        self.assertEqual(
            PersonalCampaign(self.store, self.registry).summary()["incurred_decimal"], "0.002"
        )

    def test_historical_two_rate_provider_price_cannot_activate(self):
        old = {
            **self.rate,
            "usage_semantics_version": "openai.responses.text.v1",
            "rates": {"input_uncached": "1.2", "output_text": "2.4"},
        }
        old.pop("contract")
        self.store._transaction(
            lambda: self.store.db.execute(
                "UPDATE registry_prices SET record=? WHERE config_ref=? AND price_version=?",
                (encode(old), "cfg.personal", "rate.reviewed"),
            )
        )
        self.campaign.configure("owner.local", self.config)
        with self.assertRaises(ValueError):
            self.campaign.transition("owner.local", "active")
        self.assertEqual(self.campaign.summary()["request_count"], 0)

    def test_exact_request_ceiling_and_multibyte_input_limit(self):
        self.campaign.configure(
            "owner.local", {**self.config, "per_request_decimal": "0.001538399"}
        )
        self.campaign.transition("owner.local", "active")
        with self.assertRaises(ContractError):
            self._reserve("one-nano-below")
        self.assertEqual(self.campaign.summary()["request_count"], 0)
        self.campaign.transition("owner.local", "paused")
        self.campaign.configure(
            "owner.local",
            {**self.config, "per_request_decimal": "0.001538400", "max_input_bytes": 4},
        )
        self.campaign.transition("owner.local", "active")
        record = self._record("multibyte")
        self.store.create(
            record,
            reserve=lambda db, item: self.campaign.reserve(db, item, len("éé".encode("utf-8")), 16),
        )
        self.assertEqual(self.campaign.summary()["attempts"][0]["bound_decimal"], "0.001538400")

    def test_current_authority_and_replacement_usage_revision(self):
        self.campaign.configure("owner.local", self.config)
        revision = self.campaign.transition("owner.local", "active")["revision"]
        first = self._reserve("authority")
        self.campaign.check(first["attempt_id"], revision)
        changed = {**self.connection, "revision": 4}
        self.store._transaction(
            lambda: self.store.db.execute(
                "UPDATE registry_connections SET record=? WHERE id='conn.personal'",
                (encode(changed),),
            )
        )
        self.assertEqual(self.campaign.summary()["effective_state"], "paused_stale_authority")
        with self.assertRaises(ContractError):
            self.campaign.check(first["attempt_id"], revision)
        self.store._transaction(
            lambda: self.store.db.execute(
                "UPDATE registry_connections SET record=? WHERE id='conn.personal'",
                (encode(self.connection),),
            )
        )
        self.campaign.transition("owner.local", "paused")
        with self.assertRaises(ContractError):
            self.campaign.check(first["attempt_id"], revision)
        self.campaign.settle(
            first["attempt_id"],
            {"cost": {"status": "calculated", "amount_decimal": "0.0000192"}, "revision": 1},
        )
        replacement = {
            "revision": 2,
            "cost": {"status": "calculated", "currency": "USD", "amount_decimal": "0.0000123"},
        }
        self.store._transaction(
            lambda: self.store.db.execute(
                "INSERT INTO usage_revisions VALUES (?,?,?,?)",
                (first["attempt_id"], 2, first["submission_id"], encode(replacement)),
            )
        )
        self.assertEqual(self.campaign.reconcile_recorded_usage("owner.local"), 1)
        self.assertEqual(self.campaign.summary()["incurred_decimal"], "0.0000123")
        self.assertEqual(self.campaign.summary()["request_count"], 1)
        self.assertEqual(self.campaign.reconcile_recorded_usage("owner.local"), 0)
        self.assertEqual(self.campaign.summary()["incurred_decimal"], "0.0000123")

    def test_closed_campaign_history_survives_explicit_new_allowance(self):
        self.campaign.configure("owner.local", self.config)
        self.campaign.transition("owner.local", "active")
        first = self._reserve("first-campaign")
        self.campaign.settle(
            first["attempt_id"],
            {"cost": {"status": "calculated", "amount_decimal": "0.00002"}, "revision": 1},
        )
        self.campaign.transition("owner.local", "paused")
        with self.assertRaisesRegex(ValueError, "close the existing campaign"):
            self.campaign.configure("owner.local", self.config)
        self.campaign.transition("owner.local", "closed")
        later = self.campaign.configure(
            "owner.local",
            {**self.config, "allowance_decimal": "0.005", "per_request_decimal": "0.005"},
        )
        self.assertEqual(later["id"], "personal.local.2")
        self.assertEqual(self.campaign.summary()["previous_campaigns"], 1)
        self.assertEqual(self.campaign.summary()["request_count"], 0)
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM personal_campaign_attempts").fetchone()[0],
            1,
        )
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM personal_campaigns").fetchone()[0], 2
        )

    def acknowledgement(self, attempt, **changes):
        campaign = self.campaign.summary()
        return {
            "campaign_id": campaign["id"],
            "attempt_id": attempt["attempt_id"],
            "expected_revision": campaign["revision"],
            "reason": "Owner accepts the unresolved charge",
            **changes,
        }

    def test_unknown_exposure_can_be_acknowledged_without_inventing_usage(self):
        self.campaign.configure("owner.local", self.config)
        self.campaign.transition("owner.local", "active")
        attempt = self._reserve("acknowledged")
        self.campaign.settle(attempt["attempt_id"])
        request = self.acknowledgement(attempt)
        acknowledged = self.campaign.acknowledge_exposure("owner.local", request)
        self.assertEqual(self.campaign.acknowledge_exposure("owner.local", request), acknowledged)
        summary = self.campaign.summary()
        self.assertEqual(summary["attempts"][0]["state"], "acknowledged")
        self.assertIsNone(summary["attempts"][0]["cost_decimal"])
        self.assertEqual(summary["incurred_decimal"], summary["attempts"][0]["bound_decimal"])
        self.assertEqual(summary["outstanding_decimal"], "0")
        self.assertEqual(summary["request_count"], 1)
        self.assertEqual(len(summary["exposure_acknowledgements"]), 1)
        self.assertEqual(
            self.store.db.execute(
                "SELECT COUNT(*) FROM personal_campaign_audit WHERE action='acknowledge_exposure'"
            ).fetchone()[0],
            1,
        )
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM usage_revisions").fetchone()[0], 0
        )
        self.campaign.transition("owner.local", "active")
        self._reserve("after-acknowledgement")

    def test_exposure_acknowledgement_requires_owner_review_and_a_terminal_attempt(self):
        self.campaign.configure("owner.local", self.config)
        self.campaign.transition("owner.local", "active")
        attempt = self._reserve("review")
        request = self.acknowledgement(attempt)
        with self.assertRaises(PermissionError):
            self.campaign.acknowledge_exposure("user.other", request)
        with self.assertRaises(ValueError):
            self.campaign.acknowledge_exposure("owner.local", request)
        self.campaign.settle(attempt["attempt_id"])
        with self.assertRaises(ValueError):
            self.campaign.acknowledge_exposure("owner.local", request)
        request = self.acknowledgement(attempt, reason="")
        with self.assertRaises(ValueError):
            self.campaign.acknowledge_exposure("owner.local", request)
        self.assertEqual(self.campaign.summary()["attempts"][0]["state"], "unknown")

    def test_closed_exposure_is_retained_without_blocking_a_new_explicit_allowance(self):
        first = self.campaign.configure("owner.local", self.config)
        self.campaign.transition("owner.local", "active")
        attempt = self._reserve("old-unknown")
        self.campaign.settle(attempt["attempt_id"])
        self.campaign.transition("owner.local", "closed")
        self.campaign.configure("owner.local", self.config)
        self.campaign.transition("owner.local", "active")
        summary = self.campaign.summary()
        self.assertEqual(summary["request_count"], 0)
        prior = summary["unresolved_prior_attempts"][0]
        self.assertEqual(
            (prior["attempt_id"], prior["campaign_id"], prior["state"]),
            (attempt["attempt_id"], first["id"], "unknown"),
        )
        self.campaign.acknowledge_exposure(
            "owner.local",
            {
                "campaign_id": prior["campaign_id"],
                "attempt_id": prior["attempt_id"],
                "expected_revision": prior["campaign_revision"],
                "reason": "Close prior exposure",
            },
        )
        self.assertEqual(self.campaign.summary()["unresolved_prior_attempts"], [])
        self.assertEqual(self.campaign.summary()["state"], "active")
        self.store.db.execute(
            "INSERT INTO usage_revisions VALUES (?,?,?,?)",
            (
                attempt["attempt_id"],
                2,
                attempt["submission_id"],
                encode(
                    {
                        "revision": 2,
                        "cost": {
                            "status": "calculated",
                            "currency": "USD",
                            "amount_decimal": "0.003",
                        },
                    }
                ),
            ),
        )
        self.assertEqual(self.campaign.reconcile_recorded_usage("owner.local"), 1)
        self.assertEqual(self.campaign.summary()["state"], "active")
        self.assertEqual(
            self.campaign.summary()["unresolved_prior_attempts"][0]["state"], "over_bound"
        )
        self.campaign.transition("owner.local", "paused")
        self.campaign.revalidate("owner.local")
        self.campaign.transition("owner.local", "active")

    def test_recorded_usage_can_reconcile_an_acknowledgement_without_erasing_its_audit(self):
        self.campaign.configure("owner.local", self.config)
        self.campaign.transition("owner.local", "active")
        attempt = self._reserve("late-after-acknowledgement")
        self.campaign.settle(attempt["attempt_id"])
        self.campaign.acknowledge_exposure("owner.local", self.acknowledgement(attempt))
        self.store.db.execute(
            "INSERT INTO usage_revisions VALUES (?,?,?,?)",
            (
                attempt["attempt_id"],
                2,
                attempt["submission_id"],
                encode(
                    {
                        "revision": 2,
                        "cost": {
                            "status": "calculated",
                            "currency": "USD",
                            "amount_decimal": "0.00002",
                        },
                    }
                ),
            ),
        )
        self.assertEqual(self.campaign.reconcile_recorded_usage("owner.local"), 1)
        summary = self.campaign.summary()
        self.assertEqual(summary["attempts"][0]["state"], "settled")
        self.assertEqual(summary["incurred_decimal"], "0.00002")
        self.assertEqual(len(summary["exposure_acknowledgements"]), 1)

    def test_acknowledged_over_bound_cost_keeps_the_higher_charge_for_admission(self):
        self.campaign.configure(
            "owner.local",
            {
                **self.config,
                "allowance_decimal": "0.0032",
                "per_request_decimal": "0.0032",
            },
        )
        self.campaign.transition("owner.local", "active")
        attempt = self._reserve("over-bound-acknowledgement")
        self.campaign.settle(
            attempt["attempt_id"],
            {
                "revision": 1,
                "cost": {"status": "calculated", "currency": "USD", "amount_decimal": "0.002"},
            },
        )
        result = self.campaign.acknowledge_exposure("owner.local", self.acknowledgement(attempt))
        self.assertEqual(result["charged_decimal"], "0.002")
        self.assertEqual(self.campaign.summary()["incurred_decimal"], "0.002")
        self.campaign.transition("owner.local", "active")
        with self.assertRaises(ContractError):
            self._reserve("over-remaining-allowance")

    def test_missing_keyring_and_corrupt_ciphertext_fail_closed(self):
        self.vault.seal("conn.personal", 1, "distinctive-synthetic-secret")
        root = pathlib.Path(self.temp.name) / "vault"
        key_path = root / "provider.keys.json"
        saved = key_path.read_bytes()
        key_path.unlink()
        with self.assertRaises(RuntimeError):
            ProviderVault(root)
        self.assertFalse(key_path.exists())
        sealed = self.vault._path("conn.personal", 1)
        sealed.unlink()
        with self.assertRaises(RuntimeError):
            ProviderVault(root, require_existing=True)
        key_path.write_bytes(saved)
        key_path.chmod(0o600)
        sealed.write_bytes(b"broken ciphertext")
        with self.assertRaises(RuntimeError):
            self.vault.resolve("conn.personal", 1)


if __name__ == "__main__":
    unittest.main()
