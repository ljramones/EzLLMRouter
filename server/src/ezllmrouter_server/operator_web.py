"""Operator server composition. Request handling lives in operator_http."""

from .observability import log_failure
from .operator_http.application import OperatorApplication
from .operator_http.handler import OperatorHandler
from .operator_http.common import (
    ThreadingHTTPServer,
    LocalConnectors,
    UserManager,
    LoginThrottle,
    ThreadPoolExecutor,
    Path,
    threading,
    socket,
    socketserver,
    os,
)


class UnixOperatorServer(ThreadingHTTPServer):
    address_family = socket.AF_UNIX

    def __init__(self, address, handler, public_port):
        self.public_port = public_port
        super().__init__(address, handler)

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
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
    mach33_demo=None,
    bootstrap_password_file=None,
):
    if host not in ("0.0.0.0", "127.0.0.1") or not password or len(password) < 32:
        raise ValueError("unsafe operator binding or credential")
    allowed_hosts = allowed_hosts or {f"127.0.0.1:{port}", f"localhost:{port}"}
    allowed_origins = {"http://" + value for value in allowed_hosts}
    accounts = (
        getattr(registry, "users", None)
        or UserManager(registry, bootstrap_password_file=bootstrap_password_file)
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
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
        build=build,
        fixture=fixture,
        integration_only=integration_only,
        jobs=jobs,
        local_connectors=local_connectors,
        login_throttle=login_throttle,
        mach33_demo=mach33_demo,
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
    try:
        server = (
            ThreadingHTTPServer((host, port), OperatorHandler)
            if socket_path is None
            else UnixOperatorServer(socket_path, OperatorHandler, port)
        )
        if socket_path is not None:
            os.chmod(socket_path, 0o600)
    except BaseException:
        application.close()
        jobs.shutdown(wait=False, cancel_futures=True)
        raise
    server.application = application
    server.operator_jobs = jobs
    server.daemon_threads = True
    try:
        application.start(_accounting_maintenance)
    except BaseException:
        application.close()
        server.server_close()
        raise
    original_close = server.server_close

    def close():
        application.close()
        original_close()

    server.server_close = close
    return server
