"""Rehearse installed-Python actor decisions with controlled local replies."""

import contextlib
import io
import json
from pathlib import Path
import runpy
import shutil
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]


class ActorModes(unittest.TestCase):
    def test_dev05_modes_emit_one_json_and_no_automatic_lookup(self):
        with tempfile.TemporaryDirectory() as scratch:
            work = Path(scratch)
            for source, name in (
                (ROOT / "tests/tool_cycle/python_actor.py", "python_actor.py"),
                (ROOT / "tests/tool_cycle/scenarios.json", "scenarios.json"),
                (ROOT / "tests/development_slice/request.json", "request.json"),
            ):
                shutil.copy2(source, work / name)
            for mode, expected_sends in (
                ("cycle", 2),
                ("no_store", 2),
                ("status", 0),
                ("by_work", 0),
                ("mutation", 0),
            ):
                sends = [0]
                clock = [0.0]

                class EzLLMRouterError(Exception):
                    def __init__(self, code, status, handle=None):
                        self.code, self.http_status, self.handle = code, status, handle

                class FakeReceiver:
                    def __enter__(self):
                        return self

                    def __exit__(self, *_):
                        return False

                    def get(self, _, *, sends=sends):
                        return types.SimpleNamespace(
                            raise_for_status=lambda: None,
                            json=lambda *, sends=sends: {"arrivals": [{}] * sends[0]},
                        )

                class FakeClient:
                    def __init__(self, *_args, **_kwargs):
                        pass

                    def __enter__(self):
                        return self

                    def __exit__(self, *_):
                        return False

                    def submit(self, request, _options, *, sends=sends):
                        if request["step_id"] == "step.dev03.mutation":
                            raise EzLLMRouterError(
                                "FDC_REJECTED", 409, {"submission_id": "submission.mutation"}
                            )
                        if any(
                            block.get("arguments", {}).get("key") == "forged"
                            for message in request["messages"]
                            for block in message["blocks"]
                        ):
                            raise EzLLMRouterError("SOURCE_INVALID", 422)
                        sends[0] += 1
                        index = sends[0]
                        labels = {
                            "lineage_ids": ["src.candidate.tool"],
                            "sensitivity": "confidential",
                            "restrictions": ["no.content.store"],
                        }
                        output = (
                            [
                                {
                                    "block_id": "block.call.1",
                                    "kind": "tool_call",
                                    "call_id": "call.lookup.1",
                                    "tool_name": "lookup",
                                    "arguments": {"key": "synthetic"},
                                    "source_labels": labels,
                                }
                            ]
                            if index == 1
                            else [
                                {
                                    "kind": "assistant_text",
                                    "text": "Lookup: synthetic",
                                    "source_labels": labels,
                                }
                            ]
                        )
                        candidate = {
                            "candidate_id": f"candidate.{index}",
                            "attempt_id": f"attempt.{index}",
                            "finish_reason": "tool_calls" if index == 1 else "stop",
                            "served_destination": {
                                "configuration_ref": "cfg.demo",
                                "service": "litellm.dev04",
                                "endpoint": "127.0.0.1",
                                "model": "model.demo",
                                "model_version": "v1",
                                "processing_region": "local",
                            },
                            "output_blocks": output,
                        }
                        self.candidates = getattr(self, "candidates", {})
                        self.candidates[f"submission.{index}"] = candidate
                        return {
                            "state": "delivered",
                            "handle": {"submission_id": f"submission.{index}"},
                            "candidate": candidate,
                        }

                    def getStatus(self, selector, *, mode=mode):
                        sid = selector.get("submission_id", "submission.1")
                        if sid == "submission.mutation":
                            return {"submission_state": "failed_before_transmit"}
                        candidate = getattr(self, "candidates", {}).get(sid)
                        if candidate is None:
                            candidate = {
                                "candidate_id": "candidate.1",
                                "attempt_id": "attempt.1",
                                "output_blocks": [{"kind": "tool_call"}],
                            }
                        value = {
                            "candidate_access": "not_retained" if mode == "no_store" else "present",
                            "handle": {"submission_id": sid},
                            "attempts": [
                                {
                                    "usage": {
                                        "state": "available",
                                        "revision": {"attempt_id": candidate["attempt_id"]},
                                    }
                                }
                            ],
                        }
                        if mode != "no_store":
                            value["candidate"] = candidate
                        return value

                    def getCapabilities(self):
                        return {"contract_version": "0.2"}

                fake_httpx = types.ModuleType("httpx")
                fake_httpx.Client = lambda **_kwargs: FakeReceiver()
                fake_client = types.ModuleType("ezllmrouter_client")
                fake_client.EzLLMRouterClient = FakeClient
                fake_client.EzLLMRouterError = EzLLMRouterError
                stdout, stderr = io.StringIO(), io.StringIO()
                argv = [str(work / "python_actor.py"), mode]
                if mode == "status":
                    argv.append("submission.1")
                if mode == "by_work":
                    argv.extend(("step.dev03.js", "gen.1", "tool_call"))

                def fake_sleep(duration, *, clock=clock):
                    clock[0] += duration

                with (
                    patch.dict(
                        sys.modules, {"httpx": fake_httpx, "ezllmrouter_client": fake_client}
                    ),
                    patch.object(sys, "argv", argv),
                    patch.dict(
                        "os.environ",
                        {
                            "EZLLMROUTER_SERVICE_URL": "http://service.invalid",
                            "EZLLMROUTER_RECEIVER_URL": "http://receiver.invalid",
                            "EZLLMROUTER_DEV_TOKEN": "synthetic",
                        },
                    ),
                    patch.object(time, "sleep", fake_sleep),
                    patch.object(time, "monotonic", lambda *, clock=clock: clock[0]),
                    contextlib.redirect_stdout(stdout),
                    contextlib.redirect_stderr(stderr),
                ):
                    runpy.run_path(str(work / "python_actor.py"), run_name="__main__")
                self.assertEqual(stderr.getvalue(), "")
                value = json.loads(stdout.getvalue())
                self.assertEqual(value["actor"], "python")
                self.assertEqual(sends[0], expected_sends)
                self.assertEqual(value["provider_sends_delta"], expected_sends)
                self.assertEqual(value["caller_tool_executions"], 1 if expected_sends else 0)
                if mode in ("no_store", "mutation"):
                    self.assertGreaterEqual(value["negative_stable_ms"], 5000)


if __name__ == "__main__":
    unittest.main()
