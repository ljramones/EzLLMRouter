"""Offline component controls; fake transport is not the independent receiver."""

from tests.support import wait_for_value

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]


from ezllmrouter_server.canonical import ContractError
from ezllmrouter_server.core import Coordinator
from ezllmrouter_server.store import SQLiteStore
from ezllmrouter_server.gateway.synthetic_recipe import SyntheticDevelopmentRecipe

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


class ToolCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            prefix="core-", dir=os.environ.get("EZLLMROUTER_TEST_SCRATCH")
        )
        self.store = SQLiteStore(Path(self.temp.name) / "store.sqlite")
        self.adapter = FakeAdapter()
        self.trusted = deepcopy(FIXTURE["trusted_context"])
        self.authority = CapturingAuthority()
        self.coordinator = Coordinator(
            self.store,
            identity={"token": self.trusted},
            config=deepcopy(FIXTURE["destination"]),
            prompt_blocks=deepcopy(FIXTURE["prompt_blocks"]),
            allowed_lineages=deepcopy(FIXTURE["allowed_lineages"]),
            authority=self.authority,
            adapter=self.adapter,
            retention=deepcopy(FIXTURE["retention"]),
            classification=deepcopy(FIXTURE["classification"]),
            recipe=SyntheticDevelopmentRecipe(),
            trusted_source_labels=deepcopy(FIXTURE["trusted_source_labels"]),
        )

    def tearDown(self):
        self.coordinator.pool.shutdown(wait=True)
        self.store.close()
        self.temp.cleanup()

    def request(self, generation="gen.1"):
        value = deepcopy(BASE)
        value.update(
            step_id="step.component",
            execution_generation=generation,
            requested_features=["text", "tools"],
            tool_definitions=[deepcopy(CORPUS["tool_definition"])],
            tool_choice="auto",
        )
        value["messages"][1]["blocks"][0]["text"] = "Use lookup for synthetic."
        return value

    def test_two_rounds_and_source_validation(self):
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
                            "source_labels": CORPUS["result_source_labels"],
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
        forged = deepcopy(second)
        forged["execution_generation"] = "gen.3"
        forged["messages"][2]["blocks"][0]["arguments"]["key"] = "forged"
        with self.assertRaisesRegex(ContractError, "SOURCE_INVALID"):
            self.coordinator.submit(forged, self.trusted, wait_ms=3000, credential="token")
        self.assertEqual(len(self.adapter.sends), 2)

    def test_cross_step_history_uses_authenticated_source_authority(self):
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
                            "source_labels": CORPUS["result_source_labels"],
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
        other = deepcopy(self.trusted)
        other["source_authority_id"] = "srcauth.other"
        other["context_id"] = "ctx.other"
        self.coordinator.identity["other"] = other
        forged = deepcopy(follow_b)
        forged["execution_generation"] = "gen.3"
        with self.assertRaisesRegex(ContractError, "SOURCE_INVALID"):
            self.coordinator.submit(forged, other, wait_ms=3000, credential="other")
        self.assertEqual(len(self.adapter.sends), 2)

    def test_same_step_repeated_generations_and_context_duplicates(self):
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
                                "source_labels": CORPUS["result_source_labels"],
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
                duplicate = deepcopy(follow)
                duplicate["execution_generation"] = "gen.5"
                another = deepcopy(call)
                another["block_id"] = "block.call.duplicate"
                duplicate["messages"][2]["blocks"].append(another)
                with self.assertRaisesRegex(ContractError, "SEMANTIC_INVALID"):
                    self.coordinator.submit(
                        duplicate, self.trusted, wait_ms=3000, credential="token"
                    )
        self.assertEqual(len(self.adapter.sends), 4)

    def _restricted(self, lineage):
        labels = {
            "lineage_ids": [lineage],
            "sensitivity": "confidential",
            "restrictions": ["no.content.store"],
        }
        self.coordinator.trusted_source_labels[lineage] = labels
        return labels

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
        self.assertNotIn(call["call_id"], json.dumps(record))
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
                            "source_labels": CORPUS["result_source_labels"],
                        }
                    ],
                },
            ]
        )
        forged = deepcopy(follow)
        forged["execution_generation"] = "gen.3"
        forged["messages"][2]["blocks"][0]["arguments"]["key"] = "forged"
        with self.assertRaisesRegex(ContractError, "SOURCE_INVALID"):
            self.coordinator.submit(forged, self.trusted, wait_ms=3000, credential="token")
        relabeled = deepcopy(follow)
        relabeled["execution_generation"] = "gen.4"
        relabeled["messages"][2]["blocks"][0]["source_labels"]["restrictions"] = []
        with self.assertRaisesRegex(ContractError, "SOURCE_INVALID"):
            self.coordinator.submit(relabeled, self.trusted, wait_ms=3000, credential="token")
        other = deepcopy(self.trusted)
        other["context_id"] = "ctx.other"
        other["source_authority_id"] = "srcauth.other"
        self.coordinator.identity["other"] = other
        cross_scope = deepcopy(follow)
        cross_scope["execution_generation"] = "gen.5"
        with self.assertRaisesRegex(ContractError, "SOURCE_INVALID"):
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
        replacement = Coordinator(
            self.store,
            identity=self.coordinator.identity,
            config=deepcopy(self.coordinator.config),
            prompt_blocks=deepcopy(self.coordinator.prompt_blocks),
            allowed_lineages=deepcopy(self.coordinator.allowed_lineages),
            authority=self.authority,
            adapter=self.adapter,
            retention=deepcopy(self.coordinator.retention),
            classification=deepcopy(self.coordinator.classification),
            recipe=SyntheticDevelopmentRecipe(),
            trusted_source_labels=deepcopy(self.coordinator.trusted_source_labels),
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
        request = self.request()
        labels = {
            "lineage_ids": ["src.user.1"],
            "sensitivity": "confidential",
            "restrictions": ["client.demo.only"],
        }
        self.coordinator.trusted_source_labels["src.user.1"] = labels
        request["messages"][1]["blocks"][0]["source_labels"] = labels
        with self.assertRaisesRegex(ContractError, "POLICY_DENIED"):
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
        request = self.request()
        request["messages"][1]["blocks"][0]["source_labels"] = self._restricted("src.user.1")
        self.coordinator.config["processing_region"] = "remote"
        with self.assertRaisesRegex(ContractError, "POLICY_DENIED"):
            self.coordinator.submit(request, self.trusted, wait_ms=3000, credential="token")
        self.assertEqual(self.adapter.sends, [])

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
        self.coordinator.classification.update(
            sensitivity="confidential", combined_restrictions=["no.content.store"]
        )
        entered, release = threading.Event(), threading.Event()
        original_send = self.adapter.send

        def delayed(*args):
            entered.set()
            self.assertTrue(release.wait(2))
            return original_send(*args)

        self.adapter.send = delayed
        outcome = []
        worker = threading.Thread(
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
        entered, release, tighten = threading.Event(), threading.Event(), threading.Event()
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

        worker = threading.Thread(target=tighten_policy)
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
        status = wait_for_value(
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
        entered, release = threading.Event(), threading.Event()
        first_read, changed = threading.Event(), threading.Event()
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
        worker = threading.Thread(target=tighten_after_first_read)
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
        status = wait_for_value(
            lambda: self.coordinator.status(sid, self.trusted),
            lambda status: status["submission_state"] == "completed",
        )
        self.assertEqual(status["candidate_access"], "present")

    def test_stricter_current_handling_applies_to_live_output_and_store(self):
        entered, release = threading.Event(), threading.Event()
        original_send = self.adapter.send

        def delayed(*args):
            entered.set()
            self.assertTrue(release.wait(2))
            return original_send(*args)

        self.adapter.send = delayed
        outcome = []
        worker = threading.Thread(
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
        self.coordinator.classification.update(
            sensitivity="confidential", combined_restrictions=["no.content.store"]
        )
        entered, release = threading.Event(), threading.Event()
        original_send = self.adapter.send

        def delayed(*args):
            entered.set()
            self.assertTrue(release.wait(2))
            original_send(*args)
            return {"status": 200, "body": {"text": "Synthetic final text."}}

        self.adapter.send = delayed
        outcome = []
        worker = threading.Thread(
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
        def malformed(prepared, _timeout, _expected):
            self.adapter.sends.append(json.loads(prepared))
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
        def two_calls(prepared, _timeout, _expected):
            body = json.loads(prepared)
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
                            "source_labels": CORPUS["result_source_labels"],
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
        request = self.request()
        _, first = self.coordinator.submit(request, self.trusted, wait_ms=3000, credential="token")
        first_digest = self.store.get(first["handle"]["submission_id"])["work_digest"]
        first_prepared = self.adapter.sends[0]
        second_store = SQLiteStore(Path(self.temp.name) / "parity.sqlite")
        second_adapter, second_authority = FakeAdapter(), CapturingAuthority()
        second = Coordinator(
            second_store,
            identity={"token": deepcopy(self.trusted)},
            config=deepcopy(self.coordinator.config),
            prompt_blocks=deepcopy(self.coordinator.prompt_blocks),
            allowed_lineages=deepcopy(self.coordinator.allowed_lineages),
            authority=second_authority,
            adapter=second_adapter,
            retention=deepcopy(self.coordinator.retention),
            classification=deepcopy(self.coordinator.classification),
            recipe=SyntheticDevelopmentRecipe(),
            trusted_source_labels=deepcopy(self.coordinator.trusted_source_labels),
        )
        try:
            code, reply = second.submit(
                deepcopy(request), second.identity["token"], wait_ms=3000, credential="token"
            )
            self.assertEqual(code, 200)
            second_digest = second_store.get(reply["handle"]["submission_id"])["work_digest"]
            self.assertEqual(second_digest, first_digest)
            self.assertEqual(second_adapter.sends[0], first_prepared)

            def follow(call):
                value = deepcopy(request)
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
                                    "source_labels": CORPUS["result_source_labels"],
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
            changed = deepcopy(request)
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

    def test_source_no_store_wait_expiry_is_metadata_only(self):
        request = self.request()
        request["messages"][1]["blocks"][0]["source_labels"] = self._restricted("src.user.1")
        gate = threading.Event()
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
        status = wait_for_value(
            lambda: self.coordinator.status(pending["handle"]["submission_id"], self.trusted),
            lambda status: status["submission_state"] == "completed",
        )
        self.assertEqual(status["candidate_access"], "not_retained")
        self.assertEqual(status["result_unavailable_reason"], "wait_expired_no_store")
        self.assertNotIn("candidate", status)

    def test_text_regression(self):
        code, reply = self.coordinator.submit(BASE, self.trusted, wait_ms=3000, credential="token")
        self.assertEqual((code, reply["candidate"]["output_blocks"][0]["text"]), (200, "Hello."))
        self.assertEqual(len(self.adapter.sends), 1)

    def test_pre_dispatch_capability_and_pairing(self):
        request = self.request()
        request["requested_features"] = ["text"]
        with self.assertRaisesRegex(ContractError, "SEMANTIC_INVALID"):
            self.coordinator.submit(request, self.trusted, credential="token")
        request = self.request()
        request["tool_choice"] = "required"
        with self.assertRaisesRegex(ContractError, "CAPABILITY_UNSUPPORTED"):
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
                        "source_labels": CORPUS["result_source_labels"],
                    }
                ],
            }
        )
        with self.assertRaisesRegex(ContractError, "SEMANTIC_INVALID"):
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


if __name__ == "__main__":
    unittest.main()
