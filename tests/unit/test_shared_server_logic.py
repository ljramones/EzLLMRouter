"""Shared policies retain wire versions, exact values and transactional authority."""

import json
import sqlite3
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
from unittest.mock import Mock, patch

from ezllmrouter_server import canonical, successor_contract
from ezllmrouter_server.database import Query
from ezllmrouter_server.errors import RequestError, ServerError
from ezllmrouter_server.formatting import is_utc_second, money, parse_utc_second, utc_timestamp
from ezllmrouter_server.integration_accounting import IntegrationError
from ezllmrouter_server.integration_bootstrap import BootstrapError
from ezllmrouter_server.local_connectors import ConnectorError
from ezllmrouter_server.provider_adapters import ProbeError
from ezllmrouter_server.registry import Registry, RegistryConflict
from ezllmrouter_server.repositories import authority
from ezllmrouter_server.secret_box import SecretBoxError
from ezllmrouter_server.states import DispatchState, SubmissionState
from ezllmrouter_server.user_management import UserError

from tests.operator_console.test_projection import record
from tests.operator_console.test_user_management import UserFixture
from tests.unit import test_database_batch as database_fixtures
from tests.development_slice import test_core as core_fixtures

AUDITS = Query(
    "SELECT actor,action,subject,old_revision,new_revision,authority_revision,at FROM registry_audit ORDER BY seq"
)
AUDIT_VALUES = Query("SELECT before_json,after_json FROM registry_audit_values ORDER BY seq")
USAGE = Query("SELECT revision,usage FROM usage_revisions WHERE attempt_id=? ORDER BY revision")


class FormattingTests(unittest.TestCase):
    def test_decimal_rendering_is_explicit_and_preserves_exact_values(self):
        for text, exact, compact, fixed in (
            ("0E-9", "0.000000000", "0", "0.000000000"),
            ("1.230000000", "1.230000000", "1.23", "1.230000000"),
            ("0.000000001", "0.000000001", "0.000000001", "0.000000001"),
            (
                "123456789.123456789",
                "123456789.123456789",
                "123456789.123456789",
                "123456789.123456789",
            ),
            ("1E+2", "100", "100", "100.000000000"),
        ):
            with self.subTest(value=text):
                value = Decimal(text)
                self.assertEqual(money(value), exact)
                self.assertEqual(money(value, compact=True), compact)
                self.assertEqual(money(value, places=9), fixed)

    def test_money_rendering_does_not_introduce_a_new_quantization_limit(self):
        with localcontext() as context:
            context.prec = 12
            self.assertEqual(
                money(Decimal("12345678901234567890.123456789"), places=9),
                "12345678901234567890.123456789",
            )

    def test_utc_formatting_normalizes_offsets_without_losing_precise_mode(self):
        instant = datetime(2026, 11, 19, 13, 2, 3, 456789, timezone(timedelta(hours=-5)))
        self.assertEqual(utc_timestamp(instant), "2026-11-19T18:02:03Z")
        self.assertEqual(utc_timestamp(instant, precise=True), "2026-11-19T18:02:03.456789+00:00")
        with self.assertRaises(ValueError):
            utc_timestamp(instant.replace(tzinfo=None))

    def test_utc_validation_preserves_offset_and_canonical_second_policies(self):
        self.assertEqual(canonical.utc_second("2024-02-29T23:00:00-02:00"), "2024-03-01T01:00:00Z")
        self.assertEqual(parse_utc_second("2024-02-29T23:00:00Z").tzinfo, timezone.utc)
        for value in (
            "2023-02-29T00:00:00Z",
            "2026-01-01T00:00:60Z",
            "2026-01-01T00:00:00.0Z",
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T00:00:00",
            None,
        ):
            with self.subTest(value=value):
                self.assertFalse(is_utc_second(value))
                self.assertFalse(successor_contract.utc_second(value))
        self.assertTrue(successor_contract.utc_second("2024-02-29T00:00:00Z"))


class JSONPolicyTests(unittest.TestCase):
    def test_both_protocols_reject_ambiguous_keys_and_non_integer_numbers(self):
        for decoder in (canonical.strict_loads, successor_contract.strict_decode):
            for raw in (
                b'{"a":1,"\\u0061":2}',
                b"1.0",
                b"NaN",
                b"Infinity",
                b"9007199254740992",
                b'"\\ud800"',
                b'"\xff"',
            ):
                with (
                    self.subTest(decoder=decoder.__name__, raw=raw),
                    self.assertRaises(canonical.ContractError) as failure,
                ):
                    decoder(raw)
                self.assertEqual(
                    (failure.exception.code, failure.exception.status), ("MALFORMED_JSON", 400)
                )

    def test_null_and_negative_zero_remain_version_specific(self):
        for raw in (b"null", b"-0"):
            with self.assertRaises(canonical.ContractError):
                canonical.strict_loads(raw)
        self.assertIsNone(successor_contract.strict_decode(b"null"))
        self.assertEqual(successor_contract.strict_decode(b"-0"), 0)

    def test_escaped_controls_remain_version_specific(self):
        for text in ("line\nnext", "a\tb", "\x00", "\x7f"):
            raw = json.dumps(text).encode()
            self.assertEqual(canonical.strict_loads(raw), text)
            with self.assertRaises(canonical.ContractError):
                successor_contract.strict_decode(raw)

    def test_byte_limits_are_applied_before_decoding(self):
        for decoder, cap in (
            (canonical.strict_loads, 65536),
            (successor_contract.strict_decode, 262144),
        ):
            with (
                self.subTest(decoder=decoder.__name__),
                self.assertRaises(canonical.ContractError) as failure,
            ):
                decoder(b"\xff" * (cap + 1))
            self.assertEqual(
                (failure.exception.code, failure.exception.status), ("LIMIT_EXCEEDED", 413)
            )
        self.assertEqual(canonical.strict_loads(bytearray(b"1")), 1)
        with self.assertRaises(canonical.ContractError):
            successor_contract.strict_decode(bytearray(b"1"))

    def test_depth_and_member_limits_remain_version_specific(self):
        for decoder, depth in (
            (canonical.strict_loads, 16),
            (successor_contract.strict_decode, 32),
        ):
            raw = b"[" * depth + b"0" + b"]" * depth
            decoder(raw)
            with self.assertRaises(canonical.ContractError) as failure:
                decoder(b"[" + raw + b"]")
            self.assertEqual(
                (failure.exception.code, failure.exception.status), ("LIMIT_EXCEEDED", 413)
            )
        raw = json.dumps({str(i): i for i in range(1025)}).encode()
        with self.assertRaises(canonical.ContractError):
            canonical.strict_loads(raw)
        self.assertEqual(len(successor_contract.strict_decode(raw)), 1025)

    def test_canonical_key_orders_and_digest_domains_are_not_merged(self):
        value = {"\ue000": 1, "\U00010000": 2}
        self.assertEqual(canonical.jcs(value).decode(), '{"𐀀":2,"":1}')
        self.assertEqual(successor_contract.canonical(value), '{"":1,"𐀀":2}')
        self.assertEqual(successor_contract.canonical({"x": None}), '{"x":null}')
        with self.assertRaises(canonical.ContractError):
            canonical.jcs({"x": None})

    def test_python_container_subclasses_keep_their_version_policy(self):
        class Items(list):
            pass

        value = Items([1, True])
        self.assertEqual(canonical.jcs(value), b"[1,true]")
        with self.assertRaises(TypeError):
            successor_contract.canonical(value)


class ErrorAndStateTests(unittest.TestCase):
    def test_domain_errors_share_a_root_and_preserve_existing_catch_types(self):
        for error in (
            canonical.ContractError("TEST"),
            UserError("TEST"),
            ConnectorError("TEST"),
            IntegrationError("TEST"),
            ProbeError("TEST"),
            RegistryConflict("TEST"),
            BootstrapError("TEST"),
        ):
            self.assertIsInstance(error, ServerError)
            self.assertIsInstance(error, ValueError)
            self.assertEqual(str(error), "TEST")
        self.assertIsInstance(SecretBoxError("TEST"), ServerError)
        self.assertIsInstance(SecretBoxError("TEST"), RuntimeError)

    def test_error_defaults_and_retry_attributes_preserve_recovery_behavior(self):
        self.assertEqual(canonical.ContractError("TEST").status, 422)
        self.assertEqual(UserError("TEST").status, 400)
        self.assertEqual(IntegrationError("TEST", 503, "query_first").retry_guidance, "query_first")
        self.assertFalse(hasattr(canonical.ContractError("TEST"), "retry_guidance"))
        self.assertFalse(hasattr(UserError("TEST"), "retry_guidance"))
        self.assertIsInstance(ConnectorError("TEST"), RequestError)

    def test_state_values_remain_plain_strings_for_exact_type_validation(self):
        value = {
            "submission_state": SubmissionState.ADMITTED.value,
            "dispatch_state": DispatchState.PREPARED.value,
        }
        self.assertTrue(all(type(item) is str for item in value.values()))
        self.assertEqual(
            json.dumps(value), '{"submission_state": "admitted", "dispatch_state": "prepared"}'
        )


class AuthorityAndLedgerTests(UserFixture):
    def audits(self):
        with self.store.database.read():
            return self.store.database.execute(AUDITS).fetchall()

    def revision(self):
        with self.store.database.read():
            return int(self.store.database.execute(authority.REVISION).fetchone()[0])

    def test_user_mutation_advances_authority_and_audit_together(self):
        before, count = self.revision(), len(self.audits())
        created = self.create()
        self.assertEqual(self.revision(), before + 1)
        self.assertEqual(self.registry.send_authority.epoch, before + 1)
        audits = self.audits()
        self.assertEqual(len(audits), count + 1)
        self.assertEqual(audits[-1][2:6], (created["principal_id"], None, 1, before + 1))

    def test_failed_audit_rolls_back_principal_and_authority_without_epoch_publication(self):
        before, audits = self.revision(), self.audits()
        epoch = self.registry.send_authority.epoch
        with patch.object(
            authority, "AUDIT", Query("INSERT INTO missing_audit_table VALUES (?,?,?,?,?,?,?)")
        ):
            with self.assertRaises(sqlite3.OperationalError):
                self.create()
        self.assertEqual(self.revision(), before)
        self.assertEqual(self.registry.send_authority.epoch, epoch)
        self.assertEqual(self.audits(), audits)
        self.assertEqual(self.users.list("owner.local")["items"][0]["username"], "admin")
        self.assertEqual(len(self.users.list("owner.local")["items"]), 1)

    def test_registry_replay_returns_the_same_receipt_without_another_audit(self):
        request = {
            "operation_id": "op.shared.rename",
            "action": "edit_principal",
            "subject": "svc.demo",
            "expected_revision": 1,
            "data": {"display_name": "Renamed service"},
        }
        result = self.registry.mutate("owner.local", request)
        before, audits = self.revision(), self.audits()
        self.assertEqual(self.registry.mutate("owner.local", deepcopy(request)), result)
        self.assertEqual(self.revision(), before)
        self.assertEqual(self.audits(), audits)

    def test_shared_authorization_rejects_missing_inactive_and_ordinary_principals(self):
        user = self.create()
        before = self.revision()
        for actor in ("missing", "svc.demo", user["principal_id"]):
            with self.store.database.read():
                self.assertFalse(authority.authorized(self.store.database, actor))
            with self.assertRaises(UserError) as failure:
                self.users.list(actor)
            self.assertEqual(
                (failure.exception.code, failure.exception.status), ("ADMIN_REQUIRED", 403)
            )
        self.assertEqual(self.revision(), before)

    def test_audit_values_use_the_shared_allowlist_without_secret_fields(self):
        before = self.revision()

        def change():
            return authority.record_change(
                self.store.database,
                actor="owner.local",
                action="test",
                subject="svc.demo",
                old_revision=1,
                new_revision=2,
                at="2026-11-19T00:00:00Z",
                include_values=True,
                before={"display_name": "public", "password": "SYNTHETIC_SECRET"},
                after={"revision": 2},
            )

        self.store.database.transaction(change)
        with self.store.database.read():
            raw_before, raw_after = self.store.database.execute(AUDIT_VALUES).fetchall()[-1]
        self.assertEqual(json.loads(raw_before), {"display_name": "public"})
        self.assertEqual(json.loads(raw_after), {})
        self.assertNotIn("SYNTHETIC_SECRET", raw_before)
        self.assertEqual(self.revision(), before + 1)

    def test_usage_append_and_completion_share_one_revision_chain(self):
        initial = record("submission.shared", "attempt.shared", "step.shared")
        initial["status_revision"] = 1
        initial["attempt_revision"] = 1
        initial["wait_expired_no_store"] = False
        self.store.create(initial)
        first = {"recorded_at": "2026-11-19T00:00:00Z", "cost": {"status": "unknown"}}
        second = {
            "recorded_at": "2026-11-19T00:00:01Z",
            "cost": {"status": "calculated", "amount_decimal": "0.000000001", "currency": "USD"},
        }
        originals = deepcopy((first, second))
        self.store.update("submission.shared", {}, usage=first)
        self.store.complete_candidate(
            "submission.shared",
            {"text": "synthetic"},
            second,
            None,
            True,
            None,
            "2026-11-19T00:00:02Z",
        )
        with self.store.database.read():
            rows = self.store.database.execute(USAGE, ("attempt.shared",)).fetchall()
        revisions = [json.loads(row[1]) for row in rows]
        self.assertEqual([item["revision"] for item in revisions], [1, 2])
        self.assertNotIn("previous_revision", revisions[0])
        self.assertEqual(revisions[1]["previous_revision"], 1)
        self.assertEqual(revisions[1]["cost"]["amount_decimal"], "0.000000001")
        self.assertEqual((first, second), originals)

    def test_registry_readiness_uses_the_injected_callback(self):
        ready = Mock(return_value=False)
        registry = Registry(self.store, self.registry.send_authority, runtime_ready=ready)
        model = registry.model("cfg.demo")
        self.assertEqual(registry.readiness(model), "transport_unavailable")
        ready.return_value = True
        self.assertEqual(registry.readiness(model), "synthetic_http1_ready")
        self.assertEqual(ready.call_count, 2)
        self.assertIsNone(registry.users)
        self.assertIsNone(registry.personal_campaign)
        self.assertIsNone(registry.local_connectors)
        self.assertIsNone(registry.integration_credentials)


class DispatchWiringTests(unittest.TestCase):
    setUp = core_fixtures.CoreTests.setUp
    coordinator = core_fixtures.CoreTests.coordinator

    def test_constructor_injects_guarded_sending_and_owned_successor(self):
        template = self.coordinator()
        successor = Mock()
        calls = []

        def send(prepared, timeout, expected, context):
            calls.append(context)
            context["fresh_check"]()
            return self.adapter.send(prepared, timeout, expected)

        self.adapter.send_with_context = Mock(
            side_effect=AssertionError("implicit sender selected")
        )
        coordinator = core_fixtures.Coordinator(
            self.store,
            template.identity,
            template.config,
            template.prompt_blocks,
            template.allowed_lineages,
            template.authority,
            self.adapter,
            template.retention,
            template.classification,
            template.recipe,
            successor=successor,
            context_sender=send,
        )
        self.addCleanup(coordinator.close)
        status, reply = coordinator.submit(deepcopy(core_fixtures.REQUEST), self.trusted, 1000)
        self.assertEqual((status, reply["state"]), (200, "delivered"))
        self.assertEqual(len(calls), 1)
        self.assertIn("commit", calls[0])
        self.assertIn("plan", calls[0])
        self.adapter.send_with_context.assert_not_called()
        coordinator.close()
        successor.close.assert_called_once()


class IntegrationProjectionTests(unittest.TestCase):
    setUp = database_fixtures.IntegrationQueryTests.setUp
    start = database_fixtures.IntegrationQueryTests.start
    append = database_fixtures.IntegrationQueryTests.append

    def seed(self):
        self.append(self.start("known"))
        self.append(self.start("unknown"))
        for original in database_fixtures.EXAMPLES["events"][1:3]:
            event = deepcopy(original)
            event.update(
                dataset_id=self.dataset,
                attempt_id="attempt.known",
                event_id="event.shared." + str(event["usage_revision"]),
                occurred_at="2026-11-04T00:00:30Z",
            )
            self.append(event)

    def test_all_report_versions_keep_exact_totals_and_unknown_cost_rows(self):
        self.seed()
        for version in ("1", "2", "3"):
            with self.subTest(version=version):
                report = self.registry.integration.report(self.owner, self.dataset, version=version)
                self.assertEqual(report["attempt_count"], 2)
                self.assertEqual(report["unknown_cost_attempts"], 1)
                self.assertEqual(report["known_total_by_currency"], {"USD": "0.020000000"})
                rows = {row["attempt_id"]: row for row in report["attempts"]}
                self.assertEqual(rows["attempt.known"]["usage_revision"], 2)
                self.assertEqual(rows["attempt.known"]["amount_decimal"], "0.020000000")
                self.assertIsNone(rows["attempt.unknown"]["amount_decimal"])

    def test_report_filters_apply_before_counts_and_aggregates_in_every_version(self):
        self.seed()
        for version in ("1", "2", "3"):
            with self.subTest(version=version):
                report = self.registry.integration.report(
                    self.owner, self.dataset, {"run_id": "run.absent"}, version=version
                )
                self.assertEqual(report["attempt_count"], 0)
                self.assertEqual(report["unknown_cost_attempts"], 0)
                self.assertEqual(report["known_total_by_currency"], {})
                self.assertEqual(report["attempts"], [])
