"""ToolTransportTests behaviour regressions."""

from __future__ import annotations

import unittest
from tests.tool_cycle.core_support import ToolCoreFixture


class ToolTransportTests(ToolCoreFixture, unittest.TestCase):
    def test_tool_preparation_mutation_never_commits_intent_or_sends(self):
        self.coordinator.faults["mutate_after_binding"] = lambda raw: raw.replace(
            b'"tool_choice":"auto"', b'"tool_choice":"none"'
        )
        code, reply = self.coordinator.submit(
            self.request(), self.trusted, wait_ms=3000, credential="token"
        )
        self.assertEqual(
            (code, reply["state"], reply["error"]["code"]), (409, "failed", "FDC_REJECTED")
        )
        self.assertEqual(self.store.intent_count(reply["handle"]["submission_id"]), 0)
        self.assertEqual(self.adapter.sends, [])

    def test_malformed_tool_response_is_unusable_after_send(self):
        from tests.tool_cycle import test_core as _api

        def malformed(prepared, _timeout, _expected):
            self.adapter.sends.append(_api.json.loads(prepared))
            return {
                "status": 200,
                "body": {
                    "tool_calls": [
                        {
                            "id": "call.lookup.1",
                            "name": "lookup",
                            "arguments_json": '{"key":"synthetic"}',
                        },
                        {
                            "id": "call.lookup.1",
                            "name": "lookup",
                            "arguments_json": '{"key":"synthetic"}',
                        },
                    ],
                    "finish_reason": "tool_calls",
                },
            }

        self.adapter.send = malformed
        code, reply = self.coordinator.submit(
            self.request(), self.trusted, wait_ms=3000, credential="token"
        )
        self.assertEqual(
            (code, reply["state"], reply["error"]["code"]), (502, "failed", "CANDIDATE_UNUSABLE")
        )
        self.assertEqual(len(self.adapter.sends), 1)
        status = self.coordinator.status(reply["handle"]["submission_id"], self.trusted)
        self.assertEqual(status["candidate_access"], "unavailable_due_failure")
        self.assertNotIn("candidate", status)

    def test_two_ordered_calls_and_results_preserve_transport_order(self):
        from tests.tool_cycle import test_core as _api

        def two_calls(prepared, _timeout, _expected):
            body = _api.json.loads(prepared)
            self.adapter.sends.append(body)
            if len(body["messages"]) == 2:
                return {
                    "status": 200,
                    "body": {
                        "tool_calls": [
                            {
                                "id": "call.lookup.1",
                                "name": "lookup",
                                "arguments_json": '{"key":"synthetic"}',
                            },
                            {
                                "id": "call.lookup.2",
                                "name": "lookup",
                                "arguments_json": '{"key":"synthetic"}',
                            },
                        ],
                        "finish_reason": "tool_calls",
                    },
                }
            self.assertEqual(
                [m["role"] for m in body["messages"]],
                ["system", "user", "assistant", "tool", "tool"],
            )
            self.assertEqual(
                [m["tool_call_id"] for m in body["messages"][3:]],
                ["call.lookup.1", "call.lookup.2"],
            )
            return {"status": 200, "body": {"text": "Lookup: synthetic"}}

        self.adapter.send = two_calls
        first = self.request()
        _, reply = self.coordinator.submit(first, self.trusted, wait_ms=3000, credential="token")
        calls = reply["candidate"]["output_blocks"]
        self.assertEqual([b["call_id"] for b in calls], ["call.lookup.1", "call.lookup.2"])
        follow = self.request("gen.2")
        follow["messages"].extend(
            [
                {"role": "assistant", "blocks": calls},
                {
                    "role": "tool",
                    "blocks": [
                        {
                            "block_id": f"block.result.{i}",
                            "kind": "tool_result",
                            "call_id": call["call_id"],
                            "result_value": {"value": "synthetic"},
                            "source_labels": _api.CORPUS["result_source_labels"],
                        }
                        for i, call in enumerate(calls, 1)
                    ],
                },
            ]
        )
        code, final = self.coordinator.submit(
            follow, self.trusted, wait_ms=3000, credential="token"
        )
        self.assertEqual(
            (code, final["candidate"]["output_blocks"][0]["text"]), (200, "Lookup: synthetic")
        )
        self.assertEqual(len(self.adapter.sends), 2)

    def test_tool_work_and_prepared_digest_parity_across_separate_stores(self):
        from tests.tool_cycle import test_core as _api

        request = self.request()
        _, first = self.coordinator.submit(request, self.trusted, wait_ms=3000, credential="token")
        first_digest = self.store.get(first["handle"]["submission_id"])["work_digest"]
        first_prepared = self.adapter.sends[0]
        second_store = _api.SQLiteStore(_api.Path(self.temp.name) / "parity.sqlite")
        second_adapter, second_authority = _api.FakeAdapter(), _api.CapturingAuthority()
        second = _api.Coordinator(
            second_store,
            identity={"token": _api.deepcopy(self.trusted)},
            config=_api.deepcopy(self.coordinator.config),
            prompt_blocks=_api.deepcopy(self.coordinator.prompt_blocks),
            allowed_lineages=_api.deepcopy(self.coordinator.allowed_lineages),
            authority=second_authority,
            adapter=second_adapter,
            retention=_api.deepcopy(self.coordinator.retention),
            classification=_api.deepcopy(self.coordinator.classification),
            recipe=_api.SyntheticDevelopmentRecipe(),
            trusted_source_labels=_api.deepcopy(self.coordinator.trusted_source_labels),
        )
        try:
            code, reply = second.submit(
                _api.deepcopy(request), second.identity["token"], wait_ms=3000, credential="token"
            )
            self.assertEqual(code, 200)
            second_digest = second_store.get(reply["handle"]["submission_id"])["work_digest"]
            self.assertEqual(second_digest, first_digest)
            self.assertEqual(second_adapter.sends[0], first_prepared)

            def follow(call):
                value = _api.deepcopy(request)
                value["execution_generation"] = "gen.2"
                value["messages"].extend(
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
                return value

            _, first_final = self.coordinator.submit(
                follow(first["candidate"]["output_blocks"][0]),
                self.trusted,
                wait_ms=3000,
                credential="token",
            )
            _, second_final = second.submit(
                follow(reply["candidate"]["output_blocks"][0]),
                second.identity["token"],
                wait_ms=3000,
                credential="token",
            )
            self.assertEqual(
                self.store.get(first_final["handle"]["submission_id"])["work_digest"],
                second_store.get(second_final["handle"]["submission_id"])["work_digest"],
            )
            self.assertEqual(self.adapter.sends[1], second_adapter.sends[1])
            changed = _api.deepcopy(request)
            changed["execution_generation"] = "gen.3"
            changed["messages"][1]["blocks"][0]["text"] = "Use lookup for another synthetic prompt."
            code, other = second.submit(
                changed, second.identity["token"], wait_ms=3000, credential="token"
            )
            self.assertEqual(code, 200)
            self.assertNotEqual(
                second_store.get(other["handle"]["submission_id"])["work_digest"], first_digest
            )
        finally:
            second.pool.shutdown(wait=True)
            second_store.close()

    def test_text_regression(self):
        from tests.tool_cycle import test_core as _api

        code, reply = self.coordinator.submit(
            _api.BASE, self.trusted, wait_ms=3000, credential="token"
        )
        self.assertEqual((code, reply["candidate"]["output_blocks"][0]["text"]), (200, "Hello."))
        self.assertEqual(len(self.adapter.sends), 1)

    def test_pre_dispatch_capability_and_pairing(self):
        from tests.tool_cycle import test_core as _api

        request = self.request()
        request["requested_features"] = ["text"]
        with self.assertRaisesRegex(_api.ContractError, "SEMANTIC_INVALID"):
            self.coordinator.submit(request, self.trusted, credential="token")
        request = self.request()
        request["tool_choice"] = "required"
        with self.assertRaisesRegex(_api.ContractError, "CAPABILITY_UNSUPPORTED"):
            self.coordinator.submit(request, self.trusted, credential="token")
        request = self.request()
        request["messages"].append(
            {
                "role": "tool",
                "blocks": [
                    {
                        "block_id": "block.result.1",
                        "kind": "tool_result",
                        "call_id": "call.unknown",
                        "result_text": "value.synthetic",
                        "source_labels": _api.CORPUS["result_source_labels"],
                    }
                ],
            }
        )
        with self.assertRaisesRegex(_api.ContractError, "SEMANTIC_INVALID"):
            self.coordinator.submit(request, self.trusted, credential="token")
        self.assertEqual(self.adapter.sends, [])

    def test_none_choice_is_preserved(self):
        request = self.request()
        request["tool_choice"] = "none"
        code, reply = self.coordinator.submit(
            request, self.trusted, wait_ms=3000, credential="token"
        )
        self.assertEqual((code, reply["candidate"]["output_blocks"][0]["text"]), (200, "No tool."))
        self.assertEqual(self.adapter.sends[0]["tool_choice"], "none")
