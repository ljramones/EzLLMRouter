"""Test-only shared-lock detector for network waits, password work and sleeps."""

from contextlib import ExitStack, contextmanager
from collections.abc import Iterator
import asyncio
import hashlib
import inspect
import socket
import sqlite3
import ssl
import threading
import time
from unittest.mock import patch

_ACTIVE = None


def _database_call(operation):
    if _ACTIVE is not None:
        _ACTIVE.check_database(operation)


class AuditedCursor(sqlite3.Cursor):
    def execute(self, *args, **kwargs):
        _database_call("SQLite execute")
        return super().execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        _database_call("SQLite executemany")
        return super().executemany(*args, **kwargs)

    def executescript(self, *args, **kwargs):
        _database_call("SQLite executescript")
        return super().executescript(*args, **kwargs)

    def fetchone(self):
        _database_call("SQLite fetch")
        return super().fetchone()

    def fetchmany(self, *args):
        _database_call("SQLite fetch")
        return super().fetchmany(*args)

    def fetchall(self):
        _database_call("SQLite fetch")
        return super().fetchall()

    def __next__(self):
        _database_call("SQLite fetch")
        return super().__next__()


class AuditedConnection(sqlite3.Connection):
    def cursor(self, factory=AuditedCursor):
        _database_call("SQLite cursor")
        if not issubclass(factory, AuditedCursor):
            raise AssertionError("lock audit requires an audited SQLite cursor factory")
        return super().cursor(factory)

    def execute(self, *args, **kwargs):
        return self.cursor().execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        return self.cursor().executemany(*args, **kwargs)

    def executescript(self, *args, **kwargs):
        return self.cursor().executescript(*args, **kwargs)

    def commit(self):
        _database_call("SQLite commit")
        return super().commit()

    def rollback(self):
        _database_call("SQLite rollback")
        return super().rollback()


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
        self._violations = []
        self._violations_lock = threading.Lock()

    @property
    def violations(self):
        with self._violations_lock:
            return [dict(row) for row in self._violations]

    def fail(self, operation, labels):
        # No query text, arguments, exception messages, locals or thread names.
        row = {"operation": operation, "locks": sorted(labels), "thread_id": threading.get_ident()}
        with self._violations_lock:
            self._violations.append(row)
        raise AssertionError(
            "blocking " + operation + " under shared lock: " + ",".join(sorted(labels))
        )

    def check_database(self, operation):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        self.fail(
            operation + " on asyncio event loop", {label for label, _ in self.held().values()}
        )

    def held(self):
        if not hasattr(self.local, "held"):
            self.local.held = {}
        return self.local.held

    def watch(self, lock, label):
        if isinstance(lock, WatchedLock):
            if lock.auditor is self:
                return lock
            lock = lock.lock
        return WatchedLock(lock, label, self)

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
        self.fail(operation, labels)

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
        from ezllmrouter_server.integration_credentials import DatabaseCredentialStore
        from ezllmrouter_server.provider_vault import ProviderVault
        from ezllmrouter_server.connector_availability import AvailabilityMonitor
        from ezllmrouter_server.gateway.owned_sender_transport import LocalSendAuthority

        original_store, original_registry = SQLiteStore.__init__, Registry.__init__
        original_authority = LocalSendAuthority.__init__
        original_open = SQLiteStore.open_existing.__func__
        original_connect = sqlite3.connect

        def connect(*args, **kwargs):
            _database_call("SQLite connect")
            args = list(args)
            factory = args[5] if len(args) > 5 else kwargs.get("factory", sqlite3.Connection)
            if factory is sqlite3.Connection:
                factory = AuditedConnection
            elif not issubclass(factory, AuditedConnection):
                raise AssertionError("lock audit requires an audited SQLite connection factory")
            if len(args) > 5:
                args[5] = factory
            else:
                kwargs["factory"] = factory
            return original_connect(*args, **kwargs)

        def instrument_store(store):
            gate = self.watch(store._lock, "database")
            store._lock = store.database._gate = gate

        def open_existing(cls, *args, **kwargs):
            result = original_open(cls, *args, **kwargs)
            instrument_store(result)
            return result

        def authority_init(authority, *args, **kwargs):
            original_authority(authority, *args, **kwargs)
            authority.gate = self.watch(authority.gate, "authority")

        def store_init(store, *args, **kwargs):
            original_store(store, *args, **kwargs)
            instrument_store(store)

        def registry_init(registry, *args, **kwargs):
            authority = args[1] if len(args) > 1 else kwargs.get("send_authority")
            original_registry(registry, *args, **kwargs)
            if authority is not None:
                authority.gate = self.watch(authority.gate, "authority")
            registry._probe_lock = self.watch(registry._probe_lock, "registry_probe")
            registry._token_lock = self.watch(registry._token_lock, "registry_tokens")

        for cls, field, label in (
            (DatabaseCredentialStore, "_gate", "integration_credentials"),
            (ProviderVault, "_gate", "provider_vault"),
            (AvailabilityMonitor, "_lock", "availability"),
        ):
            original = cls.__init__

            def initialize(
                instance, *args, _original=original, _field=field, _label=label, **kwargs
            ):
                _original(instance, *args, **kwargs)
                setattr(instance, _field, self.watch(getattr(instance, _field), _label))

            stack.enter_context(patch.object(cls, "__init__", initialize))

        for name, original in tuple(SQLiteStore.__dict__.items()):
            if inspect.isfunction(original) and name != "__init__":

                def guarded_store(*args, _original=original, **kwargs):
                    _database_call("SQLiteStore." + _original.__name__)
                    return _original(*args, **kwargs)

                stack.enter_context(patch.object(SQLiteStore, name, guarded_store))

        stack.enter_context(patch.object(sqlite3, "connect", connect))
        stack.enter_context(patch.object(SQLiteStore, "__init__", store_init))
        stack.enter_context(patch.object(SQLiteStore, "open_existing", classmethod(open_existing)))
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
            (ssl.SSLSocket, "send", "send"),
            (ssl.SSLSocket, "sendall", "send"),
            (ssl.SSLSocket, "write", "send"),
            (ssl.SSLSocket, "recv", "recv"),
            (ssl.SSLSocket, "recv_into", "recv"),
            (ssl.SSLSocket, "read", "recv"),
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
    global _ACTIVE
    with ExitStack() as stack:
        auditor = LockAuditor()
        auditor.install(stack)
        previous, _ACTIVE = _ACTIVE, auditor
        try:
            yield auditor
        finally:
            _ACTIVE = previous
