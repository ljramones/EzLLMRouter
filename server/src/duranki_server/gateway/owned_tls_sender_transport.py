"""Sender-owned TLS socket for one fixed HTTPS Responses operation.

The first encrypted TLS record containing HTTP request bytes is written under
the same effective-revocation gate as the original plaintext socket. Handshake
records are deliberately excluded from the model-request acceptance fact.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
import socket
import ssl
import time
from urllib.parse import urlsplit

import httpcore
import httpx

from duranki_server.provider_adapters import _allowed_ip, validate_settings
from .guard import ACTIVE, GuardRejected
from .owned_sender_transport import _writable, _ResponseStream


class OwnedTLSStream(httpcore.AsyncNetworkStream):
    def __init__(self, sock, authority, *, first_write_wait=None):
        self.sock = sock
        self.authority = authority
        self.first_write_wait = first_write_wait
        self.invocation = None
        self.request_bytes_accepted = False
        self.terminal = False
        self.tls = None
        self.incoming = None
        self.outgoing = None

    async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        if self.tls is not None or not server_hostname or ssl_context.verify_mode != ssl.CERT_REQUIRED or not ssl_context.check_hostname:
            raise GuardRejected("TLS_CONFIGURATION_REJECTED")
        self.incoming, self.outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
        self.tls = ssl_context.wrap_bio(self.incoming, self.outgoing,
                                        server_side=False, server_hostname=server_hostname)
        deadline = None if timeout is None else asyncio.get_running_loop().time() + timeout
        try:
            while True:
                try:
                    self.tls.do_handshake()
                    await self._drain(deadline, request=False)
                    return self
                except ssl.SSLWantWriteError:
                    await self._drain(deadline, request=False)
                except ssl.SSLWantReadError:
                    await self._drain(deadline, request=False)
                    self.incoming.write(await self._receive_cipher(deadline))
        except BaseException:
            self.terminal = True
            self.sock.close()
            raise

    async def _receive_cipher(self, deadline):
        loop = asyncio.get_running_loop()
        remaining = None if deadline is None else deadline - loop.time()
        if remaining is not None and remaining <= 0:
            raise httpcore.ReadTimeout()
        raw = await asyncio.wait_for(loop.sock_recv(self.sock, 65536), timeout=remaining)
        if not raw:
            raise httpcore.ReadError("TLS peer closed")
        return raw

    async def _drain(self, deadline, *, request):
        loop = asyncio.get_running_loop()
        while self.outgoing.pending:
            cipher = memoryview(self.outgoing.read())
            offset = 0
            while offset < len(cipher):
                invocation = self.invocation
                if request and not self.request_bytes_accepted:
                    if invocation is None:
                        raise GuardRejected("NO_TRUSTED_CONTEXT")
                    if self.first_write_wait is not None:
                        await self.first_write_wait()
                with self.authority.gate:
                    if request and not self.request_bytes_accepted:
                        invocation.fresh_check()
                    if request and not self.request_bytes_accepted and (
                        self.authority.revoked or invocation.authority_epoch != self.authority.epoch or
                        time.time() >= datetime.fromisoformat(invocation.plan.get(
                            "deadline", invocation.plan.get("expires_at")).replace("Z", "+00:00")).timestamp()
                    ):
                        raise GuardRejected("FDC_REJECTED")
                    try:
                        count = self.sock.send(cipher[offset:])
                    except (BlockingIOError, InterruptedError):
                        count = 0
                    if count and request and not self.request_bytes_accepted:
                        self.request_bytes_accepted = True
                        invocation.first_bytes_accepted = True
                        invocation.observations.append("FIRST_TLS_REQUEST_BYTES_ACCEPTED_BY_LOCAL_SOCKET")
                if count:
                    offset += count
                    continue
                remaining = None if deadline is None else deadline - loop.time()
                if remaining is not None and remaining <= 0:
                    raise httpcore.WriteTimeout()
                await _writable(self.sock, remaining)

    async def read(self, max_bytes, timeout=None):
        if self.tls is None or self.terminal:
            raise GuardRejected("TLS_STREAM_UNAVAILABLE")
        deadline = None if timeout is None else asyncio.get_running_loop().time() + timeout
        while True:
            try:
                return self.tls.read(max_bytes)
            except ssl.SSLWantReadError:
                await self._drain(deadline, request=self.request_bytes_accepted)
                self.incoming.write(await self._receive_cipher(deadline))
            except ssl.SSLZeroReturnError:
                return b""

    async def write(self, buffer, timeout=None):
        if self.tls is None or self.terminal:
            raise GuardRejected("TLS_STREAM_UNAVAILABLE")
        invocation = ACTIVE.get()
        if invocation is None or not invocation.committed or not invocation.released or (
                self.invocation is not None and self.invocation is not invocation):
            raise GuardRejected("NO_TRUSTED_CONTEXT")
        self.invocation = invocation
        deadline = None if timeout is None else asyncio.get_running_loop().time() + timeout
        try:
            data = memoryview(buffer)
            offset = 0
            while offset < len(data):
                try:
                    offset += self.tls.write(data[offset:])
                    await self._drain(deadline, request=True)
                except ssl.SSLWantWriteError:
                    await self._drain(deadline, request=True)
                except ssl.SSLWantReadError:
                    await self._drain(deadline, request=True)
                    self.incoming.write(await self._receive_cipher(deadline))
        except BaseException:
            self.terminal = True
            self.sock.close()
            raise

    async def aclose(self):
        self.terminal = True
        self.sock.close()

    def get_extra_info(self, info):
        if info == "ssl_object":
            return self.tls
        if info == "socket":
            return self.sock
        if info == "is_readable":
            return False
        return None


class OwnedTLSBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, authority, adapter_id, settings, *, controlled=False, first_write_wait=None):
        self.provider = validate_settings(adapter_id, settings, controlled=controlled)
        self.settings = settings
        self.authority = authority
        self.controlled = controlled
        self.first_write_wait = first_write_wait
        url = urlsplit(settings["origin"])
        self.host, self.port = url.hostname, url.port or 443

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if (host, port, local_address, socket_options) != (self.host, self.port, None, None):
            raise GuardRejected("DESTINATION_REJECTED")
        addresses = await asyncio.to_thread(socket.getaddrinfo, host, port, type=socket.SOCK_STREAM)
        if not addresses or any(not _allowed_ip(item[4][0], self.provider, controlled=self.controlled) for item in addresses):
            raise GuardRejected("DESTINATION_REJECTED")
        selected = sorted(addresses, key=lambda item: item[0] != socket.AF_INET)[0]
        sock = socket.socket(selected[0], socket.SOCK_STREAM)
        sock.setblocking(False)
        try:
            await asyncio.wait_for(asyncio.get_running_loop().sock_connect(sock, selected[4]), timeout)
            return OwnedTLSStream(sock, self.authority, first_write_wait=self.first_write_wait)
        except BaseException:
            sock.close()
            raise

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise GuardRejected("DESTINATION_REJECTED")

    async def sleep(self, seconds):
        raise GuardRejected("SECOND_SEND_REJECTED")


class OwnedTLSHTTPTransport(httpx.AsyncBaseTransport):
    def __init__(self, authority, adapter_id, settings, *, controlled=False, first_write_wait=None):
        if adapter_id != "openai.responses.v1":
            raise ValueError("selected HTTPS inference adapter unsupported")
        self.origin = settings["origin"].rstrip("/")
        self.backend = OwnedTLSBackend(authority, adapter_id, settings,
            controlled=controlled, first_write_wait=first_write_wait)
        context = ssl.create_default_context(cadata=settings.get("ca_pem"))
        self.pool = httpcore.AsyncConnectionPool(ssl_context=context, max_connections=1,
            max_keepalive_connections=0, http1=True, http2=False, retries=0,
            network_backend=self.backend)

    async def handle_async_request(self, request):
        if request.method != "POST" or str(request.url) != self.origin + "/v1/responses":
            raise GuardRejected("DESTINATION_REJECTED")
        core_request = httpcore.Request(method=request.method,
            url=httpcore.URL(scheme=request.url.raw_scheme, host=request.url.raw_host,
                port=request.url.port, target=request.url.raw_path),
            headers=request.headers.raw, content=request.stream, extensions=request.extensions)
        response = await self.pool.handle_async_request(core_request)
        return httpx.Response(response.status, headers=response.headers,
            stream=_ResponseStream(response.stream), extensions=response.extensions, request=request)

    async def aclose(self):
        await self.pool.aclose()
