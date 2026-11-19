"""Fixed installed-client caller behavior without network or package acquisition."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, os.environ.get("EZLLMROUTER_OPERATOR_SOURCE_ROOT", str(ROOT / "server/src")))
from ezllmrouter_server.operator_demo import DemoRunner, ProviderValidationRunner


class FakeClient:
    requests = []

    def __init__(self, _url, _token):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def submit(self, request, options):
        assert options == {"wait_ms": 3000}
        request = deepcopy(request)
        self.requests.append(request)
        sid = "submission." + str(len(self.requests))
        if request.get("tool_definitions") and len(request["messages"]) == 2:
            candidate = {"finish_reason": "tool_calls", "output_blocks": [{"kind": "tool_call",
                "tool_name": "lookup", "arguments": {"key": "synthetic"}, "call_id": "call.lookup.1"}]}
        else:
            candidate = {"finish_reason": "stop", "output_blocks": [{"kind": "content_text",
                "text": "DO_NOT_EXPORT"}]}
        return {"state": "delivered", "handle": {"submission_id": sid}, "candidate": candidate}


class DemoTests(unittest.TestCase):
    def setUp(self):
        FakeClient.requests = []
        base = json.loads((ROOT / "tests/development_slice/request.json").read_text())
        scenarios = json.loads((ROOT / "tests/tool_cycle/scenarios.json").read_text())
        self.runner = DemoRunner(base, scenarios, "http://127.0.0.1:8773", "synthetic-token",
                                 client_factory=FakeClient)

    def test_explicit_text_tool_and_no_store_inventory(self):
        handles = []
        text = self.runner.run("text", handles.append)
        tool = self.runner.run("tool", handles.append)
        no_store = self.runner.run("no_store_text", handles.append)
        self.assertEqual([len(text["submission_ids"]), len(tool["submission_ids"]),
                          len(no_store["submission_ids"])], [1, 2, 1])
        self.assertEqual(tool["caller_lookups"], 1)
        self.assertEqual(len(FakeClient.requests), 4)
        self.assertEqual(len(handles), 4)
        self.assertNotEqual(FakeClient.requests[1]["execution_generation"],
                            FakeClient.requests[2]["execution_generation"])
        self.assertEqual(FakeClient.requests[2]["messages"][-1]["blocks"][0]["result_value"],
                         {"value": "synthetic"})
        self.assertEqual(FakeClient.requests[3]["messages"][1]["blocks"][0]
                         ["source_labels"]["restrictions"], ["no.content.store"])
        self.assertNotIn("DO_NOT_EXPORT", json.dumps((text, tool, no_store)))

    def test_only_fixed_scenarios(self):
        with self.assertRaises(ValueError):
            self.runner.run("arbitrary", lambda _sid: None)
        self.assertEqual(FakeClient.requests, [])

    def test_provider_validation_is_one_fixed_bounded_client_request(self):
        class Client:
            requests = []

            def __init__(self, *_):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

            def submit(self, request, options):
                self.requests.append((deepcopy(request), options))
                return {"state": "delivered", "handle": {"submission_id": "submission.provider.test"},
                        "candidate": {"output_blocks": [{"kind": "content_text", "text": "hello"}]}}

        fixture = json.loads((ROOT / "tests/development_slice/request.json").read_text())
        runner = ProviderValidationRunner(fixture, "http://127.0.0.1:8773", "test-token",
                                          "svc.demo", client_factory=Client)
        handles = []
        self.assertEqual(runner.run("cfg.provider.test", "op.provider.test", 16, handles.append),
                         {"state": "completed", "candidate": {"output_blocks": [
                             {"kind": "content_text", "text": "hello"}]}})
        self.assertEqual(handles, ["submission.provider.test"])
        self.assertEqual(len(Client.requests), 1)
        request, options = Client.requests[0]
        self.assertEqual(options, {"wait_ms": 15000})
        self.assertEqual(request["requested_configuration_ref"], "cfg.provider.test")
        self.assertEqual(request["generation_settings"]["max_output_tokens"], 16)
        self.assertEqual(request["generation_settings"]["total_timeout_ms"], 10000)
        self.assertEqual(request["messages"][1]["blocks"][0]["text"], "Say hello.")
        self.assertEqual(request["requested_features"], ["text"])
        self.assertNotIn("tool_definitions", request)
        self.assertEqual(fixture["requested_configuration_ref"], "cfg.demo")
        with self.assertRaises(ValueError):
            runner.run("cfg.provider.test", "op.provider.second", 33, handles.append)
        self.assertEqual(len(Client.requests), 1)


if __name__ == "__main__":
    unittest.main()
