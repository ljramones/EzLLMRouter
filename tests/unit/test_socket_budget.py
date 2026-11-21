"""Bounded socket ownership and framing without worker-package import fixtures."""

import asyncio
import socket
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from ezllmrouter_server.connection_resources import BoundedUnixServer
from ezllmrouter_server.gateway import choice_b_wire as wire


class SocketBudgetTests(unittest.TestCase):
    def pair(self):
        first, second = socket.socketpair()
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        return first, second

    def test_shutdown_continues_when_a_tracked_connection_is_already_closed(self):
        server = BoundedUnixServer("unused", lambda *_: None, bind_and_activate=False)
        self.addCleanup(server.server_close)
        closed, closed_peer = self.pair()
        active, active_peer = self.pair()
        closed.close()
        with self.assertRaises(OSError):
            closed.shutdown(socket.SHUT_RDWR)
        # A handler can close its stream before removing it from the tracked set.
        # Pin that state instead of relying on the handler thread winning a race.
        with server._connections_lock:
            server._active_connections.update((closed, active))
        server.server_close()
        self.assertTrue(server._connections_closed)
        self.assertEqual(server.socket.fileno(), -1)
        for peer in (closed_peer, active_peer):
            peer.settimeout(2)
            self.assertEqual(peer.recv(1), b"")

    def test_handler_join_uses_one_bounded_shutdown_deadline(self):
        entered, release = threading.Event(), threading.Event()

        def handle(*_):
            entered.set()
            release.wait(3)

        server = BoundedUnixServer("unused", handle, bind_and_activate=False)
        server.handler_join_timeout = 0.02
        stream, _ = self.pair()
        server.process_request(stream, None)
        self.assertTrue(entered.wait(1))
        started = time.monotonic()
        try:
            with self.assertRaisesRegex(RuntimeError, "shutdown deadline"):
                server.server_close()
            self.assertLess(time.monotonic() - started, 0.5)
        finally:
            release.set()
            server.handler_join_timeout = 1
            server.server_close()

    def test_connection_cap_rejects_excess_and_close_releases_a_partial_reader(self):
        entered = threading.Event()

        def handle(stream, address, server):
            entered.set()
            stream.recv(1)

        server = BoundedUnixServer("unused", handle, bind_and_activate=False, max_connections=1)
        self.addCleanup(server.server_close)
        active, peer = self.pair()
        rejected, rejected_peer = self.pair()
        server.process_request(active, None)
        self.assertTrue(entered.wait(2))
        server.process_request(rejected, None)
        self.assertEqual(rejected_peer.recv(1), b"")
        server.server_close()
        self.assertTrue(server._connection_slots.acquire(timeout=2))
        self.assertEqual(peer.recv(1), b"")
        self.assertEqual(server._active_connections, set())
        server._connection_slots.release()

    def test_connection_thread_start_failure_returns_slot_and_closes_socket(self):
        server = BoundedUnixServer(
            "unused", lambda *_: None, bind_and_activate=False, max_connections=1
        )
        self.addCleanup(server.server_close)
        stream, peer = self.pair()
        with patch.object(
            threading.Thread, "start", side_effect=RuntimeError("controlled start failure")
        ):
            with self.assertRaises(RuntimeError):
                server.process_request(stream, None)
        self.assertEqual(peer.recv(1), b"")
        self.assertEqual(server._active_connections, set())
        self.assertTrue(server._connection_slots.acquire(blocking=False))
        server._connection_slots.release()

    def test_slow_frame_bytes_share_one_absolute_deadline(self):
        timeouts = []
        stream = SimpleNamespace(recv=lambda _: b"\x00", settimeout=timeouts.append)
        with patch.object(wire.time, "monotonic", side_effect=[0, 0, 1, 2, 3]):
            with self.assertRaises(TimeoutError):
                wire.receive(stream, timeout=3)
        self.assertEqual(timeouts, [3, 2, 1])

    def test_partial_frame_and_blocked_reply_time_out_on_real_socket_pairs(self):
        first, peer = self.pair()
        peer.sendall(b"\x00\x00")
        with self.assertRaises(TimeoutError):
            wire.receive(first, timeout=0.025)
        first.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024)
        with self.assertRaises(TimeoutError):
            wire.send(first, {"synthetic": "x" * 100000}, timeout=0.025)

    def test_async_exchange_cancellation_closes_the_socket_without_a_background_thread(self):
        async def scenario():
            stream, peer = self.pair()
            peer.setblocking(False)
            loop = asyncio.get_running_loop()
            socket_api = SimpleNamespace(
                AF_UNIX=socket.AF_UNIX, SOCK_STREAM=socket.SOCK_STREAM, socket=lambda *_: stream
            )
            with (
                patch.object(wire, "socket", socket_api),
                patch.object(loop, "sock_connect", new=AsyncMock()),
            ):
                task = asyncio.create_task(
                    wire.async_exchange("unused", {"request": "synthetic"}, 10)
                )
                received = await loop.sock_recv(peer, 4096)
                self.assertTrue(received)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertEqual(await loop.sock_recv(peer, 1), b"")
            self.assertEqual(stream.fileno(), -1)

        asyncio.run(scenario())

    def test_async_exchange_round_trip_preserves_the_record_and_byte_cap(self):
        async def scenario():
            stream, peer = self.pair()
            peer.setblocking(False)
            loop = asyncio.get_running_loop()
            socket_api = SimpleNamespace(
                AF_UNIX=socket.AF_UNIX, SOCK_STREAM=socket.SOCK_STREAM, socket=lambda *_: stream
            )
            with (
                patch.object(wire, "socket", socket_api),
                patch.object(loop, "sock_connect", new=AsyncMock()),
            ):
                task = asyncio.create_task(
                    wire.async_exchange("unused", {"request": "synthetic"}, 1)
                )
                self.assertTrue(await loop.sock_recv(peer, 4096))
                await loop.sock_sendall(peer, wire._frame({"result": "exact\nresponse"}))
                self.assertEqual(await task, {"result": "exact\nresponse"})
            self.assertEqual(stream.fileno(), -1)

        asyncio.run(scenario())
