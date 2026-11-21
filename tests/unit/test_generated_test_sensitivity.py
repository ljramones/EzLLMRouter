"""Confirm generated gates detect changed outcomes instead of only passing fixtures."""

from decimal import Decimal
import io
import json
import os
import random
import struct
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from ezllmrouter_server.gateway.choice_b_wire import receive
from ezllmrouter_server.personal_campaign import PersonalCampaign
from ezllmrouter_server.registry import Registry, RegistryConflict
from tests.generated_inputs import json_value
from tests.generated_checks import Divergence, run_trace
from tools import artifact_runs
from tests import generated_campaign
from tests.json_observations import observe
from tests.unit import test_campaign_interleavings as races
from tests.unit import test_generated_parsers as parsers
from tests.unit import test_generated_properties as properties


class GeneratedGateSensitivityTests(unittest.TestCase):
    def test_trace_without_health_directory_retains_the_minimized_failure(self):
        new_run = artifact_runs.new_run

        def broken(steps):
            if "bad" in steps:
                raise Divergence("synthetic invariant", "good", "bad")

        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ):
            os.environ.pop("EZLLMROUTER_TEST_HEALTH", None)
            with patch.object(
                artifact_runs,
                "new_run",
                side_effect=lambda _parent, prefix, kind: new_run(Path(temporary), prefix, kind),
            ):
                with self.assertRaisesRegex(AssertionError, "minimized"):
                    run_trace("synthetic", 42, ["bad"], broken)
            paths = list(Path(temporary).glob("generated-*/synthetic-*.json"))
            self.assertEqual(len(paths), 1)
            self.assertEqual(json.loads(paths[0].read_text())["minimized"], ["bad"])

    def test_observations_preserve_numeric_type_and_signed_zero(self):
        observations = [observe(value) for value in (True, 1, 1.0, 0, 0.0, -0.0)]
        self.assertEqual(len({json.dumps(value) for value in observations}), 6)

    def test_race_rejects_a_competitor_delayed_until_after_reservation(self):
        case = races.CampaignInterleavingTests(
            "test_reservation_commits_before_close_and_exposure_is_retained"
        )
        case.setUp()
        completed = threading.Event()
        transition, create = case.campaign.transition, case.store.create

        def delayed(actor, state):
            if state == "closed" and not completed.wait(3):
                raise AssertionError("synthetic reservation did not complete")
            return transition(actor, state)

        def completed_create(*args, **kwargs):
            value = create(*args, **kwargs)
            completed.set()
            return value

        try:
            with (
                patch.object(case.campaign, "transition", side_effect=delayed),
                patch.object(case.store, "create", side_effect=completed_create),
            ):
                with self.assertRaisesRegex(AssertionError, "close never contended"):
                    case.test_reservation_commits_before_close_and_exposure_is_retained()
        finally:
            case.doCleanups()

    def test_general_generator_covers_null_float_escaped_text_and_unicode_keys(self):
        rng = random.Random(12345)
        values, keys = [], []

        def collect(value):
            values.append(value)
            if isinstance(value, dict):
                keys.extend(value)
                for child in value.values():
                    collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)

        for _ in range(512):
            collect(json_value(rng))
        for name, condition in (
            ("null", any(value is None for value in values)),
            ("float", any(type(value) is float for value in values)),
            (
                "escaped text",
                any(
                    isinstance(value, str) and any(c in value for c in '\n\\"') for value in values
                ),
            ),
            ("Unicode keys", any(any(ord(c) > 127 for c in key) for key in keys)),
        ):
            with self.subTest(feature=name):
                self.assertTrue(condition)

    def differential_mutation(self, convert):
        original = parsers.strict_reply

        def changed(raw):
            def visit(value):
                if isinstance(value, dict):
                    return {key: visit(child) for key, child in value.items()}
                if isinstance(value, list):
                    return [visit(child) for child in value]
                return convert(value)

            return visit(original(raw))

        case = parsers.GeneratedParserTests(
            "test_json_clients_agree_and_server_request_policy_rejects_control_text"
        )
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.dict(
                os.environ,
                {
                    "EZLLMROUTER_TEST_SEED": "12345",
                    "EZLLMROUTER_TEST_EXAMPLES": "64",
                    "EZLLMROUTER_TEST_HEALTH": temporary,
                },
            ),
            patch.object(parsers, "strict_reply", side_effect=changed),
        ):
            with self.assertRaises(AssertionError):
                case.test_json_clients_agree_and_server_request_policy_rejects_control_text()

    def test_differential_rejects_boolean_to_integer_mutation(self):
        self.differential_mutation(lambda value: int(value) if type(value) is bool else value)

    def test_differential_rejects_integer_to_float_mutation(self):
        self.differential_mutation(lambda value: float(value) if type(value) is int else value)

    def test_campaign_generation_does_not_saturate_and_exercises_over_bound_costs(self):
        reserved, costs, configurations = [], [], []
        reserve, settle, configure = (
            PersonalCampaign.reserve,
            PersonalCampaign.settle,
            PersonalCampaign.configure,
        )

        def reserve_probe(campaign, *args, **kwargs):
            result = reserve(campaign, *args, **kwargs)
            reserved.append(result)
            return result

        def settle_probe(campaign, attempt, usage=None, **kwargs):
            result = settle(campaign, attempt, usage, **kwargs)
            if usage and usage.get("cost", {}).get("status") == "calculated":
                costs.append(int(Decimal(usage["cost"]["amount_decimal"]) * 1000000000))
            return result

        def configure_probe(campaign, *args, **kwargs):
            configurations.append(1)
            return configure(campaign, *args, **kwargs)

        case = properties.CampaignStateModel(
            "test_generated_reservation_settlement_reconciliation_and_close_follow_integer_model"
        )
        case.setUp()
        try:
            with (
                patch.dict(
                    os.environ,
                    {"EZLLMROUTER_TEST_SEED": "12345", "EZLLMROUTER_TEST_EXAMPLES": "128"},
                ),
                patch.object(PersonalCampaign, "reserve", reserve_probe),
                patch.object(PersonalCampaign, "settle", settle_probe),
                patch.object(PersonalCampaign, "configure", configure_probe),
            ):
                case.test_generated_reservation_settlement_reconciliation_and_close_follow_integer_model()
        finally:
            case.doCleanups()
        for name, condition in (
            ("successful reservations", len(reserved) >= 20),
            ("over-bound settlement", any(cost > 1538400 for cost in costs)),
            ("renewed allowance", len(configurations) > 1),
        ):
            with self.subTest(feature=name):
                self.assertTrue(condition)

    def test_registry_model_detects_version_changes_after_rejected_stale_writes(self):
        mutate, version = Registry.mutate, Registry.version
        offset = 0

        def mutate_probe(registry, actor, body):
            nonlocal offset
            try:
                return mutate(registry, actor, body)
            except RegistryConflict:
                if body["operation_id"].startswith("op.stale."):
                    offset += 1
                raise

        def version_probe(registry):
            return version(registry) + offset

        case = properties.RegistryStateModel(
            "test_generated_model_changes_preserve_revision_idempotency_and_stale_write_rejection"
        )
        case.setUp()
        try:
            with (
                tempfile.TemporaryDirectory() as temporary,
                patch.dict(
                    os.environ,
                    {
                        "EZLLMROUTER_TEST_SEED": "12345",
                        "EZLLMROUTER_TEST_EXAMPLES": "16",
                        "EZLLMROUTER_TEST_HEALTH": temporary,
                    },
                ),
                patch.object(Registry, "mutate", mutate_probe),
                patch.object(Registry, "version", version_probe),
            ):
                with self.assertRaises(AssertionError):
                    case.test_generated_model_changes_preserve_revision_idempotency_and_stale_write_rejection()
        finally:
            case.doCleanups()

    def test_campaign_reports_only_the_first_generated_divergence(self):
        summary = PersonalCampaign.summary

        def wrong(campaign):
            value = summary(campaign)
            if value.get("request_count", 0):
                value["available_decimal"] = str(
                    Decimal(value["available_decimal"]) + Decimal("0.0000000001")
                )
            return value

        case = properties.CampaignStateModel(
            "test_generated_reservation_settlement_reconciliation_and_close_follow_integer_model"
        )
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.dict(
                os.environ,
                {
                    "EZLLMROUTER_TEST_SEED": "12345",
                    "EZLLMROUTER_TEST_EXAMPLES": "16",
                    "EZLLMROUTER_TEST_HEALTH": temporary,
                },
            ),
            patch.object(PersonalCampaign, "summary", wrong),
        ):
            result = unittest.TextTestRunner(stream=io.StringIO()).run(case)
            paths = list((Path(temporary) / "generated-failures").glob("campaign-*.json"))
            self.assertEqual(len(paths), 1)
            trace = json.loads(paths[0].read_text())
            self.assertLess(len(trace["minimized"]), len(trace["trace"]))
            with self.assertRaises(Divergence) as replay:
                generated_campaign.execute(trace["minimized"])
            self.assertEqual(replay.exception.rule, trace["rule"])
        self.assertEqual(len(result.failures), 1, "later steps buried the first divergent state")
        self.assertIn("minimized", result.failures[0][1])

    def test_deep_ipc_json_is_an_input_error(self):
        raw = b'{"value":' + b"[" * 4096 + b"0" + b"]" * 4096 + b"}"
        frame = struct.pack("!I", len(raw)) + raw
        with self.assertRaises(ValueError):
            receive(parsers.FragmentedInput(frame, len(frame)))
