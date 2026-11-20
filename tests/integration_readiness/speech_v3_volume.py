"""Installed v3 512-attempt export envelope on a one-use retained-data clone.

Synthetic observations only. No provider client or worker is created.
"""

import csv
from datetime import datetime, timezone, timedelta
from http import client as http_client
from importlib.metadata import version
import io
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

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "deploy/local/.state/integration-v3-runs/speech-v3-20261029-12"
RUN = ROOT / "deploy/local/.state/integration-v3-runs" / sys.argv[1]
DATASET = "dataset.synthetic.speech.installed"
ACCOUNT = "account.synthetic.speech.volume"
TARGET = 512
if (version("mach33-ezllmrouter-server"), version("cognitivedynamics-ezllmrouter-client")) != (
    "0.2.4",
    "0.2.4",
):
    raise SystemExit("installed 0.2.4 service and client required")
if RUN.exists() or not sys.argv[1].startswith("volume-v3-"):
    raise SystemExit("new one-use volume-v3 run ID required")
RUN.mkdir(parents=True)


def backup(source, destination):
    with sqlite3.connect("file:" + str(source) + "?mode=ro", uri=True) as original:
        with sqlite3.connect(destination) as copy:
            original.backup(copy)


def at(seconds):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def read_all(service):
    _, _, _, base, token = service
    with IntegrationClient(base, token, version="3") as admin:
        report = admin.report(DATASET)
        exported = admin.export_dataset(DATASET)
    connection = http_client.HTTPConnection(base.split("://", 1)[1].rstrip("/"), timeout=30)
    connection.request(
        "GET",
        "/integration/v3/reports/usage?dataset_id=" + DATASET + "&export=csv",
        headers={"Authorization": "Bearer " + token, "EzLLMRouter-Integration-Version": "3"},
    )
    response = connection.getresponse()
    raw_csv = response.read()
    connection.close()
    assert response.status == 200
    csv_text = raw_csv.decode("utf-8")
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    ids = {row["attempt_id"] for row in rows}
    assert len(rows) == len(ids) == TARGET
    assert ids == {row["attempt_id"] for row in report["attempts"]}
    assert ids == {row["attempt_id"] for row in exported["attempts"]}
    assert report["attempt_count"] == report["unknown_cost_attempts"] == TARGET
    assert report["known_total_by_currency"] == {}
    assert all(row["cost_status"] == "unknown" and not row["amount_decimal"] for row in rows)
    assert len(exported["eligibility_reads"]) == len(exported["eligibility_assessments"]) == TARGET
    compact = json.dumps(exported, separators=(",", ":"), sort_keys=True).encode("utf-8")
    assert len(compact) < 16 * 1024 * 1024
    return report, exported, csv_text, len(compact)


database = RUN / "service.sqlite"
backup(SOURCE / "service.sqlite", database)
service = open_service(database)
try:
    _, _, _, base, admin_token = service
    with (
        IntegrationClient(base, admin_token, version="3") as admin,
        IntegrationClient(
            base, (SOURCE / "ingest.token").read_text().strip(), version="3"
        ) as ingest,
    ):
        original = admin.report(DATASET)
        assert original["attempt_count"] == 11
        admin.register_account(
            {
                "account_id": ACCOUNT,
                "dataset_id": DATASET,
                "provider_id": "provider.synthetic.xai",
                "credential_ref": "credential.synthetic.volume",
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
        for ordinal in range(TARGET - original["attempt_count"]):
            suffix = f"{ordinal + 1:04d}"
            attempt = "attempt.synthetic.volume." + suffix
            feature = "snapshot.synthetic.volume." + suffix + ".feature"
            decision_ref = "snapshot.synthetic.volume." + suffix + ".decision"
            observed = at(0)
            expiry = at(86400)
            eligible = ingest.operation_eligibility(DATASET, ACCOUNT, selector)
            assert eligible["usable"] and eligible["selection_kind"] == "provider_selected"
            action = {
                "selected_account_id": ACCOUNT,
                **selector,
                "policy_version": "policy.synthetic.volume",
                "eligibility_evidence": {
                    "status": "verified",
                    "eligibility_id": eligible["eligibility_id"],
                },
            }
            snapshot = {
                "integration_version": "3",
                "dataset_id": DATASET,
                "attempt_id": attempt,
                "schema_version": "1",
                "producer_version": "test.installed.volume.v3",
                "provenance": "synthetic",
                "source_at": observed,
                "available_at": observed,
                "classification": "low",
                "retention_until": expiry,
            }
            ingest.submit_snapshot(
                {
                    **snapshot,
                    "snapshot_id": feature,
                    "snapshot_kind": "feature",
                    "status": "not_collected",
                }
            )
            ingest.submit_snapshot(
                {
                    **snapshot,
                    "snapshot_id": decision_ref,
                    "snapshot_kind": "decision",
                    "status": "captured",
                    "selected_action": action,
                }
            )
            event = {
                "integration_version": "3",
                "dataset_id": DATASET,
                "attempt_id": attempt,
                "occurred_at": observed,
            }
            ingest.submit_observation(
                {
                    **event,
                    "event_id": "event.synthetic.volume." + suffix + ".start",
                    "kind": "attempt_started",
                    "started_at": observed,
                    "task_id": "task.synthetic.volume." + suffix,
                    "step_id": "step.synthetic.volume." + suffix,
                    "run_id": "run.synthetic.volume." + suffix,
                    "root_run_id": "run.synthetic.volume." + suffix,
                    "actor_kind": "service",
                    "actor_id": "service.synthetic.volume",
                    "provider_account_id": ACCOUNT,
                    "context_ref": feature,
                    "operation_family_version": "1",
                    "operation_family": "speech_output",
                    "model_identity_state": "unknown",
                    "logical_operation_id": "operation.synthetic.volume." + suffix,
                    "attempt_role": "initial",
                }
            )
            ingest.submit_observation(
                {
                    **event,
                    "event_id": "event.synthetic.volume." + suffix + ".decision",
                    "kind": "decision",
                    "decision_ref": decision_ref,
                    **action,
                }
            )
            ingest.submit_observation(
                {
                    **event,
                    "event_id": "event.synthetic.volume." + suffix + ".result",
                    "kind": "result",
                    "result_state": "completed",
                }
            )
            usage = {
                **event,
                "event_id": "event.synthetic.volume." + suffix + ".usage.1",
                "kind": "usage",
                "usage_revision": 1,
                "usage_state": "known",
                "cost_state": "unknown",
                "native_units": [
                    {"unit": "characters", "quantity_decimal": str(10 + ordinal % 17)}
                ],
                "usage_provenance": "provider_reported",
            }
            ingest.submit_observation(usage)
        receipt = ingest.recover_receipt(DATASET, usage["event_id"])
        assert receipt["event_id"] == usage["event_id"]
        assert ingest.submit_observation(usage)["event_id"] == usage["event_id"]
    first = read_all(service)
finally:
    close_service(service)

service = open_service(database)
try:
    restarted = read_all(service)
finally:
    close_service(service)
assert first == restarted

restored_database = RUN / "restored.sqlite"
backup(database, restored_database)
service = open_service(restored_database)
try:
    restored = read_all(service)
finally:
    close_service(service)
assert first == restored

report, exported, csv_text, size = first
(RUN / "report.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
(RUN / "export.json").write_text(json.dumps(exported, sort_keys=True, indent=2) + "\n")
(RUN / "report.csv").write_text(csv_text)
result = {
    "status": "PASS",
    "run_id": sys.argv[1],
    "source_run": SOURCE.name,
    "installed_server_version": version("mach33-ezllmrouter-server"),
    "installed_client_version": version("cognitivedynamics-ezllmrouter-client"),
    "attempts": TARGET,
    "new_synthetic_observations": TARGET - 11,
    "unknown_cost_attempts": TARGET,
    "known_total_by_currency": {},
    "csv_rows": TARGET,
    "export_json_bytes": size,
    "eligibility_reads": len(exported["eligibility_reads"]),
    "eligibility_assessments": len(exported["eligibility_assessments"]),
    "events": len(exported["events"]),
    "restart_and_restore_match": True,
    "provider_calls": 0,
}
(RUN / "summary.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
print(json.dumps(result, sort_keys=True))
