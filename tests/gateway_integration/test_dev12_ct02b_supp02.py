"""Focused offline controls for the single-use CT02-02b exception."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dev12_ct02b_supp02 import (
    BUDGET,
    CAMPAIGN,
    OWNER,
    ROOT_BASENAME,
    SUPP01_CAMPAIGN,
    _insert_once,
    request_pair,
    release_allocation,
    supplemental_limits,
    verify_started_limits,
)
from dev12_ct02b_host02_run import normalized_bind


class SingleUseSupplementTests(unittest.TestCase):
    def test_docker_desktop_bind_spelling_keeps_exact_source_and_mode(self):
        self.assertEqual(
            normalized_bind("/host_mnt/Users/owner/repo:/workspace:ro"),
            "/Users/owner/repo:/workspace:ro",
        )
        self.assertEqual(normalized_bind("supp02-link:/link"), "supp02-link:/link:rw")
        self.assertEqual(
            normalized_bind("/Users/owner/target:/target"), "/Users/owner/target:/target:rw"
        )

    def setUp(self):
        self.expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        expiry = patch("dev12_ct02b_supp02.EXPIRY", self.expiry)
        expiry.start()
        self.addCleanup(expiry.stop)
        self.plan = {
            "envelope": {
                "campaign_id": CAMPAIGN,
                "budget_account_id": BUDGET,
                "financial_owner_id": OWNER,
                "currency": "USD",
                "max_admissions": 1,
                "max_possible_sends": 1,
                "max_inflight": 1,
                "ceiling_decimal": "0.010000000",
                "absolute_expiry": self.expiry,
            }
        }
        self.scope = {
            "resource_started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "original_expiry": self.expiry,
        }

    def test_exact_narrow_limits_and_persisted_readback(self):
        self.assertEqual(ROOT_BASENAME, "dev12-ct02b-supplement02-20261027")
        self.assertEqual(
            supplemental_limits(self.plan, self.scope),
            {
                "max_attempts": 1,
                "max_concurrent": 1,
                "ceiling_decimal": "0.010000000",
                "window_hours": 1 / 6,
            },
        )
        started = datetime.now(timezone.utc)
        campaign = {
            **self.plan["envelope"],
            "max_attempts": 1,
            "max_concurrent": 1,
            "attempt_count": 0,
            "possible_send_count": 0,
            "inflight_count": 0,
            "paused": False,
            "expires_at": (started + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        self.assertEqual(verify_started_limits(campaign, self.scope), campaign)
        for field, invalid in (
            ("max_attempts", 512),
            ("max_concurrent", 2),
            ("ceiling_decimal", "6.000000000"),
        ):
            with self.subTest(field=field), self.assertRaises(AssertionError):
                verify_started_limits({**campaign, field: invalid}, self.scope)
        with self.assertRaises(AssertionError):
            verify_started_limits({**campaign, "expires_at": self.expiry}, self.scope)

    def test_changed_identity_or_expired_resource_start_rejected(self):
        with self.assertRaises(AssertionError):
            supplemental_limits(
                {**self.plan, "envelope": {**self.plan["envelope"], "campaign_id": "other"}},
                self.scope,
            )
        stale = {
            **self.scope,
            "resource_started_at": (datetime.now(timezone.utc) - timedelta(minutes=6)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
        }
        with self.assertRaises(PermissionError):
            supplemental_limits(self.plan, stale)

    def test_real_campaign_persists_small_limits_before_listener(self):
        from ezllmrouter_server.store import SQLiteStore
        from tools.synthetic.successor_campaign import FiniteSuccessorCampaign

        with TemporaryDirectory(dir=os.environ.get("DEV12_TEST_SCRATCH", ROOT)) as directory:
            store = SQLiteStore(Path(directory) / "finite.sqlite")
            try:
                campaign = FiniteSuccessorCampaign(
                    store, CAMPAIGN, BUDGET, financial_owner_id=OWNER
                )
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
                _insert_once(db, "fixed", {"key": "fixed", "amount_decimal": "0.020000000"})
            import sqlite3

            with sqlite3.connect(db) as connection:
                rows = connection.execute("SELECT record FROM allocations").fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(json.loads(rows[0][0]), record)

    def test_supp02_appends_after_two_consumed_allocations_once(self):
        with TemporaryDirectory(dir=os.environ.get("DEV12_TEST_SCRATCH", ROOT)) as directory:
            db = Path(directory) / "capacity.sqlite"
            original = {"campaign.sqlite": "fixed"}
            legacy = {
                "kind": "historical_conservative_capacity_v1",
                "key": "legacy",
                "observed_native_cost_decimal": None,
                "historical_conservative_consumption_decimal": "0.044000030",
            }
            old = {
                "kind": "ct02b_single_use_release_allocation_v1",
                "key": SUPP01_CAMPAIGN + "|single-use-release",
                "combined_max_conservative_consumption_decimal": "0.054000030",
                "original_file_sha256": original,
            }
            prior = {legacy["key"]: legacy, old["key"]: old}
            for key, row in prior.items():
                self.assertEqual(_insert_once(db, key, row), "recorded")
            result = release_allocation(db, prior, original, "source", "tree", "plan", "adopted")
            self.assertEqual(result["combined_max_conservative_consumption_decimal"], "0.064000030")
            with self.assertRaises(PermissionError):
                release_allocation(db, prior, original, "source", "tree", "plan", "adopted")
            import sqlite3

            with sqlite3.connect(db) as connection:
                rows = {
                    key: json.loads(raw)
                    for key, raw in connection.execute(
                        "SELECT allocation_key,record FROM allocations"
                    )
                }
            self.assertEqual(len(rows), 3)
            self.assertEqual({key: rows[key] for key in prior}, prior)

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
        self.assertEqual(
            (first["input"]["items"][0]["text"], second["input"]["items"][0]["text"]),
            ("Sky", "River"),
        )


if __name__ == "__main__":
    unittest.main()
