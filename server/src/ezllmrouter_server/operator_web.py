"""Operator server composition. Request handling lives in operator_http."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Set
from typing import cast
from .external_identity import IdentityLookup
from .integration_accounting import ExternalAccounting
from .operator_http.application import JSONValue, OperatorSession, DemoRunner
from .operator_projection import OperatorProjection
from .operator_demo import ProviderValidationRunner
from .registry import Registry
from .scripted_demo import ScriptedDemo
from .store import SQLiteStore
import os
import socket
import socketserver
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .http_server import BoundedHTTPServer
from .local_connectors import LocalConnectors
from .observability import log_failure
from .operator_http.application import OperatorApplication
from .operator_http.handler import OperatorHandler
from .operator_http.policy import OperatorPolicy
from .user_management import LoginThrottle, UserManager


class UnixOperatorServer(BoundedHTTPServer):
    address_family = socket.AF_UNIX

    def __init__(self, address: str, handler: type[OperatorHandler], public_port: int) -> None:
        self.public_port = public_port
        super().__init__(address, handler)

    def server_bind(self) -> None:
        parent = Path(cast(str, self.server_address)).parent
        metadata = parent.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_mode & 0o022
            or metadata.st_uid != os.geteuid()
        ):
            raise ValueError(
                "operator socket directory must be owned and not writable by other users"
            )
        socketserver.TCPServer.server_bind(self)
        os.chmod(cast(str, self.server_address), 0o600)
        self.server_name = "localhost"
        self.server_port = self.public_port


def _accounting_maintenance(accounting: ExternalAccounting, stopped: threading.Event) -> None:
    while not stopped.wait(60):
        try:
            accounting.maintain()
        except Exception:
            log_failure("accounting_maintenance_failed")


def serve(
    host: str,
    port: int,
    *,
    projection: OperatorProjection,
    runner: DemoRunner | None,
    password: str,
    fixture: Mapping[str, JSONValue],
    build: Mapping[str, JSONValue],
    web_root: str | Path,
    worker_probe: Callable[[], Mapping[str, JSONValue]],
    sender_status: Callable[[], Mapping[str, JSONValue]],
    allowed_hosts: Set[str] | None = None,
    socket_path: str | None = None,
    registry: Registry | None = None,
    provider_validation: ProviderValidationRunner | None = None,
    successor_store: SQLiteStore | None = None,
    integration_only: bool = False,
    scripted_demo: ScriptedDemo | None = None,
    bootstrap_password_file: str | Path | None = None,
    public_origin: str | None = None,
    identity_lookup: IdentityLookup | None = None,
) -> BoundedHTTPServer:
    if not password or len(password) < 32:
        raise ValueError("unsafe operator binding or credential")
    policy = OperatorPolicy.build(
        host, port, allowed_hosts, unix_socket=socket_path is not None, public_origin=public_origin
    )
    application, jobs = _compose_operator_application(
        bootstrap_password_file,
        build,
        fixture,
        identity_lookup,
        integration_only,
        password,
        policy,
        projection,
        provider_validation,
        registry,
        runner,
        scripted_demo,
        sender_status,
        successor_store,
        web_root,
        worker_probe,
    )
    server = None
    try:
        server = (
            BoundedHTTPServer((host, port), OperatorHandler)
            if socket_path is None
            else UnixOperatorServer(socket_path, OperatorHandler, port)
        )
        if socket_path is None and port == 0:
            bound = OperatorPolicy.build(
                host, server.server_address[1], allowed_hosts, unix_socket=False, public_origin=None
            )
            application.allowed_hosts = bound.hosts
            application.allowed_origins = bound.origins
    except BaseException:
        try:
            application.close()
        finally:
            try:
                if server is not None:
                    server.server_close()
            finally:
                jobs.shutdown(wait=True, cancel_futures=True)
        raise
    server.application = application
    server.operator_jobs = jobs
    server.daemon_threads = True
    try:
        application.start(_accounting_maintenance)
    except BaseException:
        try:
            application.close()
        finally:
            server.server_close()
        raise
    original_close = server.server_close

    def close() -> None:
        with application.session_lock:
            application._closing = True
        try:
            original_close()
        finally:
            application.close()

    server.server_close = close
    return server


def _compose_operator_application(
    bootstrap_password_file: str | Path | None,
    build: Mapping[str, JSONValue],
    fixture: Mapping[str, JSONValue],
    identity_lookup: IdentityLookup | None,
    integration_only: bool,
    password: str,
    policy: OperatorPolicy,
    projection: OperatorProjection,
    provider_validation: ProviderValidationRunner | None,
    registry: Registry | None,
    runner: DemoRunner | None,
    scripted_demo: ScriptedDemo | None,
    sender_status: Callable[[], Mapping[str, JSONValue]],
    successor_store: SQLiteStore | None,
    web_root: str | Path,
    worker_probe: Callable[[], Mapping[str, JSONValue]],
) -> tuple[OperatorApplication, ThreadPoolExecutor]:
    accounts = (
        registry.users or UserManager(registry, bootstrap_password_file=bootstrap_password_file)
        if registry
        else None
    )
    local_connectors = LocalConnectors(registry) if registry else None
    if registry:
        registry.local_connectors = local_connectors
    login_throttle = LoginThrottle()
    sessions: dict[str, OperatorSession] = {}
    session_lock = threading.Lock()
    jobs = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ezllmrouter-operator-demo")
    root = Path(web_root)
    application = OperatorApplication(
        accounts=accounts,
        allowed_hosts=policy.hosts,
        allowed_origins=policy.origins,
        secure_cookies=policy.secure_cookies,
        identity_lookup=identity_lookup,
        build=build,
        fixture=fixture,
        integration_only=integration_only,
        jobs=jobs,
        local_connectors=local_connectors,
        login_throttle=login_throttle,
        scripted_demo=scripted_demo,
        password=password,
        projection=projection,
        provider_validation=provider_validation,
        registry=registry,
        root=root,
        runner=runner,
        sender_status=sender_status,
        session_lock=session_lock,
        sessions=sessions,
        successor_store=successor_store,
        worker_probe=worker_probe,
    )
    return application, jobs
