"""Owned local TLS mapping for signed synthetic.invalid routes only."""
from __future__ import annotations

import asyncio
import socket
import ssl

import httpcore
import httpx

from guard import GuardRejected
from owned_sender_transport import _ResponseStream
from owned_tls_sender_transport import OwnedTLSStream


class SyntheticTLSBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, authority, port, *, first_write_wait=None):
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("invalid owned receiver port")
        self.authority = authority
        self.port = port
        self.first_write_wait = first_write_wait

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        actual_host = host.decode() if type(host) is bytes else host
        if (actual_host, port, local_address, socket_options) != ("synthetic.invalid", self.port, None, None):
            raise GuardRejected("DESTINATION_REJECTED")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setblocking(False)
        try:
            await asyncio.wait_for(asyncio.get_running_loop().sock_connect(sock, ("127.0.0.1", self.port)), timeout)
            return OwnedTLSStream(sock, self.authority, first_write_wait=self.first_write_wait)
        except BaseException:
            sock.close()
            raise

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise GuardRejected("DESTINATION_REJECTED")

    async def sleep(self, seconds):
        raise GuardRejected("SECOND_SEND_REJECTED")


class OwnedSyntheticTLSHTTPTransport(httpx.AsyncBaseTransport):
    def __init__(self, authority, port, ca_pem, *, first_write_wait=None):
        self.origin = f"https://synthetic.invalid:{port}"
        context = ssl.create_default_context(cadata=ca_pem)
        self.pool = httpcore.AsyncConnectionPool(
            ssl_context=context, max_connections=1, max_keepalive_connections=0,
            http1=True, http2=False, retries=0,
            network_backend=SyntheticTLSBackend(authority, port, first_write_wait=first_write_wait))

    async def handle_async_request(self, request):
        if (request.method != "POST" or str(request.url) not in
                (self.origin + "/synthetic/v1/embeddings", self.origin + "/synthetic/v1/rerank")):
            raise GuardRejected("DESTINATION_REJECTED")
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(scheme=request.url.raw_scheme, host=request.url.raw_host,
                             port=request.url.port, target=request.url.raw_path),
            headers=request.headers.raw, content=request.stream, extensions=request.extensions)
        response = await self.pool.handle_async_request(core_request)
        return httpx.Response(response.status, headers=response.headers,
                              stream=_ResponseStream(response.stream), extensions=response.extensions,
                              request=request)

    async def aclose(self):
        await self.pool.aclose()
