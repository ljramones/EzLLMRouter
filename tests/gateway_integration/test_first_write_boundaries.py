"""First-write authority and backpressure boundaries over real local socket pairs.

TLS drain tests queue opaque fixture bytes in a real MemoryBIO; the separate
loopback TLS fixture qualifies handshake, encryption and hostname verification.
"""

import asyncio
import socket
import ssl
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import httpcore

from ezllmrouter_server.gateway.guard import ACTIVE, GuardRejected, Invocation
from ezllmrouter_server.gateway import owned_sender_transport as plaintext
from ezllmrouter_server.gateway import owned_tls_sender_transport as tls


PAYLOAD = b"synthetic request bytes"


class FirstWriteBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self, mode):
        sender, receiver = socket.socketpair()
        self.addCleanup(sender.close)
        self.addCleanup(receiver.close)
        sender.setblocking(False)
        receiver.setblocking(False)
        sender.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
        authority = plaintext.LocalSendAuthority()
        fresh = Mock()
        item = Invocation(
            "submission.first-write",
            "attempt.first-write",
            {"deadline": "2099-01-01T00:00:00Z"},
            {},
            fresh,
            lambda _receipt: None,
            committed=True,
            released=True,
            authority_epoch=authority.snapshot_epoch(),
        )
        stream = (
            plaintext.OwnedSocketStream(sender, authority)
            if mode == "plain"
            else tls.OwnedTLSStream(sender, authority)
        )
        fixture = SimpleNamespace(
            sender=sender,
            receiver=receiver,
            authority=authority,
            item=item,
            context=item,
            fresh=fresh,
            stream=stream,
            module=plaintext if mode == "plain" else tls,
        )
        if mode == "tls":
            stream.outgoing = ssl.MemoryBIO()

        async def send(data=PAYLOAD, timeout=None, *, request=True):
            if mode == "plain":
                token = ACTIVE.set(fixture.context)
                try:
                    await stream.write(data, timeout)
                finally:
                    ACTIVE.reset(token)
            else:
                stream.invocation = fixture.context
                stream.outgoing.write(data)
                deadline = None if timeout is None else asyncio.get_running_loop().time() + timeout
                await stream._drain(deadline, request=request)

        fixture.send = send
        return fixture

    def fill(self, fixture):
        total = 0
        while True:
            try:
                total += fixture.sender.send(b"x" * 65536)
            except BlockingIOError:
                return total

    def received(self, fixture):
        data = bytearray()
        while True:
            try:
                part = fixture.receiver.recv(65536)
            except BlockingIOError:
                break
            if not part:
                break
            data.extend(part)
        return bytes(data)

    async def test_missing_or_incomplete_plaintext_context_never_sends(self):
        for state in ("missing", "uncommitted", "unreleased"):
            with self.subTest(state=state):
                fixture = self.fixture("plain")
                if state == "missing":
                    fixture.context = None
                else:
                    setattr(fixture.item, state.removeprefix("un"), False)
                with self.assertRaises(GuardRejected) as caught:
                    await fixture.send()
                self.assertEqual(caught.exception.code, "NO_TRUSTED_CONTEXT")
                fixture.fresh.assert_not_called()
                self.assertEqual(self.received(fixture), b"")
                self.assertFalse(fixture.item.first_bytes_accepted)
                self.assertTrue(fixture.stream.terminal)
                self.assertEqual(fixture.sender.fileno(), -1)

    async def test_pending_tls_request_requires_an_invocation(self):
        fixture = self.fixture("tls")
        fixture.context = None
        with self.assertRaises(GuardRejected) as caught:
            await fixture.send()
        self.assertEqual(caught.exception.code, "NO_TRUSTED_CONTEXT")
        fixture.fresh.assert_not_called()
        self.assertEqual(self.received(fixture), b"")
        self.assertFalse(fixture.item.first_bytes_accepted)
        self.assertFalse(fixture.stream.request_bytes_accepted)

    async def test_current_first_write_authority_rejects_each_invalid_state(self):
        for mode in ("plain", "tls"):
            for state in ("abandoned", "revoked", "stale_epoch", "expired"):
                with self.subTest(mode=mode, state=state):
                    fixture = self.fixture(mode)
                    if state == "abandoned":
                        fixture.item.abandoned = True
                    elif state == "revoked":
                        fixture.authority.revoke()
                    elif state == "stale_epoch":
                        fixture.authority.revoke()
                        fixture.authority.restore()
                    else:
                        fixture.item.execution_deadline = "2000-01-01T00:00:00Z"
                    with self.assertRaises(GuardRejected) as caught:
                        await fixture.send()
                    self.assertEqual(caught.exception.code, "FDC_REJECTED")
                    fixture.fresh.assert_called_once_with()
                    self.assertEqual(self.received(fixture), b"")
                    self.assertFalse(fixture.item.first_bytes_accepted)
                    self.assertEqual(fixture.item.observations, [])

    async def test_backpressure_preserves_bytes_and_rechecks_with_and_without_timeout(self):
        for mode in ("plain", "tls"):
            for timeout in (None, 3):
                with self.subTest(mode=mode, timeout=timeout):
                    fixture = self.fixture(mode)
                    primed = self.fill(fixture)
                    entered, waits = asyncio.Event(), []
                    original = fixture.module._writable

                    async def writable(
                        sock, remaining, *, waits=waits, entered=entered, original=original
                    ):
                        waits.append(remaining)
                        entered.set()
                        await original(sock, remaining)

                    with patch.object(fixture.module, "_writable", writable):
                        task = asyncio.create_task(fixture.send(timeout=timeout))
                        try:
                            await asyncio.wait_for(entered.wait(), 2)
                            self.assertFalse(fixture.item.first_bytes_accepted)
                            self.assertFalse(task.done())
                            expected = b"x" * primed + PAYLOAD
                            received = bytearray()
                            while len(received) < len(expected):
                                part = await asyncio.wait_for(
                                    asyncio.get_running_loop().sock_recv(fixture.receiver, 65536), 3
                                )
                                self.assertTrue(part, "stream closed before the complete request")
                                received.extend(part)
                            await asyncio.wait_for(task, 3)
                            self.assertEqual(bytes(received), expected)
                        finally:
                            if not task.done():
                                task.cancel()
                            await asyncio.gather(task, return_exceptions=True)
                    self.assertGreaterEqual(fixture.fresh.call_count, 2)
                    self.assertTrue(fixture.item.first_bytes_accepted)
                    self.assertEqual(len(fixture.item.observations), 1)
                    self.assertTrue(waits)
                    if timeout is None:
                        self.assertEqual(waits, [None] * len(waits))
                    else:
                        self.assertTrue(all(0 < remaining <= timeout for remaining in waits))

    async def test_expired_write_timeout_does_not_wait_or_accept_request_bytes(self):
        for mode in ("plain", "tls"):
            with self.subTest(mode=mode):
                fixture = self.fixture(mode)
                primed = self.fill(fixture)
                with patch.object(fixture.module, "_writable") as writable:
                    with self.assertRaises(httpcore.WriteTimeout):
                        await fixture.send(timeout=0)
                    writable.assert_not_called()
                self.assertEqual(self.received(fixture), b"x" * primed)
                self.assertFalse(fixture.item.first_bytes_accepted)
                self.assertEqual(fixture.item.observations, [])

    async def test_effective_revocation_while_backpressured_prevents_first_acceptance(self):
        for mode in ("plain", "tls"):
            with self.subTest(mode=mode):
                fixture = self.fixture(mode)
                primed = self.fill(fixture)
                entered = asyncio.Event()
                original = fixture.module._writable

                async def writable(sock, remaining, *, entered=entered, original=original):
                    entered.set()
                    await original(sock, remaining)

                with patch.object(fixture.module, "_writable", writable):
                    task = asyncio.create_task(fixture.send())
                    try:
                        await asyncio.wait_for(entered.wait(), 2)
                        self.assertFalse(fixture.item.first_bytes_accepted)
                        fixture.authority.revoke()
                        self.assertEqual(self.received(fixture), b"x" * primed)
                        with self.assertRaises(GuardRejected) as caught:
                            await asyncio.wait_for(task, 2)
                        self.assertEqual(caught.exception.code, "FDC_REJECTED")
                    finally:
                        if not task.done():
                            task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                self.assertGreaterEqual(fixture.fresh.call_count, 2)
                self.assertEqual(self.received(fixture), b"")
                self.assertFalse(fixture.item.first_bytes_accepted)
                self.assertEqual(fixture.item.observations, [])

    async def test_handshake_and_accepted_suffix_preserve_first_request_boundary(self):
        fixture = self.fixture("tls")
        fixture.context = None
        await fixture.send(b"opaque handshake fixture", request=False)
        self.assertEqual(self.received(fixture), b"opaque handshake fixture")
        fixture.fresh.assert_not_called()
        self.assertFalse(fixture.stream.request_bytes_accepted)
        self.assertFalse(fixture.item.first_bytes_accepted)
        fixture.context = fixture.item
        await fixture.send()
        self.assertEqual(self.received(fixture), PAYLOAD)
        fixture.fresh.assert_called_once_with()
        self.assertTrue(fixture.stream.request_bytes_accepted)
        self.assertTrue(fixture.item.first_bytes_accepted)
        fixture.authority.revoke()
        await fixture.send(b"same accepted request suffix")
        self.assertEqual(self.received(fixture), b"same accepted request suffix")
        fixture.fresh.assert_called_once_with()
        self.assertEqual(
            fixture.item.observations, ["FIRST_TLS_REQUEST_BYTES_ACCEPTED_BY_LOCAL_SOCKET"]
        )
