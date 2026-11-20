"""Completion-only deterministic first-write faults on the owned local TLS socket.

The normal transport remains the default. A selected T-24.b case installs
this transport only for its one controlled request; no provider route exists.
"""

from __future__ import annotations

import asyncio
import socket
import ssl

import httpcore

from dev12_tls_transport import OwnedSyntheticTLSHTTPTransport, SyntheticTLSBackend
from guard import GuardRejected
from owned_tls_sender_transport import OwnedTLSStream


class _FaultSocket:
    """Inject one bounded socket result beneath the unmodified product drain."""

    def __init__(self, sock, fault):
        self.sock = sock
        self.fault = fault
        self.stream = None

    def __getattr__(self, name):
        return getattr(self.sock, name)

    def send(self, data):
        fault = self.fault
        request = self.stream is not None and self.stream.invocation is not None
        if request and fault and not fault["fired"]:
            if fault["mode"] == "would_block_once":
                fault["fired"] = True
                fault["observations"].append("SOCKET_WOULD_BLOCK_BEFORE_FIRST_BYTE")
                fault["observations"].append("SYNTHETIC_WOULD_BLOCK_BEFORE_FIRST_BYTE")
                action = fault.get("on_block")
                if action:
                    asyncio.get_running_loop().call_soon(action)
                raise BlockingIOError()
            if fault["mode"] == "partial_after_first_bytes":
                count = self.sock.send(data[:1])
                if count:
                    fault["fired"] = True
                    fault["observations"].append("SOCKET_ACCEPTED_ONE_TLS_BYTE")
                    fault["observations"].append("SYNTHETIC_PARTIAL_TLS_RECORD_AFTER_FIRST_BYTE")
                return count
        return self.sock.send(data)


class CompletionTLSStream(OwnedTLSStream):
    def __init__(self, sock, authority, *, first_write_wait=None, fault=None):
        wrapped = _FaultSocket(sock, fault)
        super().__init__(wrapped, authority, first_write_wait=first_write_wait)
        wrapped.stream = self
        self.fault = fault

    async def read(self, max_bytes, timeout=None):
        # The first encrypted record was split across positive local writes.
        # The complete one-use request reaches the independent receiver, which
        # retains a receipt. Drop the response so the sender must preserve
        # possible-send uncertainty until an authorized late collection.
        if (
            self.fault
            and self.fault["mode"] == "partial_after_first_bytes"
            and self.fault["fired"]
            and self.request_bytes_accepted
        ):
            await asyncio.sleep(0.1)
            self.fault["observations"].append("RESPONSE_DROPPED_AFTER_FRAGMENTED_REQUEST")
            self.terminal = True
            self.sock.close()
            raise ConnectionError("synthetic response drop after fragmented TLS request")
        return await super().read(max_bytes, timeout)


class CompletionTLSBackend(SyntheticTLSBackend):
    def __init__(self, authority, port, *, first_write_wait=None, fault=None):
        super().__init__(authority, port, first_write_wait=first_write_wait)
        self.fault = fault

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        actual_host = host.decode() if type(host) is bytes else host
        if (actual_host, port, local_address, socket_options) != (
            "synthetic.invalid",
            self.port,
            None,
            None,
        ):
            raise GuardRejected("DESTINATION_REJECTED")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setblocking(False)
        try:
            await asyncio.wait_for(
                asyncio.get_running_loop().sock_connect(sock, ("127.0.0.1", self.port)), timeout
            )
            return CompletionTLSStream(
                sock, self.authority, first_write_wait=self.first_write_wait, fault=self.fault
            )
        except BaseException:
            sock.close()
            raise


class CompletionTLSHTTPTransport(OwnedSyntheticTLSHTTPTransport):
    fault = None

    def __init__(self, authority, port, ca_pem, *, first_write_wait=None):
        self.origin = f"https://synthetic.invalid:{port}"
        context = ssl.create_default_context(cadata=ca_pem)
        self.pool = httpcore.AsyncConnectionPool(
            ssl_context=context,
            max_connections=1,
            max_keepalive_connections=0,
            http1=True,
            http2=False,
            retries=0,
            network_backend=CompletionTLSBackend(
                authority, port, first_write_wait=first_write_wait, fault=self.fault
            ),
        )
