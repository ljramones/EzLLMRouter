"""Independent OpenAI-compatible synthetic receiver for DEV-04."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import hashlib
import json
import os
import threading
import time


ARRIVALS = Path(os.environ.get("DURANKI_RECEIVER_LOG", "/data/arrivals.jsonl"))
CONTROLS = ARRIVALS.with_name("controls.jsonl")
LOCK = threading.Lock()
HOLD = threading.Event()


def control(event):
    with LOCK:
        with CONTROLS.open("a") as handle:
            handle.write(json.dumps({"event": event, "at_ns": time.time_ns()}) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def records():
    return [json.loads(line) for line in ARRIVALS.read_text().splitlines()] if ARRIVALS.exists() else []


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        return

    def reply(self, status, value):
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/health":
            self.reply(200, {"live": True})
        elif self.path == "/observations":
            self.reply(200, {"arrivals": records()})
        else:
            self.reply(404, {"error": "missing"})

    def do_POST(self):
        if self.path == "/control/release":
            HOLD.set()
            control("hold_released")
            self.reply(200, {"released": True})
            return
        if self.path != "/v1/chat/completions":
            self.reply(404, {"error": "missing"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            size = 0
        if not 0 < size <= 65536:
            self.reply(413, {"error": "size"})
            return
        raw = self.rfile.read(size)
        attempt = self.headers.get("X-Duranki-Attempt")
        with LOCK:
            sequence = len(records()) + 1
            row = {"sequence": sequence, "method": "POST", "path": self.path,
                   "attempt_id": attempt, "body_sha256": hashlib.sha256(raw).hexdigest(),
                   "body_bytes": len(raw), "received_at_ns": time.time_ns()}
            try:
                body = json.loads(raw)
                if isinstance(body, dict):
                    row["model"] = body.get("model")
                    row["message_roles"] = [x.get("role") for x in body.get("messages", [])]
                    row["tool_call_ids"] = [c.get("id") for m in body.get("messages", [])
                                            for c in m.get("tool_calls", [])]
            except (TypeError, ValueError, AttributeError):
                body = None
            with ARRIVALS.open("a") as handle:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        if not isinstance(body, dict) or body.get("model") not in ("model.demo", "model.demo.alt"):
            self.reply(400, {"error": {"message": "invalid synthetic model", "type": "invalid_request_error"}})
            return
        messages = body.get("messages")
        if not isinstance(messages, list) or len(messages) < 2:
            self.reply(400, {"error": {"message": "invalid synthetic messages", "type": "invalid_request_error"}})
            return
        user_text = messages[1].get("content")
        if user_text == "Simulate hold":
            HOLD.clear()
            control("hold_entered_after_receiver_arrival")
            if not HOLD.wait(timeout=20):
                control("hold_timed_out")
                self.reply(504, {"error": {"message": "synthetic hold timed out", "type": "server_error"}})
                return
            control("hold_response_released")
        if user_text == "Simulate 422":
            self.reply(422, {"error": {"message": "synthetic rejection", "type": "invalid_request_error"}})
            return
        if user_text == "Simulate 503":
            self.reply(503, {"error": {"message": "synthetic retryable", "type": "server_error"}})
            return
        if user_text == "Simulate close":
            self.close_connection = True
            return
        calls = []
        if body.get("tools") and len(messages) == 2 and body.get("tool_choice") == "auto":
            calls = [{"id": "call.lookup.1", "type": "function", "function": {
                "name": "lookup", "arguments": '{"key":"synthetic"}'}}]
            message = {"role": "assistant", "content": None, "tool_calls": calls}
            finish = "tool_calls"
        elif body.get("tools") and len(messages) >= 4:
            result = messages[-1].get("content")
            try:
                value = json.loads(result)["value"] if result != "value.synthetic" else "synthetic"
            except (TypeError, ValueError, KeyError):
                value = "invalid"
            message = {"role": "assistant", "content": "Lookup: " + value}
            finish = "stop"
        else:
            message = {"role": "assistant", "content": "Hello."}
            finish = "stop"
        self.reply(200, {"id": f"chatcmpl.dev04.{sequence}", "object": "chat.completion",
                         "created": int(time.time()), "model": body["model"],
                         "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                         "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}})


if __name__ == "__main__":
    ARRIVALS.parent.mkdir(parents=True, exist_ok=True)
    ThreadingHTTPServer(("127.0.0.1", 8766), Handler).serve_forever()
