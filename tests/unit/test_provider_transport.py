"""Pinned DNS addresses, IPv6 sockaddr handling and probe socket ownership."""

from contextlib import ExitStack
import io
import json
import socket
import ssl
import unittest
from unittest.mock import Mock, patch

from ezllmrouter_server import provider_adapters as adapters

IPV4 = (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("1.1.1.1", 443))
IPV6 = (
    socket.AF_INET6,
    socket.SOCK_STREAM,
    socket.IPPROTO_TCP,
    "",
    ("2606:4700:4700::1111", 443, 0, 7),
)


def reply(body=b'{"data":[{"id":"model.transport"}]}', declared=True):
    length = b"Content-Length: " + str(len(body)).encode() + b"\r\n" if declared else b""
    return b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n" + length + b"\r\n" + body


class TLSStream:
    def __init__(self, wire):
        self.buffer = io.BytesIO(wire)
        self.sent = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True

    def settimeout(self, value):
        self.timeout = value

    def sendall(self, data):
        self.sent.append(data)

    def makefile(self, mode):
        return self.buffer


class ProviderTransportTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.raw = Mock(spec=("settimeout", "connect", "close"))
        self.tls = TLSStream(reply())
        self.context = Mock()
        self.context.wrap_socket.return_value = self.tls
        self.resolve = self.stack.enter_context(
            patch.object(adapters.socket, "getaddrinfo", return_value=[IPV6])
        )
        self.create = self.stack.enter_context(
            patch.object(adapters.socket, "socket", return_value=self.raw)
        )
        self.ssl_context = self.stack.enter_context(
            patch.object(adapters.ssl, "create_default_context", return_value=self.context)
        )
        self.settings = {
            "origin": "https://api.openai.com",
            "location": "commercial",
            "site": "Synthetic transport",
        }

    def probe(self):
        result = adapters.probe(
            "openai.responses.v1",
            self.settings,
            "synthetic-key",
            "inventory",
            timeout=2.5,
            controlled=True,
        )
        self.assertNotIn("synthetic-key", json.dumps(result))
        return result

    def test_ipv6_only_uses_resolved_family_and_complete_sockaddr_with_original_sni(self):
        result = self.probe()
        self.assertEqual(result["models"], ["model.transport"])
        self.resolve.assert_called_once_with("api.openai.com", 443, type=socket.SOCK_STREAM)
        self.create.assert_called_once_with(*IPV6[:3])
        self.raw.connect.assert_called_once_with(IPV6[4])
        self.raw.settimeout.assert_called_once_with(2.5)
        self.context.wrap_socket.assert_called_once_with(self.raw, server_hostname="api.openai.com")
        self.assertEqual(self.tls.timeout, 2.5)
        self.assertIn(b"Host: api.openai.com\r\n", self.tls.sent[0])
        self.assertTrue(self.tls.sent[0].startswith(b"GET /v1/models HTTP/1.1\r\n"))
        self.assertEqual(len(self.tls.sent), 1)
        self.assert_closed()

    def test_ipv4_remains_preferred_without_a_second_dns_lookup_or_request(self):
        self.resolve.return_value = [IPV6, IPV4]
        self.assertEqual(self.probe()["state"], "observed")
        self.create.assert_called_once_with(*IPV4[:3])
        self.raw.connect.assert_called_once_with(IPV4[4])
        self.resolve.assert_called_once()
        self.assertEqual(len(self.tls.sent), 1)
        self.assert_closed()

    def test_empty_or_partly_disallowed_dns_answers_never_open_a_socket(self):
        private = (*IPV4[:4], ("169.254.169.254", 443))
        for addresses in ([], [IPV6, private]):
            with self.subTest(addresses=addresses):
                self.resolve.return_value = addresses
                self.assertEqual(self.probe()["reason"], "destination_rejected")
                self.create.assert_not_called()
                self.ssl_context.assert_not_called()

    def test_invalid_tls_configuration_never_opens_a_socket(self):
        self.resolve.return_value = [IPV4]
        for error in (ssl.SSLError("synthetic CA failure"), ValueError("synthetic CA failure")):
            with self.subTest(error=type(error).__name__):
                self.ssl_context.side_effect = error
                self.assertEqual(self.probe()["reason"], "network_or_tls_failure")
                self.create.assert_not_called()

    def test_actual_invalid_pem_is_classified_before_socket_creation(self):
        self.resolve.return_value = [IPV4]
        self.ssl_context.side_effect = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).load_verify_locations
        self.settings["ca_pem"] = (
            "-----BEGIN CERTIFICATE-----\ninvalid\n-----END CERTIFICATE-----\n"
        )
        self.assertEqual(self.probe()["reason"], "network_or_tls_failure")
        self.create.assert_not_called()

    def test_connect_failure_closes_raw_socket_and_does_not_retry(self):
        for error, reason in (
            (OSError("synthetic connect failure"), "network_or_tls_failure"),
            (TimeoutError("synthetic timeout"), "timeout"),
        ):
            with self.subTest(reason=reason):
                self.raw.reset_mock()
                self.raw.connect.side_effect = error
                self.assertEqual(self.probe()["reason"], reason)
                self.raw.close.assert_called_once()
                self.raw.connect.assert_called_once()
                self.context.wrap_socket.assert_not_called()

    def test_tls_handshake_failure_closes_raw_socket(self):
        self.context.wrap_socket.side_effect = ssl.SSLError("synthetic handshake failure")
        self.assertEqual(self.probe()["reason"], "network_or_tls_failure")
        self.raw.close.assert_called_once()
        self.raw.connect.assert_called_once()
        self.assertEqual(self.tls.sent, [])

    def test_send_failure_closes_tls_and_raw_socket(self):
        self.tls.sendall = Mock(side_effect=OSError("synthetic send failure"))
        self.assertEqual(self.probe()["reason"], "network_or_tls_failure")
        self.assertTrue(self.tls.closed)
        self.raw.close.assert_called_once()

    def test_oversized_declared_or_streamed_body_closes_response_tls_and_raw_socket(self):
        for declared in (True, False):
            with self.subTest(declared=declared):
                self.raw.reset_mock()
                self.tls = TLSStream(reply(b" " * 262145, declared))
                self.context.wrap_socket.return_value = self.tls
                self.assertEqual(self.probe()["reason"], "response_too_large")
                self.assert_closed()

    def assert_closed(self):
        self.raw.close.assert_called_once()
        self.assertTrue(self.tls.closed)
        self.assertTrue(self.tls.buffer.closed)
