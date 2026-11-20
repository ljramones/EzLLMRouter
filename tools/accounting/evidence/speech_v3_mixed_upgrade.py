"""Installed 0.2.4 read/append/restore on retained synthetic 0.2.2 history.

The source database is opened read-only for a SQLite backup. The v3 attempt
is an observation about fictional external activity, not a model invocation.
"""

from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import sys
import threading

from ezllmrouter_client.integration import IntegrationClient
from ezllmrouter_server.registry import Registry
from ezllmrouter_server.store import SQLiteStore
from ezllmrouter_server.web import serve

ROOT = Path(__file__).resolve().parents[3]
SOURCE = Path(
    "/Users/larrymitchell/Mach33/EzLLMRouter-artifacts/integration-correction03-20261028-01/candidate1/corrected"
)
RUN = ROOT / "deploy/local/.state/integration-v3-runs" / sys.argv[1]
DATASET = "dataset.c03.historical"
ACCOUNT = "account.synthetic.v3.mixed"
if RUN.exists() or not sys.argv[1].startswith("mixed-v3-"):
    raise SystemExit("new one-use mixed-v3 run ID required")
RUN.mkdir(parents=True)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def backup(source, destination):
    with sqlite3.connect("file:" + str(source) + "?mode=ro", uri=True) as original:
        with sqlite3.connect(destination) as copy:
            original.backup(copy)


def historical_bytes(path):
    with sqlite3.connect("file:" + str(path) + "?mode=ro", uri=True) as db:
        events = list(
            db.execute(
                "SELECT event_id,digest,record FROM integration_events "
                "WHERE dataset_id=? AND event_id IN (?,?,?,?) ORDER BY event_id",
                (
                    DATASET,
                    "event.old.link",
                    "event.old.start",
                    "event.old.usage",
                    "event.old.before",
                ),
            )
        )
        attempts = list(
            db.execute(
                "SELECT attempt_id,record FROM integration_attempts "
                "WHERE dataset_id=? AND attempt_id IN (?,?) ORDER BY attempt_id",
                (DATASET, "attempt.old", "attempt.before"),
            )
        )
    assert len(events) == 4 and len(attempts) == 2
    return hashlib.sha256(
        json.dumps(
            {"events": events, "attempts": attempts}, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


class Authority:
    def __init__(self):
        self.gate = threading.RLock()
        self.epoch = 0


def open_service(database):
    store = SQLiteStore(database)
    registry = Registry(
        store,
        Authority(),
        legacy_destination={
            "configuration_ref": "cfg.synthetic.v3",
            "service": "litellm.dev04",
            "endpoint": "127.0.0.1",
            "model": "model.synthetic",
            "model_version": "v1",
            "processing_region": "local",
        },
        legacy_token="synthetic-legacy-service-token-000000000000",
        legacy_trusted={"principal_id": "svc.synthetic", "charging_owner_id": "team.synthetic"},
    )
    token = registry.issue_local_operator_token("owner.local")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    http = serve("127.0.0.1", port, type("Runtime", (), {"registry": registry})())
    thread = threading.Thread(target=http.serve_forever)
    thread.start()
    return store, http, thread, f"http://127.0.0.1:{port}/", token


def close_service(service):
    store, http, thread, _, _ = service
    http.shutdown()
    http.server_close()
    thread.join(timeout=3)
    store.close()


def at(seconds):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


source_db = SOURCE / "accounting.sqlite"
source_hash = digest(source_db)
expected_old_hash = json.loads((SOURCE.parent / "evidence/old-seed-summary.json").read_text())[
    "old_history_sha256"
]
assert historical_bytes(source_db) == expected_old_hash
database = RUN / "accounting.sqlite"
backup(source_db, database)
service = open_service(database)
try:
    _, _, _, base, admin_token = service
    ingest_token = (SOURCE / "secrets/ingest.token").read_text().strip()
    with (
        IntegrationClient(base, admin_token, version="2") as old_admin,
        IntegrationClient(base, admin_token, version="3") as admin,
        IntegrationClient(base, ingest_token, version="3") as ingest,
    ):
        before = old_admin.report(DATASET)
        assert before["attempt_count"] == 3
        assert before["known_total_by_currency"] == {"USD": "0.010000000"}
        assert old_admin.report("dataset.c03.mixed.linkfirst")["attempt_count"] == 1
        assert old_admin.report("dataset.c03.mixed.startfirst")["attempt_count"] == 2
        assert old_admin.report("dataset.c03.pure")["attempt_count"] == 2
        old_receipt = old_admin.export_dataset(DATASET)
        admin.register_account(
            {
                "account_id": ACCOUNT,
                "dataset_id": DATASET,
                "provider_id": "provider.synthetic.xai",
                "credential_ref": "credential.synthetic.mixed",
                "allowed_models": [],
                "allowed_operations": ["speech_output"],
                "state": "usable",
            }
        )
        selector = {
            "operation_family": "speech_output",
            "capability": "synthesis",
            "selection_kind": "provider_selected",
        }
        eligibility = ingest.operation_eligibility(DATASET, ACCOUNT, selector)
        assert eligibility["usable"]
        attempt = "attempt.synthetic.mixed.v3"
        stamp = at(0)
        action = {
            "selected_account_id": ACCOUNT,
            **selector,
            "policy_version": "policy.synthetic.mixed",
            "eligibility_evidence": {
                "status": "verified",
                "eligibility_id": eligibility["eligibility_id"],
            },
        }
        snapshot = {
            "integration_version": "3",
            "dataset_id": DATASET,
            "attempt_id": attempt,
            "schema_version": "1",
            "producer_version": "test.installed.mixed.v3",
            "provenance": "synthetic",
            "source_at": stamp,
            "available_at": stamp,
            "classification": "low",
            "retention_until": at(86400),
        }
        ingest.submit_snapshot(
            {
                **snapshot,
                "snapshot_id": "feature.synthetic.mixed.v3",
                "snapshot_kind": "feature",
                "status": "not_collected",
            }
        )
        ingest.submit_snapshot(
            {
                **snapshot,
                "snapshot_id": "decision.synthetic.mixed.v3",
                "snapshot_kind": "decision",
                "status": "captured",
                "selected_action": action,
            }
        )
        event = {
            "integration_version": "3",
            "dataset_id": DATASET,
            "attempt_id": attempt,
            "occurred_at": stamp,
        }
        ingest.submit_observation(
            {
                **event,
                "event_id": "event.synthetic.mixed.v3.start",
                "kind": "attempt_started",
                "started_at": stamp,
                "task_id": "task.synthetic.mixed.v3",
                "step_id": "step.synthetic.mixed.v3",
                "run_id": "run.synthetic.mixed.v3",
                "root_run_id": "run.synthetic.mixed.v3",
                "actor_kind": "service",
                "actor_id": "service.synthetic.mixed",
                "provider_account_id": ACCOUNT,
                "context_ref": "feature.synthetic.mixed.v3",
                "operation_family_version": "1",
                "operation_family": "speech_output",
                "model_identity_state": "unknown",
                "logical_operation_id": "operation.synthetic.mixed.v3",
                "attempt_role": "initial",
            }
        )
        ingest.submit_observation(
            {
                **event,
                "event_id": "event.synthetic.mixed.v3.decision",
                "kind": "decision",
                "decision_ref": "decision.synthetic.mixed.v3",
                **action,
            }
        )
        ingest.submit_observation(
            {
                **event,
                "event_id": "event.synthetic.mixed.v3.result",
                "kind": "result",
                "result_state": "completed",
            }
        )
        usage = {
            **event,
            "event_id": "event.synthetic.mixed.v3.usage.1",
            "kind": "usage",
            "usage_revision": 1,
            "usage_state": "known",
            "cost_state": "unknown",
            "native_units": [{"unit": "characters", "quantity_decimal": "23"}],
            "usage_provenance": "provider_reported",
        }
        accepted = ingest.submit_observation(usage)
        assert ingest.submit_observation(usage) == accepted
        assert ingest.recover_receipt(DATASET, usage["event_id"]) == accepted
        assert historical_bytes(database) == expected_old_hash
        after = admin.report(DATASET)
        assert after["attempt_count"] == 4
        assert after["unknown_cost_attempts"] == before["unknown_cost_attempts"] + 1
        assert after["known_total_by_currency"] == before["known_total_by_currency"]
        assert {
            row["attempt_id"]: row for row in after["attempts"] if row["attempt_id"] != attempt
        } == {row["attempt_id"]: row for row in before["attempts"]}
        exported = admin.export_dataset(DATASET)
        assert len(exported["attempts"]) == 4
        assert {row["event_id"] for row in old_receipt["events"]} <= {
            row["event_id"] for row in exported["events"]
        }
finally:
    close_service(service)

service = open_service(database)
try:
    _, _, _, base, admin_token = service
    with IntegrationClient(base, admin_token, version="3") as admin:
        assert admin.report(DATASET) == after
        assert admin.export_dataset(DATASET) == exported
finally:
    close_service(service)

restored_db = RUN / "restored.sqlite"
backup(database, restored_db)
service = open_service(restored_db)
try:
    _, _, _, base, admin_token = service
    with IntegrationClient(base, admin_token, version="3") as admin:
        assert admin.report(DATASET) == after
        assert admin.export_dataset(DATASET) == exported
finally:
    close_service(service)

assert digest(source_db) == source_hash
assert historical_bytes(database) == historical_bytes(restored_db) == expected_old_hash
(RUN / "report.json").write_text(json.dumps(after, sort_keys=True, indent=2) + "\n")
(RUN / "export.json").write_text(json.dumps(exported, sort_keys=True, indent=2) + "\n")
summary = {
    "status": "PASS",
    "run_id": sys.argv[1],
    "source_db_sha256_before_after": source_hash,
    "historical_record_sha256": expected_old_hash,
    "old_attempts": 3,
    "new_v3_attempts": 1,
    "mixed_dataset_attempts": 4,
    "known_usd": "0.010000000",
    "unknown_cost_attempts": 3,
    "restart_and_restore_match": True,
    "provider_calls": 0,
}
(RUN / "summary.json").write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n")
print(json.dumps(summary, sort_keys=True))
