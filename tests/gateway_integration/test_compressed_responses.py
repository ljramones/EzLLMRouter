"""Responses survive provider compression once, within the decoded byte limit."""

import base64
import gzip
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zlib

import httpx

from ezllmrouter_server.gateway import choice_b_sender as sender
from ezllmrouter_server.gateway.guard import responses_expectation
from ezllmrouter_server.gateway.owned_sender_transport import LocalSendAuthority
from ezllmrouter_server.gateway.provider_reply import candidate_from_provider
from tests.gateway_integration.test_guard import invocation

PROVIDER_REPLY = {
    "id": "response.test",
    "object": "response",
    "model": "model-test",
    "output": [{"type": "message", "content": [{"type": "output_text", "text": "Paid result.\n"}]}],
    "usage": {"input_tokens": 5, "output_tokens": 2, "total_tokens": 7},
}


def responses_sender(settings):
    authority = LocalSendAuthority()
    item = invocation()
    destination = {
        "service": "openai.responses.v1",
        "adapter_id": "openai.responses.v1",
        "connection_id": "conn.response",
        "connection_revision": 1,
        "credential_version": 1,
        "endpoint": settings["origin"],
        "model": "model-test",
    }
    item.plan["destination"] = item.projection["destination"] = destination
    item.plan["per_attempt_total_timeout_ms"] = 3000
    item.projection["work"]["generation_settings"]["temperature_decimal"] = "0"
    for message in item.projection["work"]["messages"]:
        for block in message["blocks"]:
            block["kind"] = "system_text" if message["role"] == "system" else "content_text"
    item.authority_gate = authority.gate
    item.authority_epoch = authority.snapshot_epoch()
    adapter = sender.ChoiceBSenderAdapter.__new__(sender.ChoiceBSenderAdapter)
    adapter.authority, adapter.controlled_provider_proof = authority, True
    adapter.provider_registry = SimpleNamespace(
        connection=lambda _: {
            "status": "active",
            "revision": 1,
            "credential_version": 1,
            "settings": settings,
        }
    )
    request = httpx.Request(
        "POST",
        settings["origin"] + "/v1/responses",
        json=responses_expectation(item.projection),
        headers={"Authorization": "Bearer " + item.provider_key, "Accept-Encoding": "identity"},
        extensions={"timeout": dict.fromkeys(("connect", "read", "write", "pool"), 3.0)},
    )
    return adapter, item, request


class EncodedStream(httpx.AsyncByteStream):
    def __init__(self, content):
        self.content, self.closed = content, False

    async def __aiter__(self):
        for offset in range(0, len(self.content), 13):
            yield self.content[offset : offset + 13]

    async def aclose(self):
        self.closed = True


class CompressedResponsesTests(unittest.IsolatedAsyncioTestCase):
    async def send(self, content, encoding):
        adapter, item, request = responses_sender({"origin": "https://api.openai.com"})
        stream = EncodedStream(content)
        lower = httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={
                    "Content-Encoding": encoding,
                    "Content-Length": str(len(content)),
                    "Content-Type": "application/json",
                },
                stream=stream,
            )
        )
        with patch.object(sender, "OwnedTLSHTTPTransport", return_value=lower):
            await adapter._start_lower()
            try:
                result = await adapter._send(request, item)
                return base64.b64decode(result["body_b64"]), item
            finally:
                await adapter.guard.aclose()
                self.assertTrue(stream.closed)

    async def test_gzip_and_deflate_keep_the_candidate_and_usage(self):
        raw = json.dumps(PROVIDER_REPLY).encode()
        for encoding, compress in (("gzip", gzip.compress), ("deflate", zlib.compress)):
            with self.subTest(encoding=encoding):
                result, item = await self.send(compress(raw), encoding)
                self.assertEqual(result, raw)
                candidate = candidate_from_provider(json.loads(result), responses=True)
                self.assertEqual(candidate["text"], "Paid result.\n")
                self.assertEqual(candidate["usage"], PROVIDER_REPLY["usage"])
                self.assertTrue(item.committed and item.response_received)
                self.assertIsNone(item.lower_error)

    async def test_compressed_reply_cannot_bypass_the_decoded_limit(self):
        with self.assertRaisesRegex(ValueError, "provider response size"):
            await self.send(gzip.compress(b"x" * (sender.RESPONSE_LIMIT + 1)), "gzip")
