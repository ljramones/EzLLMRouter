"""Test-only shared-lock detector for network waits, password work and sleeps."""

from contextlib import ExitStack, contextmanager
from collections.abc import Iterator
import hashlib
import inspect
import socket
import ssl
import threading
import time
from unittest.mock import patch


class WatchedLock:
    def __init__(self, lock, label, auditor):
        self.lock, self.label, self.auditor = lock, label, auditor

    def acquire(self, *args, **kwargs):
        if (
            self.label == "password_slots"
            and (not args or args[0])
            and kwargs.get("blocking", True)
        ):
            self.auditor.check("password slot wait")
        result = self.lock.acquire(*args, **kwargs)
        if result:
            held = self.auditor.held()
            held[id(self)] = (self.label, held.get(id(self), (self.label, 0))[1] + 1)
        return result

    def release(self):
        self.lock.release()
        held = self.auditor.held()
        label, depth = held[id(self)]
        if depth == 1:
            del held[id(self)]
        else:
            held[id(self)] = (label, depth - 1)

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *_error):
        self.release()

    def __getattr__(self, name):
        return getattr(self.lock, name)

    def _release_save(self):
        tracked = self.auditor.held().pop(id(self))
        return self.lock._release_save(), tracked

    def _acquire_restore(self, state):
        native, tracked = state
        self.lock._acquire_restore(native)
        self.auditor.held()[id(self)] = tracked


class LockAuditor:
    def __init__(self) -> None:
        self.local = threading.local()

    def held(self):
        if not hasattr(self.local, "held"):
            self.local.held = {}
        return self.local.held

    def watch(self, lock, label):
        return lock if isinstance(lock, WatchedLock) else WatchedLock(lock, label, self)

    def check(self, operation, connection=None):
        labels = {label for label, _ in self.held().values()}
        if not labels:
            return
        # The semaphore bounds hashes; database/authority gates must be released first.
        if operation == "scrypt" and labels <= {"password_slots"}:
            return
        if operation in {"scrypt", "password slot wait"} and self.inside(
            {("ezllmrouter_server/user_management.py", "UserManager._bootstrap.<locals>.action")}
        ):
            # Initial account seeding runs before the HTTP service binds. Routine
            # authentication and account changes have no such exemption.
            return
        if operation == "send" and labels <= {"authority"} and connection.gettimeout() == 0:
            if self.inside(
                {
                    (
                        "ezllmrouter_server/gateway/owned_sender_transport.py",
                        "OwnedSocketStream._write_once.<locals>.emit",
                    ),
                    (
                        "ezllmrouter_server/gateway/owned_tls_sender_transport.py",
                        "OwnedTLSStream._drain.<locals>.emit",
                    ),
                    ("asyncio/selector_events.py", "BaseSelectorEventLoop._write_to_self"),
                }
            ):
                return
        raise AssertionError(
            "blocking " + operation + " under shared lock: " + ",".join(sorted(labels))
        )

    @staticmethod
    def inside(allowed):
        frame = inspect.currentframe()
        try:
            frame = frame.f_back
            while frame:
                code = frame.f_code
                filename = code.co_filename.replace("\\", "/")
                if any(
                    filename.endswith("/" + suffix) and code.co_qualname == name
                    for suffix, name in allowed
                ):
                    return True
                frame = frame.f_back
            return False
        finally:
            del frame

    def install(self, stack: ExitStack) -> None:
        from ezllmrouter_server.store import SQLiteStore
        from ezllmrouter_server.registry import Registry
        from ezllmrouter_server import user_management
        from ezllmrouter_server.gateway.owned_sender_transport import LocalSendAuthority

        original_store, original_registry = SQLiteStore.__init__, Registry.__init__
        original_authority = LocalSendAuthority.__init__

        def authority_init(authority, *args, **kwargs):
            original_authority(authority, *args, **kwargs)
            authority.gate = self.watch(authority.gate, "authority")

        def store_init(store, *args, **kwargs):
            original_store(store, *args, **kwargs)
            gate = self.watch(store._lock, "database")
            store._lock = store.database._gate = gate

        def registry_init(registry, *args, **kwargs):
            authority = args[1] if len(args) > 1 else kwargs.get("send_authority")
            if authority is not None:
                authority.gate = self.watch(authority.gate, "authority")
            original_registry(registry, *args, **kwargs)

        stack.enter_context(patch.object(SQLiteStore, "__init__", store_init))
        stack.enter_context(patch.object(Registry, "__init__", registry_init))
        stack.enter_context(patch.object(LocalSendAuthority, "__init__", authority_init))
        stack.enter_context(
            patch.object(
                user_management,
                "PASSWORD_HASH_SLOTS",
                self.watch(user_management.PASSWORD_HASH_SLOTS, "password_slots"),
            )
        )
        for owner, name, operation in (
            (hashlib, "scrypt", "scrypt"),
            (time, "sleep", "sleep"),
            (ssl.SSLSocket, "do_handshake", "TLS handshake"),
            (socket.socket, "connect", "connect"),
            (socket.socket, "connect_ex", "connect"),
            (socket.socket, "recv", "recv"),
            (socket.socket, "recv_into", "recv"),
            (socket.socket, "send", "send"),
            (socket.socket, "sendall", "send"),
        ):
            original = getattr(owner, name)

            def checked(*args, _original=original, _operation=operation, **kwargs):
                self.check(_operation, args[0] if _operation == "send" and args else None)
                return _original(*args, **kwargs)

            stack.enter_context(patch.object(owner, name, checked))


@contextmanager
def auditing() -> Iterator[LockAuditor]:
    with ExitStack() as stack:
        auditor = LockAuditor()
        auditor.install(stack)
        yield auditor
