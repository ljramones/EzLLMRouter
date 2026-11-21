"""Compose the versioned work and integration HTTP server."""

from __future__ import annotations

from functools import partial
from typing import cast
from .wire_http.contracts import WorkCoordinator, RegistryCoordinator

from .http_server import BoundedHTTPServer
from .wire_http.handler import WireHandler
from .wire_http.transport import WireApplication


def serve(
    host: str,
    port: int,
    coordinator: WorkCoordinator | RegistryCoordinator,
    *,
    integration_only: bool = False,
) -> BoundedHTTPServer:
    application = WireApplication(cast(WorkCoordinator, coordinator), integration_only)
    handler = partial(WireHandler, application=application)
    server = BoundedHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server
