"""Concurrent owned HTTP/TLS exchanges against disposable loopback receivers."""

import asyncio
from http.server import ThreadingHTTPServer
import json
import socket
import threading
import unittest

import httpcore
import httpx

from ezllmrouter_server.gateway.guard import ACTIVE, GuardRejected
from ezllmrouter_server.gateway.owned_sender_transport import OwnedHTTPTransport, OwnedSocketStream
from ezllmrouter_server.gateway.owned_tls_sender_transport import OwnedTLSHTTPTransport
from tests.gateway_integration import test_owned_tls_sender_transport as tls


class PlainBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, authority, address, pause):
        self.authority, self.address, self.pause = authority, address, pause

    async def connect_tcp(self, host, port, timeout=None, **_kwargs):
        if (host, port) != ("127.0.0.1", 8766):
            raise AssertionError("unexpected synthetic destination")
        sock = socket.socket()
        sock.setblocking(False)
        try:
            await asyncio.wait_for(
                asyncio.get_running_loop().sock_connect(sock, self.address), timeout
            )
            if self.pause is not None:
                await self.pause()
            return OwnedSocketStream(sock, self.authority)
        except BaseException:
            sock.close()
            raise

    async def connect_unix_socket(self, *_args, **_kwargs):
        raise AssertionError("unexpected Unix destination")

    async def sleep(self, _seconds):
        raise AssertionError("unexpected transport replay")


class ConcurrentTransportTests(unittest.TestCase):
    invocation = tls.OwnedTLSProof.invocation

    def setUp(self):
        tls.OwnedTLSProof.setUp(self)
        self.server.socket.listen(32)
        self.plain = ThreadingHTTPServer(("127.0.0.1", 0), tls.Receiver)
        self.plain.requests = []
        self.plain.socket.listen(32)
        self.listener = threading.Thread(target=self.plain.serve_forever, daemon=True)
        self.listener.start()
        self.addCleanup(self.plain.server_close)
        self.addCleanup(self.plain.shutdown)

    def test_shared_revocation_and_cancellation_preserve_exact_concurrent_delivery_counts(self):
        for mode in ("plain", "tls"):
            with self.subTest(mode=mode):
                self.authority.restore()
                asyncio.run(self.scenario(mode))

    async def scenario(self, mode):
        arrived = asyncio.Queue()
        releases = {index: asyncio.Event() for index in range(4, 12)}
        items = {}

        async def exchange(index):
            async def pause():
                arrived.put_nowait(index)
                await releases[index].wait()

            wait = pause if index in releases else None
            item = self.invocation()
            item.attempt_id = f"attempt.concurrent.{mode}.{index}"
            items[index] = item
            payload = json.dumps(
                {"model": "model-test", "input": f"message.{index}", "stream": False}
            ).encode()
            if mode == "tls":
                transport = OwnedTLSHTTPTransport(
                    self.authority,
                    "openai.responses.v1",
                    self.settings,
                    controlled=True,
                    first_write_wait=wait,
                )
                url = self.settings["origin"] + "/v1/responses"
            else:
                transport = OwnedHTTPTransport(self.authority)
                transport.pool._network_backend = PlainBackend(
                    self.authority, self.plain.server_address, wait
                )
                url = "http://127.0.0.1:8766/v1/chat/completions"
            token = ACTIVE.set(item)
            try:
                request = httpx.Request(
                    "POST",
                    url,
                    headers={
                        "Authorization": "Bearer synthetic-concurrent-credential",
                        "Content-Type": "application/json",
                    },
                    content=payload,
                    extensions={"timeout": {"connect": 5, "read": 5, "write": 5, "pool": 5}},
                )
                response = await transport.handle_async_request(request)
                await response.aread()
                return response.status_code
            finally:
                ACTIVE.reset(token)
                await transport.aclose()

        tasks = [asyncio.create_task(exchange(index)) for index in range(12)]
        try:
            self.assertEqual(await asyncio.wait_for(asyncio.gather(*tasks[:4]), 8), [200] * 4)
            paused = [await asyncio.wait_for(arrived.get(), 8) for _ in range(8)]
            self.assertEqual(set(paused), set(range(4, 12)))
            self.authority.revoke()
            for task in tasks[8:]:
                task.cancel()
            for event in releases.values():
                event.set()
            results = await asyncio.wait_for(asyncio.gather(*tasks[4:], return_exceptions=True), 8)
            self.assertTrue(all(isinstance(value, GuardRejected) for value in results[:4]))
            self.assertTrue(all(isinstance(value, asyncio.CancelledError) for value in results[4:]))
            self.assertTrue(all(items[index].first_bytes_accepted for index in range(4)))
            self.assertTrue(all(not items[index].first_bytes_accepted for index in range(4, 12)))
            receiver = self.server if mode == "tls" else self.plain
            self.assertEqual(len(receiver.requests), 4)
            self.assertEqual(
                {json.loads(row[2])["input"] for row in receiver.requests},
                {f"message.{index}" for index in range(4)},
            )
        finally:
            for event in releases.values():
                event.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
