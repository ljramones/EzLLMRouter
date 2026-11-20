"""Read-only v3 restart and backup-restore check from a retained installed run.

Use the installed 0.2.4 consumer interpreter. Source evidence is never opened
for writes; only one-use ignored clones are started as local HTTP services.
"""

import csv
import hashlib
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
SERVER_VERSION = version("mach33-ezllmrouter-server")
CLIENT_VERSION = version("cognitivedynamics-ezllmrouter-client")
if (SERVER_VERSION, CLIENT_VERSION) != ("0.2.4", "0.2.4"):
    raise SystemExit("installed v3 candidate versions do not match 0.2.4")
if RUN.exists() or not sys.argv[1].startswith("persistence-v3-"):
    raise SystemExit("new one-use persistence-v3 run ID required")
RUN.mkdir(parents=True)
DATASET = "dataset.synthetic.speech.installed"
EXPECTED_REPORT = json.loads((SOURCE / "report.json").read_text())
EXPECTED_EXPORT = json.loads((SOURCE / "export.json").read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def backup(source, destination):
    with sqlite3.connect("file:" + str(source) + "?mode=ro", uri=True) as src:
        with sqlite3.connect(destination) as dst:
            src.backup(dst)


class Authority:
    def __init__(self):
        self.gate = threading.RLock()
        self.epoch = 0


def inspect(database):
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
    admin_token = registry.issue_local_operator_token("owner.local")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    http = serve("127.0.0.1", port, type("Runtime", (), {"registry": registry})())
    thread = threading.Thread(target=http.serve_forever)
    thread.start()
    try:
        base = f"http://127.0.0.1:{port}/"
        with IntegrationClient(base, admin_token, version="3") as admin:
            report = admin.report(DATASET)
            exported = admin.export_dataset(DATASET)
        with IntegrationClient(
            base, (SOURCE / "ingest.token").read_text().strip(), version="3"
        ) as ingest:
            receipt = ingest.recover_receipt(DATASET, "event.synthetic.python.usage2")
        connection = http_client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request(
            "GET",
            "/integration/v3/reports/usage?dataset_id=" + DATASET + "&export=csv",
            headers={
                "Authorization": "Bearer " + admin_token,
                "EzLLMRouter-Integration-Version": "3",
            },
        )
        response = connection.getresponse()
        raw_csv = response.read()
        connection.close()
        assert response.status == 200
        rows = list(csv.DictReader(io.StringIO(raw_csv.decode("utf-8"))))
        assert report == EXPECTED_REPORT
        assert exported == EXPECTED_EXPORT
        assert len(rows) == 11 and {r["attempt_id"] for r in rows} == {
            r["attempt_id"] for r in report["attempts"]
        }
        assert report["attempt_count"] == report["unknown_cost_attempts"] == 11
        assert report["known_total_by_currency"] == {}
        assert len(exported["eligibility_reads"]) == 11
        assert len(exported["eligibility_assessments"]) == 11
        assert receipt["event_id"] == "event.synthetic.python.usage2"
        raw_export_bytes = len(json.dumps(exported, separators=(",", ":")).encode("utf-8"))
        assert raw_export_bytes < 16 * 1024 * 1024
        return {
            "attempts": 11,
            "events": len(exported["events"]),
            "eligibility_reads": len(exported["eligibility_reads"]),
            "eligibility_assessments": len(exported["eligibility_assessments"]),
            "csv_rows": len(rows),
            "export_json_bytes": raw_export_bytes,
            "receipt_event_id": receipt["event_id"],
        }
    finally:
        http.shutdown()
        http.server_close()
        thread.join(timeout=3)
        store.close()


source_hash = digest(SOURCE / "service.sqlite")
clone = RUN / "restart-clone.sqlite"
backup(SOURCE / "service.sqlite", clone)
first = inspect(clone)
second = inspect(clone)
restored = RUN / "restored-clone.sqlite"
backup(clone, restored)
third = inspect(restored)
assert first == second == third
assert digest(SOURCE / "service.sqlite") == source_hash
result = {
    "status": "PASS",
    "run_id": sys.argv[1],
    "source_run": SOURCE.name,
    "installed_server_version": SERVER_VERSION,
    "installed_client_version": CLIENT_VERSION,
    "source_db_sha256_before_after": source_hash,
    "first_read": first,
    "restart_read": second,
    "backup_restore_read": third,
    "new_attempts": 0,
    "real_provider_calls": 0,
}
(RUN / "result.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
print(json.dumps(result, sort_keys=True))
