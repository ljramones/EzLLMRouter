"""Fixed-seed framing and JSON differential fuzzing with independently stated invariants."""

import base64
import json
import random
import struct
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ezllmrouter_client._json import strict_reply
from ezllmrouter_server.canonical import ContractError
from ezllmrouter_server.gateway.choice_b_wire import LIMIT, receive
from ezllmrouter_server.successor_contract import strict_decode
from ezllmrouter_server.web import serve
from ezllmrouter_server.operator_http.transport import TransportRoutes
from ezllmrouter_server.wire_http.transport import WireTransport
from tests.generated_inputs import json_cases, settings
from tests.operator_console.test_user_management_web import MemoryServer, UserHTTPFixture
from tests.unit.test_http_structure import HTTPFramingTests


class FragmentedInput:
    def __init__(self, raw, chunk):
        self.raw, self.chunk, self.requested = raw, chunk, []

    def recv(self, count):
        self.requested.append(count)
        result = self.raw[: min(count, self.chunk)]
        self.raw = self.raw[len(result) :]
        return result

    def settimeout(self, value):
        if not 0 < value <= 1:
            raise AssertionError("unbounded frame timeout")


class GeneratedParserTests(UserHTTPFixture):
    exchange = HTTPFramingTests.exchange

    def test_rejected_http_bodies_are_never_reinterpreted_as_pipelined_requests(self):
        seed, count = settings()
        operator_parser = self.enterContext(
            patch.object(TransportRoutes, "_body", autospec=True, side_effect=TransportRoutes._body)
        )
        wire_parser = self.enterContext(
            patch.object(
                WireTransport, "_json_bytes", autospec=True, side_effect=WireTransport._json_bytes
            )
        )
        rng = random.Random(seed)
        capability = Mock(return_value={"contract_version": "0.2"})
        coordinator = SimpleNamespace(
            registry=None, authenticate=lambda _: {}, capabilities=capability
        )
        with patch("ezllmrouter_server.web.BoundedHTTPServer", MemoryServer):
            wire = serve("127.0.0.1", 48761, coordinator)
        inner = b"GET /v1/capabilities HTTP/1.1\r\nHost: 127.0.0.1:48761\r\nAuthorization: Bearer synthetic\r\nEzLLMRouter-Contract-Version: 0.2\r\n\r\n"
        for index in range(count):
            capability.reset_mock()
            server, path = rng.choice(((self.server, "/operator/v1/users"), (wire, "/v1/unknown")))
            # With length zero these bytes are a legitimate subsequent request.
            length = rng.choice((1, len(inner), len(inner) + 10, 262145))
            extra = rng.choice(
                (
                    "",
                    "Content-Length: 2\r\n",
                    "Transfer-Encoding: chunked\r\n",
                    "Content-Type: text/plain\r\n",
                    "X-Fold: one\r\n two\r\n",
                    "X-Bytes: é\r\n",
                )
            )
            request = (
                f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1:48761\r\nOrigin: http://127.0.0.1:48761\r\nAuthorization: Bearer synthetic\r\nEzLLMRouter-Contract-Version: 0.2\r\n{extra}Content-Length: {length}\r\n\r\n"
            ).encode("latin-1") + inner
            if rng.randrange(4) == 0:
                request = request.replace(b"\r\n", b"\n")
            with self.subTest(seed=seed, index=index, declared_length=length):
                reply = self.exchange(server, request)
                self.assertEqual(reply.count(b"HTTP/1.1 "), 1)
                self.assertIn(b"Connection: close\r\n", reply)
                self.assertIn(int(reply.split(b" ", 2)[1]), (400, 401, 403, 404, 413))
                capability.assert_not_called()
        # These are deliberately early-rejection cases. Authenticated body-parser
        # generation lives in test_generated_http_framing, with positive controls.
        self.assertEqual(operator_parser.call_count, 0)
        self.assertEqual(wire_parser.call_count, 0)

    def test_json_clients_agree_and_server_request_policy_rejects_control_text(self):
        seed, count = settings(512)
        cases = list(json_cases(seed, count))
        result = subprocess.run(
            ["node", "tests/unit/json_differential.cjs"],
            input=json.dumps([base64.b64encode(raw).decode() for raw in cases]),
            text=True,
            capture_output=True,
            check=True,
            timeout=15,
        )
        decoded = json.loads(result.stdout)
        self.assertEqual(len(decoded), len(cases))
        for index, (raw, javascript) in enumerate(zip(cases, decoded, strict=True)):
            with self.subTest(seed=seed, index=index, raw_base64=base64.b64encode(raw).decode()):
                try:
                    python = {"accepted": True, "value": strict_reply(raw)}
                except (ValueError, UnicodeError, RecursionError):
                    python = {"accepted": False}
                self.assertEqual(python, javascript)
                # Request text intentionally excludes controls that free response text permits.
                if python["accepted"] and has_controls(python["value"]):
                    with self.assertRaises(ContractError):
                        strict_decode(raw)
                elif python["accepted"]:
                    self.assertEqual(strict_decode(raw), python["value"])
                else:
                    with self.assertRaises(ContractError):
                        strict_decode(raw)

    def test_ipc_partial_reads_invalid_sizes_and_non_objects_are_bounded(self):
        seed, count = settings()
        rng = random.Random(seed)
        for index in range(count):
            raw = json.dumps({"sequence": index, "value": "é" * rng.randrange(20)}).encode()
            frame = struct.pack("!I", len(raw)) + raw
            with self.subTest(seed=seed, index=index):
                stream = FragmentedInput(frame, rng.randrange(1, 8))
                self.assertEqual(receive(stream, timeout=1), json.loads(raw))
                self.assertLessEqual(max(stream.requested), LIMIT)
                for size in (0, LIMIT + 1, 0xFFFFFFFF):
                    stream = FragmentedInput(struct.pack("!I", size), 4)
                    with self.assertRaises(ValueError):
                        receive(stream, timeout=1)
                    self.assertEqual(stream.requested, [4])
                cut = rng.randrange(len(frame))
                with self.assertRaises(EOFError):
                    receive(FragmentedInput(frame[:cut], 3), timeout=1)
                body = rng.choice((b"[]", b"null", b"false", b"1", b'"text"'))
                with self.assertRaises(ValueError):
                    receive(FragmentedInput(struct.pack("!I", len(body)) + body, 1), timeout=1)


def has_controls(value):
    if isinstance(value, str):
        return any(ord(char) < 32 or ord(char) == 127 for char in value)
    if isinstance(value, dict):
        return any(has_controls(key) or has_controls(child) for key, child in value.items())
    if isinstance(value, list):
        return any(has_controls(child) for child in value)
    return False
