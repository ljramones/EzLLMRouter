"""Independent final Responses request guard beside the existing synthetic guard."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import unittest

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/src"))
sys.path.insert(0, str(ROOT / "tests/gateway_integration"))
sys.path.insert(0, str(ROOT / "tests/development_slice"))
from guard import ACTIVE, GuardRejected, GuardTransport, Invocation
from proxy_recipe import GatewayProxyRecipe


class Lower(httpx.AsyncBaseTransport):
    def __init__(self):
        self.requests = []
    async def handle_async_request(self, request):
        self.requests.append(request)
        return httpx.Response(200, json={"object": "response", "output": []}, request=request)


class ProviderGuardTests(unittest.TestCase):
    def setUp(self):
        self.work = json.loads((ROOT / "tests/development_slice/request.json").read_text())
        self.destination = {"configuration_ref": "cfg.provider.guard", "service": "openai.responses.v1",
            "endpoint": "https://api.openai.com", "model": "model-test", "model_version": "v1",
            "processing_region": "test", "connection_id": "conn.guard", "connection_revision": 2,
            "credential_version": 1, "adapter_id": "openai.responses.v1", "deployment_id": "deployment.guard"}
        self.projected = {"work": self.work, "destination": self.destination}
        self.plan = {"plan_id": "plan.guard", "work_digest": "sha256:test", "deadline":
            (datetime.now(timezone.utc) + timedelta(seconds=20)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "per_attempt_total_timeout_ms": 3000, "destination": self.destination}
        self.key = "test-provider-key-123456"

    def request(self, **changes):
        private, _ = GatewayProxyRecipe().expected(self.projected, 3000)
        body = json.loads(private)
        actual = {k: v for k, v in body.items() if k not in ("api_base", "max_retries", "timeout")}
        actual["model"] = self.destination["model"]
        actual.update(changes)
        return httpx.Request("POST", "https://api.openai.com/v1/responses",
            headers={"Authorization": "Bearer " + self.key, "Content-Type": "application/json"},
            content=json.dumps(actual, separators=(",", ":")).encode(),
            extensions={"timeout": {"connect": 3.0, "read": 3.0, "write": 3.0, "pool": 3.0}})

    def test_exact_request_commits_once_and_wrong_protocol_never_reaches_lower(self):
        async def run():
            lower = Lower()
            receipts = []
            guard = GuardTransport(lower)
            invocation = Invocation("submission.guard", "attempt.guard", self.plan, self.projected,
                lambda: None, receipts.append, provider_key=self.key)
            token = ACTIVE.set(invocation)
            try:
                response = await guard.handle_async_request(self.request())
                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(receipts), 1)
                self.assertEqual(receipts[0]["recipe_version"], "recipe.dev08.openai.responses.text.v1")
                self.assertEqual(len(lower.requests), 1)
                with self.assertRaises(GuardRejected):
                    await guard.handle_async_request(self.request())
            finally:
                ACTIVE.reset(token)
            for mutation in ({"store": True}, {"messages": [{"role": "user", "content": "wrong family"}]},
                             {"model": "other-model"}):
                invocation = Invocation("submission.guard", "attempt." + str(len(lower.requests)),
                    self.plan, self.projected, lambda: None, receipts.append, provider_key=self.key)
                token = ACTIVE.set(invocation)
                try:
                    with self.assertRaises(GuardRejected):
                        await guard.handle_async_request(self.request(**mutation))
                finally:
                    ACTIVE.reset(token)
            self.assertEqual(len(lower.requests), 1)
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
