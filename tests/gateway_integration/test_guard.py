"""Component controls for final-request binding and the single-use commit."""

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import sqlite3
import unittest
import threading

import httpx

ROOT = Path(__file__).resolve().parents[2]


from ezllmrouter_server.gateway.guard import (
    ACTIVE,
    GuardRejected,
    GuardTransport,
    Invocation,
    PROVIDER_URL,
    provider_expectation,
)
from ezllmrouter_server.gateway.adapter import LiteLLMAsgiAdapter
from ezllmrouter_server.gateway.proxy_recipe import GatewayProxyRecipe, PROXY_MODEL
from ezllmrouter_server.store import SQLiteStore


def projection(text="Hi"):
    return {
        "destination": {
            "service": "litellm.dev04",
            "model": "model.demo",
            "endpoint": "127.0.0.1",
            "processing_region": "local",
        },
        "work": {
            "requested_features": ["text"],
            "generation_settings": {"max_output_tokens": 32},
            "messages": [
                {"role": "system", "blocks": [{"text": "Answer briefly."}]},
                {"role": "user", "blocks": [{"text": text}]},
            ],
        },
    }


def invocation(
    aid="attempt.one", text="Hi", fresh=None, commit=None, provider_key="sk-" + "x" * 40
):
    return Invocation(
        "submission.one",
        aid,
        {
            "plan_id": "plan.one",
            "work_digest": "sha256:test",
            "deadline": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(),
            "per_attempt_total_timeout_ms": 1000,
            "work_key": {
                "principal_id": "principal.test",
                "task_id": "task.test",
                "step_id": "step.test",
                "step_revision": 1,
                "execution_generation": "gen.1",
            },
        },
        projection(text),
        fresh or (lambda: None),
        commit or (lambda _receipt: None),
        provider_key=provider_key,
    )


class GuardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.arrivals = []

        def lower(request):
            self.arrivals.append((request.headers.get("x-ezllmrouter-attempt"), request.content))
            return httpx.Response(200, json={"ok": True})

        self.client = httpx.AsyncClient(
            transport=GuardTransport(httpx.MockTransport(lower)), timeout=1.0, trust_env=False
        )

    async def asyncTearDown(self):
        await self.client.aclose()

    async def send(self, context, body=None, url=PROVIDER_URL):
        token = ACTIVE.set(context)
        try:
            return await self.client.post(
                url,
                json=body or provider_expectation(context.projection),
                headers={"Authorization": "Bearer " + ("sk-" + "x" * 40)},
            )
        finally:
            ACTIVE.reset(token)

    async def test_blocked_database_check_leaves_response_loop_responsive(self):
        entered, release = threading.Event(), threading.Event()

        def blocked():
            entered.set()
            if not release.wait(3):
                raise AssertionError("check did not release")

        context = invocation(fresh=blocked)
        task = asyncio.create_task(self.send(context))
        try:
            for _ in range(100):
                if entered.is_set():
                    break
                await asyncio.sleep(0.001)
            self.assertTrue(entered.is_set())
            # This task executes on the same loop while the SQLite callback is blocked.
            self.assertFalse(task.done())
            await asyncio.wait_for(asyncio.sleep(0), 0.1)
        finally:
            release.set()
            await task

    async def test_worker_timeout_keys_and_sdk_headers_cannot_enter_receipt(self):
        for extra in ({"x-stainless-unreviewed": "private"},):
            context = invocation()
            token = ACTIVE.set(context)
            try:
                with self.assertRaises(GuardRejected):
                    await self.client.post(
                        PROVIDER_URL,
                        json=provider_expectation(context.projection),
                        headers={"Authorization": "Bearer " + context.provider_key, **extra},
                    )
                self.assertFalse(context.committed)
            finally:
                ACTIVE.reset(token)
        for timeout in (
            {"read": 1},
            {"connect": 1, "read": 1, "write": 1, "pool": 1, "private": 1},
            {"connect": 1, "read": float("nan"), "write": 1, "pool": 1},
        ):
            context = invocation()
            token = ACTIVE.set(context)
            try:
                with self.assertRaises(GuardRejected):
                    await self.client.post(
                        PROVIDER_URL,
                        json=provider_expectation(context.projection),
                        headers={"Authorization": "Bearer " + context.provider_key},
                        extensions={"timeout": timeout},
                    )
                self.assertFalse(context.committed)
            finally:
                ACTIVE.reset(token)
        self.assertEqual(self.arrivals, [])

    async def test_valid_final_request_commits_before_one_lower_send(self):
        sequence = []
        context = invocation(
            fresh=lambda: sequence.append("fresh"),
            commit=lambda receipt: sequence.append(("commit", receipt["attempt_id"])),
        )
        response = await self.send(context)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(sequence, ["fresh", ("commit", "attempt.one")])
        self.assertEqual([x[0] for x in self.arrivals], ["attempt.one"])
        self.assertTrue(context.committed and context.released and context.response_received)
        with self.assertRaises(GuardRejected) as raised:
            await self.send(context)
        self.assertEqual(raised.exception.code, "SECOND_SEND_REJECTED")
        self.assertEqual(len(self.arrivals), 1)

    async def test_mutated_content_and_destination_block_before_commit(self):
        for changed, url in (
            ({**provider_expectation(projection()), "model": "other"}, PROVIDER_URL),
            (provider_expectation(projection()), "http://127.0.0.1:8768/v1/chat/completions"),
        ):
            commits = []
            context = invocation(commit=commits.append)
            with self.assertRaises(GuardRejected):
                await self.send(context, changed, url)
            self.assertEqual(commits, [])
            self.assertFalse(context.released)
        self.assertEqual(self.arrivals, [])

    async def test_actual_commit_failure_and_later_success(self):
        def fail(_receipt):
            raise OSError("synthetic disk fault")

        context = invocation(commit=fail)
        with self.assertRaises(GuardRejected) as raised:
            await self.send(context)
        self.assertEqual(raised.exception.code, "INTENT_PERSIST_FAILED")
        self.assertEqual(self.arrivals, [])
        self.assertEqual((await self.send(invocation(aid="attempt.next"))).status_code, 200)
        self.assertEqual([x[0] for x in self.arrivals], ["attempt.next"])

    async def test_queued_authority_and_context_isolation(self):
        current = {"valid": False}

        def fresh():
            if not current["valid"]:
                raise GuardRejected("AUTHORITY_CHANGED")

        held = invocation(fresh=fresh)
        with self.assertRaises(GuardRejected):
            await self.send(held)
        self.assertEqual(self.arrivals, [])
        current["valid"] = True
        a = invocation(aid="attempt.a", text="A")
        b = invocation(aid="attempt.b", text="B")
        await asyncio.gather(self.send(a), self.send(b))
        self.assertEqual({x[0] for x in self.arrivals}, {"attempt.a", "attempt.b"})
        swapped = invocation(aid="attempt.swapped", text="A")
        with self.assertRaises(GuardRejected):
            await self.send(swapped, provider_expectation(projection("B")))
        self.assertEqual(len(self.arrivals), 2)

    async def test_no_context_cannot_send(self):
        with self.assertRaises(GuardRejected) as raised:
            await self.client.post(
                PROVIDER_URL,
                json=provider_expectation(projection()),
                headers={"Authorization": "Bearer " + ("sk-" + "x" * 40)},
            )
        self.assertEqual(raised.exception.code, "NO_TRUSTED_CONTEXT")
        self.assertEqual(self.arrivals, [])

    async def test_unregistered_public_model_and_final_provider_model_rejected(self):
        for model in ("openai/model.demo", "model.other", "model.demo.v2"):
            projected = projection()
            projected["destination"]["model"] = model
            with self.assertRaises(GuardRejected):
                provider_expectation(projected)
        context = invocation()
        body = {**provider_expectation(context.projection), "model": "openai/model.demo"}
        with self.assertRaises(GuardRejected):
            await self.send(context, body)
        self.assertEqual(self.arrivals, [])


class StoreGuardTests(unittest.TestCase):
    def test_durable_single_use_final_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteStore(Path(directory) / "store.sqlite")
            record = {
                "submission_id": "submission.one",
                "attempt_id": "attempt.one",
                "principal_id": "svc.test",
                "task_id": "task.test",
                "work_key": {
                    "principal_id": "svc.test",
                    "task_id": "task.test",
                    "step_id": "step.test",
                    "step_revision": 1,
                    "execution_generation": "gen.1",
                },
                "work_digest": "sha256:test",
                "status_revision": 1,
            }
            store.create(record)
            store.intent(
                "submission.one",
                "attempt.one",
                {"attempt_id": "attempt.one", "plan_id": "plan.one", "work_digest": "sha256:test"},
            )
            receipt = {
                "attempt_id": "attempt.one",
                "plan_id": "plan.one",
                "work_digest": "sha256:test",
                "body_sha256": "abc",
            }
            store.guard_commit("submission.one", "attempt.one", receipt)
            self.assertEqual(store.guard_record("attempt.one"), receipt)
            with self.assertRaises(sqlite3.IntegrityError):
                store.guard_commit(
                    "submission.one", "attempt.one", {**receipt, "body_sha256": "def"}
                )
            self.assertEqual(store.guard_record("attempt.one"), receipt)
            store.close()


class ProxyMappingTests(unittest.TestCase):
    def test_front_proxy_mapping_and_independent_provider_model(self):
        projected = projection()
        before = json.loads(json.dumps(projected))
        prepared, expected = GatewayProxyRecipe().expected(projected, 1000)
        adapter = object.__new__(LiteLLMAsgiAdapter)
        self.assertEqual(adapter.describe(prepared, 1000, projected["destination"]), expected)
        self.assertEqual(json.loads(prepared)["model"], PROXY_MODEL)
        self.assertEqual(provider_expectation(projected)["model"], "model.demo")
        self.assertEqual(projected, before)
        for model in ("openai/model.demo", "model.other", "model.demo.v2"):
            changed = json.loads(json.dumps(projected["destination"]))
            changed["model"] = model
            with self.assertRaises(ValueError):
                adapter.describe(prepared, 1000, changed)


if __name__ == "__main__":
    unittest.main()
