"""Offline component controls; fake transport is not the independent receiver."""

from tests.support import wait_for_value as wait_for_value

from copy import deepcopy as deepcopy
import hashlib as hashlib
import json as json
import os as os
from pathlib import Path as Path
import tempfile as tempfile
import threading as threading
import unittest as unittest

ROOT = Path(__file__).resolve().parents[2]


from ezllmrouter_server.canonical import ContractError as ContractError
from ezllmrouter_server.core import Coordinator as Coordinator
from ezllmrouter_server.store import SQLiteStore as SQLiteStore
from ezllmrouter_server.gateway.synthetic_recipe import (
    SyntheticDevelopmentRecipe as SyntheticDevelopmentRecipe,
)

FIXTURE = json.loads((ROOT / "tests/development_slice/fixture.json").read_text())
BASE = json.loads((ROOT / "tests/development_slice/request.json").read_text())
CORPUS = json.loads((ROOT / "tests/tool_cycle/scenarios.json").read_text())


class CapturingAuthority:
    def __init__(self):
        self.policy = deepcopy(FIXTURE["policy"])
        self.plans = []

    def issue(self, projected, wd, key, classification, retention):
        tool = "tools" in projected["work"]["requested_features"]
        plan = {
            "plan_id": "plan.test",
            "work_digest": wd,
            "work_key": key,
            "destination": deepcopy(projected["destination"]),
            "classification_snapshot": deepcopy(classification),
            "effective_retention": deepcopy(retention),
            "adapter_recipe_ref": self.policy["tool_adapter_recipe_ref"]
            if tool
            else self.policy["adapter_recipe_ref"],
            "adapter_version": self.policy["tool_adapter_version"]
            if tool
            else self.policy["adapter_version"],
            "per_attempt_total_timeout_ms": projected["work"]["generation_settings"][
                "total_timeout_ms"
            ],
            "deadline": projected["work"]["deadline"],
        }
        self.plans.append(plan)
        return plan

    def verify(self, *_args):
        return None


class FakeAdapter:
    def __init__(self):
        self.sends = []

    def prepare(self, body):
        return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()

    def describe(self, prepared, timeout, config):
        return {
            "method": "POST",
            "url": "http://receiver:8766/v1/chat/completions",
            "content_type": "application/json",
            "content_length": len(prepared),
            "body_sha256": hashlib.sha256(prepared).hexdigest(),
            "timeout_ms": timeout,
            "processing_region": config["processing_region"],
        }

    def send(self, prepared, _timeout, _expected):
        body = json.loads(prepared)
        self.sends.append(body)
        if "tools" not in body:
            return {"status": 200, "body": {"text": "Hello.", "usage": {"input_tokens": 3}}}
        if body["tool_choice"] == "none" and len(body["messages"]) == 2:
            return {"status": 200, "body": {"text": "No tool.", "usage": {"input_tokens": 4}}}
        if len(body["messages"]) == 2:
            return {
                "status": 200,
                "body": {
                    "tool_calls": [
                        {
                            "id": "call.lookup.1",
                            "name": "lookup",
                            "arguments_json": '{"key":"synthetic"}',
                        }
                    ],
                    "finish_reason": "tool_calls",
                    "usage": {"input_tokens": 5, "output_tokens": 2},
                },
            }
        result = body["messages"][3]["content"]
        value = "synthetic" if result == "value.synthetic" else json.loads(result)["value"]
        return {
            "status": 200,
            "body": {"text": "Lookup: " + value, "usage": {"input_tokens": 7, "output_tokens": 3}},
        }


from tests.tool_cycle.core_support import ToolCoreFixture


class ToolCoreTests(ToolCoreFixture, unittest.TestCase):
    def test_two_rounds_and_source_validation(self):
        from tests.tool_cycle import test_core as _api

        first = self.request()
        code, reply = self.coordinator.submit(first, self.trusted, wait_ms=3000, credential="token")
        self.assertEqual((code, reply["state"]), (200, "delivered"))
        call = reply["candidate"]["output_blocks"][0]
        self.assertEqual((call["kind"], call["arguments"]), ("tool_call", {"key": "synthetic"}))
        second = self.request("gen.2")
        second["messages"].extend(
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
        code, final = self.coordinator.submit(
            second, self.trusted, wait_ms=3000, credential="token"
        )
        self.assertEqual(
            (code, final["candidate"]["output_blocks"][0]["text"]), (200, "Lookup: synthetic")
        )
        self.assertEqual(len(self.adapter.sends), 2)
        self.assertNotEqual(reply["candidate"]["attempt_id"], final["candidate"]["attempt_id"])
        for item in (reply, final):
            status = self.coordinator.status(item["handle"]["submission_id"], self.trusted)
            self.assertEqual(status["candidate"]["candidate_id"], item["candidate"]["candidate_id"])
            self.assertEqual(status["attempts"][0]["usage"]["state"], "available")
        forged = _api.deepcopy(second)
        forged["execution_generation"] = "gen.3"
        forged["messages"][2]["blocks"][0]["arguments"]["key"] = "forged"
        with self.assertRaisesRegex(_api.ContractError, "SOURCE_INVALID"):
            self.coordinator.submit(forged, self.trusted, wait_ms=3000, credential="token")
        self.assertEqual(len(self.adapter.sends), 2)

    def test_cross_step_history_uses_authenticated_source_authority(self):
        from tests.tool_cycle import test_core as _api

        first_a = self.request()
        first_a["step_id"] = "step.a"
        _, reply_a = self.coordinator.submit(
            first_a, self.trusted, wait_ms=3000, credential="token"
        )
        call_a = reply_a["candidate"]["output_blocks"][0]
        follow_b = self.request("gen.2")
        follow_b["step_id"] = "step.b"
        follow_b["messages"].extend(
            [
                {"role": "assistant", "blocks": [call_a]},
                {
                    "role": "tool",
                    "blocks": [
                        {
                            "block_id": "block.result.1",
                            "kind": "tool_result",
                            "call_id": call_a["call_id"],
                            "result_value": {"value": "synthetic"},
                            "source_labels": _api.CORPUS["result_source_labels"],
                        }
                    ],
                },
            ]
        )
        code, final_b = self.coordinator.submit(
            follow_b, self.trusted, wait_ms=3000, credential="token"
        )
        self.assertEqual(
            (code, final_b["candidate"]["output_blocks"][0]["text"]), (200, "Lookup: synthetic")
        )
        self.assertEqual(len(self.adapter.sends), 2)
        other = _api.deepcopy(self.trusted)
        other["source_authority_id"] = "srcauth.other"
        other["context_id"] = "ctx.other"
        self.coordinator.identity["other"] = other
        forged = _api.deepcopy(follow_b)
        forged["execution_generation"] = "gen.3"
        with self.assertRaisesRegex(_api.ContractError, "SOURCE_INVALID"):
            self.coordinator.submit(forged, other, wait_ms=3000, credential="other")
        self.assertEqual(len(self.adapter.sends), 2)

    def test_same_step_repeated_generations_and_context_duplicates(self):
        from tests.tool_cycle import test_core as _api

        for first_generation, follow_generation in (("gen.1", "gen.2"), ("gen.3", "gen.4")):
            first = self.request(first_generation)
            _, reply = self.coordinator.submit(
                first, self.trusted, wait_ms=3000, credential="token"
            )
            call = reply["candidate"]["output_blocks"][0]
            follow = self.request(follow_generation)
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
            code, result = self.coordinator.submit(
                follow, self.trusted, wait_ms=3000, credential="token"
            )
            self.assertEqual(
                (code, result["candidate"]["output_blocks"][0]["text"]), (200, "Lookup: synthetic")
            )
            self.assertNotEqual(reply["candidate"]["attempt_id"], result["candidate"]["attempt_id"])
            if follow_generation == "gen.4":
                duplicate = _api.deepcopy(follow)
                duplicate["execution_generation"] = "gen.5"
                another = _api.deepcopy(call)
                another["block_id"] = "block.call.duplicate"
                duplicate["messages"][2]["blocks"].append(another)
                with self.assertRaisesRegex(_api.ContractError, "SEMANTIC_INVALID"):
                    self.coordinator.submit(
                        duplicate, self.trusted, wait_ms=3000, credential="token"
                    )
        self.assertEqual(len(self.adapter.sends), 4)
