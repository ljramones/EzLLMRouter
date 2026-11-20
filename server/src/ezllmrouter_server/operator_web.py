"""Operator server composition. Request handling lives in operator_http."""

import os
import socket
import socketserver
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .http_server import BoundedHTTPServer as ThreadingHTTPServer
from .local_connectors import LocalConnectors
from .observability import log_failure
from .operator_http.application import OperatorApplication
from .operator_http.handler import OperatorHandler
from .operator_http.policy import OperatorPolicy
from .user_management import LoginThrottle, UserManager


class UnixOperatorServer(ThreadingHTTPServer):
    address_family = socket.AF_UNIX

    def __init__(self, address, handler, public_port):
        self.public_port = public_port
        super().__init__(address, handler)

    def server_bind(self):
        parent = Path(self.server_address).parent
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
        os.chmod(self.server_address, 0o600)
        self.server_name = "localhost"
        self.server_port = self.public_port


def _accounting_maintenance(accounting, stopped):
    while not stopped.wait(60):
        try:
            accounting.maintain()
        except Exception:
            log_failure("accounting_maintenance_failed")


def serve(
    host,
    port,
    *,
    projection,
    runner,
    password,
    fixture,
    build,
    web_root,
    worker_probe,
    sender_status,
    allowed_hosts=None,
    socket_path=None,
    registry=None,
    provider_validation=None,
    successor_store=None,
    integration_only=False,
    scripted_demo=None,
    bootstrap_password_file=None,
    public_origin=None,
    identity_lookup=None,
):
    if not password or len(password) < 32:
        raise ValueError("unsafe operator binding or credential")
    policy = OperatorPolicy.build(
        host, port, allowed_hosts, unix_socket=socket_path is not None, public_origin=public_origin
    )
    accounts = (
        registry.users or UserManager(registry, bootstrap_password_file=bootstrap_password_file)
        if registry
        else None
    )
    local_connectors = LocalConnectors(registry) if registry else None
    if registry:
        registry.local_connectors = local_connectors
    login_throttle = LoginThrottle()
    sessions = {}
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
    server = None
    try:
        server = (
            ThreadingHTTPServer((host, port), OperatorHandler)
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

    def close():
        with application.session_lock:
            application._closing = True
        try:
            original_close()
        finally:
            application.close()

    server.server_close = close
    return server
