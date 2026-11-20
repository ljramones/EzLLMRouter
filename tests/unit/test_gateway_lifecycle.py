"""Deadline, response bounds and abandonment checks without a worker or provider."""

import asyncio
import base64
from concurrent.futures import Future
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import socket
import signal
import selectors
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import httpx

from ezllmrouter_server.diagnostic_journal import append_event, read_events
from ezllmrouter_server.canonical import ContractError
from ezllmrouter_server.gateway import guard
from ezllmrouter_server.gateway.choice_b_sender import (
    ChoiceBSenderAdapter,
    read_response,
    RESPONSE_LIMIT,
)
from ezllmrouter_server.gateway.choice_b_wire import (
    LIMIT,
    MAX_ATTEMPT_TIMEOUT_MS,
    remaining_seconds,
    send,
)
from ezllmrouter_server.gateway.owned_sender_transport import LocalSendAuthority, OwnedSocketStream
from tests.worker_support import runtime as _worker

RelayTransport, RECENT_ATTEMPTS, Worker = (
    _worker.RelayTransport,
    _worker.RECENT_ATTEMPTS,
    _worker.Worker,
)


def deadline():
    return (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()


def invocation():
    return guard.Invocation(
        "submission.synthetic",
        "attempt.synthetic",
        {
            "per_attempt_total_timeout_ms": 60000,
            "deadline": deadline(),
            "destination": {
                "configuration_ref": "cfg.demo",
                "service": "litellm.dev04",
                "endpoint": "127.0.0.1",
                "model": "model.demo",
                "model_version": "v1",
                "processing_region": "local",
            },
        },
        {},
        lambda: None,
        lambda _: None,
    )


class Stream(httpx.AsyncByteStream):
    def __init__(self):
        self.reads, self.closed = 0, False

    async def __aiter__(self):
        for _ in range(20):
            self.reads += 1
            yield b"x" * 8192

    async def aclose(self):
        self.closed = True


class GatewayLifecycleTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "POSIX worker signal lifecycle")
    def test_worker_sigterm_unwinds_main_and_returns_success(self):
        root = Path(__file__).resolve().parents[2]
        source = (
            "import signal,sys\n"
            f"sys.path.insert(0, {str(root)!r})\n"
            "from tests.worker_support import runtime as worker\n"
            "def serve():\n"
            " try:\n  print('READY',flush=True); signal.pause()\n"
            " finally:\n  print('CLEANED',flush=True)\n"
            "worker._serve=serve\nworker.main()\n"
        )
        process = subprocess.Popen(
            [sys.executable, "-I", "-c", source],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            with selectors.DefaultSelector() as ready:
                ready.register(process.stdout, selectors.EVENT_READ)
                self.assertTrue(ready.select(timeout=5), "worker failed to become ready")
                self.assertEqual(process.stdout.readline().strip(), "READY")
            process.send_signal(signal.SIGTERM)
            output, error = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, error)
            self.assertIn("CLEANED", output)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)

    def test_diagnostic_rotation_is_bounded_and_counts_dropped_events(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "events.jsonl"
            for number in range(50):
                append_event(
                    target, {"attempt_id": str(number), "padding": "x" * 50}, max_bytes=200
                )
            self.assertEqual(len(list(Path(directory).iterdir())), 3)
            self.assertTrue(all(p.stat().st_size <= 200 for p in Path(directory).iterdir()))
            rows = read_events(target)
            self.assertEqual(rows[-1]["attempt_id"], "49")
            self.assertLess(len(rows), 50)
            append_event(target, {"attempt_id": "50"}, max_bytes=200)
            self.assertEqual(read_events(target)[-1]["attempt_id"], "50")
        before = guard.diagnostic_status()["dropped"]
        with patch.object(guard._EVENT_QUEUE, "put_nowait", side_effect=guard.queue.Full):
            guard.enqueue_event("unused", {"stage": "synthetic"})
        self.assertEqual(guard.diagnostic_status()["dropped"], before + 1)

    def test_expired_or_malformed_pre_send_context_is_definitely_rejected(self):
        adapter = ChoiceBSenderAdapter.__new__(ChoiceBSenderAdapter)
        adapter.provider_key = "sk-" + "x" * 40
        for destination, expires in (
            ({}, deadline()),
            (invocation().plan["destination"], "2000-01-01T00:00:00Z"),
        ):
            context = invocation()
            context.plan["destination"] = destination
            context.plan["deadline"] = expires
            with self.assertRaises(ContractError) as caught:
                adapter.send_with_context(
                    b"{}",
                    1000,
                    {},
                    {
                        "submission_id": context.submission_id,
                        "attempt_id": context.attempt_id,
                        "plan": context.plan,
                        "projection": {},
                        "fresh_check": lambda: None,
                        "commit": lambda _: None,
                    },
                )
            self.assertEqual(caught.exception.code, "FDC_REJECTED")

    def test_long_plan_budgets_are_not_cut_to_thirty_five_seconds(self):
        self.assertEqual(remaining_seconds(60000, deadline()), 60)
        self.assertEqual(remaining_seconds(MAX_ATTEMPT_TIMEOUT_MS, deadline()) > 60, True)
        with self.assertRaises(ValueError):
            remaining_seconds(MAX_ATTEMPT_TIMEOUT_MS + 1, deadline())
        with self.assertRaises(TimeoutError):
            remaining_seconds(60000, "2000-01-01T00:00:00Z")

    def test_worker_dispatch_uses_the_envelope_budget(self):
        worker = Worker.__new__(Worker)
        worker.loop = None
        observed = []

        def schedule(coro, _loop):
            coro.close()

            class Result(Future):
                def result(self, timeout=None):
                    observed.append(timeout)
                    return {"status": 200}

            return Result()

        with patch(
            "ezllmrouter_worker.worker.asyncio.run_coroutine_threadsafe", side_effect=schedule
        ):
            worker.dispatch(
                {"kind": "selected_request", "timeout_ms": 60000, "deadline": deadline()}
            )
        self.assertEqual(observed, [62])

    def test_worker_dispatch_cancels_its_coroutine_on_timeout(self):
        worker = Worker.__new__(Worker)
        worker.loop = None

        class Result(Future):
            def result(self, timeout=None):
                raise TimeoutError("synthetic worker deadline")

        future = Result()

        def schedule(coro, _loop):
            coro.close()
            return future

        with patch(
            "ezllmrouter_worker.worker.asyncio.run_coroutine_threadsafe", side_effect=schedule
        ):
            with self.assertRaises(TimeoutError):
                worker.dispatch(
                    {"kind": "selected_request", "timeout_ms": 60000, "deadline": deadline()}
                )
        self.assertTrue(future.cancelled())

    def test_worker_identity_history_stays_within_the_socket_frame(self):
        relay = RelayTransport()
        for index in range(10000):
            relay.claim("attempt.synthetic." + str(index))
        self.assertEqual(
            (len(relay.seen), len(relay.attempt_counts)), (RECENT_ATTEMPTS, RECENT_ATTEMPTS)
        )
        with self.assertRaises(httpx.TransportError):
            relay.claim("attempt.synthetic.9999")
        worker = Worker.__new__(Worker)
        worker.client = type("Client", (), {"_transport": relay})()
        worker.module_identities = {"boundary": "synthetic module identity"}
        frame = io.BytesIO()
        frame.sendall = frame.write
        send(frame, worker.dispatch({"kind": "module_identity"}))
        self.assertLess(len(frame.getvalue()), LIMIT)

    def test_declared_oversize_is_closed_without_reading(self):
        stream = Stream()
        response = httpx.Response(
            200, headers={"Content-Length": str(RESPONSE_LIMIT + 1)}, stream=stream
        )
        with self.assertRaises(ValueError):
            asyncio.run(read_response(response))
        self.assertEqual(stream.reads, 0)
        self.assertTrue(stream.closed)

    def test_unknown_length_stops_reading_at_the_cap(self):
        stream = Stream()
        with self.assertRaises(ValueError):
            asyncio.run(read_response(httpx.Response(200, stream=stream)))
        self.assertEqual(stream.reads, 9)
        self.assertTrue(stream.closed)

    def test_abandoned_attempt_cannot_commit_or_reach_the_lower_transport(self):
        item, commits, lower_calls = invocation(), [], []
        item.abandoned = True
        item.commit = commits.append
        transport = guard.GuardTransport(
            httpx.MockTransport(lambda request: lower_calls.append(request))
        )
        token = guard.ACTIVE.set(item)
        try:
            with patch.object(guard, "check_request", return_value={}):
                with self.assertRaises(guard.GuardRejected):
                    asyncio.run(
                        transport.handle_async_request(httpx.Request("POST", "http://127.0.0.1"))
                    )
        finally:
            guard.ACTIVE.reset(token)
        self.assertEqual((commits, lower_calls), ([], []))

    def test_abandonment_after_commit_still_blocks_the_first_socket_byte(self):
        item, authority = invocation(), LocalSendAuthority()
        item.committed = item.released = item.abandoned = True
        item.authority_epoch = authority.epoch
        first, second = socket.socketpair()
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        first.setblocking(False)
        stream = OwnedSocketStream(first, authority)
        token = guard.ACTIVE.set(item)
        try:
            with self.assertRaises(guard.GuardRejected):
                asyncio.run(stream.write(b"POST / HTTP/1.1\r\n\r\n", timeout=1))
        finally:
            guard.ACTIVE.reset(token)
        self.assertEqual(second.recv(1), b"")
        self.assertFalse(item.first_bytes_accepted)

    def test_worker_error_cannot_discard_an_inflight_paid_response(self):
        for rpc_failure in (False, True):
            with self.subTest(rpc_failure=rpc_failure):
                adapter = ChoiceBSenderAdapter.__new__(ChoiceBSenderAdapter)
                adapter.provider_key = "sk-" + "s" * 40
                adapter.authority = LocalSendAuthority()
                adapter.registry, adapter.claimed, adapter.lock = {}, set(), threading.Lock()
                waiting = threading.Event()

                class ObservedFuture(Future):
                    def result(self, timeout=None, *, waiting=waiting):
                        waiting.set()
                        return super().result(timeout)

                future = ObservedFuture()
                provider = {
                    "choices": [{"message": {"content": "Paid result\npreserved"}}],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 1},
                }

                def complete(*, waiting=waiting, future=future, provider=provider):
                    if waiting.wait(2):
                        future.set_result(
                            {
                                "status": 200,
                                "body_b64": base64.b64encode(
                                    json.dumps(provider).encode()
                                ).decode(),
                            }
                        )

                thread = threading.Thread(target=complete)
                thread.start()
                item = invocation()

                def command(
                    _envelope,
                    _timeout,
                    *,
                    adapter=adapter,
                    item=item,
                    future=future,
                    rpc_failure=rpc_failure,
                ):
                    current = adapter.registry[item.attempt_id]
                    remaining = (
                        datetime.fromisoformat(_envelope["deadline"]) - datetime.now(timezone.utc)
                    ).total_seconds()
                    self.assertGreater(remaining, 59)
                    self.assertLessEqual(remaining, 60)
                    self.assertLess(
                        datetime.fromisoformat(current.deadline),
                        datetime.fromisoformat(current.plan["deadline"]),
                    )
                    current.relay_future = future
                    current.committed = current.released = current.first_bytes_accepted = True
                    if rpc_failure:
                        raise OSError("synthetic worker response lost")
                    return {"status": 500}

                adapter._worker_command = command
                context = {
                    key: getattr(item, key)
                    for key in (
                        "submission_id",
                        "attempt_id",
                        "plan",
                        "projection",
                        "fresh_check",
                        "commit",
                    )
                }
                prepared = b"{}"
                try:
                    result = adapter.send_with_context(
                        prepared,
                        60000,
                        adapter.describe(prepared, 60000, item.plan["destination"]),
                        context,
                    )
                finally:
                    thread.join(timeout=3)
                self.assertEqual(result["status"], 200)
                self.assertEqual(result["body"]["text"], "Paid result\npreserved")
                self.assertEqual(adapter.registry, {})

    def test_failure_classification_requires_the_first_byte_fact(self):
        item = invocation()
        item.released = True
        with self.assertRaises(ContractError):
            ChoiceBSenderAdapter._reject_or_unknown(item, OSError("synthetic"))
        self.assertTrue(item.abandoned)
        item.first_bytes_accepted = True
        with self.assertRaises(OSError):
            ChoiceBSenderAdapter._reject_or_unknown(item, OSError("synthetic"))

    def test_diagnostic_disk_failure_is_reported_without_failing_the_send(self):
        item = invocation()
        item.commit = lambda _: None
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(
                os.environ,
                {"EZLLMROUTER_GATEWAY_GUARD_EVENTS": str(Path(directory) / "events.jsonl")},
            ),
        ):
            self.assertTrue(guard.flush_events(2))
            token = guard.ACTIVE.set(item)
            try:
                with (
                    patch.object(guard, "check_request", return_value={}),
                    patch.object(guard.os, "fsync", side_effect=OSError("synthetic disk full")),
                    patch.object(guard, "log_failure") as logged,
                ):
                    response = asyncio.run(
                        guard.GuardTransport(
                            httpx.MockTransport(lambda _: httpx.Response(200, json={}))
                        ).handle_async_request(httpx.Request("POST", "http://127.0.0.1"))
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertTrue(guard.flush_events(2))
                    logged.assert_called_with("gateway.diagnostic_write_failed")
                    self.assertTrue(item.committed)
            finally:
                guard.ACTIVE.reset(token)

    def test_blocked_diagnostic_fsync_does_not_hold_up_the_guard(self):
        entered, release, commits, sent = threading.Event(), threading.Event(), [], []
        item = invocation()
        item.commit = commits.append

        def fsync(_descriptor):
            entered.set()
            if not release.wait(5):
                raise AssertionError("request did not finish while diagnostics were blocked")

        def lower(request):
            sent.append(request)
            return httpx.Response(200, json={})

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(
                os.environ,
                {"EZLLMROUTER_GATEWAY_GUARD_EVENTS": str(Path(directory) / "events.jsonl")},
            ),
        ):
            self.assertTrue(guard.flush_events(2))
            token = guard.ACTIVE.set(item)
            try:
                with (
                    patch.object(guard, "check_request", return_value={}),
                    patch.object(guard.os, "fsync", side_effect=fsync),
                ):
                    try:
                        response = asyncio.run(
                            guard.GuardTransport(httpx.MockTransport(lower)).handle_async_request(
                                httpx.Request("POST", "http://127.0.0.1")
                            )
                        )
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual((len(commits), len(sent)), (1, 1))
                        self.assertTrue(entered.wait(2))
                    finally:
                        release.set()
                        self.assertTrue(guard.flush_events(2))
            finally:
                guard.ACTIVE.reset(token)
