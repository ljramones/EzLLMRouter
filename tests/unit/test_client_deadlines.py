"""Whole-exchange deadlines with real HTTP parsing and controlled network time."""

from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from copy import deepcopy
import socket
import threading
import unittest
from unittest.mock import patch

import httpcore
import httpx

from ezllmrouter_client import (
    EzLLMRouterClient,
    EzLLMRouterError,
    IntegrationClient,
    IntegrationClientError,
)
from ezllmrouter_client import _deadline as deadlines
from ezllmrouter_client._http import ResponseReadError, bounded_request
from tests.client_parity.test_python_client import EXAMPLES
from tests.development_slice.test_retrieval_client import REQUEST


class Clock:
    now = 0.0

    def monotonic(self):
        return self.now

    def wait(self, duration, timeout, error):
        if timeout is not None and duration >= timeout:
            self.now += timeout
            raise error("synthetic phase timeout")
        self.now += duration


class WireStream(httpcore.NetworkStream):
    def __init__(self, clock, reads):
        self.clock, self.reads = clock, deque(reads)
        self.read_timeouts, self.writes, self.tls_timeouts = [], [], []
        self.closed, self.write_delay, self.tls_delay = False, 0, 0
        self.network_socket = None

    def read(self, max_bytes, timeout=None):
        self.read_timeouts.append(timeout)
        duration, value = self.reads.popleft() if self.reads else (0, b"")
        self.clock.wait(duration, timeout, httpcore.ReadTimeout)
        return value

    def write(self, buffer, timeout=None):
        self.clock.wait(self.write_delay, timeout, httpcore.WriteTimeout)
        self.writes.append(buffer)

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self.tls_timeouts.append((server_hostname, timeout))
        self.clock.wait(self.tls_delay, timeout, httpcore.ConnectTimeout)
        return self

    def close(self):
        self.closed = True

    def get_extra_info(self, info):
        return self.network_socket if info == "socket" else None


class Backend(httpcore.NetworkBackend):
    def __init__(self, stream, delay=0):
        self.stream, self.delay, self.connections = stream, delay, []

    def connect_tcp(self, host, port, timeout=None, **kwargs):
        self.connections.append((host, port, timeout))
        self.stream.clock.wait(self.delay, timeout, httpcore.ConnectTimeout)
        return self.stream


class ClientDeadlineTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.clock = Clock()
        self.stack.enter_context(patch.object(deadlines.time, "monotonic", self.clock.monotonic))

    def transport(self, reads, delay=0):
        stream = WireStream(self.clock, reads)
        backend = Backend(stream, delay)
        transport = httpx.Client(
            transport=deadlines.DeadlineHTTPTransport(backend=backend),
            timeout=httpx.Timeout(connect=10, read=35, write=30, pool=10),
            trust_env=False,
        )
        self.addCleanup(transport.close)
        return transport, stream, backend

    def test_slow_body_has_one_deadline_even_when_each_read_meets_phase_timeout(self):
        transport, stream, backend = self.transport(
            [(0, b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n"), *[(0.75, b"x")] * 20]
        )
        with self.assertRaises(ResponseReadError) as error:
            bounded_request(
                transport,
                "GET",
                "http://synthetic.invalid/",
                headers={},
                limit=100,
                total_timeout=2,
            )
        self.assertEqual(error.exception.status_code, 200)
        self.assertEqual(self.clock.now, 2)
        self.assertEqual(stream.read_timeouts, [2, 2, 1.25, 0.5])
        self.assertTrue(stream.closed)
        self.assertEqual(len(backend.connections), 1)
        self.assertEqual(len(stream.writes), 1)

    def test_partial_headers_are_also_bounded(self):
        transport, stream, _ = self.transport([(0.75, byte) for byte in (b"H", b"T", b"T", b"P")])
        with self.assertRaises(httpx.ReadTimeout):
            bounded_request(
                transport,
                "GET",
                "http://synthetic.invalid/",
                headers={},
                limit=100,
                total_timeout=2,
            )
        self.assertEqual(self.clock.now, 2)
        self.assertTrue(stream.closed)

    def test_connect_and_tls_consume_the_same_budget_before_response(self):
        transport, stream, backend = self.transport(
            [(0.5, b"HTTP/1.1 200 OK\r\nContent-Length: 1\r\n\r\n"), (1, b"x")], delay=0.5
        )
        stream.tls_delay = 0.5
        with self.assertRaises(ResponseReadError):
            bounded_request(
                transport,
                "GET",
                "https://synthetic.invalid/",
                headers={},
                limit=100,
                total_timeout=2,
            )
        self.assertEqual(backend.connections[0][2], 2)
        self.assertEqual(stream.tls_timeouts, [("synthetic.invalid", 1.5)])
        self.assertEqual(self.clock.now, 2)
        self.assertTrue(stream.closed)

    def test_write_is_limited_by_remaining_total_budget(self):
        transport, stream, _ = self.transport([], delay=0.75)
        stream.write_delay = 0.5
        with self.assertRaises(httpx.WriteTimeout):
            bounded_request(
                transport,
                "POST",
                "http://synthetic.invalid/",
                headers={},
                limit=100,
                content=b"payload",
                total_timeout=1,
            )
        self.assertEqual(self.clock.now, 1)
        self.assertTrue(stream.closed)

    def test_production_socket_write_uses_sendall_with_one_remaining_budget(self):
        class Socket:
            def settimeout(inner, timeout):
                inner.timeout = timeout

            def sendall(inner, data):
                self.clock.wait(0.75, inner.timeout, socket.timeout)

        stream = WireStream(self.clock, [])
        stream.network_socket = Socket()
        with deadlines.deadline_scope(0.5):
            with self.assertRaises(httpcore.WriteTimeout):
                deadlines._DeadlineStream(stream).write(b"payload", timeout=30)
        self.assertEqual(stream.network_socket.timeout, 0.5)
        self.assertEqual(self.clock.now, 0.5)

    def test_phase_limits_remain_shorter_than_total_budget(self):
        transport, stream, _ = self.transport([(40, b"")])
        with self.assertRaises(httpx.ReadTimeout):
            bounded_request(
                transport,
                "GET",
                "http://synthetic.invalid/",
                headers={},
                limit=100,
                total_timeout=60,
            )
        self.assertEqual(self.clock.now, 35)
        self.assertEqual(stream.read_timeouts, [35])

    def test_late_dns_connection_is_closed_before_any_request_is_sent(self):
        transport, stream, backend = self.transport([])
        original = backend.connect_tcp

        def late(*args, **kwargs):
            value = original(*args, **kwargs)
            self.clock.now += 3
            return value

        with patch.object(backend, "connect_tcp", side_effect=late):
            with self.assertRaises(httpx.ConnectTimeout):
                bounded_request(
                    transport,
                    "GET",
                    "http://synthetic.invalid/",
                    headers={},
                    limit=100,
                    total_timeout=2,
                )
        self.assertTrue(stream.closed)
        self.assertEqual(stream.writes, [])

    def test_deadline_is_fresh_when_a_connection_is_reused(self):
        response = b"HTTP/1.1 200 OK\r\nContent-Length: 1\r\n\r\nx"
        transport, stream, backend = self.transport([(0.75, response), (2, response)])
        for total in (1, 3):
            self.assertEqual(
                bounded_request(
                    transport,
                    "GET",
                    "http://synthetic.invalid/",
                    headers={},
                    limit=100,
                    total_timeout=total,
                ).content,
                b"x",
            )
        self.assertEqual(len(backend.connections), 1)
        self.assertEqual(self.clock.now, 2.75)
        self.assertEqual(deadlines.remaining(), None)

    def test_explicit_total_disable_keeps_phase_timeouts(self):
        transport, stream, _ = self.transport(
            [(30, b"HTTP/1.1 200 OK\r\nContent-Length: 1\r\n\r\n"), (30, b"x")]
        )
        self.assertEqual(
            bounded_request(
                transport,
                "GET",
                "http://synthetic.invalid/",
                headers={},
                limit=100,
                total_timeout=None,
            ).content,
            b"x",
        )
        self.assertEqual(self.clock.now, 60)
        self.assertEqual(stream.read_timeouts, [35, 35])

    def test_custom_stream_is_checked_without_coalescing_small_chunks(self):
        clock = self.clock

        class Drip(httpx.SyncByteStream):
            closed = False
            reads = 0

            def __iter__(inner):
                for _ in range(100):
                    inner.reads += 1
                    clock.now += 0.75
                    yield b"x"

            def close(inner):
                inner.closed = True

        stream = Drip()
        with httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream))
        ) as client:
            with self.assertRaises(ResponseReadError):
                bounded_request(
                    client,
                    "GET",
                    "http://synthetic.invalid/",
                    headers={},
                    limit=100,
                    total_timeout=2,
                )
        self.assertEqual(stream.reads, 3)
        self.assertTrue(stream.closed)

    def test_every_sdk_protocol_preserves_query_first_recovery_without_replay(self):
        for kind in ("wire", "successor", "attribution", "integration"):
            with self.subTest(kind=kind):
                transport, stream, backend = self.transport(
                    [(0, b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n"), *[(0.75, b"x")] * 20]
                )
                cls = IntegrationClient if kind == "integration" else EzLLMRouterClient
                with cls(
                    "http://synthetic.invalid",
                    "synthetic-token",
                    transport=transport,
                    total_timeout=2,
                ) as client:
                    action = {
                        "wire": lambda: client.submit(EXAMPLES["submit_text"]),
                        "successor": lambda: client.submit_rerank(deepcopy(REQUEST)),
                        "attribution": lambda: client.get_run("run.synthetic"),
                        "integration": lambda: client.report("dataset.synthetic"),
                    }[kind]
                    with self.assertRaises((EzLLMRouterError, IntegrationClientError)) as error:
                        action()
                self.assertEqual(error.exception.code, "TRANSPORT_OUTCOME_UNKNOWN")
                self.assertEqual(error.exception.http_status, 200)
                self.assertEqual(error.exception.retry_guidance, "query_first")
                self.assertTrue(stream.closed)
                self.assertEqual(len(backend.connections), 1)
                self.assertEqual(
                    sum(data.startswith((b"GET ", b"POST ")) for data in stream.writes), 1
                )
                if kind in ("wire", "successor"):
                    self.assertIsNotNone(error.exception.selector)

    def test_invalid_total_timeouts_are_rejected_at_construction(self):
        for cls in (EzLLMRouterClient, IntegrationClient):
            for value in (True, 0, -1, float("nan"), float("inf"), 10**1000, "10"):
                with self.subTest(client=cls.__name__, value=value), self.assertRaises(ValueError):
                    cls("http://synthetic.invalid", "token", total_timeout=value)

    def test_concurrent_requests_have_independent_deadline_contexts(self):
        barrier = threading.Barrier(2)

        def request(total):
            with deadlines.deadline_scope(total):
                barrier.wait(timeout=3)
                budget = deadlines.remaining()
            return budget, deadlines.remaining()

        with ThreadPoolExecutor(max_workers=2) as executor:
            first, second = executor.submit(request, 2), executor.submit(request, 7)
            self.assertEqual(first.result(timeout=3), (2, None))
            self.assertEqual(second.result(timeout=3), (7, None))


class SocketDeadlineTests(unittest.TestCase):
    def test_real_blocked_header_and_body_reads_expire_without_a_listener(self):
        for body in (False, True):
            with self.subTest(body=body):
                self.assert_socket_deadline(body)

    def assert_socket_deadline(self, body):
        from contextlib import suppress

        client_socket, peer = socket.socketpair()
        released = threading.Event()
        received = []

        class ConnectedSocket:
            def setsockopt(self, *_args):
                pass  # AF_UNIX socket pair has no TCP_NODELAY option.

            def __getattr__(self, name):
                return getattr(client_socket, name)

        def server():
            peer.settimeout(2)
            data = b""
            try:
                while b"\r\n\r\n" not in data:
                    chunk = peer.recv(4096)
                    if not chunk:
                        return
                    data += chunk
                received.append(data)
                peer.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n" if body else b"H")
                released.wait(3)
            except OSError:
                return  # Cleanup also releases a failed test's blocked peer.

        thread = threading.Thread(target=server)
        thread.start()
        with ThreadPoolExecutor(max_workers=1) as executor:
            try:
                with patch.object(socket, "create_connection", return_value=ConnectedSocket()):
                    with EzLLMRouterClient(
                        "http://synthetic.invalid", "token", total_timeout=0.15
                    ) as client:
                        future = executor.submit(client.get_capabilities)
                        with self.assertRaises(EzLLMRouterError) as error:
                            future.result(timeout=2)
                        self.assertEqual(error.exception.http_status, 200 if body else None)
                        self.assertEqual(error.exception.retry_guidance, "query_first")
                self.assertEqual(len(received), 1)
                self.assertEqual(client_socket.fileno(), -1)
            finally:
                released.set()
                for endpoint in (client_socket, peer):
                    with suppress(OSError):
                        endpoint.shutdown(socket.SHUT_RDWR)
                    endpoint.close()
                thread.join(3)
        self.assertFalse(thread.is_alive())
