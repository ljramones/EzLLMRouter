"""The frozen worker discriminator reports an early failure without request data."""
import asyncio
import base64
import json
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests/gateway_integration"))
import test_provider_worker_target as target


class WorkerDiagnosticTests(unittest.TestCase):
    def test_selected_responses_passes_pinned_handler_and_attempt(self):
        from choice_b_worker import Worker, WORKER_KEY
        relay = object()
        worker = Worker.__new__(Worker)
        worker.client = SimpleNamespace(_transport=relay)
        worker.responses_handler = SimpleNamespace(client=SimpleNamespace(_transport=relay))
        called = []

        async def aresponses(**kwargs):
            called.append(kwargs)
            return SimpleNamespace(model_dump=lambda mode: {"object": "response", "output": []})

        fake_litellm = SimpleNamespace(aresponses=aresponses, aclient_session=worker.client)
        body = {"model": "openai/test-response-model", "input": "Hi", "store": False,
                "stream": False, "max_retries": 0, "api_base": "https://api.openai.com/v1"}
        envelope = {"kind": "selected_request", "route": "responses",
                    "attempt_id": "attempt.selected.test", "prepared_b64":
                        base64.b64encode(json.dumps(body).encode()).decode()}
        with patch.dict(sys.modules, {"litellm": fake_litellm}):
            result = asyncio.run(worker._selected(envelope))
        self.assertEqual(result["status"], 200)
        self.assertEqual(len(called), 1)
        self.assertIs(called[0]["client"], worker.responses_handler)
        self.assertEqual(called[0]["extra_headers"],
                         {"X-Duranki-Attempt": envelope["attempt_id"]})
        self.assertEqual(called[0]["api_key"], WORKER_KEY)

    def test_early_failure_names_exception_but_not_message(self):
        class FailingWorker:
            def dispatch(self, _envelope):
                raise ValueError("secret-canary-request-data")

        with patch.object(target, "Worker", FailingWorker), patch.object(
                target.CapturedRelay, "requests", []), patch.dict(
                target.os.environ, {"DURANKI_DEV_TOKEN": "", "DURANKI_DEV04_PROVIDER_KEY": ""}):
            with self.assertRaises(AssertionError) as caught:
                target.main()
        diagnostic = str(caught.exception)
        self.assertIn('"captured_requests": 0', diagnostic)
        self.assertIn('"exception_types": ["ValueError"]', diagnostic)
        self.assertNotIn("secret-canary", diagnostic)


if __name__ == "__main__":
    unittest.main()
