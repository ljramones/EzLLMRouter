"""Finite resources, failed startup and shutdown without providers or bound sockets."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from ezllmrouter_server.canonical import ContractError
from ezllmrouter_server.gateway import (
    adapter as asgi_module,
    choice_b_sender as sender,
    choice_b_wire as wire,
)
from ezllmrouter_server.gateway.owned_sender_transport import LocalSendAuthority
from ezllmrouter_server.runtime_resources import (
    AdmissionGate,
    BoundedExecutor,
    BoundedUnixServer,
    LoopThread,
    ServiceClosing,
)
from tools.synthetic.successor_service import SuccessorService
from tests.development_slice import test_core as core_fixtures
from tests.operator_console import test_integration_credentials as credential_fixtures
from tests.unit import test_accounting_recovery as recovery_fixtures
from worker import choice_b_worker as worker


class ResourcePrimitiveTests(unittest.TestCase):
    def test_executor_bounds_running_and_queued_work_and_reuses_cancelled_slots(self):
        pool = BoundedExecutor(max_workers=1, max_pending=2, thread_name_prefix="resource-test")
        held, release = threading.Event(), threading.Event()

        def wait():
            held.set()
            self.assertTrue(release.wait(3))

        try:
            first = pool.submit(wait)
            self.assertTrue(held.wait(1))
            second = pool.submit(lambda: "cancelled")
            with self.assertRaises(RuntimeError):
                pool.submit(lambda: "excess")
            self.assertTrue(second.cancel())
            third = pool.submit(lambda: "accepted")
            release.set()
            first.result(timeout=3)
            self.assertEqual(third.result(timeout=3), "accepted")
        finally:
            release.set()
            pool.shutdown()

    def test_failed_scheduling_returns_the_executor_slot(self):
        pool = BoundedExecutor(max_workers=1, max_pending=1, thread_name_prefix="resource-test")
        pool.shutdown()
        for _ in range(2):
            with self.assertRaises(RuntimeError):
                pool.submit(lambda: None)
        self.assertTrue(pool._slots.acquire(blocking=False))
        self.assertFalse(pool._slots.acquire(blocking=False))

    def test_submit_failure_after_enqueue_cannot_execute_the_rejected_work_later(self):
        pool = BoundedExecutor(max_workers=1, max_pending=1, thread_name_prefix="resource-test")
        self.addCleanup(pool.shutdown)
        queued = []
        action = Mock()

        def fail_after_enqueue(wrapper):
            queued.append(wrapper)
            raise RuntimeError("controlled thread creation failure")

        with patch.object(pool._pool, "submit", side_effect=fail_after_enqueue):
            with self.assertRaises(RuntimeError):
                pool.submit(action)
            with self.assertRaises(RuntimeError):
                pool.submit(action)
        self.assertEqual(len(queued), 1)
        queued[0]()
        action.assert_not_called()

    def test_admission_close_waits_for_existing_callers_and_rejects_new_ones(self):
        gate = AdmissionGate()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with gate.enter():
                closing = pool.submit(gate.close)
                with gate._condition:
                    self.assertTrue(gate._condition.wait_for(lambda: gate._closed, 2))
                self.assertFalse(closing.done())
                with self.assertRaises(ServiceClosing), gate.enter():
                    self.fail("closed gate admitted work")
            closing.result(timeout=2)
        gate.close()

    def test_loop_timeout_cancels_the_task_and_closes_its_loop(self):
        runtime = LoopThread("resource-test-loop")
        entered, cancelled = threading.Event(), threading.Event()

        async def held():
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        future = runtime.submit(held())
        self.assertTrue(entered.wait(2))
        with self.assertRaises(TimeoutError):
            runtime._wait(future, 0.02)
        runtime.close()
        self.assertTrue(cancelled.is_set())
        self.assertTrue(runtime.loop.is_closed())
        self.assertFalse(runtime.thread.is_alive())
        runtime.close()
        with self.assertRaises(RuntimeError):
            runtime.submit(held())

    def test_cleanup_failure_still_stops_the_event_loop(self):
        runtime = LoopThread("resource-test-loop")

        async def broken():
            raise OSError("controlled cleanup failure")

        with self.assertRaises(OSError):
            runtime.close(broken())
        self.assertFalse(runtime.thread.is_alive())
        self.assertTrue(runtime.loop.is_closed())
        runtime.close()

    def test_failed_thread_start_closes_the_allocated_loop(self):
        loop = asyncio.new_event_loop()
        with (
            patch("ezllmrouter_server.runtime_resources.asyncio.new_event_loop", return_value=loop),
            patch.object(
                threading.Thread, "start", side_effect=RuntimeError("controlled thread start")
            ),
        ):
            with self.assertRaises(RuntimeError):
                LoopThread("resource-test-loop")
        self.assertTrue(loop.is_closed())


class SocketBudgetTests(unittest.TestCase):
    def pair(self):
        first, second = socket.socketpair()
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        return first, second

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


class StartupCleanupTests(unittest.TestCase):
    def runtimes(self):
        values = []

        def create(name):
            runtime = LoopThread(name)
            values.append(runtime)
            return runtime

        return values, create

    def assert_stopped(self, values):
        self.assertEqual(len(values), 1)
        self.assertFalse(values[0].thread.is_alive())
        self.assertTrue(values[0].loop.is_closed())

    def test_asgi_startup_failure_closes_the_supplied_transport_and_thread(self):
        values, create = self.runtimes()
        lower = SimpleNamespace(aclose=AsyncMock())
        with (
            patch.object(asgi_module, "LoopThread", side_effect=create),
            patch.object(
                asgi_module.LiteLLMAsgiAdapter,
                "_start",
                new=AsyncMock(side_effect=ValueError("controlled startup")),
            ),
        ):
            with self.assertRaises(ValueError):
                asgi_module.LiteLLMAsgiAdapter(lower=lower, provider_key="sk-" + "s" * 40)
        lower.aclose.assert_awaited_once()
        self.assert_stopped(values)

    def test_worker_startup_failure_closes_both_clients_and_thread(self):
        values, create = self.runtimes()
        client, response_client = (
            SimpleNamespace(aclose=AsyncMock()),
            SimpleNamespace(aclose=AsyncMock()),
        )

        async def broken(item):
            item.client = client
            item.responses_handler = SimpleNamespace(client=response_client)
            raise ValueError("controlled startup")

        with (
            patch.object(worker, "LoopThread", side_effect=create),
            patch.object(worker.Worker, "_start", broken),
            patch.dict(worker.os.environ, {}, clear=True),
        ):
            with self.assertRaises(ValueError):
                worker.Worker()
        client.aclose.assert_awaited_once()
        response_client.aclose.assert_awaited_once()
        self.assert_stopped(values)

    def test_worker_client_cleanup_failure_still_closes_the_other_client_and_thread(self):
        values, create = self.runtimes()
        client = SimpleNamespace(aclose=AsyncMock())
        response_client = SimpleNamespace(aclose=AsyncMock(side_effect=OSError("controlled close")))

        async def start(item):
            item.client = client
            item.responses_handler = SimpleNamespace(client=response_client)

        with (
            patch.object(worker, "LoopThread", side_effect=create),
            patch.object(worker.Worker, "_start", start),
            patch.dict(worker.os.environ, {}, clear=True),
        ):
            item = worker.Worker()
        with self.assertRaises(OSError):
            item.close()
        item.close()
        client.aclose.assert_awaited_once()
        self.assert_stopped(values)

    def test_sender_socket_collision_does_not_start_a_loop_or_remove_the_existing_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sender.sock"
            path.write_text("existing")
            with (
                patch.object(sender, "LINK", Path(temporary)),
                patch.object(sender, "LoopThread") as create,
                patch.dict(sender.os.environ, {"EZLLMROUTER_DEV04_PROVIDER_KEY": "synthetic"}),
            ):
                with self.assertRaises(RuntimeError):
                    sender.ChoiceBSenderAdapter(LocalSendAuthority(), provider_key="sk-" + "s" * 40)
            create.assert_not_called()
            self.assertEqual(path.read_text(), "existing")

    def test_sender_chmod_failure_closes_partial_server_transport_and_owned_socket(self):
        values, create = self.runtimes()
        lower = SimpleNamespace(aclose=AsyncMock())
        server = Mock()

        async def start(item):
            item.lower = lower

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sender.sock"
            server.server_bind.side_effect = lambda: path.write_text("owned")
            with (
                patch.object(sender, "LINK", Path(temporary)),
                patch.object(sender, "LoopThread", side_effect=create),
                patch.object(sender, "BoundedUnixServer", return_value=server),
                patch.object(sender.ChoiceBSenderAdapter, "_start_lower", start),
                patch.object(sender.os, "chmod", side_effect=PermissionError("controlled chmod")),
                patch.dict(sender.os.environ, {"EZLLMROUTER_DEV04_PROVIDER_KEY": "synthetic"}),
            ):
                with self.assertRaises(PermissionError):
                    sender.ChoiceBSenderAdapter(LocalSendAuthority(), provider_key="sk-" + "s" * 40)
            self.assertFalse(path.exists())
        server.server_close.assert_called_once()
        server.shutdown.assert_not_called()
        lower.aclose.assert_awaited_once()
        self.assert_stopped(values)

    def test_sender_cleanup_preserves_a_replacement_socket_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sender.sock"
            path.write_text("original")
            status = path.stat()
            item = sender.ChoiceBSenderAdapter.__new__(sender.ChoiceBSenderAdapter)
            item._socket_path = path
            item._socket_identity = (status.st_dev, status.st_ino)
            path.rename(path.with_suffix(".old"))
            path.write_text("replacement")
            item._remove_socket()
            self.assertEqual(path.read_text(), "replacement")


class CoordinatorResourceTests(unittest.TestCase):
    setUp = core_fixtures.CoreTests.setUp
    coordinator = core_fixtures.CoreTests.coordinator

    def test_close_drains_a_paid_request_before_returning_and_rejects_new_work(self):
        adapter = core_fixtures.HeldAdapter()
        coordinator = self.coordinator(adapter=adapter)
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = pool.submit(
                coordinator.submit, deepcopy(core_fixtures.REQUEST), self.trusted, 3000
            )
            try:
                self.assertTrue(adapter.entered.wait(2))
                closing = pool.submit(coordinator.close)
                with coordinator._admission._condition:
                    self.assertTrue(
                        coordinator._admission._condition.wait_for(
                            lambda: coordinator._admission._closed, 2
                        )
                    )
                self.assertFalse(closing.done())
                with self.assertRaises(ContractError) as stopped:
                    coordinator.submit(deepcopy(core_fixtures.REQUEST), self.trusted)
                self.assertEqual(stopped.exception.code, "INTERNAL_UNAVAILABLE")
            finally:
                adapter.release.set()
            status, response = pending.result(timeout=3)
            closing.result(timeout=3)
        self.assertEqual((status, response["state"]), (200, "delivered"))
        self.assertEqual(
            self.store.get(response["handle"]["submission_id"])["submission_state"], "completed"
        )
        self.assertEqual(coordinator._futures, {})
        coordinator.close()

    def test_queue_exhaustion_is_a_durable_no_send_failure(self):
        adapter = core_fixtures.HeldAdapter()
        coordinator = self.coordinator(adapter=adapter)
        coordinator.pool.shutdown()
        coordinator.pool = BoundedExecutor(
            max_workers=1, max_pending=1, thread_name_prefix="resource-test"
        )
        self.addCleanup(coordinator.close)
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(
                coordinator.submit, deepcopy(core_fixtures.REQUEST), self.trusted, 3000
            )
            try:
                self.assertTrue(adapter.entered.wait(2))
                other = deepcopy(core_fixtures.REQUEST)
                other["step_id"] = "step.excess"
                status, reply = coordinator.submit(other, self.trusted, 0)
                self.assertEqual(status, 503)
                stored = self.store.get(reply["handle"]["submission_id"])
                self.assertEqual(stored["submission_state"], "failed_before_transmit")
                self.assertEqual(stored["terminal_failure"]["code"], "INTERNAL_UNAVAILABLE")
            finally:
                adapter.release.set()
            self.assertEqual(first.result(timeout=3)[0], 200)

    def test_coordinator_closes_its_attached_successor_before_the_pool(self):
        coordinator = self.coordinator()
        coordinator.successor = Mock()
        coordinator.close()
        coordinator.successor.close.assert_called_once()
        with self.assertRaises(RuntimeError):
            coordinator.pool.submit(lambda: None)


class SuccessorResourceTests(unittest.TestCase):
    setUp = recovery_fixtures.SuccessorRecoveryTests.setUp

    def service(self):
        from datetime import datetime, timedelta, timezone
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from tools.synthetic.successor_authority import SyntheticSuccessorAuthority
        from tools.synthetic.successor_campaign import FiniteSuccessorCampaign
        from tests.development_slice import test_retrieval_service_states as fixtures

        example = next(
            row for row in fixtures.VECTORS["examples"] if row["id"] == "DIRECT_DOCUMENT"
        )
        at = datetime.now(timezone.utc).replace(microsecond=0)
        fmt = lambda value: value.strftime("%Y-%m-%dT%H:%M:%SZ")
        context = deepcopy(example["trusted_context"])
        context.update(
            authenticated_at=fmt(at - timedelta(minutes=1)), expires_at=fmt(at + timedelta(hours=1))
        )
        trusted = {**context["identity"], "task_id": "task.demo"}
        authority = SyntheticSuccessorAuthority(
            self.store, Ed25519PrivateKey.generate(), "key.resource", "v1"
        )
        campaign = FiniteSuccessorCampaign(self.store, "campaign.resources", "budget.resources")
        campaign.start({}, [], max_attempts=100)
        authority.set_historical_access(
            context["identity"], read=True, write=True, resume=True, observed_at=fmt(at)
        )
        executor = fixtures.RecordedOutcomeExecutor()
        original = executor.execute

        def observed(*args):
            result = original(*args)
            result["usage_component"] = {
                "component": "document_units",
                "presence": "known",
                "quantity": 3,
                "evidence": "reported",
                "source_ref": "receiver.synthetic",
            }
            return result

        executor.execute = observed
        service = SuccessorService(
            self.store,
            {"credential.synthetic": context},
            authority,
            executor,
            campaign,
            read_allowed=lambda *_: True,
            usage_write_allowed=lambda *_: True,
        )
        self.addCleanup(service.close)
        request = deepcopy(example["request"])
        request["deadline"] = fmt(at + timedelta(minutes=5))
        return service, request, trusted

    def test_successor_releases_all_completed_futures_and_keeps_results_queryable(self):
        service, request, trusted = self.service()
        ids = []
        for index in range(30):
            current = deepcopy(request)
            current["work_selector"]["step_id"] = "step.resource." + str(index)
            _status, result = service.submit(
                current, trusted, 1000, credential="credential.synthetic"
            )
            ids.append(result["handle"]["submission_id"])
        service.close()
        self.assertEqual(service.futures, {})
        self.assertEqual(len(ids), len(set(ids)))
        for sid in ids:
            self.assertEqual(service.status(sid, trusted)["submission_state"], "completed")
        with self.assertRaises(ContractError) as stopped:
            service.submit(request, trusted, 1000, credential="credential.synthetic")
        self.assertEqual(stopped.exception.code, "INTERNAL_UNAVAILABLE")

    def test_successor_scheduling_failure_settles_the_reservation_without_send(self):
        service, request, trusted = self.service()
        service.pool.shutdown()
        status, reply = service.submit(request, trusted, 1000, credential="credential.synthetic")
        self.assertEqual((status, reply["state"]), (503, "failed"))
        stored = self.store.successor_get(reply["handle"]["submission_id"])
        self.assertEqual(stored["failure_stage"], "before_send")
        self.assertEqual(stored["failure"]["code"], "INTERNAL_UNAVAILABLE")
        self.assertEqual(
            self.store.db.execute(
                "SELECT state,possible_send FROM dev12_campaign_attempts"
            ).fetchall(),
            [("finished", 0)],
        )
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM dev12_send_ownership").fetchone(), (0,)
        )


class TokenResourceTests(unittest.TestCase):
    setUp = credential_fixtures.CredentialTests.setUp

    def test_issuing_and_authenticating_tokens_prunes_expired_entries(self):
        from ezllmrouter_server import registry as module

        with patch.object(module.time, "monotonic", return_value=100):
            self.registry._operator_tokens.update(
                {str(i): ("owner.local", 99) for i in range(3000)}
            )
            token = self.registry.issue_local_operator_token("owner.local")
            self.assertEqual(len(self.registry._operator_tokens), 1)
            self.assertEqual(
                self.registry.credential_principal(token)["principal_id"], "owner.local"
            )
        with patch.object(module.time, "monotonic", return_value=1901):
            with self.assertRaises(ContractError):
                self.registry.credential_principal(token)
        self.assertEqual(self.registry._operator_tokens, {})

    def test_token_capacity_preserves_existing_live_credentials(self):
        import time

        self.registry._operator_tokens.update(
            {str(i): ("owner.local", time.monotonic() + 3600) for i in range(4096)}
        )
        with self.assertRaises(RuntimeError):
            self.registry.issue_local_operator_token("owner.local")
        self.assertEqual(len(self.registry._operator_tokens), 4096)

    def test_revocation_during_a_slow_lookup_does_not_wait_for_the_database_or_authenticate(self):
        token = self.registry.issue_local_operator_token("owner.local")
        entered, release = threading.Event(), threading.Event()
        principal = self.registry.principal

        def held(*args):
            entered.set()
            self.assertTrue(release.wait(3))
            return principal(*args)

        with (
            ThreadPoolExecutor(max_workers=2) as pool,
            patch.object(self.registry, "principal", side_effect=held),
        ):
            pending = pool.submit(self.registry.credential_principal, token)
            try:
                self.assertTrue(entered.wait(2))
                pool.submit(self.registry.revoke_local_operator_token, token).result(timeout=1)
            finally:
                release.set()
            with self.assertRaises(ContractError):
                pending.result(timeout=3)
        self.assertNotIn(hashlib.sha256(token.encode()).hexdigest(), self.registry._operator_tokens)


class IngressResourceTests(unittest.TestCase):
    def test_blocked_ingress_write_has_a_timeout_and_closes_its_upstream(self):
        ingress = importlib.import_module("deploy.local.console_ingress")
        upstream = MagicMock()
        upstream.__enter__.return_value = upstream
        upstream.__exit__.side_effect = lambda *_: upstream.close()
        upstream.sendall.side_effect = TimeoutError("controlled blocked reader")
        request = Mock()
        request.recv.return_value = b"synthetic request"
        socket_api = SimpleNamespace(
            AF_UNIX=socket.AF_UNIX,
            SOCK_STREAM=socket.SOCK_STREAM,
            socket=Mock(return_value=upstream),
        )
        with (
            patch.object(ingress, "socket", socket_api),
            patch.object(ingress.select, "select", return_value=([request], [], [])),
        ):
            ingress.Handler(request, None, None)
        upstream.sendall.assert_called_once_with(b"synthetic request")
        upstream.close.assert_called_once()
        self.assertGreater(upstream.settimeout.call_args.args[0], 0)
        self.assertLessEqual(upstream.settimeout.call_args.args[0], 5)

    def test_failed_ingress_connect_closes_the_socket(self):
        ingress = importlib.import_module("deploy.local.console_ingress")
        upstream = MagicMock()
        upstream.connect.side_effect = OSError("controlled unavailable upstream")
        socket_api = SimpleNamespace(
            AF_UNIX=socket.AF_UNIX,
            SOCK_STREAM=socket.SOCK_STREAM,
            socket=Mock(return_value=upstream),
        )
        with patch.object(ingress, "socket", socket_api):
            ingress.Handler(Mock(), None, None)
        upstream.close.assert_called_once()


class DeploymentCleanupTests(unittest.TestCase):
    setUp = core_fixtures.CoreTests.setUp

    def run_failed_startup(self, *, close_failure=False):
        import sys

        with patch.object(
            sys, "path", [str(Path(__file__).resolve().parents[2] / "deploy/local"), *sys.path]
        ):
            module = importlib.import_module("deploy.local.local_service")
        values = {
            "/run/ezllmrouter/credentials.json": json.dumps(
                {"service_token": "t" * 40, "synthetic_provider_key": "sk-" + "s" * 40}
            ),
            "/run/ezllmrouter/operator-password": "p" * 40,
            "/app/dev_slice/fixture.json": json.dumps(core_fixtures.FIXTURE),
            "/app/local/request.json": "{}",
            "/app/local/scenarios.json": "{}",
            "/app/local/build-identity.json": "{}",
        }
        order = []
        adapter, coordinator, wire_server = Mock(), Mock(), Mock()
        adapter.close.side_effect = lambda: order.append("adapter")
        if close_failure:

            def broken():
                order.append("adapter")
                raise OSError("controlled close failure")

            adapter.close.side_effect = broken
        coordinator.close.side_effect = lambda: order.append("coordinator")
        wire_server.server_close.side_effect = lambda: order.append("wire")
        close = self.store.close

        def close_store():
            order.append("store")
            close()

        with ExitStack() as patches:
            patches.enter_context(
                patch.object(
                    module,
                    "Path",
                    side_effect=lambda name: SimpleNamespace(read_text=lambda: values[str(name)]),
                )
            )
            for name, value in (
                ("configure_logging", Mock()),
                ("SQLiteStore", Mock(return_value=self.store)),
                ("ProviderVault", Mock()),
                ("remove_stale_socket", Mock()),
                ("Registry", Mock()),
                ("PersonalCampaign", Mock()),
                ("ChoiceBSenderAdapter", Mock(return_value=adapter)),
                ("Coordinator", Mock(return_value=coordinator)),
                ("OperatorProjection", Mock()),
                ("DemoRunner", Mock()),
                ("ProviderValidationRunner", Mock()),
                ("serve_wire", Mock(return_value=wire_server)),
                ("serve_operator", Mock(side_effect=ValueError("controlled startup"))),
            ):
                patches.enter_context(patch.object(module, name, value))
            patches.enter_context(patch.object(self.store, "close", side_effect=close_store))
            patches.enter_context(patch.dict(module.os.environ, {"EZLLMROUTER_DB_PATH": "unused"}))
            with self.assertRaises(OSError if close_failure else ValueError):
                module.main()
        self.assertEqual(order, ["wire", "coordinator", "adapter", "store"])

    def test_failed_deployment_startup_closes_resources_in_dependency_order(self):
        self.run_failed_startup()

    def test_cleanup_failure_does_not_skip_closing_the_database(self):
        self.run_failed_startup(close_failure=True)


from tests.operator_console import test_user_management_web as user_fixtures


class SessionShutdownTests(user_fixtures.UserHTTPFixture):
    def test_operator_shutdown_revokes_its_session_tokens(self):
        self.ready_admin()
        token = self.registry.issue_local_operator_token("owner.local")
        self.server.application.sessions["resource.test"] = {"wire_token": token}
        self.server.application.close()
        self.assertEqual(self.server.application.sessions, {})
        with self.assertRaises(ContractError):
            self.registry.credential_principal(token)

    def test_launch_racing_shutdown_does_not_leave_an_unscheduled_running_row(self):
        self.server.application.close()
        handler = self.server.handler.__new__(self.server.handler)
        handler.server = self.server
        handler.path = "/operator/v1/demos/text"
        handler._fail = Mock(return_value="stopped")
        result = handler.post_operator_v1_demos(
            None, ("session", {"role": "registry_admin"}), {"operation_id": "op.closed"}, None
        )
        self.assertEqual(result, "stopped")
        handler._fail.assert_called_once_with(503, "INTERNAL_UNAVAILABLE")
        self.assertEqual(self.server.application.projection.launch("op.closed")["state"], "failed")

    def test_login_cannot_publish_a_new_session_after_shutdown(self):
        self.ready_admin()
        self.server.application.close()
        status, _, _body = self.request(
            "POST", "/operator/v1/login", {"username": "admin", "password": user_fixtures.PASSWORD}
        )
        self.assertEqual(status, 503)
        self.assertEqual(self.server.application.sessions, {})


class AdditionalSocketBudgetTests(unittest.TestCase):
    pair = SocketBudgetTests.pair

    def test_async_reply_deadline_closes_a_stalled_socket(self):
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
                    wire.async_exchange("unused", {"request": "synthetic"}, 0.03)
                )
                self.assertTrue(await loop.sock_recv(peer, 4096))
                with self.assertRaises(TimeoutError):
                    await task
                self.assertEqual(stream.fileno(), -1)

        asyncio.run(scenario())

    def test_async_exchange_rejects_an_oversize_frame_before_reading_its_body(self):
        import struct

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
                await loop.sock_sendall(peer, struct.pack("!I", wire.LIMIT + 1))
                with self.assertRaises(ValueError):
                    await task
                self.assertEqual(stream.fileno(), -1)

        asyncio.run(scenario())


class HTTPInputResourceTests(unittest.TestCase):
    def pair(self):
        return SocketBudgetTests.pair(self)

    def test_real_http_round_trip_uses_no_timer_thread(self):
        from ezllmrouter_server.http_server import SafeHTTPRequestHandler

        class Handler(SafeHTTPRequestHandler):
            def do_GET(self):
                self.send_response(204)
                self.end_headers()

        stream, peer = self.pair()
        peer.settimeout(2)
        with patch.object(threading, "Timer", side_effect=AssertionError("per-request timer")):
            thread = threading.Thread(
                target=Handler, args=(stream, ("local", 0), SimpleNamespace())
            )
            thread.start()
            try:
                peer.sendall(b"GET / HTTP/1.1\r\nHost: local\r\nConnection: close\r\n\r\n")
                self.assertIn(b"204", peer.recv(8192))
            finally:
                thread.join(timeout=2)
        self.assertFalse(thread.is_alive())

    def test_real_incomplete_http_input_expires_without_a_timer_thread(self):
        from ezllmrouter_server import http_server

        stream, peer = self.pair()
        with (
            patch.object(http_server, "REQUEST_TIMEOUT_SECONDS", 0.03),
            patch.object(threading, "Timer", side_effect=AssertionError("per-request timer")),
        ):
            thread = threading.Thread(
                target=http_server.SafeHTTPRequestHandler,
                args=(stream, ("local", 0), SimpleNamespace()),
            )
            thread.start()
            peer.sendall(b"G")
            thread.join(timeout=2)
        self.assertFalse(thread.is_alive())

    def test_completed_input_resets_the_read_budget_before_long_processing(self):
        from ezllmrouter_server.http_server import SafeHTTPRequestHandler, REQUEST_TIMEOUT_SECONDS

        handler = SafeHTTPRequestHandler.__new__(SafeHTTPRequestHandler)
        handler.connection = Mock()
        handler._input_deadline = 0
        handler._finish_input()
        self.assertIsNone(handler._input_deadline)
        handler.connection.settimeout.assert_called_once_with(REQUEST_TIMEOUT_SECONDS)


class OperatorFailureCleanupTests(unittest.TestCase):
    def arguments(self):
        return dict(
            projection=Mock(),
            runner=None,
            password="p" * 40,
            fixture={},
            build={},
            web_root=Path(__file__).resolve().parents[2] / "web",
            worker_probe=lambda: {},
            sender_status=lambda: {},
        )

    def test_operator_listener_closes_even_when_application_cleanup_raises(self):
        from ezllmrouter_server import operator_web

        listener = SimpleNamespace(server_close=Mock())
        original = listener.server_close
        with patch.object(operator_web, "ThreadingHTTPServer", return_value=listener):
            server = operator_web.serve("127.0.0.1", 12345, **self.arguments())
        self.addCleanup(server.application.close)
        with patch.object(server.application, "close", side_effect=OSError("controlled cleanup")):
            with self.assertRaises(OSError):
                server.server_close()
        original.assert_called_once()

    def test_operator_socket_permission_failure_closes_the_allocated_listener(self):
        from ezllmrouter_server import operator_web

        stream = Mock()
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "operator.sock")
            stream.getsockname.return_value = path
            with (
                patch.object(operator_web.socket, "socket", return_value=stream),
                patch.object(
                    operator_web.os, "chmod", side_effect=PermissionError("controlled permissions")
                ),
            ):
                with self.assertRaises(PermissionError):
                    operator_web.serve("127.0.0.1", 12345, socket_path=path, **self.arguments())
        stream.listen.assert_not_called()
        stream.close.assert_called_once()
