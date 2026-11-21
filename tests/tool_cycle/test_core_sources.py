"""ToolSourceTests behaviour regressions."""

from __future__ import annotations

import unittest
from tests.tool_cycle.core_support import ToolCoreFixture


class ToolSourceTests(ToolCoreFixture, unittest.TestCase):
    def test_trusted_input_restriction_controls_signed_plan_output_and_store(self):
        request = self.request()
        request["messages"][1]["blocks"][0]["source_labels"] = self._restricted("src.user.1")
        code, reply = self.coordinator.submit(
            request, self.trusted, wait_ms=3000, credential="token"
        )
        self.assertEqual((code, reply["state"]), (200, "delivered"))
        plan = self.authority.plans[-1]
        self.assertEqual(
            plan["classification_snapshot"]["combined_restrictions"], ["no.content.store"]
        )
        self.assertFalse(plan["effective_retention"]["content_store_allowed"])
        self.assertEqual(plan["effective_retention"]["retention_class"], "no_store")
        call = reply["candidate"]["output_blocks"][0]
        self.assertEqual(
            call["source_labels"],
            {
                "lineage_ids": ["src.candidate.tool"],
                "sensitivity": "confidential",
                "restrictions": ["no.content.store"],
            },
        )
        status = self.coordinator.status(reply["handle"]["submission_id"], self.trusted)
        self.assertEqual(status["candidate_access"], "not_retained")
        self.assertNotIn("candidate", status)
        self.assertIsNone(self.store.get(reply["handle"]["submission_id"]).get("candidate"))

    def test_live_no_store_call_can_be_carried_only_as_complete_authorized_source(self):
        from tests.tool_cycle import test_core as _api

        first = self.request()
        first["messages"][1]["blocks"][0]["source_labels"] = self._restricted("src.user.1")
        code, reply = self.coordinator.submit(first, self.trusted, wait_ms=3000, credential="token")
        self.assertEqual((code, reply["state"]), (200, "delivered"))
        sid = reply["handle"]["submission_id"]
        call = reply["candidate"]["output_blocks"][0]
        record = self.store.get(sid)
        self.assertIsNone(record.get("candidate"))
        self.assertEqual(record["candidate_access"], "not_retained")
        self.assertEqual(len(record["live_source_tags"]), 1)
        self.assertNotIn(call["call_id"], _api.json.dumps(record))
        follow = self.request("gen.2")
        follow["messages"][1]["blocks"][0]["source_labels"] = self._restricted("src.user.1")
        follow["messages"].extend(
            [
                {"role": "assistant", "blocks": [call]},
                {
                    "role": "tool",
                    "blocks": [
                        {
                            "block_id": "block.result.1",
                            "kind": "tool_result",
                            "call_id": call["call_id"],
                            "result_value": {"value": "synthetic"},
                            "source_labels": _api.CORPUS["result_source_labels"],
                        }
                    ],
                },
            ]
        )
        forged = _api.deepcopy(follow)
        forged["execution_generation"] = "gen.3"
        forged["messages"][2]["blocks"][0]["arguments"]["key"] = "forged"
        with self.assertRaisesRegex(_api.ContractError, "SOURCE_INVALID"):
            self.coordinator.submit(forged, self.trusted, wait_ms=3000, credential="token")
        relabeled = _api.deepcopy(follow)
        relabeled["execution_generation"] = "gen.4"
        relabeled["messages"][2]["blocks"][0]["source_labels"]["restrictions"] = []
        with self.assertRaisesRegex(_api.ContractError, "SOURCE_INVALID"):
            self.coordinator.submit(relabeled, self.trusted, wait_ms=3000, credential="token")
        other = _api.deepcopy(self.trusted)
        other["context_id"] = "ctx.other"
        other["source_authority_id"] = "srcauth.other"
        self.coordinator.identity["other"] = other
        cross_scope = _api.deepcopy(follow)
        cross_scope["execution_generation"] = "gen.5"
        with self.assertRaisesRegex(_api.ContractError, "SOURCE_INVALID"):
            self.coordinator.submit(cross_scope, other, wait_ms=3000, credential="other")
        code, final = self.coordinator.submit(
            follow, self.trusted, wait_ms=3000, credential="token"
        )
        self.assertEqual(
            (code, final["candidate"]["output_blocks"][0]["text"]), (200, "Lookup: synthetic")
        )
        self.assertEqual(len(self.adapter.sends), 2)
        self.assertEqual(
            self.coordinator.status(sid, self.trusted)["candidate_access"], "not_retained"
        )

    def test_live_source_tag_requires_delivery_and_process_key(self):
        from tests.tool_cycle import test_core as _api

        self.coordinator.retention.update(retention_class="no_store", content_store_allowed=False)
        self.coordinator.retention.pop("content_expires_at", None)
        _, reply = self.coordinator.submit(
            self.request(), self.trusted, wait_ms=3000, credential="token"
        )
        sid = reply["handle"]["submission_id"]
        call = reply["candidate"]["output_blocks"][0]
        args = (
            self.trusted["principal_id"],
            self.trusted["task_id"],
            self.trusted["source_authority_id"],
            self.trusted["context_id"],
            call,
            self.coordinator._live_source_tag(call),
        )
        self.assertTrue(self.store.has_authorized_tool_call(*args))
        self.store.update(sid, {"delivery_state": "none"})
        self.assertFalse(self.store.has_authorized_tool_call(*args))
        self.store.update(sid, {"delivery_state": "candidate_delivered"})
        replacement = _api.Coordinator(
            self.store,
            identity=self.coordinator.identity,
            config=_api.deepcopy(self.coordinator.config),
            prompt_blocks=_api.deepcopy(self.coordinator.prompt_blocks),
            allowed_lineages=_api.deepcopy(self.coordinator.allowed_lineages),
            authority=self.authority,
            adapter=self.adapter,
            retention=_api.deepcopy(self.coordinator.retention),
            classification=_api.deepcopy(self.coordinator.classification),
            recipe=_api.SyntheticDevelopmentRecipe(),
            trusted_source_labels=_api.deepcopy(self.coordinator.trusted_source_labels),
        )
        try:
            self.assertNotEqual(self.coordinator._live_source_key, replacement._live_source_key)
            self.assertFalse(
                self.store.has_authorized_tool_call(*args[:-1], replacement._live_source_tag(call))
            )
        finally:
            replacement.pool.shutdown(wait=True)
        self.store.update(sid, {"wait_expired_no_store": True})
        self.assertFalse(self.store.has_authorized_tool_call(*args))

    def test_live_source_scope_fields_reject_independently(self):
        self.coordinator.retention.update(retention_class="no_store", content_store_allowed=False)
        self.coordinator.retention.pop("content_expires_at", None)
        _, reply = self.coordinator.submit(
            self.request(), self.trusted, wait_ms=3000, credential="token"
        )
        call = reply["candidate"]["output_blocks"][0]
        tag = self.coordinator._live_source_tag(call)
        scope = [
            self.trusted[k]
            for k in ("principal_id", "task_id", "source_authority_id", "context_id")
        ]
        for index in range(4):
            with self.subTest(field=index):
                changed = list(scope)
                changed[index] += ".other"
                self.assertFalse(self.store.has_authorized_tool_call(*changed, call, tag))

    def test_trusted_tool_result_restriction_controls_final_output_and_store(self):
        first = self.request()
        _, reply = self.coordinator.submit(first, self.trusted, wait_ms=3000, credential="token")
        call = reply["candidate"]["output_blocks"][0]
        follow = self.request("gen.2")
        follow["messages"].extend(
            [
                {"role": "assistant", "blocks": [call]},
                {
                    "role": "tool",
                    "blocks": [
                        {
                            "block_id": "block.result.1",
                            "kind": "tool_result",
                            "call_id": call["call_id"],
                            "result_value": {"value": "synthetic"},
                            "source_labels": self._restricted("src.tool.1"),
                        }
                    ],
                },
            ]
        )
        code, final = self.coordinator.submit(
            follow, self.trusted, wait_ms=3000, credential="token"
        )
        self.assertEqual((code, final["state"]), (200, "delivered"))
        plan = self.authority.plans[-1]
        self.assertFalse(plan["effective_retention"]["content_store_allowed"])
        self.assertEqual(
            final["candidate"]["output_blocks"][0]["source_labels"],
            {
                "lineage_ids": ["src.candidate.synthetic"],
                "sensitivity": "confidential",
                "restrictions": ["no.content.store"],
            },
        )
        status = self.coordinator.status(final["handle"]["submission_id"], self.trusted)
        self.assertEqual(status["candidate_access"], "not_retained")
        self.assertNotIn("candidate", status)

    def test_unsupported_handling_rejects_before_send(self):
        from tests.tool_cycle import test_core as _api

        request = self.request()
        labels = {
            "lineage_ids": ["src.user.1"],
            "sensitivity": "confidential",
            "restrictions": ["client.demo.only"],
        }
        self.coordinator.trusted_source_labels["src.user.1"] = labels
        request["messages"][1]["blocks"][0]["source_labels"] = labels
        with self.assertRaisesRegex(_api.ContractError, "POLICY_DENIED"):
            self.coordinator.submit(request, self.trusted, wait_ms=3000, credential="token")
        self.assertEqual(self.adapter.sends, [])
        self.assertIsNone(
            self.store.by_work(
                {
                    "principal_id": self.trusted["principal_id"],
                    "task_id": request["task_id"],
                    "step_id": request["step_id"],
                    "step_revision": request["step_revision"],
                    "execution_generation": request["execution_generation"],
                }
            )
        )

    def test_restricted_source_cannot_use_nonlocal_destination(self):
        from tests.tool_cycle import test_core as _api

        request = self.request()
        request["messages"][1]["blocks"][0]["source_labels"] = self._restricted("src.user.1")
        self.coordinator.config["processing_region"] = "remote"
        with self.assertRaisesRegex(_api.ContractError, "POLICY_DENIED"):
            self.coordinator.submit(request, self.trusted, wait_ms=3000, credential="token")
        self.assertEqual(self.adapter.sends, [])
