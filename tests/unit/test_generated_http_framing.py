"""Authenticated parser generation over real socket pairs; no model or account writes."""

from copy import deepcopy
import json
import random
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ezllmrouter_server.operator_http.transport import TransportRoutes
from ezllmrouter_server.wire_http.transport import WireTransport
from ezllmrouter_server.web import serve
from tests.development_slice.test_core import REQUEST
from tests.generated_inputs import settings
from tests.operator_console.test_user_management_web import MemoryServer, UserHTTPFixture
from tests.unit.test_http_structure import HTTPFramingTests


def framing_cases(length, limit):
    size = str(length).encode()
    cl = b"Content-Length: " + size + b"\r\n"
    return (
        ("signed", b"Content-Length: +" + size + b"\r\n"),
        ("negative", b"Content-Length: -" + size + b"\r\n"),
        ("trailing-space", cl.replace(b"\r\n", b" \r\n")),
        ("duplicate-identical", cl + cl),
        ("duplicate-conflicting", cl + b"Content-Length: 1\r\n"),
        ("chunked", cl + b"Transfer-Encoding: chunked\r\n"),
        ("mixed-encoding", cl + b"tRaNsFeR-EnCoDiNg: ChUnKeD, identity\r\n"),
        ("empty-encoding", cl + b"Transfer-Encoding:\r\n"),
        ("folded-length", cl.replace(b"\r\n", b"\r\n 0\r\n")),
        ("nul-length", cl.replace(b"\r\n", b"\x00\r\n")),
        ("bare-cr", b"Content-Length:\r999\r\n"),
        ("colon-space", b"Content-Length : " + size + b"\r\n"),
        ("non-ascii-digit", b"Content-Length: \xb2\r\n"),
        ("over-limit", b"Content-Length: " + str(limit + 1).encode() + b"\r\n"),
    )


class AuthenticatedFramingTests(UserHTTPFixture):
    exchange = HTTPFramingTests.exchange

    def targets(self):
        self.ready_admin()
        create = self.enterContext(
            patch.object(
                self.server.application.accounts,
                "create",
                return_value={"principal_id": "user.synthetic.framing"},
            )
        )
        submit = Mock(return_value=(200, {"contract_version": "0.2", "state": "accepted"}))
        capability = Mock(return_value={"contract_version": "0.2"})
        coordinator = SimpleNamespace(
            registry=None,
            authenticate=lambda _: {"principal_id": "svc.demo"},
            submit=submit,
            capabilities=capability,
        )
        with patch("ezllmrouter_server.web.BoundedHTTPServer", MemoryServer):
            wire = serve("127.0.0.1", 48761, coordinator)
        operator_parser = self.enterContext(
            patch.object(TransportRoutes, "_body", autospec=True, side_effect=TransportRoutes._body)
        )
        wire_parser = self.enterContext(
            patch.object(
                WireTransport, "_json_bytes", autospec=True, side_effect=WireTransport._json_bytes
            )
        )
        return (
            ("operator", self.server, "/operator/v1/users", 8192, create, operator_parser),
            ("wire", wire, "/v1/submissions", 65536, submit, wire_parser),
        ), capability

    @staticmethod
    def payload(kind, index):
        if kind == "operator":
            return {
                "username": "parser" + str(index),
                "display_name": "Synthetic parser user",
                "role": "ordinary",
                "status": "active",
                "password": "Synthetic parser-only passphrase",
            }
        request = deepcopy(REQUEST)
        request["step_id"] = "step.parser." + str(index)
        return request

    def request_bytes(self, path, framing, body, *, poison=False, close=False):
        prefix = (
            f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1:48761\r\nOrigin: http://127.0.0.1:48761\r\nCookie: {self.cookie}\r\nX-EzLLMRouter-CSRF: {self.csrf}\r\nAuthorization: Bearer synthetic\r\nEzLLMRouter-Contract-Version: 0.2\r\nContent-Type: application/json\r\n"
        ).encode()
        if close:
            prefix += b"Connection: close\r\n"
        suffix = (
            b"GET /v1/capabilities HTTP/1.1\r\nHost: 127.0.0.1:48761\r\nAuthorization: Bearer synthetic\r\nEzLLMRouter-Contract-Version: 0.2\r\n\r\n"
            if poison
            else b""
        )
        return prefix + framing + b"\r\n" + body + suffix

    def test_authenticated_controls_dispatch_once_with_the_exact_declared_body(self):
        targets, capability = self.targets()
        for kind, server, path, _limit, dispatch, reader in targets:
            for index, spelling in enumerate(("{}", "0{}", "\t{}")):
                with self.subTest(target=kind, spelling=spelling):
                    body = self.payload(kind, index)
                    raw = json.dumps(body).encode()
                    dispatch.reset_mock()
                    reader.reset_mock()
                    header = ("Content-Length: " + spelling.format(len(raw)) + "\r\n").encode()
                    reply = self.exchange(server, self.request_bytes(path, header, raw, close=True))
                    self.assertEqual(reply.count(b"HTTP/1.1 "), 1)
                    self.assertIn(int(reply.split(b" ", 2)[1]), (200, 201))
                    self.assertEqual(reader.call_count, 1)
                    dispatch.assert_called_once()
                    self.assertEqual(dispatch.call_args.args[1 if kind == "operator" else 0], body)
                    capability.assert_not_called()

    def test_generated_invalid_framing_reaches_parsers_and_cannot_dispatch_a_following_request(
        self,
    ):
        seed, count = settings()
        rng = random.Random(seed)
        targets, capability = self.targets()
        order = list(range(len(framing_cases(1, 1))))
        rng.shuffle(order)
        for kind, server, path, limit, dispatch, reader in targets:
            count = max(count, len(order))
            for index in range(count):
                raw = json.dumps(self.payload(kind, rng.randrange(1_000_000))).encode()
                hazard, framing = framing_cases(len(raw), limit)[order[index % len(order)]]
                with self.subTest(seed=seed, index=index, target=kind, hazard=hazard):
                    dispatch.reset_mock()
                    before = reader.call_count
                    reply = self.exchange(
                        server, self.request_bytes(path, framing, raw, poison=True)
                    )
                    self.assertEqual(
                        reader.call_count - before, 1, "case bypassed the authenticated body parser"
                    )
                    self.assertEqual(reply.count(b"HTTP/1.1 "), 1)
                    self.assertIn(int(reply.split(b" ", 2)[1]), (400, 413))
                    self.assertIn(b"Connection: close\r\n", reply)
                    dispatch.assert_not_called()
                    capability.assert_not_called()
            self.assertEqual(reader.call_count, count)

    def test_valid_json_inside_a_truncated_declared_body_is_never_dispatched(self):
        targets, _ = self.targets()
        for kind, server, path, _limit, dispatch, reader in targets:
            with self.subTest(target=kind):
                raw = json.dumps(self.payload(kind, 0)).encode()
                framing = b"Content-Length: " + str(len(raw) + 1).encode() + b"\r\n"
                reply = self.exchange(server, self.request_bytes(path, framing, raw))
                self.assertEqual(reply.count(b"HTTP/1.1 "), 1)
                self.assertEqual(int(reply.split(b" ", 2)[1]), 400)
                self.assertIn(b"Connection: close\r\n", reply)
                self.assertEqual(reader.call_count, 1)
                dispatch.assert_not_called()
