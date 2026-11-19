"""Independent receiver parser controls using manually constructed transport data."""
import importlib.util
import os
from pathlib import Path
import unittest

os.environ.setdefault("EZLLMROUTER_RECEIVER_LOG", "/private/tmp/ezllmrouter-dev-03/run-20261018-01/receiver-test-unused.jsonl")
path = Path(__file__).resolve().parents[1] / "development_slice/receiver.py"
spec = importlib.util.spec_from_file_location("synthetic_receiver_test", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ReceiverTests(unittest.TestCase):
    def setUp(self):
        self.body = {"model": "model.demo", "messages": [{"role": "system", "content": "Answer briefly."},
            {"role": "user", "content": "Use lookup for synthetic."}], "tool_choice": "auto",
            "tools": [{"type": "function", "function": {"name": "lookup",
                "description": "Synthetic lookup", "parameters": {"type": "object",
                "properties": {"key": {"type": "string"}}, "required": ["key"]}}}]}

    def test_call_result_and_mutation(self):
        observe = module.Handler._tool_observation
        self.assertEqual(observe(self.body)["round"], "call")
        self.body["messages"].extend([
            {"role": "assistant", "content": "", "tool_calls": [{"id": "call.lookup.1", "type": "function",
                "function": {"name": "lookup", "arguments": '{"key":"synthetic"}'}}]},
            {"role": "tool", "tool_call_id": "call.lookup.1", "content": '{"value":"synthetic"}'}])
        self.assertEqual(observe(self.body)["value"], "synthetic")
        self.body["messages"][3]["content"] = '{"value":"changed"}'
        self.assertEqual(observe(self.body)["error"], "tool_result_mismatch")

    def test_none_choice_does_not_request_call(self):
        self.body["tool_choice"] = "none"
        self.assertEqual(module.Handler._tool_observation(self.body)["round"], "none")

    def test_two_ordered_calls_and_results(self):
        self.body["messages"][1]["content"] = "Use two lookups for synthetic."
        self.body["messages"].append({"role": "assistant", "content": "", "tool_calls": [
            {"id": f"call.lookup.{i}", "type": "function",
             "function": {"name": "lookup", "arguments": '{"key":"synthetic"}'}} for i in (1, 2)]})
        self.body["messages"].extend({"role": "tool", "tool_call_id": f"call.lookup.{i}",
                                      "content": '{"value":"synthetic"}'} for i in (1, 2))
        result = module.Handler._tool_observation(self.body)
        self.assertEqual((result["round"], result["call_ids"], result["values"]),
                         ("result_multi", ["call.lookup.1", "call.lookup.2"],
                          ["synthetic", "synthetic"]))
        self.body["messages"][4]["tool_call_id"] = "call.lookup.1"
        self.assertEqual(module.Handler._tool_observation(self.body)["error"],
                         "multi_tool_call_mismatch")


if __name__ == "__main__":
    unittest.main()
