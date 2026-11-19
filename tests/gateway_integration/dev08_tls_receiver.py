"""Independent process for one controlled HTTPS Responses text request."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
from pathlib import Path
import ssl
import sys
import time


TEST_KEY = "test-provider-key-123456"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    log_path: Path
    dev10 = False

    def log_message(self, *_args):
        pass

    def reply(self, status, value):
        raw = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            size = 0
        if not 0 < size <= 65536:
            self.reply(413, {"error": {"message": "bounded request required", "type": "invalid_request_error"}})
            return
        raw = self.rfile.read(size)
        try:
            body = json.loads(raw)
        except ValueError:
            body = None
        valid = (self.path == "/v1/responses" and type(body) is dict and
                 body.get("model") == "test-response-model" and
                 type(body.get("input")) is list and len(body["input"]) == 2 and
                 body.get("store") is False and body.get("stream", False) is False and
                 body.get("max_output_tokens") == 32 and
                 self.headers.get("Authorization") == "Bearer " + TEST_KEY and
                 self.headers.get("Content-Type", "").split(";", 1)[0] == "application/json")
        row = {"method": "POST", "path": self.path,
               "attempt_id": self.headers.get("X-EzLLMRouter-Attempt"),
               "body_sha256": hashlib.sha256(raw).hexdigest(), "body_bytes": len(raw),
               "request_valid": bool(valid), "received_at_ns": time.time_ns()}
        with self.log_path.open("a") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
            handle.flush()
        if not valid:
            self.reply(400, {"error": {"message": "controlled request rejected", "type": "invalid_request_error"}})
            return
        if self.dev10 and "DEV10_TRANSPORT_UNKNOWN" in json.dumps(body):
            # The controlled receiver has the bytes but deliberately gives no
            # response, so the sender must retain possible post-send exposure.
            self.close_connection = True
            self.connection.close()
            return
        usage = {"input_tokens": 5, "output_tokens": 2, "total_tokens": 7}
        if self.dev11:
            request_text = json.dumps(body)
            read = 70 if "DEV11_CACHE_READ" in request_text else 0 if (
                "DEV11_CACHE_ZERO" in request_text or "DEV11_CACHE_MISSING" in request_text or
                "DEV11_CACHE_NULL" in request_text) else 70
            write = 0 if any(marker in request_text for marker in
                ("DEV11_CACHE_READ", "DEV11_CACHE_ZERO", "DEV11_CACHE_MISSING", "DEV11_CACHE_NULL")) else 30
            details = {"cached_tokens": read}
            if "DEV11_CACHE_NULL" in request_text:
                details["cache_write_tokens"] = None
            elif "DEV11_CACHE_MISSING" not in request_text:
                details["cache_write_tokens"] = write
                details["cache_write_tokens_details"] = {
                    "ttl_30m_tokens": write, "ttl_12h_tokens": 0}
            usage = {"input_tokens": 120, "output_tokens": 20, "total_tokens": 140,
                "input_tokens_details": details,
                "output_tokens_details": {"reasoning_tokens": 2}}
        elif self.dev10:
            usage.update(input_tokens_details={"cached_tokens": 0, "cache_write_tokens": 0},
                         output_tokens_details={"reasoning_tokens": 0})
        self.reply(200, {"id": "resp.dev08.synthetic", "object": "response",
            "created_at": int(time.time()), "status": "completed", "model": "test-response-model",
            "output": [{"id": "msg.dev08.synthetic", "type": "message", "status": "completed",
                "role": "assistant", "content": [{"type": "output_text", "text": "Hello.",
                    "annotations": []}]}],
            "usage": usage})


def main():
    if len(sys.argv) not in (4, 5) or (len(sys.argv) == 5 and sys.argv[4] not in ("--dev10", "--dev11")):
        raise SystemExit("usage: dev08_tls_receiver.py CERT KEY LOG [--dev10|--dev11]")
    cert, key, log = map(Path, sys.argv[1:4])
    Handler.dev10 = sys.argv[4:] == ["--dev10"]
    Handler.dev11 = sys.argv[4:] == ["--dev11"]
    Handler.log_path = log
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert), str(key))
    server = ThreadingHTTPServer(("127.0.0.1", 8766), Handler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
