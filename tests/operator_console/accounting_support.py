"""Isolated external observations through registry, normal HTTP and durable SQLite."""

import http.client
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]

from ezllmrouter_server.registry import Registry
from ezllmrouter_server.store import SQLiteStore
from ezllmrouter_server.web import serve

EXAMPLES = json.loads(
    (ROOT / "tests/fixtures/contracts/integration-readiness-v1/examples.json").read_text()
)
DEST = {
    "configuration_ref": "cfg.demo",
    "service": "litellm.dev04",
    "endpoint": "127.0.0.1",
    "model": "model.demo",
    "model_version": "v1",
    "processing_region": "local",
}
TRUSTED = {"principal_id": "svc.demo", "charging_owner_id": "team.demo"}


class Authority:
    def __init__(self):
        self.gate = threading.RLock()
        self.epoch = 0


class AccountingHTTPFixture:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = SQLiteStore(Path(self.tmp.name) / "integration.sqlite")
        self.addCleanup(self.store.close)
        self.registry = Registry(
            self.store,
            Authority(),
            legacy_destination=DEST,
            legacy_token="synthetic-legacy-service-token-000000000000",
            legacy_trusted=TRUSTED,
        )
        self.registry.mutate(
            "owner.local",
            {
                "operation_id": "op.integration.principal",
                "action": "create_principal",
                "subject": "svc.integration",
                "expected_revision": 0,
                "data": {
                    "display_name": "Synthetic integration",
                    "kind": "service",
                    "owner": "owner.local",
                    "role": "ordinary",
                },
            },
        )
        _, self.ingest_token = self.registry.provision_credential(
            "owner.local", "svc.integration", 1, "op.integration.credential"
        )
        self.registry.mutate(
            "owner.local",
            {
                "operation_id": "op.integration.activate",
                "action": "principal_state",
                "subject": "svc.integration",
                "expected_revision": 2,
                "data": {"status": "active", "reason": "isolated test"},
            },
        )
        self.admin_token = self.registry.issue_local_operator_token("owner.local")
        self.port = 0
        self.http = serve("127.0.0.1", self.port, SimpleNamespace(registry=self.registry))
        self.port = self.http.server_port
        self.thread = threading.Thread(target=self.http.serve_forever)
        self.thread.start()
        self.addCleanup(self._stop)
        self.dataset = {**EXAMPLES["dataset"], "ingest_principal_id": "svc.integration"}
        self.account = EXAMPLES["account"]

    def _stop(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=3)

    def request(self, method, path, body=None, *, admin=False, token=None, version="1"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {
            "Authorization": "Bearer "
            + (token or (self.admin_token if admin else self.ingest_token)),
            "EzLLMRouter-Integration-Version": version,
        }
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body, separators=(",", ":"))
        try:
            conn.request(method, path, data, headers)
            response = conn.getresponse()
            raw = response.read()
            return response.status, (
                raw.decode()
                if response.getheader("Content-Type").startswith("text/csv")
                else json.loads(raw)
            )
        finally:
            conn.close()

    def create(self):
        self.assertEqual(
            self.request("POST", "/integration/v1/datasets", self.dataset, admin=True)[0], 201
        )
        self.assertEqual(
            self.request("POST", "/integration/v1/accounts", self.account, admin=True)[0], 201
        )

    def event(self, value):
        return self.request("POST", "/integration/v1/events", value)

    def correction02_fixture(self, suffix):
        did = "dataset.c02." + suffix
        dataset = {**self.dataset, "dataset_id": did}
        account = {**self.account, "dataset_id": did, "account_id": "account.c02." + suffix}
        api = lambda method, path, body=None, admin=False: self.request(
            method, "/integration/v2" + path, body, admin=admin, version="2"
        )
        self.assertEqual(api("POST", "/datasets", dataset, True)[0], 201)
        self.assertEqual(api("POST", "/accounts", account, True)[0], 201)
        start = {
            **EXAMPLES["events"][2],
            "integration_version": "2",
            "dataset_id": did,
            "event_id": "event.base",
            "attempt_id": "attempt.base",
            "started_at": "2099-01-01T00:00:10Z",
            "occurred_at": "2099-01-01T00:00:10Z",
            "run_id": "run.c02",
            "root_run_id": "run.c02",
            "task_id": "task.c02",
            "provider_account_id": account["account_id"],
            "context_ref": "feature.base",
            "operation_family_version": "1",
            "operation_family": "generation",
            "model_identity_state": "known",
            "logical_operation_id": "logical.c02",
            "attempt_role": "initial",
        }
        start.pop("parent_run_id")
        return api, did, account, start
