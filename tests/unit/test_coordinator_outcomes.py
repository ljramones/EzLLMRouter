"""Durable coordinator failure/uncertainty boundaries; no provider traffic."""

from contextlib import closing
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ezllmrouter_server import core, observability
from ezllmrouter_server.core import Coordinator
from ezllmrouter_server.store import SQLiteStore
from tests.development_slice import test_core as core_fixtures
from tests.operator_console import test_cache_accounting as cache_fixtures
from tests.operator_console import test_personal_campaign as campaign_fixtures


def create_attempt(store, suffix, *, base=None, reserve=None):
    record = (
        deepcopy(base)
        if base is not None
        else {
            "submission_id": "submission." + suffix,
            "attempt_id": "attempt." + suffix,
            "principal_id": "svc.demo",
            "task_id": "task.demo",
            "work_key": {
                "principal_id": "svc.demo",
                "task_id": "task.demo",
                "step_id": "step." + suffix,
                "step_revision": 1,
                "execution_generation": "gen.1",
            },
            "work_digest": "sha256:" + "1" * 64,
        }
    )
    record.update(
        submission_state="admitted",
        dispatch_state="prepared",
        candidate_access="not_yet_available",
        candidate=None,
        status_revision=1,
        attempt_revision=1,
        content_store_allowed=True,
        wait_expired_no_store=False,
        updated_at="2026-11-21T00:00:00Z",
    )
    store.create(record, reserve=reserve)
    store.intent(
        record["submission_id"],
        record["attempt_id"],
        {"plan_id": "plan." + suffix, "work_digest": record["work_digest"]},
    )
    return record


def decision(schedule):
    return {
        "price_schedule": deepcopy(schedule),
        "price_version": schedule["price_version"],
        "usage_semantics_version": schedule["usage_semantics_version"],
        "provider_model": "unrelated.caller-model",
    }


class CoordinatorOutcomeTests(unittest.TestCase):
    setUp = core_fixtures.CoreTests.setUp
    coordinator = core_fixtures.CoreTests.coordinator

    def unknown(self, record, **kwargs):
        context = SimpleNamespace(store=self.store, personal_campaign=None)
        result = Coordinator._outcome_unknown(
            context, record["submission_id"], record["attempt_id"], **kwargs
        )
        self.assertEqual(result, {"kind": "unknown"})
        observed = self.store.get(record["submission_id"])
        self.assertEqual(observed["submission_state"], "outcome_unknown")
        self.assertEqual(observed["dispatch_state"], "outcome_unknown")
        self.assertEqual(observed["candidate_access"], "not_yet_available")
        self.assertIsNone(observed["candidate"])
        self.assertEqual(self.store.intent_count(record["submission_id"]), 1)
        self.assertEqual(
            self.store.work_owner(record["work_key"]),
            {"contract_version": "0.2", "submission_id": record["submission_id"]},
        )
        return observed

    def usage_count(self, record):
        return self.store.db.execute(
            "SELECT COUNT(*) FROM usage_revisions WHERE attempt_id=?", (record["attempt_id"],)
        ).fetchone()[0]

    def test_missing_or_malformed_response_usage_never_fabricates_a_revision(self):
        responses = (
            None,
            [],
            {"body": None},
            {"body": []},
            {"body": "not an object"},
            {"body": {}},
            {"body": {"usage": None}},
            {"body": {"usage": []}},
        )
        for index, response in enumerate(responses):
            with self.subTest(response=response):
                record = create_attempt(self.store, f"missing.{index}")
                observed = self.unknown(record, response=response)
                self.assertEqual(observed["usage"], {"state": "not_recorded"})
                self.assertEqual(self.usage_count(record), 0)

    def test_salvaged_usage_is_durable_and_cannot_be_repriced_on_reentry(self):
        record = create_attempt(self.store, "salvaged")
        observed = self.unknown(
            record,
            plan={"destination": {"service": "synthetic"}},
            response={"body": {"usage": {"input_tokens": 3, "output_tokens": 1}}},
        )
        usage = observed["usage"]["revision"]
        self.assertEqual(usage["revision"], 1)
        self.assertEqual(
            usage["normalized_usage"]["input_uncached"], {"state": "known", "count": 3}
        )
        self.assertEqual(usage["normalized_usage"]["output_text"], {"state": "known", "count": 1})
        self.assertEqual(usage["cost"], {"status": "unknown", "currency": "USD"})
        with patch.object(core, "usage_revision") as normalize:
            repeated = self.unknown(
                record, response={"body": {"usage": {"input_tokens": 999, "output_tokens": 999}}}
            )
            normalize.assert_not_called()
        self.assertEqual(repeated["usage"], observed["usage"])
        self.assertEqual(self.usage_count(record), 1)
        self.store.close()
        with closing(SQLiteStore(self.store.path)) as reopened:
            self.assertEqual(reopened.get(record["submission_id"])["usage"], observed["usage"])
            self.assertEqual(reopened.intent_count(record["submission_id"]), 1)

    def test_provider_usage_prices_only_the_signed_route_and_matching_reported_model(self):
        schedule = cache_fixtures.fixture()
        for index, (service, priced, reported, expected) in enumerate(
            (
                ("openai.responses.v1", True, "fixture.responses.model", "calculated"),
                ("openai.responses.v1", False, "fixture.responses.model", "unknown"),
                ("openai.responses.v1", True, "different.model", "unknown"),
                ("synthetic", True, "fixture.responses.model", "unknown"),
            )
        ):
            with self.subTest(service=service, priced=priced, reported=reported):
                record = create_attempt(self.store, f"provider.{index}")
                pricing = decision(schedule) if priced else None
                original = deepcopy(pricing)
                observed = self.unknown(
                    record,
                    plan={"destination": {"service": service, "model": "fixture.responses.model"}},
                    decision=pricing,
                    response={
                        "body": {"served_model": reported, "usage": cache_fixtures.usage(70, 30)}
                    },
                )
                usage = observed["usage"]["revision"]
                self.assertEqual(usage["cost"]["status"], expected)
                self.assertEqual(usage["attempt_id"], record["attempt_id"])
                self.assertEqual(self.usage_count(record), 1)
                self.assertEqual(pricing, original, "recovery mutated the admission decision")
                if expected == "calculated":
                    self.assertEqual(usage["cost"]["amount_decimal"], "0.000104500")
                    self.assertEqual(usage["cost"]["source_ref"], "fictional.cache.v1")
                    self.assertEqual(usage["normalized_usage"]["input_uncached"]["count"], 20)
                    self.assertEqual(usage["normalized_usage"]["output_total"]["count"], 20)
                else:
                    self.assertNotIn("amount_decimal", usage["cost"])

    def test_unusable_plan_or_normalizer_failure_keeps_unknown_and_redacts_diagnostics(self):
        canary = "private-response-normalizer-canary"
        for index, bad_plan in enumerate((True, False)):
            with self.subTest(bad_plan=bad_plan):
                record = create_attempt(self.store, f"unusable.{index}")
                original = core.usage_revision
                with (
                    patch.object(core, "usage_revision", wraps=original) as normalize,
                    self.assertLogs("ezllmrouter", level="ERROR") as logs,
                ):
                    if not bad_plan:
                        normalize.side_effect = ValueError(canary)
                    observed = self.unknown(
                        record,
                        plan=None if bad_plan else {"destination": {"service": "synthetic"}},
                        response={"body": {"usage": {"input_tokens": 3, "output_tokens": 1}}},
                    )
                self.assertEqual([r.event for r in logs.records], ["response_usage_unusable"])
                self.assertNotIn(
                    canary, "".join(observability.EventFormatter().format(r) for r in logs.records)
                )
                self.assertEqual(observed["usage"], {"state": "not_recorded"})
                self.assertEqual(self.usage_count(record), 0)

    def test_failed_reply_prefers_durable_failure_and_falls_back_without_writing(self):
        record = create_attempt(self.store, "failed-reply")
        context = SimpleNamespace(store=self.store, personal_campaign=None)
        failed = Coordinator._failed(
            context,
            record["submission_id"],
            record["attempt_id"],
            "REMOTE_EXECUTION_FAILED",
            "after_transmit",
        )
        for sid, code in (
            (record["submission_id"], "INTERNAL_UNAVAILABLE"),
            ("submission.absent", "FDC_REJECTED"),
        ):
            with self.subTest(submission=sid):
                handle = {"submission_id": sid, "work_key": record["work_key"]}
                before = self.store.db.total_changes
                reply = Coordinator._failed_reply(
                    context, handle, record["attempt_id"], code, "after_transmit"
                )
                self.assertEqual(self.store.db.total_changes, before)
                self.assertEqual(reply["handle"], handle)
                self.assertEqual(reply["attempt_id"], record["attempt_id"])
                self.assertEqual(reply["state"], "failed")
                self.assertEqual(reply["error"]["retry_guidance"], "query_first")
                if sid == record["submission_id"]:
                    self.assertEqual(reply["error"], failed["terminal_failure"])
                else:
                    self.assertEqual(reply["error"]["code"], "FDC_REJECTED")
                    self.assertEqual(
                        set(reply["error"]), {"code", "correlation_id", "retry_guidance"}
                    )

    def test_post_send_response_failure_recovers_usage_and_same_work_never_resends(self):
        coordinator = self.coordinator()
        with (
            patch.object(
                coordinator, "_observe_response", side_effect=RuntimeError("response unavailable")
            ),
            self.assertLogs("ezllmrouter", level="ERROR"),
        ):
            status, reply = coordinator.submit(deepcopy(core_fixtures.REQUEST), self.trusted, 3000)
        self.assertEqual((status, reply["state"]), (202, "pending"))
        sid = reply["handle"]["submission_id"]
        observed = coordinator.status(sid, self.trusted)
        self.assertEqual(observed["submission_state"], "outcome_unknown")
        self.assertEqual(observed["attempts"][0]["usage"]["revision"]["revision"], 1)
        self.assertEqual(self.store.intent_count(sid), 1)
        again_status, again = coordinator.submit(
            deepcopy(core_fixtures.REQUEST), self.trusted, 3000
        )
        self.assertEqual((again_status, again["handle"]), (202, reply["handle"]))
        self.assertEqual(len(self.adapter.sent), 1)
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM usage_revisions").fetchone()[0], 1
        )


class CoordinatorCampaignOutcomeTests(unittest.TestCase):
    setUp = campaign_fixtures.CampaignTests.setUp
    _record = campaign_fixtures.CampaignTests._record

    def context(self):
        return SimpleNamespace(store=self.store, personal_campaign=self.campaign)

    def reserve(self, suffix):
        self.campaign.configure("owner.local", self.config)
        self.campaign.transition("owner.local", "active")
        return create_attempt(
            self.store,
            suffix,
            base=self._record(suffix),
            reserve=lambda db, item: self.campaign.reserve(db, item, 20, 16),
        )

    def recover(self, record):
        report = cache_fixtures.usage()
        report.update(output_tokens=4, total_tokens=124)
        return Coordinator._outcome_unknown(
            self.context(),
            record["submission_id"],
            record["attempt_id"],
            plan={"destination": {"service": "openai.responses.v1", "model": "model-test"}},
            decision=decision(self.rate),
            response={"body": {"served_model": "model-test", "usage": report}},
        )

    def test_configured_campaign_does_not_settle_an_unrelated_failed_attempt(self):
        self.campaign.configure("owner.local", self.config)
        record = create_attempt(self.store, "unrelated-failure")
        before = self.campaign.summary()
        with patch.object(self.campaign, "settle", wraps=self.campaign.settle) as settle:
            Coordinator._failed(
                self.context(),
                record["submission_id"],
                record["attempt_id"],
                "FDC_REJECTED",
                "before_transmit",
            )
            settle.assert_not_called()
        self.assertEqual(self.campaign.summary(), before)
        self.assertEqual(
            self.store.get(record["submission_id"])["submission_state"], "failed_before_transmit"
        )

    def test_configured_campaign_does_not_settle_an_unrelated_unknown_attempt(self):
        self.campaign.configure("owner.local", self.config)
        record = create_attempt(self.store, "unrelated-unknown")
        before = self.campaign.summary()
        with patch.object(self.campaign, "settle", wraps=self.campaign.settle) as settle:
            Coordinator._outcome_unknown(
                self.context(), record["submission_id"], record["attempt_id"]
            )
            settle.assert_not_called()
        self.assertEqual(self.campaign.summary(), before)

    def test_after_transmit_failure_keeps_the_full_unknown_charge_exposure(self):
        record = self.reserve("after-send")
        result = Coordinator._failed(
            self.context(),
            record["submission_id"],
            record["attempt_id"],
            "REMOTE_EXECUTION_FAILED",
            "after_transmit",
        )
        self.assertEqual(result["submission_state"], "failed_after_transmit")
        summary = self.campaign.summary()
        self.assertEqual(summary["attempts"][0]["state"], "unknown")
        self.assertEqual(summary["outstanding_decimal"], "0.001538400")
        self.assertEqual(summary["state"], "paused")
        self.assertEqual(summary["request_count"], 1)

    def test_unknown_result_without_usage_retains_the_reservation(self):
        record = self.reserve("unknown-unpriced")
        Coordinator._outcome_unknown(self.context(), record["submission_id"], record["attempt_id"])
        summary = self.campaign.summary()
        self.assertEqual(summary["attempts"][0]["state"], "unknown")
        self.assertEqual(summary["outstanding_decimal"], "0.001538400")
        self.assertEqual(
            self.store.get(record["submission_id"])["usage"], {"state": "not_recorded"}
        )

    def test_salvaged_usage_settles_once_without_publishing_a_candidate(self):
        record = self.reserve("unknown-priced")
        self.assertEqual(self.recover(record), {"kind": "unknown"})
        summary = self.campaign.summary()
        self.assertEqual(summary["attempts"][0]["state"], "settled")
        self.assertEqual(summary["incurred_decimal"], "0.000153600")
        self.assertEqual(Decimal(summary["outstanding_decimal"]), 0)
        self.assertEqual(summary["request_count"], 1)
        stored = self.store.get(record["submission_id"])
        self.assertEqual(stored["submission_state"], "outcome_unknown")
        self.assertIsNone(stored["candidate"])
        self.recover(record)
        self.assertEqual(self.campaign.summary(), summary)
        self.assertEqual(self.store.get(record["submission_id"])["usage"], stored["usage"])

    def test_completed_candidate_and_usage_survive_post_commit_recovery(self):
        record = self.reserve("completed-recovery")
        report = cache_fixtures.usage()
        report.update(output_tokens=4, total_tokens=124)
        pricing = {**decision(self.rate), "provider_model": "model-test"}
        usage = core.usage_revision(
            record["attempt_id"], report, decision=pricing, reported_model="model-test"
        )
        self.store.complete_candidate(
            record["submission_id"],
            {"candidate_id": "candidate.retained", "output_blocks": [{"text": "synthetic result"}]},
            usage,
            None,
            True,
            None,
            "2026-11-21T00:00:00Z",
        )
        before = self.store.get(record["submission_id"])
        self.assertEqual(self.recover(record), {"kind": "unknown"})
        self.assertEqual(self.store.get(record["submission_id"]), before)
        self.assertEqual(before["submission_state"], "completed")
        self.assertEqual(self.campaign.summary()["attempts"][0]["state"], "settled")
        self.assertEqual(self.campaign.summary()["incurred_decimal"], "0.000153600")
