"""Per-server operator state, execution and background-job lifecycle."""

from __future__ import annotations

import threading
import time
import uuid
from _thread import LockType
from collections.abc import Callable, Mapping, Set
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, TypedDict

from ..identity import DEFAULT_IDENTITY
from ..external_identity import IdentityLookup
from ..integration_accounting import ExternalAccounting
from ..local_connectors import LocalConnectors
from ..scripted_demo import ScriptedDemo
from ..observability import log_failure
from ..operator_demo import ProviderValidationRunner
from ..operator_projection import OperatorProjection
from ..registry import Registry
from ..store import SQLiteStore
from ..user_management import LoginThrottle, UserManager

type JSONValue = str | int | float | bool | None | list[JSONValue] | dict[str, JSONValue]


class OperatorSession(TypedDict):
    csrf: str
    principal_id: str
    role: str
    named_login: bool
    username: str | None
    display_name: str | None
    user_auth_version: int | None
    must_change_password: bool
    wire_token: str | None
    expires: float


class LaunchResult(TypedDict):
    submission_ids: list[str]
    caller_lookups: int


class DemoRunner(Protocol):
    def run(self, kind: str, on_handle: Callable[[str], None]) -> LaunchResult: ...


@dataclass
class OperatorApplication:
    accounts: UserManager | None
    allowed_hosts: Set[str]
    allowed_origins: Set[str]
    build: Mapping[str, JSONValue]
    fixture: Mapping[str, JSONValue]
    integration_only: bool
    jobs: ThreadPoolExecutor
    local_connectors: LocalConnectors | None
    login_throttle: LoginThrottle
    scripted_demo: ScriptedDemo | None
    password: str
    projection: OperatorProjection
    provider_validation: ProviderValidationRunner | None
    registry: Registry | None
    root: Path
    runner: DemoRunner | None
    sender_status: Callable[[], Mapping[str, JSONValue]]
    session_lock: LockType
    sessions: dict[str, OperatorSession]
    successor_store: SQLiteStore | None
    worker_probe: Callable[[], Mapping[str, JSONValue]]
    identity_lookup: IdentityLookup | None = None
    secure_cookies: bool = False
    _closing: bool = field(default=False, init=False)
    scheduler_stop: threading.Event = field(default_factory=threading.Event, init=False)
    maintenance_stop: threading.Event = field(default_factory=threading.Event, init=False)
    scheduler_thread: threading.Thread | None = field(default=None, init=False)
    maintenance_thread: threading.Thread | None = field(default=None, init=False)

    @property
    def owner_id(self) -> str:
        return self.registry.identity.owner_id if self.registry else DEFAULT_IDENTITY.owner_id

    @property
    def task_class(self) -> str:
        return self.registry.identity.task_class if self.registry else DEFAULT_IDENTITY.task_class

    def execute(self, operation_id: str, kind: str) -> None:
        try:
            if self.runner is None:
                raise RuntimeError("demo runner unavailable")
            result = self.runner.run(
                kind, lambda sid: self.projection.record_launch_submission(operation_id, sid)
            )
            self.projection.finish_launch(
                operation_id, "completed", result["submission_ids"], result["caller_lookups"]
            )
        except Exception as exc:
            log_failure("operator_http.demo.execute.failed")
            prior = self.projection.launch(operation_id)
            ids = prior["submission_ids"] if prior else []
            code = getattr(exc, "code", None)
            if code is None and str(exc) in ("DEMO_OUTCOME_UNKNOWN", "DEMO_NO_CANDIDATE"):
                code = str(exc)
            self.projection.finish_launch(
                operation_id,
                "outcome_unknown"
                if code in ("DEMO_OUTCOME_UNKNOWN", "TRANSPORT_OUTCOME_UNKNOWN")
                else "failed",
                ids,
                error_code=code or "DEMO_FAILED",
            )

    def scheduled_checks(self) -> None:
        registry = self.registry
        if registry is None:
            return
        due: dict[str, tuple[tuple[int, str], float]] = {}
        while not self.scheduler_stop.wait(2):
            try:
                connections = registry.list_connections()
            except Exception:
                log_failure("operator_http.scheduler.list_connections.failed")
                continue
            active = set()
            for connection in connections:
                if not connection.get("checks_scheduled") or connection["status"] not in (
                    "draft",
                    "active",
                ):
                    continue
                key = connection["connection_id"]
                active.add(key)
                now = time.monotonic()
                interval = connection["check_interval_seconds"]
                operation = connection["scheduled_operation"]
                if interval is None or operation is None:
                    continue
                state = (connection["revision"], operation)
                if key not in due or due[key][0] != state:
                    due[key] = (state, now + interval)
                    continue
                if now < due[key][1]:
                    continue
                due[key] = (state, now + interval)
                try:
                    registry.probe_connection(
                        self.owner_id,
                        key,
                        connection["revision"],
                        "probe.scheduled." + uuid.uuid4().hex,
                        operation,
                    )
                except Exception:
                    log_failure("operator_http.scheduler.probe_connection.failed")
            for key in set(due) - active:
                due.pop(key, None)

    def start(self, maintenance: Callable[[ExternalAccounting, threading.Event], None]) -> None:
        self._closing = False
        self.scheduler_stop = threading.Event()
        self.maintenance_stop = threading.Event()
        self.scheduler_thread = None
        self.maintenance_thread = None
        if self.registry is not None:
            self.scheduler_thread = threading.Thread(
                target=self.scheduled_checks, daemon=True, name="ezllmrouter-provider-checks"
            )
            self.scheduler_thread.start()
            self.maintenance_thread = threading.Thread(
                target=maintenance,
                args=(self.registry.integration, self.maintenance_stop),
                daemon=True,
                name="ezllmrouter-accounting-maintenance",
            )
            self.maintenance_thread.start()

    def close(self) -> None:
        with self.session_lock:
            self._closing = True
        with ExitStack() as cleanup:
            if self.local_connectors:
                cleanup.callback(self.local_connectors.close)
            token_cleanup = ExitStack()
            cleanup.callback(token_cleanup.close)
            cleanup.callback(self.jobs.shutdown, wait=True, cancel_futures=False)
            self.scheduler_stop.set()
            self.maintenance_stop.set()
            if self.maintenance_thread is not None and self.maintenance_thread.ident is not None:
                self.maintenance_thread.join()
            if self.scheduler_thread is not None and self.scheduler_thread.ident is not None:
                self.scheduler_thread.join()
            with self.session_lock:
                discarded = tuple(self.sessions.values())
                self.sessions.clear()
            if self.registry:
                for item in discarded:
                    wire_token = item["wire_token"]
                    if wire_token:
                        token_cleanup.callback(
                            self.registry.revoke_local_operator_token, wire_token
                        )
