"""No-send controls for the fixed same-campaign completion inventory."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dev12_completion_catalog import (
    SUPPLEMENT_LIMITS,
    SUPPLEMENT_PREDICATES,
    SUPPLEMENT_REQUIRED_PAIRS,
)
from dev12_completion_supplement_runner import ORDER, _eligible, _wire03_sent_once, check


class SupplementGateTests(unittest.TestCase):
    EMPTY_LEGACY = {
        "admissions": 0,
        "possible_send_upper_count": 0,
        "finite_financial_upper_bound": "0.000000000",
    }

    def test_fixed_inventory_and_terminal_authority_case(self):
        self.assertEqual(set(ORDER), SUPPLEMENT_REQUIRED_PAIRS)
        self.assertEqual(set(SUPPLEMENT_PREDICATES), SUPPLEMENT_REQUIRED_PAIRS)
        self.assertEqual(ORDER[-1], ("ct02_authority_wait", "activation_pause_expiry"))
        self.assertLess(sum(value[0] for value in SUPPLEMENT_LIMITS.values()), 512 - 91)
        self.assertLess(sum(value[1] for value in SUPPLEMENT_LIMITS.values()), 512 - 91)

    def test_original_expiry_cannot_be_extended_by_case_plan(self):
        campaign = {
            "campaign_id": "campaign.dev12.c02.20261026.continue01",
            "budget_account_id": "budget.dev12.c02.20261026.continue01",
            "financial_owner_id": "team.dev12.c02.20261026.continue01",
            "start_at": "2026-10-26T21:54:14Z",
            "expires_at": "2026-10-27T21:54:14Z",
            "currency": "USD",
            "ceiling_decimal": "6.000000000",
            "max_attempts": 512,
            "max_concurrent": 2,
            "inflight_count": 0,
            "paused": False,
            "attempt_count": 91,
            "possible_send_count": 91,
            "cumulative_reserved_decimal": "0.027600030",
        }
        from datetime import datetime, timezone

        with patch(
            "dev12_completion_supplement_runner._now",
            return_value=datetime(2026, 10, 27, 21, 54, 14, tzinfo=timezone.utc),
        ):
            with self.assertRaisesRegex(RuntimeError, "deadline expired"):
                _eligible(campaign, legacy=self.EMPTY_LEGACY)
        changed = deepcopy(campaign)
        changed["expires_at"] = "2026-10-28T21:54:14Z"
        with self.assertRaisesRegex(RuntimeError, "identity/bounds differ"):
            _eligible(changed, legacy=self.EMPTY_LEGACY)

    def test_mixed_legacy_capacity_is_counted_and_unbounded_finance_blocks(self):
        campaign = {
            "campaign_id": "campaign.dev12.c02.20261026.continue01",
            "budget_account_id": "budget.dev12.c02.20261026.continue01",
            "financial_owner_id": "team.dev12.c02.20261026.continue01",
            "start_at": "2026-10-26T21:54:14Z",
            "expires_at": "2026-10-27T21:54:14Z",
            "currency": "USD",
            "ceiling_decimal": "6.000000000",
            "max_attempts": 512,
            "max_concurrent": 2,
            "inflight_count": 0,
            "paused": False,
            "attempt_count": 123,
            "possible_send_count": 108,
            "cumulative_reserved_decimal": "0.034000030",
        }
        legacy = {
            "admissions": 1,
            "possible_send_upper_count": 1,
            "finite_financial_upper_bound": None,
        }
        from datetime import datetime, timezone

        with patch(
            "dev12_completion_supplement_runner._now",
            return_value=datetime(2026, 10, 27, 2, 0, tzinfo=timezone.utc),
        ):
            with self.assertRaisesRegex(RuntimeError, "financial upper bound unestablished"):
                _eligible(campaign, legacy=legacy, allocated_admissions=1, allocated_sends=1)
            bounded = {**legacy, "finite_financial_upper_bound": "5.900000000"}
            with self.assertRaisesRegex(RuntimeError, "financial allowance insufficient"):
                _eligible(campaign, legacy=bounded, allocated_usd=Decimal("0.1"))
            counted = {**legacy, "admissions": 390, "finite_financial_upper_bound": "0"}
            with self.assertRaisesRegex(RuntimeError, "aggregate allowance insufficient"):
                _eligible(campaign, legacy=counted)

    def test_missing_variant_rejected_before_durable_access(self):
        pairs = list(ORDER[:-1])
        plan = {
            "kind": "dev12_completion02_same_campaign_supplement_v1",
            "cases": [{"scenario_id": a, "variant": b} for a, b in pairs],
        }
        with patch("dev12_completion_supplement_runner._supplement_prefix", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "inventory differs"):
                check(plan, Path("/nonexistent"), host=False)

    def test_failed_prewrite_cannot_count_as_wire03_ownership_pass(self):
        with TemporaryDirectory(dir=Path(__file__).resolve().parents[2]) as directory:
            root = Path(directory)
            path = root / "wire03.json"
            before = {"receiver_arrivals": 8, "guard_ownership": 8}
            stopped = {"receiver_arrivals": 8, "guard_ownership": 8}
            document = {
                "payload": {
                    "before": before,
                    "middle": stopped,
                    "first": {"status": {"submission_state": "failed"}},
                }
            }
            path.write_text(json.dumps(document))
            row = {"result": {"observations": [{"evidence_path": path.name}]}}
            self.assertFalse(_wire03_sent_once(root, row))
            document["payload"]["middle"] = {"receiver_arrivals": 9, "guard_ownership": 9}
            document["payload"]["first"]["status"]["submission_state"] = "completed"
            path.write_text(json.dumps(document))
            self.assertTrue(_wire03_sent_once(root, row))


if __name__ == "__main__":
    unittest.main()
