"""ToolRetentionTests behaviour regressions."""

from __future__ import annotations

import unittest
from tests.tool_cycle.core_support import ToolCoreFixture


class ToolRetentionTests(ToolCoreFixture, unittest.TestCase):
    def test_current_handling_upgrade_redacts_retained_candidate(self):
        _, reply = self.coordinator.submit(
            self.request(), self.trusted, wait_ms=3000, credential="token"
        )
        self.assertEqual(
            self.coordinator.status(reply["handle"]["submission_id"], self.trusted)[
                "candidate_access"
            ],
            "present",
        )
        self.coordinator.classification["combined_restrictions"] = ["no.content.store"]
        status = self.coordinator.status(reply["handle"]["submission_id"], self.trusted)
        self.assertEqual(status["candidate_access"], "not_retained")
        self.assertNotIn("candidate", status)

    def test_admitted_handling_remains_floor_after_classifier_relaxes(self):
        from tests.tool_cycle import test_core as _api

        self.coordinator.classification.update(
            sensitivity="confidential", combined_restrictions=["no.content.store"]
        )
        entered, release = _api.threading.Event(), _api.threading.Event()
        original_send = self.adapter.send

        def delayed(*args):
            entered.set()
            self.assertTrue(release.wait(2))
            return original_send(*args)

        self.adapter.send = delayed
        outcome = []
        worker = _api.threading.Thread(
            target=lambda: outcome.append(
                self.coordinator.submit(
                    self.request(), self.trusted, wait_ms=3000, credential="token"
                )
            )
        )
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            self.coordinator.classification.update(sensitivity="internal", combined_restrictions=[])
        finally:
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        code, reply = outcome[0]
        self.assertEqual((code, reply["state"]), (200, "delivered"))
        self.assertEqual(
            reply["candidate"]["output_blocks"][0]["source_labels"],
            {
                "lineage_ids": ["src.candidate.tool"],
                "sensitivity": "confidential",
                "restrictions": ["no.content.store"],
            },
        )
        status = self.coordinator.status(reply["handle"]["submission_id"], self.trusted)
        self.assertEqual(status["candidate_access"], "not_retained")
        self.assertNotIn("candidate", status)

    def test_metadata_only_wait_expiry_is_durable_after_classifier_relaxes(self):
        from tests.tool_cycle import test_core as _api

        entered, release, tighten = (
            _api.threading.Event(),
            _api.threading.Event(),
            _api.threading.Event(),
        )
        original_send = self.adapter.send

        def delayed(*args):
            entered.set()
            self.assertTrue(release.wait(2))
            return original_send(*args)

        self.adapter.send = delayed

        def tighten_policy():
            if entered.wait(2):
                self.coordinator.classification["combined_restrictions"] = ["no.content.store"]
                tighten.set()

        worker = _api.threading.Thread(target=tighten_policy)
        worker.start()
        try:
            code, pending = self.coordinator.submit(
                self.request(), self.trusted, wait_ms=100, credential="token"
            )
            self.assertTrue(tighten.wait(2))
            self.assertEqual(
                (code, pending["pending_result_policy"]), (202, "metadata_only_no_store")
            )
            sid = pending["handle"]["submission_id"]
            self.assertTrue(self.store.get(sid)["wait_expired_no_store"])
            self.coordinator.classification["combined_restrictions"] = []
        finally:
            release.set()
            worker.join(3)
        status = _api.wait_for_value(
            lambda: self.coordinator.status(sid, self.trusted),
            lambda status: status["submission_state"] == "completed",
        )
        self.assertEqual(status["candidate_access"], "not_retained")
        self.assertEqual(status["result_unavailable_reason"], "wait_expired_no_store")
        self.assertNotIn("candidate", status)
        self.assertEqual(
            self.store.get(pending["handle"]["submission_id"]).get("live_source_tags", []), []
        )

    def test_pending_reply_uses_the_single_durable_policy_snapshot(self):
        from tests.tool_cycle import test_core as _api

        entered, release = _api.threading.Event(), _api.threading.Event()
        first_read, changed = _api.threading.Event(), _api.threading.Event()
        original_send, original_pending = self.adapter.send, self.coordinator._pending
        reads = []

        def delayed(*args):
            entered.set()
            self.assertTrue(release.wait(2))
            return original_send(*args)

        def pending(record):
            result = original_pending(record)
            reads.append(result["pending_result_policy"])
            if len(reads) == 1:
                first_read.set()
                self.assertTrue(changed.wait(2))
            return result

        def tighten_after_first_read():
            if first_read.wait(2):
                self.coordinator.classification.update(
                    sensitivity="confidential", combined_restrictions=["no.content.store"]
                )
                changed.set()

        self.adapter.send = delayed
        self.coordinator._pending = pending
        worker = _api.threading.Thread(target=tighten_after_first_read)
        worker.start()
        try:
            code, reply = self.coordinator.submit(
                self.request(), self.trusted, wait_ms=100, credential="token"
            )
            self.assertTrue(entered.is_set())
            self.assertEqual(
                (code, reads, reply["pending_result_policy"]),
                (202, ["pollable_if_retained"], "pollable_if_retained"),
            )
            sid = reply["handle"]["submission_id"]
            self.assertFalse(self.store.get(sid)["wait_expired_no_store"])
            self.coordinator.classification.update(sensitivity="internal", combined_restrictions=[])
        finally:
            release.set()
            changed.set()
            worker.join(3)
        status = _api.wait_for_value(
            lambda: self.coordinator.status(sid, self.trusted),
            lambda status: status["submission_state"] == "completed",
        )
        self.assertEqual(status["candidate_access"], "present")

    def test_stricter_current_handling_applies_to_live_output_and_store(self):
        from tests.tool_cycle import test_core as _api

        entered, release = _api.threading.Event(), _api.threading.Event()
        original_send = self.adapter.send

        def delayed(*args):
            entered.set()
            self.assertTrue(release.wait(2))
            return original_send(*args)

        self.adapter.send = delayed
        outcome = []
        worker = _api.threading.Thread(
            target=lambda: outcome.append(
                self.coordinator.submit(
                    self.request(), self.trusted, wait_ms=3000, credential="token"
                )
            )
        )
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            self.coordinator.classification.update(
                sensitivity="confidential", combined_restrictions=["no.content.store"]
            )
        finally:
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        code, reply = outcome[0]
        self.assertEqual((code, reply["state"]), (200, "delivered"))
        self.assertEqual(
            reply["candidate"]["output_blocks"][0]["source_labels"],
            {
                "lineage_ids": ["src.candidate.tool"],
                "sensitivity": "confidential",
                "restrictions": ["no.content.store"],
            },
        )
        record = self.store.get(reply["handle"]["submission_id"])
        self.assertFalse(record["content_store_allowed"])
        self.assertIsNone(record["candidate"])

    def test_admitted_handling_floor_applies_to_text_output(self):
        from tests.tool_cycle import test_core as _api

        self.coordinator.classification.update(
            sensitivity="confidential", combined_restrictions=["no.content.store"]
        )
        entered, release = _api.threading.Event(), _api.threading.Event()
        original_send = self.adapter.send

        def delayed(*args):
            entered.set()
            self.assertTrue(release.wait(2))
            original_send(*args)
            return {"status": 200, "body": {"text": "Synthetic final text."}}

        self.adapter.send = delayed
        outcome = []
        worker = _api.threading.Thread(
            target=lambda: outcome.append(
                self.coordinator.submit(
                    self.request(), self.trusted, wait_ms=3000, credential="token"
                )
            )
        )
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            self.coordinator.classification.update(sensitivity="internal", combined_restrictions=[])
        finally:
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        code, reply = outcome[0]
        self.assertEqual((code, reply["state"]), (200, "delivered"))
        self.assertEqual(
            reply["candidate"]["output_blocks"][0]["source_labels"],
            {
                "lineage_ids": ["src.candidate.synthetic"],
                "sensitivity": "confidential",
                "restrictions": ["no.content.store"],
            },
        )
        self.assertIsNone(self.store.get(reply["handle"]["submission_id"])["candidate"])

    def test_source_no_store_wait_expiry_is_metadata_only(self):
        from tests.tool_cycle import test_core as _api

        request = self.request()
        request["messages"][1]["blocks"][0]["source_labels"] = self._restricted("src.user.1")
        gate = _api.threading.Event()
        original_send = self.adapter.send

        def delayed(*args):
            gate.wait(1)
            return original_send(*args)

        self.adapter.send = delayed
        code, pending = self.coordinator.submit(
            request, self.trusted, wait_ms=0, credential="token"
        )
        self.assertEqual((code, pending["pending_result_policy"]), (202, "metadata_only_no_store"))
        gate.set()
        status = _api.wait_for_value(
            lambda: self.coordinator.status(pending["handle"]["submission_id"], self.trusted),
            lambda status: status["submission_state"] == "completed",
        )
        self.assertEqual(status["candidate_access"], "not_retained")
        self.assertEqual(status["result_unavailable_reason"], "wait_expired_no_store")
        self.assertNotIn("candidate", status)
