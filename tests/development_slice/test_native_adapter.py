"""Container-only actual HTTPX request checks with mocked lower network I/O."""
import json
import unittest
from unittest.mock import patch

from duranki_server.canonical import ContractError
from native_adapter import NativeSyntheticAdapter
from recipe import SyntheticTextRecipe


class Response:
    status_code = 200
    def json(self): return {"text": "Hello.", "usage": {"input_tokens": 3}}


class Client:
    sent = []
    def __init__(self, **_kwargs): pass
    def __enter__(self): return self
    def __exit__(self, *_args): return False
    def send(self, request):
        self.sent.append(request)
        return Response()


class AdapterTests(unittest.TestCase):
    def setUp(self):
        Client.sent = []
        self.destination = {"endpoint": "receiver", "model": "model.demo", "processing_region": "local"}
        self.projection = {"destination": self.destination, "work": {
            "messages": [{"role": "user", "blocks": [{"text": "Hello"}]}],
            "generation_settings": {"max_output_tokens": 8}}}
        self.expected, self.controls = SyntheticTextRecipe().expected(self.projection, 1000)
        self.adapter = NativeSyntheticAdapter(self.controls["url"], "receiver")

    def test_positive_request_is_actual_checked_request(self):
        with patch("native_adapter.httpx.Client", Client):
            result = self.adapter.send(self.expected, 1000, self.controls)
        self.assertEqual(result["status"], 200)
        self.assertEqual(len(Client.sent), 1)
        self.assertEqual(Client.sent[0].content, self.expected)

    def test_body_or_url_drift_rejected_before_lower_send(self):
        wrong = self.expected.replace(b"model.demo", b"model.other")
        with patch("native_adapter.httpx.Client", Client):
            with self.assertRaises(ContractError):
                self.adapter.send(wrong, 1000, self.controls)
            self.adapter.url = "http://receiver:8766/v1/chat/completions?mutated=1"
            with self.assertRaises(ContractError):
                self.adapter.send(self.expected, 1000, self.controls)
        self.assertEqual(Client.sent, [])


if __name__ == "__main__": unittest.main()
