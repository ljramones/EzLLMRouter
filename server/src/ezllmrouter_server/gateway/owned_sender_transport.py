"""Narrow DEV-04 plaintext HTTP/1.1 sender I/O using documented httpcore hooks."""
from __future__ import annotations

import asyncio
from datetime import datetime
import socket
import threading
import time

import httpcore
import httpx

from .guard import ACTIVE, GuardRejected


HOST = "127.0.0.1"
PORT = 8766


class LocalSendAuthority:
    """The only local effective-revocation/write gate for this experiment."""

    def __init__(self):
        self.gate = threading.RLock()
        self.revoked = False
        self.epoch = 0

    def revoke(self):
        with self.gate:
            self.revoked = True
            self.epoch += 1
            return self.epoch

    def restore(self):
        with self.gate:
            self.revoked = False
            self.epoch += 1
            return self.epoch

    def is_revoked(self):
        with self.gate:
            return self.revoked

    def snapshot_epoch(self):
        with self.gate:
            if self.revoked:
                raise GuardRejected("FDC_REJECTED")
            return self.epoch


async def _writable(sock, timeout):
    loop = asyncio.get_running_loop()
    ready = loop.create_future()

    def wake():
        if not ready.done():
            ready.set_result(None)

    loop.add_writer(sock.fileno(), wake)
    try:
        await asyncio.wait_for(ready, timeout=timeout)
    finally:
        loop.remove_writer(sock.fileno())


class OwnedSocketStream(httpcore.AsyncNetworkStream):
    """One connection, one trusted invocation; no TLS or keep-alive reuse."""

    def __init__(self, sock, authority):
        if sock.getblocking():
            raise ValueError("owned sender socket must be nonblocking")
        self.sock = sock
        self.authority = authority
        self.invocation = None
        self.first_bytes_accepted = False
        self.accepted_bytes = 0
        self.terminal = False

    async def read(self, max_bytes, timeout=None):
        loop = asyncio.get_running_loop()
        operation = loop.sock_recv(self.sock, max_bytes)
        return await asyncio.wait_for(operation, timeout=timeout)

    async def write(self, buffer, timeout=None):
        if self.terminal:
            raise GuardRejected("SECOND_SEND_REJECTED")
        try:
            await self._write_once(buffer, timeout)
        except BaseException:
            # An interrupted HTTP/1.1 frame cannot be resumed by a new call.
            # The in-progress call alone may continue its unsent suffix.
            self.terminal = True
            self.sock.close()
            raise

    async def _write_once(self, buffer, timeout):
        if not buffer:
            return
        invocation = ACTIVE.get()
        if invocation is None or not invocation.committed or not invocation.released:
            raise GuardRejected("NO_TRUSTED_CONTEXT")
        if self.invocation is None:
            self.invocation = invocation
        elif self.invocation is not invocation:
            raise GuardRejected("SECOND_SEND_REJECTED")

        loop = asyncio.get_running_loop()
        deadline = None if timeout is None else loop.time() + timeout
        plan_deadline = datetime.fromisoformat(invocation.plan["deadline"].replace("Z", "+00:00")).timestamp()
        data = memoryview(buffer)
        offset = 0
        while offset < len(data):
            # This can inspect signed work and policy. It runs before the gate,
            # after connection/pool waits, and again after every would-block wait.
            if not self.first_bytes_accepted:
                invocation.fresh_check()
            with self.authority.gate:
                # Only fixed local authority changes through this gate. No await,
                # disk work or callback intervenes before the nonblocking send.
                if not self.first_bytes_accepted and (
                    self.authority.revoked or
                    invocation.authority_epoch != self.authority.epoch or
                    time.time() >= plan_deadline
                ):
                    raise GuardRejected("FDC_REJECTED")
                try:
                    count = self.sock.send(data[offset:])
                except (BlockingIOError, InterruptedError):
                    count = 0
                if count > 0:
                    if not self.first_bytes_accepted:
                        self.first_bytes_accepted = True
                        invocation.first_bytes_accepted = True
                        invocation.observations.append("FIRST_BYTES_ACCEPTED_BY_LOCAL_SOCKET")
                    self.accepted_bytes += count
            if count > 0:
                offset += count
                continue
            remaining = None if deadline is None else deadline - loop.time()
            if remaining is not None and remaining <= 0:
                raise httpcore.WriteTimeout()
            await _writable(self.sock, remaining)

    async def aclose(self):
        self.sock.close()

    async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        raise RuntimeError("DEV-04 owned sender excludes TLS")

    def get_extra_info(self, info):
        if info == "socket":
            return self.sock
        if info == "is_readable":
            return False
        return None


class OwnedSocketBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, authority):
        self.authority = authority

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if (host, port, local_address, socket_options) != (HOST, PORT, None, None):
            raise RuntimeError("DEV-04 owned sender destination/options rejected")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setblocking(False)
        try:
            await asyncio.wait_for(asyncio.get_running_loop().sock_connect(sock, (HOST, PORT)), timeout)
            return OwnedSocketStream(sock, self.authority)
        except BaseException:
            sock.close()
            raise

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise RuntimeError("DEV-04 owned sender excludes Unix provider destinations")

    async def sleep(self, seconds):
        raise RuntimeError("DEV-04 owned sender excludes connection retries")


class _ResponseStream(httpx.AsyncByteStream):
    def __init__(self, stream):
        self.stream = stream

    async def __aiter__(self):
        async for part in self.stream:
            yield part

    async def aclose(self):
        await self.stream.aclose()


class OwnedHTTPTransport(httpx.AsyncBaseTransport):
    """HTTPX public transport adapter; httpcore retains HTTP and pool logic."""

    def __init__(self, authority):
        self.pool = httpcore.AsyncConnectionPool(
            max_connections=1, max_keepalive_connections=0,
            http1=True, http2=False, retries=0,
            network_backend=OwnedSocketBackend(authority),
        )

    async def handle_async_request(self, request):
        if (request.method, str(request.url)) != (
            "POST", f"http://{HOST}:{PORT}/v1/chat/completions"
        ):
            raise GuardRejected("FDC_REJECTED")
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        response = await self.pool.handle_async_request(core_request)
        return httpx.Response(
            response.status, headers=response.headers,
            stream=_ResponseStream(response.stream),
            extensions=response.extensions, request=request,
        )

    async def aclose(self):
        await self.pool.aclose()
