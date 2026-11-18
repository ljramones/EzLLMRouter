"""Focused offline controls for the single-use CT02-02b exception."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dev12_ct02b_supplement import (
    BUDGET, CAMPAIGN, EXPIRY, OWNER, _insert_once, request_pair,
    supplemental_limits, verify_started_limits,
)


class SingleUseSupplementTests(unittest.TestCase):
    def setUp(self):
        self.plan = {"envelope": {"campaign_id": CAMPAIGN,
            "budget_account_id": BUDGET, "financial_owner_id": OWNER,
            "currency": "USD", "max_admissions": 1,
            "max_possible_sends": 1, "max_inflight": 1,
            "ceiling_decimal": "0.010000000", "absolute_expiry": EXPIRY}}
        self.scope = {"resource_started_at":
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "original_expiry": EXPIRY}

    def test_exact_narrow_limits_and_persisted_readback(self):
        self.assertEqual(supplemental_limits(self.plan, self.scope),
            {"max_attempts": 1, "max_concurrent": 1,
             "ceiling_decimal": "0.010000000", "window_hours": 1 / 6})
        started = datetime.now(timezone.utc)
        campaign = {**self.plan["envelope"],
            "max_attempts": 1, "max_concurrent": 1,
            "attempt_count": 0, "possible_send_count": 0, "inflight_count": 0,
            "paused": False, "expires_at":
                (started + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        self.assertEqual(verify_started_limits(campaign, self.scope), campaign)
        for field, invalid in (("max_attempts", 512), ("max_concurrent", 2),
                               ("ceiling_decimal", "6.000000000")):
            with self.subTest(field=field), self.assertRaises(AssertionError):
                verify_started_limits({**campaign, field: invalid}, self.scope)
        with self.assertRaises(AssertionError):
            verify_started_limits({**campaign, "expires_at": EXPIRY}, self.scope)

    def test_changed_identity_or_expired_resource_start_rejected(self):
        with self.assertRaises(AssertionError):
            supplemental_limits({**self.plan, "envelope":
                {**self.plan["envelope"], "campaign_id": "other"}}, self.scope)
        stale = {**self.scope, "resource_started_at":
            (datetime.now(timezone.utc) - timedelta(minutes=6)).strftime(
                "%Y-%m-%dT%H:%M:%SZ")}
        with self.assertRaises(PermissionError):
            supplemental_limits(self.plan, stale)

    def test_real_campaign_persists_small_limits_before_listener(self):
        from duranki_server.store import SQLiteStore
        from duranki_server.successor_campaign import FiniteSuccessorCampaign
        with TemporaryDirectory(dir=os.environ.get("DEV12_TEST_SCRATCH", ROOT)) as directory:
            store = SQLiteStore(Path(directory) / "finite.sqlite")
            try:
                campaign = FiniteSuccessorCampaign(store, CAMPAIGN, BUDGET,
                    financial_owner_id=OWNER)
                campaign.start({}, [], **supplemental_limits(self.plan, self.scope))
                verify_started_limits(campaign.inspect(), self.scope)
                self.assertEqual(campaign.inspect()["max_attempts"], 1)
                self.assertEqual(campaign.inspect()["max_concurrent"], 1)
            finally:
                store.close()

    def test_one_use_booking_identical_readback_and_conflict(self):
        with TemporaryDirectory(dir=os.environ.get("DEV12_TEST_SCRATCH", ROOT)) as directory:
            db = Path(directory) / "capacity.sqlite"
            record = {"key": "fixed", "amount_decimal": "0.010000000"}
            self.assertEqual(_insert_once(db, "fixed", record), "recorded")
            self.assertEqual(_insert_once(db, "fixed", record), "already_recorded")
            with self.assertRaises(AssertionError):
                _insert_once(db, "fixed",
                    {"key": "fixed", "amount_decimal": "0.020000000"})
            import sqlite3
            with sqlite3.connect(db) as connection:
                rows = connection.execute("SELECT record FROM allocations").fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(json.loads(rows[0][0]), record)

    def test_pair_has_one_complete_key_and_distinct_work_digests(self):
        from dev12_integrated import fixture
        _request, context = fixture("DIRECT_DOCUMENT")
        context["identity"]["charging_owner_id"] = OWNER
        token = "synthetic-token"
        class Runtime:
            credentials = {"DIRECT_DOCUMENT": token}
            contexts_by_credential = {token: context}
        first, second, first_hash, second_hash = request_pair(Runtime)
        self.assertEqual(first["work_selector"], second["work_selector"])
        self.assertNotEqual(first_hash, second_hash)
        self.assertEqual((first["input"]["items"][0]["text"],
                          second["input"]["items"][0]["text"]), ("Sky", "River"))


if __name__ == "__main__":
    unittest.main()
