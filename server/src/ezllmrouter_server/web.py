"""Compose the versioned work and integration HTTP server."""

from functools import partial

from .http_server import BoundedHTTPServer
from .wire_http.handler import WireHandler
from .wire_http.transport import WireApplication


def serve(host: str, port: int, coordinator, *, integration_only=False):
    application = WireApplication(coordinator, integration_only)
    handler = partial(WireHandler, application=application)
    server = BoundedHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server
