"""Authenticated framing cases traverse the actual credential-free ingress relay."""

from contextlib import suppress
import socket
import threading
from types import SimpleNamespace
from unittest.mock import patch

from deploy.local import console_ingress as ingress
from tests.unit import test_generated_http_framing as framing


class UpstreamSocket:
    def __init__(self, raw, destinations):
        self.raw, self.destinations = raw, destinations

    def connect(self, destination):
        self.destinations.append(destination)

    def __getattr__(self, name):
        return getattr(self.raw, name)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.raw.close()


class IngressFramingTests(framing.AuthenticatedFramingTests):
    def exchange(self, server, raw):
        client, relay = socket.socketpair()
        upstream, backend = socket.socketpair()
        destinations, failures = [], []

        def handle_backend():
            try:
                server.handler(backend, ("127.0.0.1", 12345), server)
            except OSError:
                pass  # The parser may close before a rejected body finishes arriving.
            except BaseException as error:
                failures.append(type(error).__name__)
            finally:
                backend.close()

        def handle_relay():
            try:
                ingress.Handler(relay, ("127.0.0.1", 12345), SimpleNamespace())
            except BaseException as error:
                failures.append(type(error).__name__)
            finally:
                relay.close()

        threads = [threading.Thread(target=handle_backend), threading.Thread(target=handle_relay)]
        with patch.object(
            ingress.socket, "socket", return_value=UpstreamSocket(upstream, destinations)
        ):
            for thread in threads:
                thread.start()
            try:
                client.settimeout(3)
                with suppress(BrokenPipeError, ConnectionResetError):
                    for offset in range(0, len(raw), 31):
                        client.sendall(raw[offset : offset + 31])
                    client.shutdown(socket.SHUT_WR)
                chunks = []
                with suppress(ConnectionResetError):
                    while chunk := client.recv(65536):
                        chunks.append(chunk)
                result = b"".join(chunks)
            finally:
                client.close()
                for thread in threads:
                    thread.join(3)
                for endpoint in (client, relay, upstream, backend):
                    with suppress(OSError):
                        endpoint.shutdown(socket.SHUT_RDWR)
                    endpoint.close()
                for thread in threads:
                    thread.join(5)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(failures, [])
        self.assertEqual(destinations, [str(ingress.TARGET)])
        return result
