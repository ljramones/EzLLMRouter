"""Local deterministic controls for the bounded owned-socket sender."""

import asyncio
from tests.support import async_wait_until
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import socket
import unittest
import threading


ROOT = Path(__file__).resolve().parents[2]
import httpcore  # noqa: E402
import httpx  # noqa: E402
from ezllmrouter_server.gateway.guard import (
    ACTIVE,
    GuardRejected,
    GuardTransport,
    Invocation,
    PROVIDER_URL,
    provider_expectation,
)  # noqa: E402
from ezllmrouter_server.gateway.owned_sender_transport import (
    LocalSendAuthority,
    OwnedHTTPTransport,
    OwnedSocketStream,
)  # noqa: E402
from tests.gateway_integration.test_guard import invocation as guard_invocation  # noqa: E402


def local_invocation(attempt="attempt.owned.local", authority_epoch=0):
    deadline = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    item = Invocation(
        "submission.owned.local",
        attempt,
        {"deadline": deadline, "per_attempt_total_timeout_ms": 3000},
        {},
        lambda: None,
        lambda _receipt: None,
    )
    item.committed = True
    item.released = True
    item.authority_epoch = authority_epoch
    return item


def pair():
    sender, receiver = socket.socketpair()
    sender.setblocking(False)
    receiver.setblocking(False)
    return sender, receiver


def fill_sender(sock):
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
    total = 0
    while True:
        try:
            total += sock.send(b"x" * 65536)
        except BlockingIOError:
            return total


class PairBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, authority, sockets):
        self.authority, self.sockets = authority, sockets

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if (host, port) != ("127.0.0.1", 8766):
            raise AssertionError("wrong destination")
        return OwnedSocketStream(self.sockets.pop(0), self.authority)

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise AssertionError("unexpected Unix provider connection")

    async def sleep(self, seconds):
        raise AssertionError("unexpected retry")


class OwnedSenderTests(unittest.TestCase):
    def test_blocked_final_check_does_not_stall_another_paid_reply(self):
        async def scenario():
            authority = LocalSendAuthority()
            sender, receiver = pair()
            paid_sender, paid_receiver = pair()
            stream, paid_stream = (
                OwnedSocketStream(sender, authority),
                OwnedSocketStream(paid_sender, authority),
            )
            item = local_invocation()
            entered, release = threading.Event(), threading.Event()

            def fresh():
                entered.set()
                if not release.wait(3):
                    raise AssertionError("final check was not released")

            item.fresh_check = fresh
            token = ACTIVE.set(item)
            pending = asyncio.create_task(stream.write(b"pending request", timeout=1))
            try:
                for _ in range(100):
                    if entered.is_set():
                        break
                    await asyncio.sleep(0.001)
                self.assertTrue(entered.is_set())
                paid_receiver.send(b"paid result")
                self.assertEqual(await paid_stream.read(64, timeout=0.1), b"paid result")
                self.assertFalse(item.first_bytes_accepted)
            finally:
                release.set()
                await pending
                ACTIVE.reset(token)
                await stream.aclose()
                await paid_stream.aclose()
                receiver.close()
                paid_receiver.close()

        asyncio.run(scenario())

    def test_real_httpcore_pool_queue_revocation_blocks_second_headers(self):
        async def scenario():
            first_sender, first_receiver = pair()
            second_sender, second_receiver = pair()
            authority = LocalSendAuthority()
            transport = OwnedHTTPTransport(authority)
            await transport.aclose()
            transport.pool = httpcore.AsyncConnectionPool(
                max_connections=1,
                max_keepalive_connections=0,
                http1=True,
                http2=False,
                retries=0,
                network_backend=PairBackend(authority, [first_sender, second_sender]),
            )
            guard = GuardTransport(transport)
            receipts = []
            first = guard_invocation(aid="attempt.queue.first", commit=receipts.append)
            second = guard_invocation(aid="attempt.queue.second", commit=receipts.append)
            for item in (first, second):
                item.plan["deadline"] = (
                    datetime.now(timezone.utc) + timedelta(minutes=1)
                ).isoformat()
                item.plan["per_attempt_total_timeout_ms"] = 3000
                item.authority_epoch = authority.snapshot_epoch()
            key = "sk-" + "q" * 40
            for item in (first, second):
                item.provider_key = key
            entered, release = asyncio.Event(), asyncio.Event()

            async def held_receiver():
                raw = b""
                while b'"model":"model.demo"' not in raw:
                    raw += await asyncio.wait_for(
                        asyncio.get_running_loop().sock_recv(first_receiver, 65536), 2
                    )
                entered.set()
                await release.wait()
                await asyncio.get_running_loop().sock_sendall(
                    first_receiver,
                    b"HTTP/1.1 200 OK\r\ncontent-length: 2\r\nconnection: close\r\n\r\nOK",
                )
                return raw

            async def request(item):
                token = ACTIVE.set(item)
                try:
                    final = httpx.Request(
                        "POST",
                        PROVIDER_URL,
                        json=provider_expectation(item.projection),
                        headers={"authorization": "Bearer " + key},
                        extensions={
                            "timeout": {"connect": 2.0, "read": 2.0, "write": 2.0, "pool": 2.0}
                        },
                    )
                    response = await guard.handle_async_request(final)
                    return await response.aread()
                finally:
                    ACTIVE.reset(token)

            server = asyncio.create_task(held_receiver())
            first_task = asyncio.create_task(request(first))
            try:
                await asyncio.wait_for(entered.wait(), 2)
                second_task = asyncio.create_task(request(second))
                await async_wait_until(
                    lambda: len(transport.pool._requests) == 2
                    and transport.pool._requests[-1].is_queued()
                )
                self.assertEqual(len(transport.pool._requests), 2)
                self.assertTrue(transport.pool._requests[-1].is_queued())
                self.assertFalse(second.first_bytes_accepted)
                epoch = authority.revoke()
                release.set()
                self.assertEqual(await asyncio.wait_for(first_task, 2), b"OK")
                with self.assertRaises(GuardRejected):
                    await asyncio.wait_for(second_task, 2)
                arrival = await asyncio.wait_for(server, 2)
                try:
                    second_bytes = second_receiver.recv(65536)
                except BlockingIOError:
                    second_bytes = b""
                self.assertEqual(second_bytes, b"")
                return (
                    epoch,
                    arrival,
                    receipts,
                    first.first_bytes_accepted,
                    second.first_bytes_accepted,
                )
            finally:
                for task in (first_task, server):
                    if not task.done():
                        task.cancel()
                await transport.aclose()
                first_receiver.close()
                second_receiver.close()

        epoch, arrival, receipts, first, second = asyncio.run(scenario())
        self.assertEqual(epoch, 1)
        self.assertIn(b"attempt.queue.first", arrival)
        self.assertEqual(len(receipts), 2)
        self.assertTrue(first)
        self.assertFalse(second)

    def test_positive_guard_httpcore_h11_and_one_socket_arrival(self):
        async def scenario():
            sender, receiver = pair()
            authority = LocalSendAuthority()
            transport = OwnedHTTPTransport(authority)
            await transport.aclose()
            transport.pool = httpcore.AsyncConnectionPool(
                max_connections=1,
                max_keepalive_connections=0,
                http1=True,
                http2=False,
                retries=0,
                network_backend=PairBackend(authority, [sender]),
            )
            receipts = []
            item = guard_invocation(aid="attempt.owned.guard", commit=receipts.append)
            item.plan["deadline"] = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
            item.plan["per_attempt_total_timeout_ms"] = 3000
            item.authority_epoch = authority.snapshot_epoch()
            key = "sk-" + "t" * 40
            item.provider_key = key

            async def synthetic_receiver():
                body = b""
                while b"\r\n\r\n" not in body or b'"model":"model.demo"' not in body:
                    body += await asyncio.wait_for(
                        asyncio.get_running_loop().sock_recv(receiver, 65536), 2
                    )
                response = {
                    "choices": [{"message": {"content": "Hello."}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 2, "completion_tokens": 1},
                }
                raw = json.dumps(response).encode()
                await asyncio.get_running_loop().sock_sendall(
                    receiver,
                    b"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\ncontent-length: "
                    + str(len(raw)).encode()
                    + b"\r\nconnection: close\r\n\r\n"
                    + raw,
                )
                return body

            task = asyncio.create_task(synthetic_receiver())
            token = ACTIVE.set(item)
            try:
                request = httpx.Request(
                    "POST",
                    PROVIDER_URL,
                    json=provider_expectation(item.projection),
                    headers={"authorization": "Bearer " + key},
                    extensions={
                        "timeout": {"connect": 2.0, "read": 2.0, "write": 2.0, "pool": 2.0}
                    },
                )
                response = await GuardTransport(transport).handle_async_request(request)
                data = await response.aread()
                arrival = await task
                return response.status_code, data, arrival, receipts, item.first_bytes_accepted
            finally:
                ACTIVE.reset(token)
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                await transport.aclose()
                receiver.close()

        status, data, arrival, receipts, accepted = asyncio.run(scenario())
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data)["choices"][0]["message"]["content"], "Hello.")
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]["attempt_id"], "attempt.owned.guard")
        self.assertIn(b"x-ezllmrouter-attempt: attempt.owned.guard", arrival.lower())
        self.assertTrue(accepted)

    def test_revoke_before_first_write_rejects_without_bytes(self):
        async def scenario():
            sender, receiver = pair()
            authority = LocalSendAuthority()
            stream = OwnedSocketStream(sender, authority)
            item = local_invocation()
            authority.revoke()
            token = ACTIVE.set(item)
            try:
                with self.assertRaises(GuardRejected):
                    await stream.write(b"POST /v1/chat/completions HTTP/1.1\r\n\r\n", 1)
                try:
                    observed = receiver.recv(1)
                except BlockingIOError:
                    observed = b""
                self.assertEqual(observed, b"")
                return item.first_bytes_accepted
            finally:
                ACTIVE.reset(token)
                await stream.aclose()
                receiver.close()

        self.assertFalse(asyncio.run(scenario()))

    def test_restore_does_not_resurrect_queued_attempt(self):
        async def scenario():
            sender, receiver = pair()
            authority = LocalSendAuthority()
            item = local_invocation(authority_epoch=authority.snapshot_epoch())
            authority.revoke()
            authority.restore()
            self.assertFalse(authority.is_revoked())
            stream = OwnedSocketStream(sender, authority)
            token = ACTIVE.set(item)
            try:
                with self.assertRaises(GuardRejected):
                    await stream.write(b"POST /v1/chat/completions HTTP/1.1\r\n\r\n", 1)
                observed = receiver.recv(1)
                return observed, item.first_bytes_accepted
            finally:
                ACTIVE.reset(token)
                await stream.aclose()
                receiver.close()

        observed, accepted = asyncio.run(scenario())
        self.assertEqual(observed, b"")
        self.assertFalse(accepted)

    def test_actual_backpressure_rechecks_after_effective_revocation(self):
        async def scenario():
            sender, receiver = pair()
            primed = fill_sender(sender)
            authority = LocalSendAuthority()
            stream = OwnedSocketStream(sender, authority)
            item = local_invocation()

            async def blocked_write():
                token = ACTIVE.set(item)
                try:
                    await stream.write(b"POST /v1/chat/completions HTTP/1.1\r\n\r\n", 2)
                finally:
                    ACTIVE.reset(token)

            task = asyncio.create_task(blocked_write())
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            self.assertFalse(item.first_bytes_accepted)
            authority.revoke()
            drained = bytearray()
            while True:
                try:
                    drained.extend(receiver.recv(65536))
                except BlockingIOError:
                    break
            with self.assertRaises(GuardRejected):
                await asyncio.wait_for(task, 2)
            try:
                observed = receiver.recv(1)
            except BlockingIOError:
                observed = b""
            self.assertEqual(observed, b"")
            await stream.aclose()
            receiver.close()
            return primed, len(drained), item.first_bytes_accepted

        primed, drained, accepted = asyncio.run(scenario())
        self.assertEqual(primed, drained)
        self.assertFalse(accepted)

    def test_partial_write_consumes_first_authority_and_finishes_same_attempt(self):
        async def scenario():
            sender, receiver = pair()
            sender.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
            authority = LocalSendAuthority()
            stream = OwnedSocketStream(sender, authority)
            item = local_invocation()
            data = b"p" * 200000

            async def send():
                token = ACTIVE.set(item)
                try:
                    await stream.write(data, 3)
                finally:
                    ACTIVE.reset(token)

            task = asyncio.create_task(send())
            await async_wait_until(lambda: item.first_bytes_accepted)
            self.assertTrue(item.first_bytes_accepted)
            self.assertFalse(task.done())
            authority.revoke()
            received = bytearray()
            while len(received) < len(data):
                received.extend(
                    await asyncio.wait_for(asyncio.get_running_loop().sock_recv(receiver, 65536), 3)
                )
            await asyncio.wait_for(task, 3)
            self.assertEqual(stream.accepted_bytes, len(data))
            await stream.aclose()
            receiver.close()
            return bytes(received), data

        received, expected = asyncio.run(scenario())
        self.assertEqual(received, expected)

    def test_consumed_connection_rejects_another_attempt(self):
        async def scenario():
            sender, receiver = pair()
            authority = LocalSendAuthority()
            stream = OwnedSocketStream(sender, authority)
            first, second = local_invocation("attempt.first"), local_invocation("attempt.second")
            token = ACTIVE.set(first)
            try:
                await stream.write(b"first", 1)
            finally:
                ACTIVE.reset(token)
            token = ACTIVE.set(second)
            try:
                with self.assertRaises(GuardRejected):
                    await stream.write(b"second", 1)
            finally:
                ACTIVE.reset(token)
            result = receiver.recv(100)
            await stream.aclose()
            receiver.close()
            return result, first.first_bytes_accepted, second.first_bytes_accepted

        result, first, second = asyncio.run(scenario())
        self.assertEqual(result, b"first")
        self.assertTrue(first)
        self.assertFalse(second)

    def test_cancel_before_first_acceptance_is_known_no_send(self):
        async def scenario():
            sender, receiver = pair()
            primed = fill_sender(sender)
            stream = OwnedSocketStream(sender, LocalSendAuthority())
            item = local_invocation()

            async def send():
                token = ACTIVE.set(item)
                try:
                    await stream.write(b"POST /v1/chat/completions HTTP/1.1\r\n\r\n", 2)
                finally:
                    ACTIVE.reset(token)

            task = asyncio.create_task(send())
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            drained = bytearray()
            while True:
                try:
                    chunk = receiver.recv(65536)
                    if not chunk:
                        break
                    drained.extend(chunk)
                except BlockingIOError:
                    break
            receiver.close()
            return primed, len(drained), item.first_bytes_accepted, stream.terminal

        primed, drained, accepted, terminal = asyncio.run(scenario())
        self.assertEqual(primed, drained)
        self.assertFalse(accepted)
        self.assertTrue(terminal)

    def test_cancel_after_partial_acceptance_is_uncertain_and_not_replayable(self):
        async def scenario():
            sender, receiver = pair()
            sender.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
            stream = OwnedSocketStream(sender, LocalSendAuthority())
            item = local_invocation()

            async def send():
                token = ACTIVE.set(item)
                try:
                    await stream.write(b"p" * 200000, 3)
                finally:
                    ACTIVE.reset(token)

            task = asyncio.create_task(send())
            await async_wait_until(lambda: item.first_bytes_accepted)
            self.assertTrue(item.first_bytes_accepted)
            self.assertFalse(task.done())
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            accepted_bytes = stream.accepted_bytes
            self.assertGreater(accepted_bytes, 0)
            self.assertLess(accepted_bytes, 200000)
            token = ACTIVE.set(item)
            try:
                with self.assertRaises(GuardRejected):
                    await stream.write(b"p" * 200000, 1)
            finally:
                ACTIVE.reset(token)
            received = bytearray()
            while True:
                chunk = receiver.recv(65536)
                if not chunk:
                    break
                received.extend(chunk)
            receiver.close()
            return accepted_bytes, bytes(received), stream.terminal

        accepted, received, terminal = asyncio.run(scenario())
        self.assertEqual(len(received), accepted)
        self.assertEqual(received, b"p" * accepted)
        self.assertTrue(terminal)

    def test_socket_failure_before_acceptance_is_known_no_send(self):
        async def scenario():
            sender, receiver = pair()
            receiver.close()
            stream = OwnedSocketStream(sender, LocalSendAuthority())
            item = local_invocation()
            token = ACTIVE.set(item)
            try:
                with self.assertRaises(OSError):
                    await stream.write(b"POST /v1/chat/completions HTTP/1.1\r\n\r\n", 1)
                return item.first_bytes_accepted, stream.terminal
            finally:
                ACTIVE.reset(token)
                await stream.aclose()

        accepted, terminal = asyncio.run(scenario())
        self.assertFalse(accepted)
        self.assertTrue(terminal)


if __name__ == "__main__":
    unittest.main(verbosity=2)
