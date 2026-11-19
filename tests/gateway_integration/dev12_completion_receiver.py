"""Independent completion-only TLS receiver for fixed fictional retrieval cases.

The extra selectors below create bounded malformed responses while preserving
the same durable arrival and native-usage receipt path as ordinary responses.
They never contact an external provider.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import os
from pathlib import Path
import ssl
import sys
import threading
import time


TEST_KEY = "test-dev12-synthetic-receiver-key"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    log_path: Path
    receipt_path: Path
    log_lock = threading.Lock()

    @staticmethod
    def durable_row(path, row):
        raw = (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()
        with Handler.log_lock:
            with path.open("ab", buffering=0) as stream:
                if stream.write(raw) != len(raw):
                    raise OSError("incomplete receiver evidence write")
                os.fsync(stream.fileno())

    def log_message(self, *_args):
        pass

    def reply(self, status, value):
        raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
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
        if not 0 < size <= 262144:
            self.reply(413, {"error": "bounded request required"})
            return
        raw = self.rfile.read(size)
        try:
            body = json.loads(raw)
        except (UnicodeError, ValueError):
            body = None
        attempt = self.headers.get("X-EzLLMRouter-Attempt")
        authorized = (self.headers.get("Authorization") == "Bearer " + TEST_KEY and
                      self.headers.get("Content-Type") == "application/json" and
                      type(body) is dict and type(attempt) is str and
                      len(attempt) <= 160)
        valid = authorized and (
            (self.path == "/synthetic/v1/embeddings" and body.get("operation") == "embedding.create@1" and
             body.get("configuration_ref") == "cfg.embed.synthetic" and
             body.get("role") in ("document", "query") and type(body.get("items")) is list) or
            (self.path == "/synthetic/v1/rerank" and body.get("operation") == "rerank@1" and
             body.get("configuration_ref") in ("cfg.rerank.synthetic", "cfg.rerank.synthetic.a") and
             type(body.get("candidates")) is list))
        row = {"attempt_id": attempt, "path": self.path,
               "body_sha256": hashlib.sha256(raw).hexdigest(), "body_bytes": len(raw),
               "request_valid": bool(valid), "received_at_ns": time.time_ns()}
        self.durable_row(self.log_path, row)
        if not valid:
            self.reply(400, {"error": "controlled request rejected"})
            return
        if self.path.endswith("/embeddings"):
            component = "query_units" if body["role"] == "query" else "document_units"
            quantity = len(body["items"])
            item_ids = {item.get("item_id") for item in body["items"] if type(item) is dict}
        else:
            component = "search_units" if body["configuration_ref"].endswith(".a") else "document_units"
            quantity = ((len(body["candidates"]) + 9) // 10 if component == "search_units"
                        else len(body["candidates"]))
            item_ids = {item.get("candidate_id") for item in body["candidates"]
                        if type(item) is dict}
        usage = {"component": component, "presence": "known", "evidence": "reported",
                 "quantity": quantity, "source_ref": "receiver.synthetic.dev12"}
        if "doc.unknown.no_evidence" not in item_ids:
            self.durable_row(self.receipt_path, {"kind": "native_usage_receipt", "attempt_id": attempt,
                "path": self.path, "body_sha256": row["body_sha256"], "body_bytes": len(raw),
                "received_at_ns": row["received_at_ns"], "usage_component": usage})
        if item_ids & {"doc.unknown", "doc.unknown.recoverable", "doc.unknown.no_evidence"}:
            # The independent receiver has the bytes but intentionally gives
            # no result. The sender must preserve possible-send exposure.
            self.close_connection = True
            self.connection.close()
            return
        if item_ids & {"doc.failure.known", "doc.failure.absent", "doc.failure.invalid"}:
            # Delivery outcome and financial evidence are independent.
            reported = ({"component": component, "presence": "absent"}
                        if "doc.failure.absent" in item_ids else []
                        if "doc.failure.invalid" in item_ids else usage)
            self.reply(502, {"usage_component": reported})
            return
        if self.path.endswith("/embeddings"):
            values = ["0.1", "0.2", "0.3"]
            result = {"contract_version": "0.3", "attempt_id": attempt,
                      "operation": {"type": "embedding.create", "version": 1},
                      "profile_id": "space.synthetic.v1", "model_ref": "model.embed.synthetic.v1",
                      "dimensions": 3,
                      "vectors": [{"input_index": index, "item_id": item["item_id"], "values": values}
                                  for index, item in enumerate(body["items"])]}
        else:
            result = {"contract_version": "0.3", "attempt_id": attempt,
                      "operation": {"type": "rerank", "version": 1},
                      "ranking_profile_id": body["ranking_profile_id"],
                      "results": [{"rank": index + 1, "input_index": index,
                                   "candidate_id": item["candidate_id"], "score": "0.9"}
                                  for index, item in enumerate(body["candidates"][:body["top_k"]])]}
        if "doc.result.short" in item_ids and self.path.endswith("/embeddings"):
            result["vectors"] = result["vectors"][:-1]
        elif "doc.result.dimension" in item_ids and self.path.endswith("/embeddings"):
            result["vectors"][0]["values"] = ["0.1", "0.2"]
        elif "doc.result.nonfinite" in item_ids and self.path.endswith("/embeddings"):
            result["vectors"][0]["values"][0] = "NaN"
        elif "doc.result.space" in item_ids and self.path.endswith("/embeddings"):
            result["profile_id"] = "space.wrong.synthetic"
        elif "doc.result.profile" in item_ids and self.path.endswith("/rerank"):
            result["ranking_profile_id"] = "rank.wrong.synthetic"
        elif "doc.result.duplicate" in item_ids and self.path.endswith("/rerank"):
            if len(result["results"]) > 1:
                result["results"][1]["candidate_id"] = result["results"][0]["candidate_id"]
        elif "doc.result.out_of_range" in item_ids and self.path.endswith("/rerank"):
            result["results"][0]["input_index"] = len(body["candidates"])
        elif "doc.result.order" in item_ids and self.path.endswith("/rerank"):
            if len(result["results"]) > 1:
                result["results"][0]["score"] = "0.1"
                result["results"][1]["score"] = "0.9"
        if "doc.valid.absent" in item_ids:
            self.reply(200, {"result": result})
        elif "doc.valid.null" in item_ids:
            self.reply(200, {"result": result, "usage_component": None})
        elif "doc.valid.array" in item_ids:
            self.reply(200, {"result": result, "usage_component": []})
        elif "doc.valid.number" in item_ids:
            self.reply(200, {"result": result, "usage_component": 1})
        elif "doc.valid.string" in item_ids:
            self.reply(200, {"result": result, "usage_component": "invalid"})
        elif "doc.valid.boolean" in item_ids:
            self.reply(200, {"result": result, "usage_component": True})
        elif "doc.valid.derived" in item_ids:
            self.reply(200, {"result": result, "usage_component": {**usage, "evidence": "derived"}})
        elif "doc.valid.zero" in item_ids:
            self.reply(200, {"result": result, "usage_component": {**usage, "quantity": 0}})
        elif "doc.valid.negative" in item_ids:
            self.reply(200, {"result": result, "usage_component": {**usage, "quantity": -1}})
        elif "doc.valid.out_of_domain" in item_ids:
            self.reply(200, {"result": result, "usage_component": {**usage, "quantity": 999999999}})
        elif "doc.valid.malformed_unicode" in item_ids:
            self.reply(200, {"result": result, "usage_component": "\ud800"})
        else:
            self.reply(200, {"result": result, "usage_component": usage})


def main():
    if len(sys.argv) != 5:
        raise SystemExit("usage: dev12_tls_receiver.py CERT KEY LOG PORT")
    cert, key, log = map(Path, sys.argv[1:4])
    Handler.log_path = log
    Handler.receipt_path = log.with_name("receiver-receipts.jsonl")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert), str(key))
    server = ThreadingHTTPServer(("127.0.0.1", int(sys.argv[4])), Handler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
