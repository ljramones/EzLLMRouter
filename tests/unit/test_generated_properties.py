"""Seeded arithmetic, identity, canonical and registry models independent of runtime code."""

from copy import deepcopy
from decimal import Decimal, localcontext
import json
import random
import string
import unittest

from ezllmrouter_client._validation import identifier as client_identifier
from ezllmrouter_server.canonical import ContractError, digest, ident, jcs, strict_loads
from ezllmrouter_server.formatting import money
from ezllmrouter_server.identifiers import valid_identifier
from tests.generated_inputs import canonical_case, settings
from tests import generated_campaign, generated_registry
from tests.operator_console import test_personal_campaign as campaign_support
from tests.operator_console.test_user_management import UserFixture


class CanonicalProperties(unittest.TestCase):
    def test_key_order_whitespace_and_round_trips_preserve_canonical_identity(self):
        seed, count = settings(256)
        rng = random.Random(seed)
        for index in range(count):
            value, expected = canonical_case(rng)
            raw = json.dumps(value, indent=2, ensure_ascii=True).encode()
            with self.subTest(seed=seed, index=index):
                canonical = jcs(value)
                self.assertEqual(canonical, expected)
                self.assertEqual(jcs(strict_loads(raw)), canonical)
                self.assertEqual(jcs(strict_loads(canonical)), canonical)
                if isinstance(value, dict):
                    self.assertEqual(jcs(dict(reversed(list(value.items())))), canonical)
        self.assertEqual(jcs({"\ue000": 2, "😀": 1}), '{"😀":1,"\ue000":2}'.encode())
        # Published SHA-256 known answers, independent of the implementation.
        self.assertEqual(
            digest(b""), "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )
        self.assertEqual(
            digest(b"abc"),
            "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        )

    def test_decimal_round_trip_and_conservation_use_integer_units(self):
        seed, count = settings(256)
        rng = random.Random(seed)
        with localcontext() as context:
            context.prec = 80
            for index in range(count):
                scale = rng.randrange(19)
                left, right = (
                    rng.randrange(-9007199254740991, 9007199254740992),
                    rng.randrange(-9007199254740991, 9007199254740992),
                )
                unit = Decimal(10) ** -scale
                a, b = Decimal(left) * unit, Decimal(right) * unit
                with self.subTest(seed=seed, index=index, scale=scale):
                    self.assertEqual(Decimal(money(a)), a)
                    self.assertEqual(Decimal(money(a, compact=True)), a)
                    self.assertNotIn("E", money(a).upper())
                    self.assertEqual(Decimal(money(a + b)), Decimal(left + right) * unit)
                    self.assertEqual(
                        money(a, places=scale),
                        f"{'-' if left < 0 else ''}{abs(left) // 10**scale}"
                        + ("." + str(abs(left) % 10**scale).zfill(scale) if scale else ""),
                    )

    def test_identifier_grammar_boundaries_agree_between_server_and_python_client(self):
        seed, count = settings(256)
        rng = random.Random(seed)
        alphabet = string.ascii_letters + string.digits
        for index in range(count):
            length = rng.choice((1, 2, 159, 160))
            valid = rng.choice(alphabet) + "".join(
                rng.choice(alphabet + "._:-") for _ in range(length - 1)
            )
            with self.subTest(seed=seed, index=index):
                for predicate in (valid_identifier, client_identifier):
                    self.assertTrue(predicate(valid))
                self.assertEqual(ident(valid), valid)
                for invalid in (
                    valid + "\n",
                    valid + "\0",
                    "_" + valid,
                    "é" + valid,
                    "A" * 161,
                    True,
                ):
                    self.assertFalse(valid_identifier(invalid))
                    self.assertFalse(client_identifier(invalid))
                    with self.assertRaises(ContractError):
                        ident(invalid)


class RegistryStateModel(UserFixture):
    def test_generated_model_changes_preserve_revision_idempotency_and_stale_write_rejection(self):
        seed, count = settings(64)
        generated_registry.run(seed, count)


class AccountingOrderProperties(UserFixture):
    def test_shuffled_events_duplicates_and_late_corrections_conserve_latest_exact_cost(self):
        from tests.operator_console.accounting_support import EXAMPLES

        seed, count = settings(32)
        rng = random.Random(seed)
        ledger = self.registry.integration
        owner = self.registry.principal("owner.local")
        self.registry.mutate(
            "owner.local",
            {
                "operation_id": "op.generated.ingest",
                "action": "create_principal",
                "subject": "svc.generated",
                "expected_revision": 0,
                "data": {
                    "display_name": "Generated accounting fixture",
                    "kind": "service",
                    "owner": "owner.local",
                    "role": "ordinary",
                },
            },
        )
        self.registry.provision_credential(
            "owner.local", "svc.generated", 1, "op.generated.credential"
        )
        self.registry.mutate(
            "owner.local",
            {
                "operation_id": "op.generated.activate",
                "action": "principal_state",
                "subject": "svc.generated",
                "expected_revision": 2,
                "data": {"status": "active", "reason": "synthetic property test"},
            },
        )
        ingest = self.registry.principal("svc.generated")
        for index in range(count):
            did = f"dataset.generated.{index}"
            dataset = {
                **EXAMPLES["dataset"],
                "dataset_id": did,
                "ingest_principal_id": "svc.generated",
            }
            account = {
                **EXAMPLES["account"],
                "dataset_id": did,
                "account_id": f"account.generated.{index}",
            }
            ledger.create_dataset(owner, dataset)
            ledger.create_account(owner, account)
            events = deepcopy(EXAMPLES["events"])
            for event in events:
                event["dataset_id"] = did
                if "provider_account_id" in event:
                    event["provider_account_id"] = account["account_id"]
                if "selected_account_id" in event:
                    event["selected_account_id"] = account["account_id"]
            # Independent latest-revision model; integer nanodollars avoid shared Decimal logic.
            nanos = {"attempt.1": rng.randrange(1000000000), "attempt.2": rng.randrange(1000000000)}
            for event in events:
                if event["kind"] == "usage" and event["usage_state"] == "known":
                    amount = nanos[event["attempt_id"]]
                    event["amount_decimal"] = (
                        str(amount // 1000000000) + "." + str(amount % 1000000000).zfill(9)
                    )
            shuffled = events + rng.choices(events, k=12)
            rng.shuffle(shuffled)
            with self.subTest(seed=seed, index=index):
                for event in shuffled:
                    self.assertIn(ledger.append_event(ingest, event)[0], (200, 201))
                report = ledger.report(owner, did)
                self.assertEqual(report["attempt_count"], 2)
                self.assertEqual(report["unknown_cost_attempts"], 0)
                self.assertEqual(
                    Decimal(report["known_total_by_currency"]["USD"]),
                    Decimal(sum(nanos.values())) / 1000000000,
                )
                self.assertEqual(len(report["attempts"]), 2)


class CampaignStateModel(unittest.TestCase):
    setUp = campaign_support.CampaignTests.setUp

    def test_generated_reservation_settlement_reconciliation_and_close_follow_integer_model(self):
        seed, count = settings(128)
        generated_campaign.run(seed, count)
