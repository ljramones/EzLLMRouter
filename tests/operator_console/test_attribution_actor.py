"""Exercise the exact staged actor's private-input and one-JSON consumer path."""

import contextlib
import io
import json
from pathlib import Path
import runpy
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
TOKEN = "synthetic-dev07-private-token-00000000000000000000000"


class ActorOutputTests(unittest.TestCase):
    def test_pending_and_status_outputs_are_one_safe_json_document(self):
        with tempfile.TemporaryDirectory() as scratch:
            target = Path(scratch)
            for source, name in (
                ("tools/gateway/evidence/dev07_actor.py", "dev07_actor.py"),
                ("tests/development_slice/request.json", "request.json"),
                ("tests/tool_cycle/scenarios.json", "scenarios.json"),
            ):
                shutil.copy2(ROOT / source, target / name)
            calls = []

            class FakeClient:
                def __init__(self, _url, token):
                    self.token = token

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

                def submit(self, request, options):
                    calls.append((request, options, self.token))
                    return {"state": "pending", "handle": {"submission_id": "submission.dev07.1"}}

                def getStatus(self, selector):
                    self.status_selector = selector
                    return {
                        "submission_state": "failed_before_transmit",
                        "candidate_access": "unavailable_due_failure",
                        "attempts": [
                            {"attempt_id": "attempt.dev07.1", "dispatch_state": "prepared"}
                        ],
                        "terminal_failure": {"code": "FDC_REJECTED"},
                    }

            fake = types.ModuleType("ezllmrouter_client")
            fake.EzLLMRouterClient = FakeClient
            fake.EzLLMRouterError = type("EzLLMRouterError", (Exception,), {})
            for input_value, expected_kind in (
                (
                    {
                        "token": TOKEN,
                        "configuration_ref": "cfg.dev07.a",
                        "step_id": "step.dev07.1",
                        "generation": "gen.dev07.1",
                        "mode": "pending_hold",
                    },
                    "pending_hold",
                ),
                (
                    {"token": TOKEN, "mode": "status", "submission_id": "submission.dev07.1"},
                    "status",
                ),
            ):
                stdout, stderr = io.StringIO(), io.StringIO()
                with (
                    patch.dict(sys.modules, {"ezllmrouter_client": fake}),
                    patch.object(sys, "stdin", io.StringIO(json.dumps(input_value))),
                    contextlib.redirect_stdout(stdout),
                    contextlib.redirect_stderr(stderr),
                ):
                    runpy.run_path(str(target / "dev07_actor.py"), run_name="__main__")
                self.assertEqual(stderr.getvalue(), "")
                result = json.loads(stdout.getvalue())
                self.assertEqual(result["kind"], expected_kind)
                self.assertNotIn(TOKEN, stdout.getvalue())
                self.assertEqual(len(stdout.getvalue().splitlines()), 1)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][1], {"wait_ms": 0})
            self.assertEqual(calls[0][0]["messages"][1]["blocks"][0]["text"], "Simulate hold")
            self.assertEqual(calls[0][0]["generation_settings"]["total_timeout_ms"], 30000)


if __name__ == "__main__":
    unittest.main()
