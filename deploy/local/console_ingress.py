"""Fixed, credential-free bridge from host loopback to the trusted console socket."""

from __future__ import annotations

from pathlib import Path
import select
import socket
import socketserver
import time

from runtime_resources import BoundedThreadingMixIn


TARGET = Path("/console/operator.sock")


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        upstream = None
        try:
            upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            upstream.settimeout(3)
            upstream.connect(str(TARGET))
        except OSError:
            if upstream is not None:
                upstream.close()
            return
        with upstream:
            upstream.settimeout(5)
            self.request.settimeout(5)
            expires = time.monotonic() + 360
            streams = (self.request, upstream)
            try:
                while True:
                    remaining = expires - time.monotonic()
                    if remaining <= 0:
                        return
                    readable, _, _ = select.select(streams, [], [], min(30, remaining))
                    if not readable:
                        return
                    for source in readable:
                        data = source.recv(65536)
                        if not data:
                            return
                        destination = upstream if source is self.request else self.request
                        remaining = expires - time.monotonic()
                        if remaining <= 0:
                            return
                        destination.settimeout(min(5, remaining))
                        destination.sendall(data)
            except OSError:
                return


class Server(BoundedThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    with Server(("0.0.0.0", 8780), Handler) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
