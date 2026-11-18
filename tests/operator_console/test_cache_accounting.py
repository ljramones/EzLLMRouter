"""DEV-11 contract regression: independent token/rate oracle, no provider traffic."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/src"))
from duranki_server.cache_accounting import (CONTRACT, SEMANTICS, cache_usage_revision,
                                              exposure_bound, validate_contract)
from duranki_server.core import public_usage


def fixture():
    contract = {"version": CONTRACT, "requested_model": "fixture.responses.model",
        "returned_models": ["fixture.responses.model"], "cache_mode": "implicit_default_30m",
        "input_token_ceiling": 1000, "max_output_tokens": 20,
        "input_bound_basis": "provider_enforced_context_window",
        "temperature_zero_supported": True, "price_conditions": "single_tier_no_modifiers",
        "price_source_url": "https://example.test/fictional-model-contract",
        "observed_on": "2026-10-25"}
    schedule = {"usage_semantics_version": SEMANTICS, "contract": contract,
        "price_version": "fictional.cache.v1", "currency": "USD", "unit_denominator": 1000000,
        "rates": {"input_uncached": "1", "input_cache_read": "0.1",
                  "input_cache_write_30m": "1.25", "output_text": "2"}}
    return schedule


def usage(read=0, write=0, *, reason=2):
    return {"input_tokens": 120, "output_tokens": 20, "total_tokens": 140,
        "input_tokens_details": {"cached_tokens": read, "cache_write_tokens": write,
            "cache_write_tokens_details": {"ttl_30m_tokens": write, "ttl_12h_tokens": 0}},
        "output_tokens_details": {"reasoning_tokens": reason}}


class CacheAccountingTests(unittest.TestCase):
    def setUp(self):
        self.schedule = fixture()

    def revision(self, report, *, returned="fixture.responses.model"):
        return cache_usage_revision("attempt.fixture", report, self.schedule,
                                    "fixture.responses.model", returned)

    def test_plain_read_write_and_mixed_are_disjoint(self):
        cases = ((0, 0, 120, "0.000160000"),
                 (70, 0, 50, "0.000097000"),
                 (0, 30, 90, "0.000167500"),
                 (70, 30, 20, "0.000104500"))
        for read, write, ordinary, expected in cases:
            with self.subTest(read=read, write=write):
                result = self.revision(usage(read, write))
                self.assertEqual(result["normalized_usage"]["input_uncached"]["count"], ordinary)
                self.assertEqual(result["normalized_usage"]["input_total"]["count"], 120)
                self.assertEqual(result["normalized_usage"]["output_total"]["count"], 20)
                self.assertEqual(result["normalized_usage"]["output_text"]["count"], 18)
                self.assertEqual(result["cost"]["amount_decimal"], expected)
                # Independent category arithmetic, including reasoning only
                # in the total output bucket.
                oracle = (Decimal(ordinary) + Decimal(read) * Decimal("0.1") +
                          Decimal(write) * Decimal("1.25") + Decimal(20) * 2) / 1000000
                self.assertEqual(Decimal(expected), oracle)

    def test_missing_null_and_zero_are_distinct(self):
        for value, state in (("absent", "absent"), (None, "null"), (0, "known")):
            report = usage()
            details = report["input_tokens_details"]
            if value == "absent":
                del details["cache_write_tokens"]
            else:
                details["cache_write_tokens"] = value
            result = self.revision(report)
            self.assertEqual(result["reported_usage"]["input_cache_write"]["state"], state)
            self.assertEqual(result["cost"]["status"], "calculated" if state == "known" else "unknown")

    def test_inconsistent_lifetimes_and_malformed_counters_remain_unknown(self):
        changes = (
            lambda r: r["input_tokens_details"]["cache_write_tokens_details"].update(ttl_12h_tokens=1),
            lambda r: r["input_tokens_details"].update(cache_write_tokens=31),
            lambda r: r["input_tokens_details"].update(cached_tokens=121),
            lambda r: r.update(input_tokens=True),
            lambda r: r.update(output_tokens=-1),
            lambda r: r.update(total_tokens=139),
            lambda r: r["input_tokens_details"]["cache_write_tokens_details"].update(ttl_24h_tokens=0),
            lambda r: r["output_tokens_details"].update(reasoning_tokens=21),
        )
        for change in changes:
            report = usage(70, 30)
            change(report)
            with self.subTest(report=report):
                self.assertEqual(self.revision(report)["cost"]["status"], "unknown")
        self.assertEqual(self.revision(usage(), returned="different.model")["cost"]["status"], "unknown")

    def test_missing_reasoning_split_can_still_price_total_output(self):
        report = usage(70, 30)
        del report["output_tokens_details"]
        result = self.revision(report)
        self.assertEqual(result["cost"]["amount_decimal"], "0.000104500")
        self.assertEqual(result["reported_usage"]["output_reasoning"]["state"], "absent")
        self.assertEqual(result["normalized_usage"]["output_text"]["state"], "unknown")

    def test_wire_projection_keeps_installed_contract_while_ledger_retains_evidence(self):
        ledger = self.revision(usage(70, 30))
        ledger["revision"] = 1
        wire = public_usage({"state": "available", "revision": ledger})
        self.assertEqual(set(wire["revision"]["normalized_usage"]),
            {"input_uncached", "input_cache_read", "input_cache_write",
             "output_text", "output_reasoning", "other_billable"})
        self.assertNotIn("reported_usage", wire["revision"])
        self.assertEqual(ledger["reported_usage"]["input_cache_write"]["count"], 30)
        for value, state in (("absent", "absent"), (None, "null")):
            report = usage()
            if value == "absent":
                del report["input_tokens_details"]["cache_write_tokens"]
            else:
                report["input_tokens_details"]["cache_write_tokens"] = value
            ledger = self.revision(report)
            ledger["revision"] = 1
            wire = public_usage({"state": "available", "revision": ledger})
            self.assertEqual(ledger["reported_usage"]["input_cache_write"]["state"], state)
            self.assertEqual(wire["revision"]["normalized_usage"]["input_cache_write"],
                             {"state": "unknown"})

    def test_bound_and_publish_reject_unsupported_conditions(self):
        schedule = self.schedule
        self.assertEqual(exposure_bound(schedule, 20), Decimal("0.001290000"))
        self.assertEqual(validate_contract(schedule["contract"], "fixture.responses.model",
                                           schedule["rates"]), schedule["contract"])
        with self.assertRaises(ValueError):
            exposure_bound(schedule, 21)
        for key, value in (("requested_model", "other.model"),
                           ("cache_mode", "explicit_12h"),
                           ("temperature_zero_supported", False),
                           ("price_conditions", "unknown_threshold")):
            bad = deepcopy(schedule["contract"])
            bad[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_contract(bad, "fixture.responses.model", schedule["rates"])
        with self.assertRaises(ValueError):
            validate_contract(schedule["contract"], "fixture.responses.model",
                              {k: v for k, v in schedule["rates"].items() if k != "input_cache_write_30m"})


if __name__ == "__main__":
    unittest.main()
