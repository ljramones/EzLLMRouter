"""Accounting survives rejected plans, malformed replies and post-send failures."""
import io
import json
from decimal import Decimal
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from tests.development_slice import test_core as core_fixtures
from tests.tool_cycle import test_core as tool_fixtures
from tests.operator_console import test_personal_campaign as campaign_fixtures
from duranki_server.canonical import ContractError
from duranki_server.core import Coordinator
from duranki_server import observability


class CoreFailureTests(unittest.TestCase):
    setUp = core_fixtures.CoreTests.setUp
    coordinator = core_fixtures.CoreTests.coordinator

    def test_plan_issuance_failures_are_durable_before_send_failures(self):
        for index, failure in enumerate((RuntimeError("private diagnostic"), KeyError("missing"),
                                         ContractError("PLAN_INVALID_OR_STALE", 409))):
            with self.subTest(failure=type(failure).__name__):
                coordinator = self.coordinator()
                request = core_fixtures.copy.deepcopy(core_fixtures.REQUEST)
                request["step_id"] = "step.plan." + str(index)
                with patch.object(coordinator.authority, "issue", side_effect=failure):
                    status, reply = coordinator.submit(request, self.trusted, 1000)
                self.assertIn(status, (409, 503))
                sid = reply["handle"]["submission_id"]
                self.assertEqual(self.store.get(sid)["submission_state"], "failed_before_transmit")
                self.assertEqual(self.store.intent_count(sid), 0)
                self.assertEqual(self.adapter.sent, [])
                coordinator.submit(request, self.trusted, 1000)
                self.assertEqual(coordinator.status(sid, self.trusted)["submission_state"], "failed_before_transmit")
                self.assertEqual(self.adapter.sent, [])

    def test_scheduler_failure_is_terminal_without_a_send(self):
        coordinator = self.coordinator()
        with patch.object(coordinator.pool, "submit", side_effect=RuntimeError("scheduler unavailable")):
            code, reply = coordinator.submit(core_fixtures.REQUEST, self.trusted, 1000)
        self.assertEqual(code, 503)
        self.assertEqual(self.store.get(reply["handle"]["submission_id"])["submission_state"], "failed_before_transmit")
        self.assertEqual(self.adapter.sent, [])

    def test_unexpected_response_processing_failure_preserves_usage_and_prevents_resend(self):
        coordinator = self.coordinator()
        with patch("duranki_server.core.public_served_destination", side_effect=RuntimeError("private reply")):
            code, reply = coordinator.submit(core_fixtures.REQUEST, self.trusted, 1000)
        self.assertEqual(code, 202)
        sid = reply["handle"]["submission_id"]
        record = coordinator.status(sid, self.trusted)
        self.assertEqual(record["submission_state"], "outcome_unknown")
        self.assertEqual(record["attempts"][0]["usage"]["state"], "available")
        coordinator.submit(core_fixtures.REQUEST, self.trusted, 1000)
        self.assertEqual(len(self.adapter.sent), 1)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM usage_revisions").fetchone()[0], 1)

    def test_invalid_candidate_keeps_reported_usage(self):
        self.adapter.body = {"text": None, "usage": {"input_tokens": 3, "output_tokens": 1}}
        coordinator = self.coordinator()
        code, reply = coordinator.submit(core_fixtures.REQUEST, self.trusted, 1000)
        self.assertEqual(code, 502)
        status = coordinator.status(reply["handle"]["submission_id"], self.trusted)
        self.assertEqual(status["submission_state"], "failed_after_transmit")
        self.assertEqual(status["attempts"][0]["usage"]["state"], "available")

    def test_post_commit_failure_does_not_downgrade_completed_accounting(self):
        coordinator = self.coordinator()
        complete = self.store.complete_candidate
        def complete_then_raise(*args, **kwargs):
            complete(*args, **kwargs)
            raise RuntimeError("reply construction failed")
        with patch.object(self.store, "complete_candidate", side_effect=complete_then_raise):
            _, reply = coordinator.submit(core_fixtures.REQUEST, self.trusted, 1000)
        status = coordinator.status(reply["handle"]["submission_id"], self.trusted)
        self.assertEqual(status["submission_state"], "completed")
        self.assertEqual(status["attempts"][0]["usage"]["state"], "available")
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM usage_revisions").fetchone()[0], 1)

    def test_background_response_failure_keeps_the_request_correlation(self):
        coordinator = self.coordinator()
        correlation = observability.REQUEST_CORRELATION.set("request.synthetic-correlation")
        captured = []
        try:
            with patch("duranki_server.core.public_served_destination", side_effect=RuntimeError("private response")), \
                    patch("duranki_server.core.log_failure", side_effect=lambda *_args: captured.append(
                        observability.REQUEST_CORRELATION.get())):
                code, _ = coordinator.submit(core_fixtures.REQUEST, self.trusted, 1000)
            self.assertEqual(code, 202)
            self.assertEqual(captured, ["request.synthetic-correlation"])
        finally:
            observability.REQUEST_CORRELATION.reset(correlation)

    def test_sqlite_automatic_rollback_preserves_the_original_failure(self):
        failure = RuntimeError("original database failure")
        def action():
            self.store.db.execute("ROLLBACK")
            raise failure
        with self.assertRaises(RuntimeError) as raised:
            self.store._transaction(action)
        self.assertIs(raised.exception, failure)
        self.assertTrue(failure.duranki_definite_rollback)


class CampaignFailureTests(unittest.TestCase):
    setUp = campaign_fixtures.CampaignTests.setUp
    _record = campaign_fixtures.CampaignTests._record

    def test_coordinator_failure_releases_a_real_before_send_reservation(self):
        self.campaign.configure("owner.local", {**self.config, "max_requests": 1})
        self.campaign.transition("owner.local", "active")
        attempt = self._record("plan-failed")
        attempt["status_revision"] = 1
        self.store.create(attempt, reserve=lambda db, item: self.campaign.reserve(db, item, 20, 16))
        coordinator = SimpleNamespace(store=self.store, registry=self.registry)
        Coordinator._failed(coordinator, attempt["submission_id"], attempt["attempt_id"],
                            "INTERNAL_UNAVAILABLE", "before_transmit")
        state = self.store.db.execute("SELECT state FROM personal_campaign_attempts WHERE attempt_id=?",
                                      (attempt["attempt_id"],)).fetchone()[0]
        self.assertEqual(state, "released")
        self.assertEqual(self.store.get(attempt["submission_id"])["submission_state"], "failed_before_transmit")
        summary = self.campaign.summary()
        self.assertEqual(Decimal(summary["outstanding_decimal"]), 0)
        self.assertEqual(Decimal(summary["available_decimal"]), Decimal(self.config["allowance_decimal"]))


class ToolResponseTests(unittest.TestCase):
    def test_null_text_with_valid_tool_calls_completes_and_records_usage_once(self):
        fixture = tool_fixtures.ToolCoreTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        original = fixture.adapter.send
        def send(*args):
            reply = original(*args)
            reply["body"]["text"] = None
            return reply
        with patch.object(fixture.adapter, "send", side_effect=send):
            code, reply = fixture.coordinator.submit(fixture.request(), fixture.trusted, 3000, credential="token")
        self.assertEqual(code, 200)
        self.assertEqual(reply["candidate"]["output_blocks"][0]["kind"], "tool_call")
        self.assertEqual(reply["candidate"]["usage"]["state"], "available")
        self.assertEqual(fixture.store.db.execute("SELECT COUNT(*) FROM usage_revisions").fetchone()[0], 1)


class LoggingTests(unittest.TestCase):
    def test_structured_failure_logs_stack_locations_without_secret_values(self):
        handlers = observability.LOGGER.handlers[:]
        level, propagate = observability.LOGGER.level, observability.LOGGER.propagate
        self.addCleanup(setattr, observability.LOGGER, "handlers", handlers)
        self.addCleanup(setattr, observability.LOGGER, "level", level)
        self.addCleanup(setattr, observability.LOGGER, "propagate", propagate)
        stream = io.StringIO()
        observability.configure_logging(stream)
        try:
            raise RuntimeError("secret-provider-key private-user-prompt")
        except RuntimeError:
            observability.log_failure("response_failed", correlation_id="corr.test", status=503)
        text = stream.getvalue()
        entry = json.loads(text)
        self.assertEqual(entry["exception_type"], "RuntimeError")
        self.assertEqual(entry["correlation_id"], "corr.test")
        self.assertTrue(entry["stack"])
        self.assertNotIn("secret-provider-key", text)
        self.assertNotIn("private-user-prompt", text)
