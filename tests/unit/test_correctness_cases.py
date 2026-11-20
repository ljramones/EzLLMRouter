"""Remaining review edge cases, using synthetic data and no provider requests."""

from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ezllmrouter_server import (
    canonical,
    catalogue,
    operator_projection,
    provider_adapters,
    registry as registry_module,
    successor_contract,
)
from ezllmrouter_server.core import Coordinator
from ezllmrouter_server.identifiers import require_identifier, valid_identifier
from ezllmrouter_server.scripted_demo import ScriptedDemo
from ezllmrouter_server.provider_vault import ProviderVault
from ezllmrouter_server.store import encode
from tests.development_slice import test_core as core_fixtures
from tests.development_slice import test_retrieval_contract as successor_fixtures
from tests.operator_console import test_catalogue as catalogue_fixtures
from tests.operator_console import test_reporting as reporting_fixtures
from tests.operator_console import test_registry_core as registry_fixtures


class AuthenticationTests(unittest.TestCase):
    setUp = registry_fixtures.RegistryCoordinatorTests.setUp

    def test_empty_map_without_a_registry_rejects_authentication_cleanly(self):
        self.coordinator.registry = None
        self.coordinator.identity = {}
        with self.assertRaises(canonical.ContractError) as denied:
            self.coordinator.authenticate("unknown")
        self.assertEqual(
            (denied.exception.code, denied.exception.status), ("AUTHENTICATION_FAILED", 401)
        )

    def test_empty_map_with_a_registry_requires_a_trusted_context(self):
        self.coordinator.identity = {}
        with self.assertRaises(canonical.ContractError) as denied:
            self.coordinator.authenticate(registry_fixtures.TOKEN)
        self.assertEqual(denied.exception.status, 401)

    def test_explicit_context_supports_an_empty_map_and_is_copied(self):
        context = deepcopy(registry_fixtures.FIXTURE["trusted_context"])
        base = self.coordinator
        service = Coordinator(
            self.store,
            {},
            base.config,
            base.prompt_blocks,
            base.allowed_lineages,
            base.authority,
            base.adapter,
            base.retention,
            base.classification,
            base.recipe,
            registry=self.registry,
            authentication_context=context,
        )
        self.addCleanup(service.close)
        context["task_id"] = "task.changed.after.construction"
        observed = service.authenticate(registry_fixtures.TOKEN)
        self.assertEqual(observed["task_id"], base.identity[registry_fixtures.TOKEN]["task_id"])
        self.assertEqual(observed["principal_id"], "svc.demo")

    def test_exact_credential_context_is_independent_of_map_order(self):
        own = deepcopy(registry_fixtures.FIXTURE["trusted_context"])
        other = {**own, "task_id": "task.foreign", "source_authority_id": "authority.foreign"}
        for entries in (
            (("other", other), (registry_fixtures.TOKEN, own)),
            ((registry_fixtures.TOKEN, own), ("other", other)),
        ):
            self.coordinator.identity = dict(entries)
            self.assertEqual(
                self.coordinator.authenticate(registry_fixtures.TOKEN)["task_id"], own["task_id"]
            )

    def test_unknown_registry_credential_does_not_inherit_an_ambiguous_scope(self):
        own = deepcopy(registry_fixtures.FIXTURE["trusted_context"])
        other = {**own, "task_id": "task.foreign"}
        for entries in ((("a", own), ("b", other)), (("b", other), ("a", own))):
            self.coordinator.identity = dict(entries)
            with self.assertRaises(canonical.ContractError) as denied:
                self.coordinator.authenticate(registry_fixtures.TOKEN)
            self.assertEqual(denied.exception.status, 401)

    def test_common_registry_scope_is_independent_of_identity_order(self):
        own = deepcopy(registry_fixtures.FIXTURE["trusted_context"])
        other = {**own, "principal_id": "svc.other", "charging_owner_id": "owner.other"}
        for entries in ((("a", own), ("b", other)), (("b", other), ("a", own))):
            self.coordinator.identity = dict(entries)
            got = self.coordinator.authenticate(registry_fixtures.TOKEN)
            self.assertEqual(
                (got["task_id"], got["principal_id"], got["charging_owner_id"]),
                (own["task_id"], "svc.demo", own["charging_owner_id"]),
            )

    def test_invalid_or_missing_expiry_is_an_authentication_failure(self):
        self.coordinator.registry = None
        for value in (None, "not-a-date", "2030-01-01T00:00:00", "2000-01-01T00:00:00Z"):
            self.coordinator.identity = {"token": {"expires_at": value}}
            with self.assertRaises(canonical.ContractError) as denied:
                self.coordinator.authenticate("token")
            self.assertEqual(denied.exception.status, 401)


class VaultCleanupTests(unittest.TestCase):
    setUp = catalogue_fixtures.CatalogueTests.setUp

    def connection(self):
        self.vault = ProviderVault(Path(self.temp.name) / "vault")
        self.registry.provider_vault = self.vault
        self.registry.mutate(
            "owner.local",
            {
                "operation_id": "op.connection",
                "action": "create_connection",
                "subject": "conn.cleanup",
                "expected_revision": 0,
                "data": {
                    "display_name": "Synthetic cleanup test",
                    "funding_kind": "personal_testing",
                    "adapter_id": "openai.responses.v1",
                    "settings": {
                        "origin": "https://api.openai.com",
                        "location": "commercial",
                        "site": "fixture",
                    },
                    "owner": "owner.local",
                },
            },
        )
        return self.registry.set_provider_credential(
            "owner.local", "conn.cleanup", 1, "op.first", "replace", "synthetic-secret-one"
        )

    def rotate(self):
        return self.registry.set_provider_credential(
            "owner.local", "conn.cleanup", 2, "op.rotate", "replace", "synthetic-secret-two"
        )

    def test_cleanup_failure_after_commit_retries_without_rotating_again(self):
        self.connection()
        old, current = self.vault._path("conn.cleanup", 1), self.vault._path("conn.cleanup", 2)
        with patch.object(self.vault, "remove", side_effect=PermissionError("controlled unlink")):
            with self.assertRaises(PermissionError):
                self.rotate()
        before = self.store.db.execute(
            "SELECT * FROM registry_operations ORDER BY operation_id"
        ).fetchall()
        self.assertTrue(old.exists())
        self.assertTrue(current.exists())
        with patch.object(self.vault, "seal", side_effect=AssertionError("rotation replayed")):
            result = self.rotate()
        self.assertEqual(result["record"]["credential_version"], 2)
        self.assertFalse(old.exists())
        self.assertEqual(self.vault.resolve("conn.cleanup", 2), "synthetic-secret-two")
        self.assertEqual(
            self.store.db.execute(
                "SELECT * FROM registry_operations ORDER BY operation_id"
            ).fetchall(),
            before,
        )
        self.assertEqual(self.rotate(), result)

    def test_committed_removal_also_resumes_cleanup_without_changing_the_record(self):
        self.connection()
        args = ("owner.local", "conn.cleanup", 2, "op.remove", "remove")
        with patch.object(self.vault, "remove", side_effect=PermissionError("controlled unlink")):
            with self.assertRaises(PermissionError):
                self.registry.set_provider_credential(*args)
        committed = self.registry.connection("conn.cleanup")
        self.assertEqual(committed["credential_state"], "absent")
        self.registry.set_provider_credential(*args)
        self.assertEqual(self.registry.connection("conn.cleanup"), committed)
        self.assertFalse(self.vault._path("conn.cleanup", 1).exists())

    def test_cleanup_is_recoverable_after_reopening_registry_and_vault(self):
        self.connection()
        with patch.object(self.vault, "remove", side_effect=PermissionError("controlled unlink")):
            with self.assertRaises(PermissionError):
                self.rotate()
        reopened = ProviderVault(self.vault.root, require_existing=True)
        self.registry = registry_module.Registry(
            self.store, self.authority, provider_vault=reopened
        )
        self.assertEqual(self.rotate()["record"]["credential_version"], 2)
        self.assertFalse(reopened._path("conn.cleanup", 1).exists())
        self.assertEqual(reopened.resolve("conn.cleanup", 2), "synthetic-secret-two")

    def test_old_cleanup_retry_never_removes_a_newer_selected_version(self):
        self.connection()
        with patch.object(self.vault, "remove", side_effect=PermissionError("controlled unlink")):
            with self.assertRaises(PermissionError):
                self.rotate()
        self.registry.set_provider_credential(
            "owner.local", "conn.cleanup", 3, "op.newer", "replace", "synthetic-secret-three"
        )
        self.assertEqual(self.rotate()["record"]["credential_version"], 2)
        self.assertEqual(self.registry.connection("conn.cleanup")["credential_version"], 3)
        self.assertEqual(self.vault.resolve("conn.cleanup", 3), "synthetic-secret-three")
        self.assertFalse(self.vault._path("conn.cleanup", 1).exists())

    def test_cleanup_retry_rejects_an_operation_with_different_credentials(self):
        self.connection()
        with patch.object(self.vault, "remove", side_effect=PermissionError("controlled unlink")):
            with self.assertRaises(PermissionError):
                self.rotate()
        with patch.object(self.vault, "remove") as remove:
            with self.assertRaises(registry_module.RegistryConflict):
                self.registry.set_provider_credential(
                    "owner.local",
                    "conn.cleanup",
                    2,
                    "op.rotate",
                    "replace",
                    "different-synthetic-secret",
                )
        remove.assert_not_called()
        self.assertTrue(self.vault._path("conn.cleanup", 2).exists())


class RegistryIdentifierTests(unittest.TestCase):
    setUp = catalogue_fixtures.CatalogueTests.setUp
    request = catalogue_fixtures.CatalogueTests.request

    def test_registry_catalogue_and_reports_preserve_a_full_length_configuration_id(self):
        entry = deepcopy(catalogue_fixtures.SEED["models"][0])
        entry["catalogue_key"] = "k" * (160 - len("catalogue."))
        request = self.request(entry, "o" * 160)
        self.registry.mutate("owner.local", request)
        selected = self.registry.model(request["subject"])
        self.assertEqual(selected["configuration_ref"], request["subject"])
        self.assertEqual(self.registry.history(request["subject"])[0]["action"], "import_catalogue")
        from ezllmrouter_server.reporting import usage_costs

        got = usage_costs(
            self.registry,
            {"role": "registry_admin", "principal_id": "owner.local"},
            {"configuration_ref": request["subject"]},
        )
        self.assertEqual(got["filters"]["configuration_ref"], request["subject"])


class IdentifierAndLimitTests(unittest.TestCase):
    setUp = core_fixtures.CoreTests.setUp
    coordinator = core_fixtures.CoreTests.coordinator

    def test_identifier_boundaries_and_grammar_agree(self):
        from ezllmrouter_client._validation import ID as client_ids

        validators = (
            canonical.ident,
            registry_module.identifier,
            catalogue._key,
            require_identifier,
        )
        for value in ("a", "0", "a-b._:C", "a" * 128, "a" * 129, "a" * 160):
            self.assertTrue(client_ids.fullmatch(value))
            self.assertEqual(operator_projection._identifier(value), value)
            for validate in validators:
                self.assertEqual(validate(value), value)
        for value in (
            "",
            "_prefix",
            ".prefix",
            ":prefix",
            "-prefix",
            "a" * 161,
            "é",
            "a/b",
            "a\n",
            None,
            True,
        ):
            self.assertFalse(valid_identifier(value))
            self.assertIsNone(operator_projection._identifier(value))
            for validate in validators:
                with self.assertRaises(ValueError):
                    validate(value)

    def test_long_admitted_ids_are_preserved_in_operator_activity_and_usage(self):
        request = deepcopy(core_fixtures.REQUEST)
        request["step_id"] = "s" * 160
        service = self.coordinator()
        status, reply = service.submit(request, self.trusted)
        self.assertEqual(status, 200)
        view = operator_projection.OperatorProjection(self.store, self.trusted["principal_id"])
        self.assertEqual(view.activity()["items"][0]["step_id"], request["step_id"])
        self.assertEqual(view.usage()["by_step"][0]["step_id"], request["step_id"])
        self.assertEqual(
            view.detail(reply["handle"]["submission_id"])["step_id"],
            request["step_id"],
        )

    def test_catalogue_generated_ids_fit_the_same_limit(self):
        entry = deepcopy(catalogue_fixtures.SEED["models"][0])
        entry["catalogue_key"] = "k" * (160 - len("catalogue."))
        sources = {row["id"]: row for row in catalogue_fixtures.SEED["sources"]}
        data = {"entry": entry, "sources": [sources[ref] for ref in entry["source_refs"]]}
        subject = "catalogue." + entry["catalogue_key"]
        self.assertEqual(catalogue.validate_catalogue(subject, data)["configuration_ref"], subject)
        with self.assertRaises(ValueError):
            catalogue.validate_catalogue(subject + "x", data)
        with self.assertRaises(ValueError):
            catalogue.operator_source(
                "https://example.test", "Fixture", "2030-01-01T00:00:00Z", "a" * 160
            )

    def test_output_limit_is_enforced_before_durable_admission(self):
        service = self.coordinator()
        request = deepcopy(core_fixtures.REQUEST)
        request["generation_settings"]["max_output_tokens"] = canonical.MAX_OUTPUT_TOKENS + 1
        with self.assertRaises(canonical.ContractError) as rejected:
            service.submit(request, self.trusted)
        self.assertEqual(
            (rejected.exception.code, rejected.exception.status), ("LIMIT_EXCEEDED", 422)
        )
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM submissions").fetchone(), (0,))
        self.assertEqual(self.adapter.sent, [])

    def test_output_limit_boundary_and_bad_types(self):
        request = deepcopy(core_fixtures.REQUEST)
        request["generation_settings"]["max_output_tokens"] = canonical.MAX_OUTPUT_TOKENS
        self.assertEqual(self.coordinator().submit(request, self.trusted)[0], 200)
        for value in (0, -1, True, "32768", 1.5):
            request["generation_settings"]["max_output_tokens"] = value
            with self.assertRaises(canonical.ContractError) as rejected:
                canonical.validate_text_request(
                    request,
                    self.trusted,
                    core_fixtures.FIXTURE["destination"],
                    core_fixtures.FIXTURE["prompt_blocks"],
                    core_fixtures.FIXTURE["allowed_lineages"],
                )
            self.assertEqual(
                rejected.exception.code,
                "MALFORMED_JSON" if type(value) is float else "SCHEMA_INVALID",
            )

    def test_implicit_execution_credential_does_not_depend_on_alias_order(self):
        service = self.coordinator()
        for index, tokens in enumerate((("a", "b"), ("b", "a"))):
            service.identity = {token: self.trusted for token in tokens}
            request = deepcopy(core_fixtures.REQUEST)
            request["step_id"] = "step.alias." + str(index)
            status, _reply = service.submit(request, self.trusted)
            self.assertEqual(status, 409)
        self.assertEqual(self.adapter.sent, [])
        request["step_id"] = "step.explicit.credential"
        self.assertEqual(service.submit(request, self.trusted, credential="b")[0], 200)

    def test_completion_requires_an_existing_running_launch(self):
        view = operator_projection.OperatorProjection(self.store, "svc.demo")
        operation = "o" * 160
        self.assertFalse(view.finish_launch(operation, "completed", []))
        self.assertTrue(view.begin_launch(operation, "text"))
        self.assertTrue(view.finish_launch(operation, "completed", ["submission.original"]))
        before = view.launch(operation)
        self.assertFalse(view.finish_launch(operation, "failed", ["submission.other"]))
        self.assertEqual(view.launch(operation), before)


class ReportFilterTests(unittest.TestCase):
    setUp = reporting_fixtures.ReportingTests.setUp
    report = reporting_fixtures.ReportingTests.report

    def test_absent_agent_versions_do_not_match_the_literal_none_filter(self):
        got = self.report({"agent_version": "None"})
        self.assertEqual(got["total"]["attempts"], 0)
        self.assertEqual(got["outcome_coverage"]["visible_root_runs"], 0)

    def test_absent_model_values_do_not_match_attempt_or_cohort_filters(self):
        self.store.db.execute("UPDATE intents SET intent=json_remove(intent,'$.destination.model')")
        got = self.report({"model": "None"})
        self.assertEqual(got["attempts"], [])
        self.assertEqual(got["cohorts"], [])

    def test_a_recorded_literal_none_value_still_matches_exactly(self):
        self.store.db.execute(
            "UPDATE intents SET intent=json_set(intent,'$.destination.model','None')"
        )
        got = self.report({"model": "None"})
        self.assertGreater(got["total"]["attempts"], 0)
        self.assertTrue(all(item["model"] == "None" for item in got["attempts"]))
        self.assertGreater(got["outcome_coverage"]["visible_root_runs"], 0)

    def test_long_internal_ids_are_selectable_without_truncation(self):
        identifier = "agent." + "a" * 154
        self.store.db.execute(
            "UPDATE submissions SET record=json_set(record,'$.attribution.agent_id',?)",
            (identifier,),
        )
        got = self.report({"agent_id": identifier})
        self.assertEqual(got["total"]["attempts"], 10)
        self.assertTrue(all(item["agent_id"] == identifier for item in got["attempts"]))
        with self.assertRaises(ValueError):
            self.report({"agent_id": identifier + "x"})

    def test_reporting_buckets_remain_available_without_becoming_valid_internal_ids(self):
        self.assertFalse(valid_identifier("__direct_human__"))
        self.store.db.execute(
            "UPDATE submissions SET record=json_set(record,'$.attribution.mode','direct_human') "
            "WHERE json_extract(record,'$.attribution.agent_id') IS NULL"
        )
        got = self.report({"agent_id": "__direct_human__"})
        self.assertGreater(got["total"]["attempts"], 0)
        self.assertTrue(all(item["agent_id"] == "__direct_human__" for item in got["attempts"]))
        with self.assertRaises(ValueError):
            self.report({"agent_id": "__not_a_bucket__"})


class ProbeSettingsTests(unittest.TestCase):
    def settings(self):
        return {"origin": "https://api.openai.com", "location": "commercial", "site": "Fixture"}

    def test_invalid_settings_are_safe_failed_observations_without_network_calls(self):
        settings = self.settings()
        cases = (
            None,
            {},
            {**settings, "origin": "http://api.openai.com"},
            {**settings, "origin": "https://api.openai.com:invalid"},
            {**settings, "site": None},
            {**settings, "credential": "synthetic-private-value"},
            {**settings, "location": "private_cloud"},
        )
        with patch.object(
            provider_adapters, "_wire_get", side_effect=AssertionError("network called")
        ):
            for value in cases:
                got = provider_adapters.probe(
                    "openai.responses.v1", value, "synthetic-private-value", "inventory"
                )
                self.assertEqual(
                    got, {"state": "failed", "reason": "invalid_settings", "models": []}
                )
                self.assertNotIn("synthetic-private-value", json.dumps(got))

    def test_unknown_or_unhashable_adapters_have_the_same_invalid_settings_result(self):
        for adapter in ("unknown", None, [], {}):
            got = provider_adapters.probe(adapter, self.settings(), None, "inventory")
            self.assertEqual(got["reason"], "invalid_settings")

    def test_unsupported_operations_are_distinct_from_invalid_settings(self):
        with patch.object(
            provider_adapters, "_wire_get", side_effect=AssertionError("network called")
        ):
            for operation in ("inference", None, [], {}):
                got = provider_adapters.probe(
                    "openai.responses.v1", self.settings(), None, operation
                )
                self.assertEqual(
                    (got["state"], got["reason"]), ("unsupported", "operation_not_implemented")
                )

    def test_malformed_response_remains_a_response_failure(self):
        with patch.object(
            provider_adapters, "_wire_get", return_value=(200, "application/json", b"not json")
        ):
            got = provider_adapters.probe(
                "openai.responses.v1", self.settings(), "synthetic-credential", "inventory"
            )
        self.assertEqual(got["state"], "failed")
        self.assertEqual(got["reason"], "malformed_response")


class DemoCutoffAndGraphTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.data = {
            "metadata": {
                "dataset_id": "demo.dataset",
                "synthetic": True,
                "display_name": "Synthetic edge cases",
                "display_timezone": "UTC",
                "report_cutoff_utc": "2026-11-19T12:00:00Z",
                "first_local_date": "2026-11-19",
                "last_local_date": "2026-11-19",
            },
            "workflows": [
                {
                    "id": "demo.workflow",
                    "title": "Fixture",
                    "started_at": "2026-11-19T10:00:00Z",
                    "initiating_user_id": None,
                    "root_run_id": "demo.run",
                    "task_outcome": "unknown",
                }
            ],
            "runs": [
                {
                    "id": "demo.run",
                    "workflow_id": "demo.workflow",
                    "parent_run_id": None,
                    "actor_id": "demo.actor",
                }
            ],
            "tasks": [{"id": "demo.task", "workflow_id": "demo.workflow"}],
            "attempts": [
                {
                    "id": "demo.attempt",
                    "workflow_id": "demo.workflow",
                    "task_id": "demo.task",
                    "run_id": "demo.run",
                    "executing_actor_id": "demo.actor",
                    "executing_actor_type": "agent",
                    "initiating_user_id": None,
                    "charging_owner_id": "demo.owner",
                    "provider_id": "demo.provider",
                    "provider_account_id": "demo.account",
                    "model_profile_id": "demo.model",
                    "label": "Fixture",
                    "started_at": "2026-11-19T10:00:00Z",
                    "ended_at": "2026-11-19T10:00:01Z",
                    "provider_result": "observed",
                    "retry_of_attempt_id": None,
                    "simulated_provider_write": True,
                }
            ],
            "usage_revisions": [
                {
                    "id": "demo.revision",
                    "attempt_id": "demo.attempt",
                    "revision": 1,
                    "recorded_at": "2026-11-19T13:00:00Z",
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                    "usage_state": "known",
                    "cost_state": "calculated_demo",
                    "currency": "USD",
                    "amount": "0.010000000",
                    "price_schedule_id": "demo.price",
                }
            ],
            "timeline_events": [],
            "outcomes": [],
            "users": [],
            "agents": [],
            "service_actors": [],
            "providers": [],
            "provider_accounts": [],
            "model_profiles": [],
        }

    def load(self):
        payload = encode(self.data).encode()
        (self.root / "fixture.json").write_bytes(payload)
        (self.root / "scope.json").write_text(
            encode(
                {
                    "dataset_id": "demo.dataset",
                    "fixture_sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
        )
        return ScriptedDemo(self.root)

    def test_attempt_without_a_qualifying_revision_is_explicitly_unknown(self):
        demo = self.load()
        report = demo.report()
        self.assertEqual(report["counts"]["attempts"], 1)
        self.assertEqual(report["counts"]["unknown_cost_attempts"], 1)
        self.assertEqual(report["counts"]["usage_revisions"], 0)
        self.assertEqual(report["counts"]["replacement_revisions"], 0)
        self.assertIsNone(report["attempts"][0]["usage_revision_id"])
        self.assertIsNone(report["attempts"][0]["amount_decimal"])
        self.assertEqual(report["observation_cost_steps"], [])
        self.assertEqual(demo.workflow("demo.workflow")["usage_revisions"], [])

    def test_empty_revision_history_does_not_crash_the_report(self):
        self.data["usage_revisions"] = []
        self.assertEqual(self.load().report()["counts"]["unknown_usage_attempts"], 1)

    def test_future_attempts_and_revisions_do_not_leak_past_the_cutoff(self):
        self.data["attempts"][0]["started_at"] = "2026-11-19T13:00:00Z"
        report = self.load().report()
        self.assertEqual(report["counts"]["attempts"], 0)
        self.assertEqual(report["counts"]["usage_revisions"], 0)

    def test_latest_qualifying_revision_replaces_earlier_cost_exactly(self):
        revision = self.data["usage_revisions"][0]
        revision["recorded_at"] = "2026-11-19T11:00:00Z"
        self.data["usage_revisions"].append(
            {**revision, "id": "demo.revision.2", "revision": 2, "amount": "0.020000000"}
        )
        self.data["usage_revisions"].append(
            {
                **revision,
                "id": "demo.revision.3",
                "revision": 3,
                "recorded_at": "2026-11-19T13:00:00Z",
                "amount": "9.000000000",
            }
        )
        report = self.load().report()
        self.assertEqual(report["counts"]["known_cost_subtotal_usd"], "0.020000000")
        self.assertEqual(report["counts"]["replacement_revisions"], 1)

    def test_self_and_multi_run_cycles_are_rejected(self):
        for parents in (
            {"demo.run": "demo.run"},
            {"demo.run": "demo.second", "demo.second": "demo.run"},
        ):
            self.data["runs"] = [
                {
                    "id": key,
                    "parent_run_id": parent,
                    "workflow_id": "demo.workflow",
                    "actor_id": "demo.actor",
                }
                for key, parent in parents.items()
            ]
            with self.assertRaisesRegex(ValueError, "cyclic"):
                self.load().workflow("demo.workflow")

    def test_missing_parent_is_a_controlled_error_and_valid_delegation_is_not_double_charged(self):
        self.data["runs"][0]["parent_run_id"] = "demo.missing"
        with self.assertRaisesRegex(ValueError, "parent"):
            self.load().workflow("demo.workflow")
        self.data["runs"][0]["parent_run_id"] = None
        self.data["runs"].append(
            {
                "id": "demo.child",
                "parent_run_id": "demo.run",
                "workflow_id": "demo.workflow",
                "actor_id": "demo.actor",
            }
        )
        self.data["attempts"][0]["run_id"] = "demo.child"
        self.data["usage_revisions"][0]["recorded_at"] = "2026-11-19T11:00:00Z"
        workflow = self.load().workflow("demo.workflow")
        rollups = {row["run_id"]: row for row in workflow["run_rollups"]}
        self.assertEqual(rollups["demo.run"]["direct"]["attempts"], 0)
        self.assertEqual(rollups["demo.run"]["delegated"]["known_cost_subtotal_usd"], "0.010000000")
        self.assertEqual(workflow["counts"]["known_cost_subtotal_usd"], "0.010000000")


class TariffDataTests(unittest.TestCase):
    def price_request(self, kind):
        price = next(
            item
            for item in successor_contract.REGISTRATIONS["price_contracts"]
            if item["schedule_kind"] == kind
        )
        request = deepcopy(
            next(
                item["request"]
                for item in successor_fixtures.VECTORS["examples"]
                if item["request"]["operation"] == price["operation"]
                and (
                    kind.startswith("tariff_") or item["request"]["input"]["role"] == price["role"]
                )
            )
        )
        key = "candidates" if request["operation"]["type"] == "rerank" else "items"
        request["input"][key] = request["input"][key][:1]
        return price, request, key

    def test_all_four_tariffs_use_the_packaged_rate_data(self):
        data = deepcopy(successor_contract.TARIFFS)
        data["schedule_a"].update(per_unit_usd="0.001", minimum_per_attempt_usd="0.001")
        data["schedule_b"].update(
            whole_request_tier_le_10_usd="0.0001", whole_request_tier_ge_11_usd="0.0002"
        )
        for kind in ("embedding_document", "embedding_query"):
            data[kind]["per_item_usd"] = "0.0001"
        with patch.object(successor_contract, "TARIFFS", data):
            for kind in ("tariff_a", "tariff_b", "embedding_document", "embedding_query"):
                price, request, _ = self.price_request(kind)
                result = successor_contract.tariff(request, price)
                self.assertEqual(
                    Decimal(result["settled"]), Decimal("0.001" if kind == "tariff_a" else "0.0001")
                )

    def test_zero_rates_keep_the_registered_decimal_format(self):
        price, request, _ = self.price_request("embedding_query")
        data = deepcopy(successor_contract.TARIFFS)
        data["embedding_query"]["per_item_usd"] = "0"
        with patch.object(successor_contract, "TARIFFS", data):
            got = successor_contract.tariff(request, price)
        self.assertEqual((got["settled"], got["bound"]), ("0.000000000", "0.000000000"))

    def test_embedding_cardinalities_match_every_published_vector(self):
        for kind, rows in (
            ("embedding_document", successor_contract.TARIFFS["embedding_document_rows"]),
            ("embedding_query", [successor_contract.TARIFFS["embedding_query_row"]]),
        ):
            price, request, key = self.price_request(kind)
            item = deepcopy(request["input"][key][0])
            for vector in rows:
                request["input"][key] = [deepcopy(item) for _ in range(vector["items"])]
                result = successor_contract.tariff(request, price)
                self.assertEqual(result["settled"], vector["settled_usd"])
                self.assertEqual(result["bound"], vector["request_bound_usd"])

    def test_bad_cardinalities_and_registration_mismatches_fail_closed(self):
        for kind in ("tariff_a", "tariff_b", "embedding_document", "embedding_query"):
            price, request, key = self.price_request(kind)
            item = request["input"][key][0]
            for count in (0, price["maximum_items"] + 1):
                request["input"][key] = [deepcopy(item) for _ in range(count)]
                with self.assertRaises(ValueError):
                    successor_contract.tariff(request, price)
            request["input"][key] = [item]
            for field, value in (
                ("price_ref", "price.wrong"),
                ("component", "wrong_units"),
                ("currency", "EUR"),
            ):
                with self.assertRaises(ValueError):
                    successor_contract.tariff(request, {**price, field: value})

    def test_invalid_rates_and_rates_above_the_registration_bound_are_rejected(self):
        price, request, _ = self.price_request("embedding_query")
        for rate in ("NaN", "Infinity", "-1", "999", "not-a-decimal", None, True):
            data = deepcopy(successor_contract.TARIFFS)
            data["embedding_query"]["per_item_usd"] = rate
            with patch.object(successor_contract, "TARIFFS", data), self.assertRaises(ValueError):
                successor_contract.tariff(request, price)

    def test_tariff_formula_is_read_as_a_bounded_formula_not_evaluated(self):
        price, request, key = self.price_request("tariff_a")
        request["input"][key] *= 10
        data = deepcopy(successor_contract.TARIFFS)
        data["schedule_a"]["units_formula"] = "ceil(documents/5)"
        with patch.object(successor_contract, "TARIFFS", data):
            self.assertEqual(successor_contract.tariff(request, price)["quantity"], 2)
        data["schedule_a"]["units_formula"] = "__import__('os')"
        with patch.object(successor_contract, "TARIFFS", data), self.assertRaises(ValueError):
            successor_contract.tariff(request, price)
