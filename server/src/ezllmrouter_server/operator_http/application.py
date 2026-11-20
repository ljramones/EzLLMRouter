"""Per-server operator state, execution and background-job lifecycle."""

from dataclasses import dataclass
from contextlib import ExitStack
from .common import threading, time, uuid, log_failure


@dataclass
class OperatorApplication:
    accounts: object
    allowed_hosts: object
    allowed_origins: object
    build: object
    fixture: object
    integration_only: object
    jobs: object
    local_connectors: object
    login_throttle: object
    mach33_demo: object
    password: object
    projection: object
    provider_validation: object
    registry: object
    root: object
    runner: object
    sender_status: object
    session_lock: object
    sessions: object
    successor_store: object
    worker_probe: object

    def execute(self, operation_id, kind):
        try:
            result = self.runner.run(
                kind, lambda sid: self.projection.record_launch_submission(operation_id, sid)
            )
            self.projection.finish_launch(
                operation_id, "completed", result["submission_ids"], result["caller_lookups"]
            )
        except Exception as exc:
            log_failure("operator_web.serve.execute.failed")
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

    def scheduled_checks(self):
        due = {}
        while not self.scheduler_stop.wait(2):
            try:
                connections = self.registry.list_connections() if self.registry else []
            except Exception:
                log_failure("operator_web.serve.scheduled_checks.failed")
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
                state = (connection["revision"], connection["scheduled_operation"])
                if key not in due or due[key][0] != state:
                    due[key] = (state, now + interval)
                    continue
                if now < due[key][1]:
                    continue
                due[key] = (state, now + interval)
                try:
                    self.registry.probe_connection(
                        "owner.local",
                        key,
                        connection["revision"],
                        "probe.scheduled." + uuid.uuid4().hex,
                        connection["scheduled_operation"],
                    )
                except Exception:
                    log_failure("operator_web.serve.scheduled_checks.failed")
                    pass
            for key in set(due) - active:
                due.pop(key, None)

    def start(self, maintenance):
        self._closing = False
        self.scheduler_stop = threading.Event()
        self.maintenance_stop = threading.Event()
        self.scheduler_thread = None
        self.maintenance_thread = None
        self.scheduler_thread = threading.Thread(
            target=self.scheduled_checks, daemon=True, name="ezllmrouter-provider-checks"
        )
        self.scheduler_thread.start()
        if self.registry is not None:
            self.maintenance_thread = threading.Thread(
                target=maintenance,
                args=(self.registry.integration, self.maintenance_stop),
                daemon=True,
                name="ezllmrouter-accounting-maintenance",
            )
            self.maintenance_thread.start()

    def close(self):
        with self.session_lock:
            self._closing = True
        with ExitStack() as cleanup:
            if self.local_connectors:
                cleanup.callback(self.local_connectors.close)
            token_cleanup = ExitStack()
            cleanup.callback(token_cleanup.close)
            cleanup.callback(self.jobs.shutdown, wait=True, cancel_futures=False)
            if hasattr(self, "scheduler_stop"):
                self.scheduler_stop.set()
                self.maintenance_stop.set()
                if (
                    self.maintenance_thread is not None
                    and self.maintenance_thread.ident is not None
                ):
                    self.maintenance_thread.join()
                if self.scheduler_thread is not None and self.scheduler_thread.ident is not None:
                    self.scheduler_thread.join()
            with self.session_lock:
                discarded = tuple(self.sessions.values())
                self.sessions.clear()
            if self.registry:
                for item in discarded:
                    if item.get("wire_token"):
                        token_cleanup.callback(
                            self.registry.revoke_local_operator_token, item["wire_token"]
                        )
