"""First HTTPS request write, revocation and cancellation on a real TLS socket."""

from __future__ import annotations

import shutil

import asyncio
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import ssl
import subprocess
import tempfile
import threading
import unittest

import httpx

ROOT = Path(__file__).resolve().parents[2]


from ezllmrouter_server.gateway.guard import ACTIVE, Invocation, GuardRejected
from ezllmrouter_server.gateway.owned_sender_transport import LocalSendAuthority
from ezllmrouter_server.gateway.owned_tls_sender_transport import OwnedTLSHTTPTransport
from ezllmrouter_server.provider_vault import ProviderVault
from ezllmrouter_server.registry import Registry
from ezllmrouter_server.store import SQLiteStore


class Receiver(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.server.requests.append((self.path, dict(self.headers), body))
        payload = json.dumps({"id": "response.test", "object": "response", "output": []}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        pass


@unittest.skipUnless(shutil.which("openssl"), "openssl is required for this fixture")
class OwnedTLSProof(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        cert, key = root / "cert.pem", root / "key.pem"
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(key),
                "-out",
                str(cert),
                "-days",
                "1",
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=DNS:localhost",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
        self.server.requests = []
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(cert), str(key))
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.settings = {
            "origin": f"https://localhost:{self.server.server_port}",
            "location": "commercial",
            "site": "Controlled TLS",
            "ca_pem": cert.read_text(),
        }
        self.authority = LocalSendAuthority()

    def invocation(self):
        return Invocation(
            submission_id="submission.test",
            attempt_id="attempt.test",
            plan={
                "deadline": (datetime.now(timezone.utc) + timedelta(seconds=20)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
            },
            projection={},
            fresh_check=lambda: None,
            commit=lambda _: None,
            committed=True,
            released=True,
            authority_epoch=self.authority.snapshot_epoch(),
        )

    def request(self):
        return httpx.Request(
            "POST",
            self.settings["origin"] + "/v1/responses",
            headers={
                "Authorization": "Bearer test-provider-key-123456",
                "Content-Type": "application/json",
            },
            content=b'{"model":"model-test","input":"hello","stream":false}',
            extensions={"timeout": {"connect": 3.0, "read": 3.0, "write": 3.0, "pool": 3.0}},
        )

    def test_positive_and_exact_origin(self):
        async def run():
            transport = OwnedTLSHTTPTransport(
                self.authority, "openai.responses.v1", self.settings, controlled=True
            )
            invocation = self.invocation()
            token = ACTIVE.set(invocation)
            try:
                response = await transport.handle_async_request(self.request())
                self.assertEqual(response.status_code, 200)
                await response.aread()
                self.assertTrue(invocation.first_bytes_accepted)
                self.assertEqual(
                    invocation.observations, ["FIRST_TLS_REQUEST_BYTES_ACCEPTED_BY_LOCAL_SOCKET"]
                )
                with self.assertRaises(GuardRejected):
                    await transport.handle_async_request(
                        httpx.Request("POST", self.settings["origin"] + "/v1/chat/completions")
                    )
            finally:
                ACTIVE.reset(token)
                await transport.aclose()

        asyncio.run(run())
        self.assertEqual(len(self.server.requests), 1)
        self.assertEqual(self.server.requests[0][0], "/v1/responses")

    def test_revoked_after_tls_handshake_before_first_request_write(self):
        async def run():
            entered, release = asyncio.Event(), asyncio.Event()

            async def wait():
                entered.set()
                await release.wait()

            transport = OwnedTLSHTTPTransport(
                self.authority,
                "openai.responses.v1",
                self.settings,
                controlled=True,
                first_write_wait=wait,
            )
            invocation = self.invocation()
            token = ACTIVE.set(invocation)
            try:
                task = asyncio.create_task(transport.handle_async_request(self.request()))
                await asyncio.wait_for(entered.wait(), timeout=3)
                self.authority.revoke()
                release.set()
                with self.assertRaises(GuardRejected):
                    await task
                self.assertFalse(invocation.first_bytes_accepted)
            finally:
                ACTIVE.reset(token)
                await transport.aclose()

        asyncio.run(run())
        self.assertEqual(self.server.requests, [])

    def test_revocation_after_first_send_reports_backpressure(self):
        """An EAGAIN before acceptance must recheck authority on retry."""

        async def run():
            transport = OwnedTLSHTTPTransport(
                self.authority, "openai.responses.v1", self.settings, controlled=True
            )
            original_connect = transport.backend.connect_tcp
            blocked = []

            class FirstSendEagain:
                def __init__(self, sock, stream):
                    self.sock, self.stream = sock, stream

                def send(self, data):
                    if (
                        self.stream.invocation is not None
                        and not self.stream.request_bytes_accepted
                        and not blocked
                    ):
                        blocked.append(True)
                        self.authority.revoke()
                        raise BlockingIOError()
                    return self.sock.send(data)

                def __getattr__(self, name):
                    return getattr(self.sock, name)

            async def connect(*args, **kwargs):
                stream = await original_connect(*args, **kwargs)
                socket_wrapper = FirstSendEagain(stream.sock, stream)
                socket_wrapper.authority = self.authority
                stream.sock = socket_wrapper
                return stream

            transport.backend.connect_tcp = connect
            invocation = self.invocation()
            token = ACTIVE.set(invocation)
            try:
                with self.assertRaises(GuardRejected):
                    await transport.handle_async_request(self.request())
                self.assertEqual(blocked, [True])
                self.assertFalse(invocation.first_bytes_accepted)
            finally:
                ACTIVE.reset(token)
                await transport.aclose()

        asyncio.run(run())
        self.assertEqual(self.server.requests, [])

    def test_cancelled_before_first_write_and_tls_hostname(self):
        async def cancel():
            entered = asyncio.Event()

            async def wait():
                entered.set()
                await asyncio.Event().wait()

            transport = OwnedTLSHTTPTransport(
                self.authority,
                "openai.responses.v1",
                self.settings,
                controlled=True,
                first_write_wait=wait,
            )
            invocation = self.invocation()
            token = ACTIVE.set(invocation)
            try:
                task = asyncio.create_task(transport.handle_async_request(self.request()))
                await asyncio.wait_for(entered.wait(), timeout=3)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertFalse(invocation.first_bytes_accepted)
            finally:
                ACTIVE.reset(token)
                await transport.aclose()

        asyncio.run(cancel())
        self.assertEqual(self.server.requests, [])

        async def hostname():
            settings = {**self.settings, "origin": f"https://127.0.0.1:{self.server.server_port}"}
            transport = OwnedTLSHTTPTransport(
                self.authority, "openai.responses.v1", settings, controlled=True
            )
            token = ACTIVE.set(self.invocation())
            try:
                with self.assertRaises(ssl.SSLCertVerificationError):
                    await transport.handle_async_request(
                        httpx.Request(
                            "POST",
                            settings["origin"] + "/v1/responses",
                            headers={"Content-Type": "application/json"},
                            content=b"{}",
                        )
                    )
            finally:
                ACTIVE.reset(token)
                await transport.aclose()

        asyncio.run(hostname())
        self.assertEqual(self.server.requests, [])

    def test_connection_disable_and_key_rotation_after_handshake(self):
        store = SQLiteStore(Path(self.temp.name) / "authority.sqlite")
        self.addCleanup(store.close)
        registry = Registry(
            store,
            self.authority,
            legacy_destination={
                "configuration_ref": "cfg.demo",
                "service": "litellm.dev04",
                "endpoint": "127.0.0.1",
                "model": "model.demo",
                "model_version": "v1",
                "processing_region": "local",
            },
            legacy_token="synthetic-local-token-0000000000000000000000",
            legacy_trusted={"principal_id": "svc.demo", "charging_owner_id": "team.demo"},
            provider_vault=ProviderVault(Path(self.temp.name) / "vault"),
        )
        registry.mutate(
            "owner.local",
            {
                "operation_id": "op.tls.conn",
                "action": "create_connection",
                "subject": "conn.tls",
                "expected_revision": 0,
                "data": {
                    "display_name": "Controlled authority",
                    "adapter_id": "openai.responses.v1",
                    "settings": {
                        "origin": "https://api.openai.com",
                        "location": "commercial",
                        "site": "test",
                    },
                    "owner": "owner.local",
                },
            },
        )
        registry.set_provider_credential(
            "owner.local", "conn.tls", 1, "op.tls.cred.1", "replace", "test-provider-key-123456"
        )
        registry.mutate(
            "owner.local",
            {
                "operation_id": "op.tls.active",
                "action": "connection_state",
                "subject": "conn.tls",
                "expected_revision": 2,
                "data": {"status": "active", "reason": "Controlled test"},
            },
        )

        async def held(change):
            entered, release = asyncio.Event(), asyncio.Event()

            async def wait():
                entered.set()
                await release.wait()

            transport = OwnedTLSHTTPTransport(
                self.authority,
                "openai.responses.v1",
                self.settings,
                controlled=True,
                first_write_wait=wait,
            )
            invocation = self.invocation()
            token = ACTIVE.set(invocation)
            try:
                task = asyncio.create_task(transport.handle_async_request(self.request()))
                await asyncio.wait_for(entered.wait(), timeout=3)
                change()
                release.set()
                with self.assertRaises(GuardRejected):
                    await task
                self.assertFalse(invocation.first_bytes_accepted)
            finally:
                ACTIVE.reset(token)
                await transport.aclose()

        asyncio.run(
            held(
                lambda: registry.mutate(
                    "owner.local",
                    {
                        "operation_id": "op.tls.disable",
                        "action": "connection_state",
                        "subject": "conn.tls",
                        "expected_revision": 3,
                        "data": {"status": "disabled", "reason": "Effective queued revocation"},
                    },
                )
            )
        )
        self.assertEqual(self.server.requests, [])
        registry.mutate(
            "owner.local",
            {
                "operation_id": "op.tls.restore",
                "action": "connection_state",
                "subject": "conn.tls",
                "expected_revision": 4,
                "data": {"status": "active", "reason": "Controlled continuation"},
            },
        )
        asyncio.run(
            held(
                lambda: registry.set_provider_credential(
                    "owner.local",
                    "conn.tls",
                    5,
                    "op.tls.cred.2",
                    "replace",
                    "test-provider-key-654321",
                )
            )
        )
        self.assertEqual(self.server.requests, [])


if __name__ == "__main__":
    unittest.main()
