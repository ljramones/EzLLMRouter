"""Independent synthetic provider: own process and append-only arrival file."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import hashlib
import json
import os
import time

mode = os.environ.get("EZLLMROUTER_RECEIVER_MODE", "normal")
if mode not in ("normal", "fail", "delay", "drop", "partial"):
    raise ValueError("unsupported synthetic receiver mode")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _fmt, *_args):
        return

    def send_json(self, status, value):
        data = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        arrivals = Path(os.environ["EZLLMROUTER_RECEIVER_LOG"])
        if self.path != "/observations":
            return self.send_json(404, {"error": "missing"})
        records = (
            [json.loads(line) for line in arrivals.read_text().splitlines()]
            if arrivals.exists()
            else []
        )
        self.send_json(200, {"arrivals": records})

    def do_POST(self):
        arrivals = Path(os.environ["EZLLMROUTER_RECEIVER_LOG"])
        if self.path != "/v1/chat/completions":
            return self.send_json(404, {"error": "missing"})
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size <= 65536:
            return self.send_json(413, {"error": "size"})
        raw = self.rfile.read(size)
        tool_observation = None
        received = None
        try:
            received = json.loads(raw)
            if isinstance(received, dict) and "tools" in received:
                tool_observation = self._tool_observation(received)
        except (TypeError, ValueError, KeyError):
            tool_observation = {"error": "malformed_tool_request"}
        record = {
            "sequence": len(arrivals.read_text().splitlines()) + 1 if arrivals.exists() else 1,
            "method": "POST",
            "path": self.path,
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        if tool_observation is not None:
            record["tool_observation"] = tool_observation
        with arrivals.open("a") as out:
            out.write(json.dumps(record, sort_keys=True) + "\n")
            out.flush()
            os.fsync(out.fileno())
        messages = received.get("messages") if isinstance(received, dict) else None
        user_text = (
            messages[1].get("content")
            if isinstance(messages, list) and len(messages) > 1 and isinstance(messages[1], dict)
            else None
        )
        if user_text == "Use lookup for synthetic wait.":
            time.sleep(0.25)
        if mode == "delay":
            time.sleep(1.5)
        if mode == "drop":
            self.close_connection = True
            return
        if mode == "fail":
            return self.send_json(502, {"error": "synthetic remote failure"})
        if mode == "partial":
            return self.send_json(200, {"text": "Hello.", "usage": {"input_tokens": 3}})
        if tool_observation is not None:
            if "error" in tool_observation:
                return self.send_json(400, {"error": "invalid synthetic tool request"})
            if tool_observation["round"] == "call":
                if user_text == "Use lookup for synthetic malformed.":
                    return self.send_json(
                        200,
                        {
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
                    )
                if user_text == "Use two lookups for synthetic.":
                    return self.send_json(
                        200,
                        {
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
                            "usage": {"input_tokens": 5, "output_tokens": 4},
                        },
                    )
                return self.send_json(
                    200,
                    {
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
                )
            if tool_observation["round"] == "none":
                return self.send_json(
                    200, {"text": "No tool.", "usage": {"input_tokens": 4, "output_tokens": 2}}
                )
            if tool_observation["round"] == "result_multi":
                return self.send_json(
                    200,
                    {
                        "text": "Lookup pair: " + " ".join(tool_observation["values"]),
                        "usage": {"input_tokens": 9, "output_tokens": 3},
                    },
                )
            return self.send_json(
                200,
                {
                    "text": "Lookup: " + tool_observation["value"],
                    "usage": {"input_tokens": 7, "output_tokens": 3},
                },
            )
        self.send_json(200, {"text": "Hello.", "usage": {"input_tokens": 3, "output_tokens": 1}})

    @staticmethod
    def _tool_observation(body):
        """Independent assertions over received transport data, not adapter output."""
        tools = body.get("tools")
        expected = [
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "description": "Synthetic lookup",
                    "parameters": {
                        "type": "object",
                        "properties": {"key": {"type": "string"}},
                        "required": ["key"],
                    },
                },
            }
        ]
        messages = body.get("messages")
        choice = body.get("tool_choice")
        if (
            tools != expected
            or choice not in ("auto", "none")
            or not isinstance(messages, list)
            or len(messages) not in (2, 4, 5)
            or [x.get("role") for x in messages[:2]] != ["system", "user"]
        ):
            return {"error": "tool_definition_or_message_shape"}
        if len(messages) == 2:
            if choice == "none":
                return {"round": "none", "tool_name": "lookup"}
            return {"round": "call", "tool_name": "lookup", "key": "synthetic"}
        if len(messages) == 5:
            assistant, *results = messages[2:]
            calls = assistant.get("tool_calls")
            if (
                assistant.get("role") != "assistant"
                or not isinstance(calls, list)
                or len(calls) != 2
                or [r.get("role") for r in results] != ["tool", "tool"]
            ):
                return {"error": "multi_tool_history_shape"}
            expected_ids = ["call.lookup.1", "call.lookup.2"]
            if (
                [c.get("id") for c in calls] != expected_ids
                or [r.get("tool_call_id") for r in results] != expected_ids
                or any(
                    c.get("type") != "function"
                    or c.get("function", {}).get("name") != "lookup"
                    or json.loads(c.get("function", {}).get("arguments", "null"))
                    != {"key": "synthetic"}
                    for c in calls
                )
            ):
                return {"error": "multi_tool_call_mismatch"}
            values = []
            for result in results:
                parsed = json.loads(result.get("content", "null"))
                if parsed != {"value": "synthetic"}:
                    return {"error": "multi_tool_result_mismatch"}
                values.append(parsed["value"])
            return {
                "round": "result_multi",
                "call_ids": expected_ids,
                "tool_name": "lookup",
                "values": values,
            }
        assistant, result = messages[2:]
        calls = assistant.get("tool_calls")
        if (
            assistant.get("role") != "assistant"
            or result.get("role") != "tool"
            or not isinstance(calls, list)
            or len(calls) != 1
        ):
            return {"error": "tool_history_shape"}
        call = calls[0]
        if (
            call.get("id") != result.get("tool_call_id")
            or call.get("type") != "function"
            or call.get("function", {}).get("name") != "lookup"
            or json.loads(call.get("function", {}).get("arguments", "null")) != {"key": "synthetic"}
        ):
            return {"error": "tool_call_mismatch"}
        content = result.get("content")
        if content == "value.synthetic":
            value = "synthetic"
        else:
            parsed = json.loads(content)
            if not isinstance(parsed, dict) or parsed != {"value": "synthetic"}:
                return {"error": "tool_result_mismatch"}
            value = parsed["value"]
        return {
            "round": "result",
            "call_id": call["id"],
            "tool_name": "lookup",
            "arguments": {"key": "synthetic"},
            "result": content,
            "value": value,
        }


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8766"))), Handler).serve_forever()
