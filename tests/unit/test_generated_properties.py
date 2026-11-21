"""Seeded arithmetic, identity, canonical and registry models independent of runtime code."""

from copy import deepcopy
from decimal import Decimal, localcontext
import hashlib
import json
import random
import string
import unittest

from ezllmrouter_client._validation import identifier as client_identifier
from ezllmrouter_server.canonical import ContractError, digest, ident, jcs, strict_loads
from ezllmrouter_server.formatting import money
from ezllmrouter_server.identifiers import valid_identifier
from tests.generated_inputs import json_value, settings
from tests.operator_console import test_registry as registry_support
from tests.operator_console import test_personal_campaign as campaign_support
from tests.operator_console.test_user_management import UserFixture


class CanonicalProperties(unittest.TestCase):
    def test_key_order_whitespace_and_round_trips_preserve_canonical_identity(self):
        seed, count = settings(256)
        rng = random.Random(seed)
        for index in range(count):
            value = json_value(rng)
            raw = json.dumps(value, indent=2, ensure_ascii=True).encode()
            with self.subTest(seed=seed, index=index):
                canonical = jcs(value)
                self.assertEqual(jcs(strict_loads(raw)), canonical)
                self.assertEqual(jcs(strict_loads(canonical)), canonical)
                self.assertEqual(
                    digest(canonical), "sha256:" + hashlib.sha256(canonical).hexdigest()
                )
                if isinstance(value, dict):
                    self.assertEqual(jcs(dict(reversed(list(value.items())))), canonical)
        self.assertEqual(jcs({"\ue000": 2, "😀": 1}), '{"😀":1,"\ue000":2}'.encode())

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
    change = registry_support.RegistryTests.change
    model_b = registry_support.RegistryTests.model_b

    def test_generated_model_changes_preserve_revision_idempotency_and_stale_write_rejection(self):
        seed, count = settings(64)
        rng = random.Random(seed)
        self.number = 0
        self.model_b()
        model = self.registry.model("cfg.beta")
        revision, status = model["revision"], model["status"]
        for index in range(count):
            selected = rng.choice(("enabled", "disabled"))
            before = self.registry.version()
            body = {
                "operation_id": f"op.generated.{index}",
                "action": "model_state",
                "subject": "cfg.beta",
                "expected_revision": revision,
                "data": {"status": selected, "reason": "synthetic generated model"},
            }
            with self.subTest(seed=seed, index=index):
                reply = self.registry.mutate("owner.local", body)
                revision += 1
                status = selected
                self.assertEqual(self.registry.model("cfg.beta")["revision"], revision)
                self.assertEqual(self.registry.model("cfg.beta")["status"], status)
                self.assertEqual(self.registry.version(), before + 1)
                self.assertEqual(self.registry.mutate("owner.local", deepcopy(body)), reply)
                self.assertEqual(self.registry.version(), before + 1)
                stale = {**body, "operation_id": f"op.stale.{index}"}
                from ezllmrouter_server.registry import RegistryConflict

                with self.assertRaises(RegistryConflict):
                    self.registry.mutate("owner.local", stale)
                self.assertEqual(self.registry.model("cfg.beta")["revision"], revision)


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
    _reserve = campaign_support.CampaignTests._reserve

    def _record(self, suffix):
        return {**campaign_support.CampaignTests._record(self, suffix), "status_revision": 1}

    def test_generated_reservation_settlement_reconciliation_and_close_follow_integer_model(self):
        seed, count = settings(128)
        rng = random.Random(seed)
        # Synthetic reviewed contract: 1000 input tokens at 1.5/million and
        # 16 output tokens at 2.4/million, independently expressed as nanodollars.
        bound, allowance = 1538400, 12000000
        self.campaign.configure("owner.local", {**self.config, "max_requests": 100})
        self.campaign.transition("owner.local", "active")
        state, attempts = "active", {}

        def totals():
            spent = sum(row["cost"] for row in attempts.values() if row["state"] == "settled")
            held = sum(
                bound for row in attempts.values() if row["state"] in ("reserved", "unknown")
            )
            return spent, held

        for index in range(count):
            operation = (
                rng.choice(
                    ("reserve", "reserve", "release", "unknown", "settle", "reconcile", "resume")
                )
                if attempts
                else "reserve"
            )
            spent, held = totals()
            with self.subTest(seed=seed, index=index, operation=operation):
                if operation == "reserve":
                    permitted = (
                        state == "active"
                        and not held
                        and len(attempts) < 100
                        and spent + bound <= allowance
                    )
                    if permitted:
                        attempt = self._reserve(f"generated.{index}")
                        attempts[attempt["attempt_id"]] = {"state": "reserved", "cost": 0}
                    else:
                        with self.assertRaises(ContractError):
                            self._reserve(f"generated.{index}")
                        self.assertIsNone(self.store.get(f"submission.generated.{index}"))
                elif operation == "resume":
                    if state == "paused" and not held:
                        self.campaign.transition("owner.local", "active")
                        state = "active"
                else:
                    aid = rng.choice(list(attempts))
                    row = attempts[aid]
                    amount = rng.randrange(bound + 1)
                    cost = {
                        "status": "calculated",
                        "currency": "USD",
                        "amount_decimal": f"0.{amount:09d}",
                    }
                    if operation == "release":
                        self.campaign.settle(aid, before_transmit=True)
                        if row["state"] == "reserved":
                            row["state"] = "released"
                    elif operation == "unknown":
                        self.campaign.settle(aid)
                        if row["state"] in ("reserved", "unknown"):
                            row["state"] = "unknown"
                            state = "paused"
                    elif operation == "settle":
                        self.campaign.settle(aid, {"cost": cost})
                        if row["state"] in ("reserved", "unknown"):
                            row.update(state="settled", cost=amount)
                    elif operation == "reconcile":
                        self.store.update(
                            aid.replace("attempt.", "submission.", 1),
                            {},
                            usage={"attempt_id": aid, "cost": cost},
                        )
                        self.campaign.reconcile_recorded_usage("owner.local")
                        if row["state"] != "released":
                            row.update(state="settled", cost=amount)
                        before = self.campaign.summary()
                        self.assertEqual(self.campaign.reconcile_recorded_usage("owner.local"), 0)
                        self.assertEqual(self.campaign.summary(), before)
                summary = self.campaign.summary()
                spent, held = totals()
                self.assertEqual(Decimal(summary["incurred_decimal"]), Decimal(spent) / 1000000000)
                self.assertEqual(
                    Decimal(summary["outstanding_decimal"]), Decimal(held) / 1000000000
                )
                self.assertEqual(
                    Decimal(summary["available_decimal"]),
                    Decimal(max(0, allowance - spent - held)) / 1000000000,
                )
                self.assertEqual(summary["request_count"], len(attempts))
                self.assertEqual(summary["state"], state)
                self.assertEqual(
                    {row["attempt_id"]: row["state"] for row in summary["attempts"]},
                    {aid: row["state"] for aid, row in attempts.items()},
                )
        self.campaign.transition("owner.local", "closed")
        before = self.campaign.summary()
        with self.assertRaises(ContractError):
            self._reserve("after-close")
        self.assertEqual(self.campaign.summary(), before)
