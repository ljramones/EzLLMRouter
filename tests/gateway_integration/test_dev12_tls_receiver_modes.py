"""Offline receiver probes: retained usage precedes withheld or malformed replies."""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dev12_tls_receiver import Handler, TEST_KEY


class ClosedConnection:
    closed = False

    def close(self):
        self.closed = True


class ProbeHandler(Handler):
    def reply(self, status, value):
        self.observed_reply = (status, value)


class ReceiverModesTests(unittest.TestCase):
    def invoke(self, root, item_id, attempt, *, good=True):
        body = {"operation": "embedding.create@1", "configuration_ref": "cfg.embed.synthetic",
                "role": "document", "items": [{"item_id": item_id}]}
        raw = json.dumps(body, separators=(",", ":")).encode()
        handler = object.__new__(ProbeHandler)
        handler.path = "/synthetic/v1/embeddings"
        handler.headers = {"Content-Length": str(len(raw)),
            "Authorization": "Bearer " + (TEST_KEY if good else "wrong"),
            "Content-Type": "application/json", "X-EzLLMRouter-Attempt": attempt}
        handler.rfile = BytesIO(raw)
        handler.connection = ClosedConnection()
        handler.close_connection = False
        handler.observed_reply = None
        Handler.log_path = root / "receiver.jsonl"
        Handler.receipt_path = root / "receiver-receipts.jsonl"
        handler.do_POST()
        arrivals = [json.loads(line) for line in Handler.log_path.read_text().splitlines()]
        receipts = ([json.loads(line) for line in Handler.receipt_path.read_text().splitlines()]
                    if Handler.receipt_path.exists() else [])
        return handler, raw, arrivals, receipts

    def test_withheld_response_retains_bound_independent_receipt(self):
        with TemporaryDirectory() as temporary:
            handler, raw, arrivals, receipts = self.invoke(Path(temporary),
                "doc.unknown.recoverable", "attempt.recoverable")
            self.assertTrue(handler.connection.closed)
            self.assertIsNone(handler.observed_reply)
            self.assertEqual(len(arrivals), 1)
            self.assertEqual(len(receipts), 1)
            self.assertEqual((receipts[0]["attempt_id"], receipts[0]["body_sha256"],
                              receipts[0]["body_bytes"]),
                             ("attempt.recoverable", sha256(raw).hexdigest(), len(raw)))
            self.assertEqual(receipts[0]["received_at_ns"], arrivals[0]["received_at_ns"])
            self.assertEqual(receipts[0]["usage_component"]["quantity"], 1)

    def test_terminal_unknown_and_invalid_request_do_not_invent_usage(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            handler, _, arrivals, receipts = self.invoke(root,
                "doc.unknown.no_evidence", "attempt.terminal")
            self.assertTrue(handler.connection.closed)
            self.assertEqual((len(arrivals), len(receipts)), (1, 0))
            handler, _, arrivals, receipts = self.invoke(root,
                "doc.normal", "attempt.unauthorized", good=False)
            self.assertEqual(handler.observed_reply[0], 400)
            self.assertEqual((len(arrivals), len(receipts)), (2, 0))

    def test_delivery_and_native_observation_are_separate(self):
        for item_id, expected_http, reported in (
                ("doc.valid.array", 200, []),
                ("doc.failure.absent", 502, {"component": "document_units", "presence": "absent"})):
            with self.subTest(item_id=item_id), TemporaryDirectory() as temporary:
                handler, _, arrivals, receipts = self.invoke(Path(temporary), item_id,
                    "attempt." + item_id)
                self.assertEqual(handler.observed_reply[0], expected_http)
                self.assertEqual(handler.observed_reply[1]["usage_component"], reported)
                self.assertEqual((len(arrivals), len(receipts)), (1, 1))
                self.assertEqual(receipts[0]["usage_component"]["evidence"], "reported")


if __name__ == "__main__":
    unittest.main()
