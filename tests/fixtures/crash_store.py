"""Disposable process-kill fixture. Checkpoints never enter runtime source code."""

from pathlib import Path
import sys
from unittest.mock import patch

from ezllmrouter_server.instance_lock import InstanceBusy
from ezllmrouter_server.provider_vault import ProviderVault
from ezllmrouter_server.store import SQLiteStore
from ezllmrouter_server import private_files

SECRET = "synthetic-crash-fixture-secret-000001"
NEXT_SECRET = "synthetic-crash-fixture-secret-000002"


def checkpoint():
    print("CHECKPOINT", flush=True)
    # The parent kills this process after receiving the marker. No timing race.
    sys.stdin.read(1)
    raise RuntimeError("crash fixture was unexpectedly resumed")


def sample():
    return {
        "submission_id": "submission.crash",
        "attempt_id": "attempt.crash",
        "principal_id": "svc.crash",
        "task_id": "task.crash",
        "work_key": {
            "principal_id": "svc.crash",
            "task_id": "task.crash",
            "step_id": "step.crash",
            "step_revision": 1,
            "execution_generation": "gen.crash",
        },
        "work_digest": "sha256:" + "1" * 64,
        "submission_state": "admitted",
        "dispatch_state": "prepared",
        "status_revision": 1,
        "candidate_access": "not_yet_available",
    }


def database_case(root, phase, point):
    store = SQLiteStore(root / "store.sqlite")
    record = sample()
    intent = {
        "plan_id": "plan.crash",
        "attempt_id": record["attempt_id"],
        "work_digest": record["work_digest"],
    }
    if phase != "create":
        store.create(record)
    if phase in ("guard", "usage"):
        store.intent(record["submission_id"], record["attempt_id"], intent)
    if phase == "usage":
        store.guard_commit(record["submission_id"], record["attempt_id"], intent)
    if phase == "hold":
        checkpoint()

    def trace(sql):
        if (point == "before_begin" and sql == "BEGIN IMMEDIATE") or (
            point == "before_commit" and sql == "COMMIT"
        ):
            checkpoint()

    store.db.set_trace_callback(trace)
    if phase == "create":
        store.create(record)
    elif phase == "intent":
        store.intent(record["submission_id"], record["attempt_id"], intent)
    elif phase == "guard":
        store.guard_commit(record["submission_id"], record["attempt_id"], intent)
    elif phase == "usage":
        store.update(
            record["submission_id"],
            {"submission_state": "completed", "dispatch_state": "response_observed"},
            usage={
                "attempt_id": record["attempt_id"],
                "recorded_at": "2030-01-01T00:00:00Z",
                "cost": {
                    "status": "calculated",
                    "currency": "USD",
                    "amount_decimal": "0.125000001",
                },
            },
        )
    else:
        raise ValueError("unknown database crash phase")
    if point == "after_commit":
        checkpoint()
    raise RuntimeError("checkpoint was not reached")


def vault_case(root, phase, point):
    vault = ProviderVault(root / "vault")
    vault.seal("conn.crash", 1, SECRET)
    target = vault._path("conn.crash", 2) if phase == "seal" else vault.key_path
    operation = "replace"
    publish = getattr(private_files.os, operation)

    def interrupted(source, destination):
        selected = Path(destination) == target
        if selected and point == "before_publish":
            checkpoint()
        result = publish(source, destination)
        if selected and point == "after_publish":
            checkpoint()
        return result

    with patch.object(private_files.os, operation, interrupted):
        if phase == "seal":
            vault.seal("conn.crash", 2, NEXT_SECRET, committed_version=1)
        else:
            vault.rotate_encryption_key(["conn.crash"])
    if point == "after_complete":
        checkpoint()
    raise RuntimeError("vault checkpoint was not reached")


def main():
    root, phase, point = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if phase == "probe":
        try:
            store = SQLiteStore(root / "store.sqlite")
        except InstanceBusy:
            print("INSTANCE_IN_USE")
            return 73
        store.close()
        return 0
    if phase.startswith("migration.") or phase in ("backup", "wal"):
        from tests.fixtures import crash_maintenance

        if phase.startswith("migration."):
            crash_maintenance.migration_case(root, int(phase.split(".")[1]), point, checkpoint)
        elif phase == "backup":
            crash_maintenance.backup_case(root, point, checkpoint)
        else:
            crash_maintenance.wal_case(root, point, checkpoint)
        return 0
    if phase in ("seal", "rotate"):
        vault_case(root, phase, point)
    else:
        database_case(root, phase, point)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
