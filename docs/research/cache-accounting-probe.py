"""Offline synthetic usage shapes against the frozen service image."""
from decimal import Decimal
import json

from duranki_server.core import usage_revision

schedule = {"price_version": "synthetic.probe", "currency": "USD",
            "usage_semantics_version": "openai.responses.text.v1",
            "unit_denominator": 1000000,
            "rates": {"input_uncached": "1", "output_text": "2"}}
decision = {"price_schedule": schedule, "price_version": "synthetic.probe",
            "usage_semantics_version": "openai.responses.text.v1",
            "provider_model": "probe-model"}
base = {"input_tokens": 120, "output_tokens": 20,
        "output_tokens_details": {"reasoning_tokens": 2}}
cases = {
    "missing_details": base,
    "missing_write_only": {**base, "input_tokens_details": {"cached_tokens": 0}},
    "zero_write": {**base, "input_tokens_details": {"cached_tokens": 0,
                                                   "cache_write_tokens": 0}},
    "read_70": {**base, "input_tokens_details": {"cached_tokens": 70,
                                                "cache_write_tokens": 0}},
    "write_30": {**base, "input_tokens_details": {"cached_tokens": 0,
                                                 "cache_write_tokens": 30}},
    "mixed_70_30": {**base, "input_tokens_details": {"cached_tokens": 70,
                                                    "cache_write_tokens": 30}},
    "contradictory_read": {**base, "input_tokens_details": {"cached_tokens": 121,
                                                          "cache_write_tokens": 0}},
}
results = {}
for name, report in cases.items():
    actual = usage_revision("attempt.probe", report, decision=decision,
                            reported_model="probe-model")
    results[name] = {
        "cost": actual["cost"],
        "input_uncached": actual["normalized_usage"]["input_uncached"],
        "input_cache_read": actual["normalized_usage"]["input_cache_read"],
        "input_cache_write": actual["normalized_usage"]["input_cache_write"],
        "output_text": actual["normalized_usage"]["output_text"],
        "output_reasoning": actual["normalized_usage"]["output_reasoning"],
    }
assert results["zero_write"]["cost"]["amount_decimal"] == "0.000160000"
assert results["missing_write_only"]["cost"]["amount_decimal"] == "0.000160000"
assert results["missing_details"]["cost"]["status"] == "unknown"
assert results["read_70"]["cost"]["status"] == "unknown"
assert results["write_30"]["cost"]["status"] == "unknown"
assert results["mixed_70_30"]["cost"]["status"] == "unknown"
assert results["contradictory_read"]["cost"]["status"] == "unknown"
assert results["mixed_70_30"]["input_uncached"]["count"] == 50
assert results["mixed_70_30"]["input_cache_write"]["state"] == "unknown"
print(json.dumps(results, sort_keys=True))
print("independent_30m_write_example_usd", (Decimal(90) + Decimal(30) * Decimal("1.25") + Decimal(20) * 2) / Decimal(1000000))
