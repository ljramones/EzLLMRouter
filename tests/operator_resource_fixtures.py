"""Real operator identities and disposable resources with controlled metadata I/O."""

from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch

from ezllmrouter_server.integration_credentials import DatabaseCredentialStore
from ezllmrouter_server.local_connectors import discover
from tests.operator_console.test_authorization_matrix import AuthorizationFixture
from tests.operator_console.test_connector_availability import drain
from tests.operator_console.test_local_connectors import INVENTORY
from tests.operator_console.test_projection import record
from tests.operator_console.test_user_management import PASSWORD, ROOT
from tests.unit import test_correctness_cases as demo_cases

POLICY = json.loads((ROOT / "tests/fixtures/operator_resources.json").read_text())
EXAMPLES = json.loads(
    (ROOT / "tests/fixtures/contracts/integration-readiness-v2/examples.json").read_text()
)
SECRET = "operator-resource-fixture-key"


class ResourceFixture(AuthorizationFixture):
    def setUp(self):
        super().setUp()
        self.enterContext(
            patch(
                "ezllmrouter_server.integration_accounting._time",
                return_value="2026-11-22T00:00:00Z",
            )
        )
        self.application = self.server.application
        self.identities = dict(
            owner=self.admin,
            ordinary=self.ordinary,
            readonly=self.readonly,
            pending=self.password_change,
        )
        self.principals = {}
        for role, identity in self.identities.items():
            self.cookie, self.csrf = identity
            self.principals[role] = self.request("GET", "/operator/v1/session")[2]["principal_id"]
        other = self.create("resource.admin", "registry_admin")
        self.users.change_password(
            other["principal_id"],
            {
                "current_password": PASSWORD,
                "new_password": "Resource administrator replacement password",
            },
        )
        self.principals["other_admin"] = other["principal_id"]
        self.change(
            "edit_principal",
            other["principal_id"],
            {"display_name": "Separate dataset owner", "owner": other["principal_id"]},
        )
        self.login("resource.admin", "Resource administrator replacement password")
        self.identities["other_admin"] = self.cookie, self.csrf
        self.target = self.create("resource.target")["principal_id"]
        self.io, self.demo_calls, self.futures = [], [], []
        self._setup_connectors()
        self._setup_accounting()
        self._setup_registry()
        self._setup_records()
        self.cookie, self.csrf = self.identities["owner"]

    def change(self, action, subject, data, expected=None):
        if expected is None:
            expected = self.registry.principal(subject)["revision"]
        return self.registry.mutate(
            "owner.local",
            {
                "operation_id": f"op.resource.{action}.{subject}.{expected}",
                "action": action,
                "subject": subject,
                "expected_revision": expected,
                "data": data,
            },
        )

    def service(self, subject, owner):
        self.change(
            "create_principal",
            subject,
            {"display_name": subject, "kind": "service", "owner": owner},
            0,
        )
        _, token = self.registry.provision_credential(
            "owner.local", subject, 1, "op.resource.credential." + subject
        )
        self.change(
            "principal_state",
            subject,
            {"status": "active", "reason": "controlled resource fixture"},
        )
        return self.registry.credential_principal(token)

    def _setup_connectors(self):
        self.connectors = self.registry.local_connectors
        self.connectors.monitor.clock = lambda: 100

        def read(url, path, key, **_options):
            self.io.append(("local", path))
            return (
                deepcopy(INVENTORY) if path == "/api/tags" else {"models": [], "version": "0.12.0"}
            )

        self.connectors.discover_fn = lambda kind, url, key: discover(kind, url, key, read=read)
        self.connectors.availability_read = read
        connector = self.connectors.create(
            "owner.local",
            {
                "display_name": "Resource connector",
                "kind": "ollama",
                "base_url": "http://localhost:11434",
                "api_key": SECRET,
            },
        )
        self.connector = connector["connector_id"]
        self.connectors.discover(
            "owner.local", self.connector, {"expected_revision": connector["revision"]}
        )
        self.connectors.availability("owner.local", {"connector_ids": [self.connector]})
        self.connectors.nearby("owner.local", {})
        drain(self.connectors.monitor)

    def _setup_accounting(self):
        self.datasets, self.accounts, self.dataset_bodies, self.account_bodies = {}, {}, {}, {}
        for role in ("owner", "other_admin"):
            owner = self.principals[role]
            ingest = self.service("svc.resource." + role, owner)
            principal = self.registry.principal(owner)
            dataset = {
                **EXAMPLES["dataset"],
                "dataset_id": "dataset.resource." + role,
                "owner_id": owner,
                "ingest_principal_id": ingest["principal_id"],
            }
            account = {
                **EXAMPLES["account"],
                "dataset_id": dataset["dataset_id"],
                "account_id": "account.resource." + role,
                "allowed_operations": [],
            }
            self.registry.integration.create_dataset(principal, dataset, "3")
            self.registry.integration.create_account(principal, account, "3")
            event = {
                **EXAMPLES["events"][0],
                "integration_version": "3",
                "dataset_id": dataset["dataset_id"],
                "event_id": "event.resource." + role,
                "provider_account_id": account["account_id"],
            }
            self.registry.integration.append_event(ingest, event, "3")
            self.datasets[role], self.accounts[role] = dataset["dataset_id"], account["account_id"]
            self.dataset_bodies[role], self.account_bodies[role] = dataset, account

        def inventory(*_args, **_kwargs):
            self.io.append(("credential", "inventory"))
            return {
                "state": "observed",
                "reason": "controlled metadata",
                "models": ["model.synthetic"],
                "has_more": False,
            }

        self.credentials = DatabaseCredentialStore(
            self.registry,
            Path(self.tmp.name) / "resource.keys.json",
            discover=inventory,
            controlled=True,
        )
        self.registry.integration_credentials = self.credentials
        owner = self.registry.principal("owner.local")
        item = self.credentials.connect(owner, self.connect_body())
        self.binding = item["account_id"]
        item = self.credentials.save(owner, self.binding, self.selection(item))
        item = self.credentials.replace(
            owner,
            self.binding,
            {
                "dataset_id": self.datasets["owner"],
                "expected_revision": item["revision"],
                "api_key": SECRET,
            },
        )
        self.credentials.save(owner, self.binding, self.selection(item))

    def connect_body(self):
        return {
            "dataset_id": self.datasets["owner"],
            "provider": "xai",
            "api_key": SECRET,
            "friendly_name": "Resource fixture",
            "operation_id": "op.resource.connect",
        }

    def selection(self, item):
        return {
            "dataset_id": self.datasets["owner"],
            "expected_revision": item["revision"],
            "selected_models": ["model.synthetic"],
            "allowed_operations": [],
        }

    def _setup_registry(self):
        self.change(
            "set_grant",
            self.principals["ordinary"],
            {
                "configuration_ref": "cfg.demo",
                "status": "active",
                "purposes": ["execution"],
                "task_classes": ["class.demo"],
            },
            0,
        )
        self.change(
            "create_model",
            "cfg.resource.private",
            {
                "display_name": "Private resource model",
                "model": "model.resource.private",
                "model_version": "v1",
                "owner": "owner.local",
                "capabilities": ["text"],
                "purposes": ["execution"],
                "task_classes": ["class.demo"],
            },
            0,
        )
        self.registry.controlled_provider_proof = True
        self.change(
            "create_connection",
            "conn.resource",
            {
                "display_name": "Resource connection",
                "adapter_id": "vllm.openai-compatible.v1",
                "settings": {
                    "origin": "https://localhost:8766",
                    "location": "office_lab",
                    "site": "Fixture",
                },
                "owner": "owner.local",
            },
            0,
        )

    def _setup_records(self):
        for role in ("owner", "ordinary"):
            value = record(
                "submission.resource." + role, "attempt.resource." + role, "step.resource." + role
            )
            value["principal_id"] = self.principals[role]
            value["work_key"]["principal_id"] = self.principals[role]
            self.store.create(value)
        projection = self.application.projection
        projection.begin_launch("op.resource.launch", "text")
        projection.finish_launch("op.resource.launch", "completed", ["submission.resource.owner"])
        projection.begin_provider_validation(
            "op.resource.validation", "conn.resource", 1, "cfg.demo", 1, 16
        )
        projection.finish_provider_validation("op.resource.validation", "completed")
        demo = demo_cases.DemoCutoffAndGraphTests()
        demo.setUp()
        self.addCleanup(demo.doCleanups)
        demo.data["metadata"]["required_banner"] = (
            "DEMO — scripted activity and simulated USD; no real provider calls"
        )
        self.application.scripted_demo = demo.load()

        def execute(operation, kind):
            self.demo_calls.append(kind)
            projection.finish_launch(operation, "completed", [])

        self.application.execute = execute
        original = self.application.jobs.submit

        def submit(*args):
            future = original(*args)
            self.futures.append(future)
            return future

        self.enterContext(patch.object(self.application.jobs, "submit", side_effect=submit))

    def settle(self):
        for future in self.futures:
            future.result(timeout=5)
        drain(self.connectors.monitor)

    def footprint(self):
        self.settle()
        with self.connectors.monitor._lock:
            entries = len(self.connectors.monitor._entries)
        return (
            self.store.db.total_changes,
            self.registry.version(),
            len(self.io),
            len(self.demo_calls),
            len(self.futures),
            entries,
        )

    def request_for(self, row):
        path = row["path"].format(
            target=self.target,
            connector=self.connector,
            dataset=self.datasets["owner"],
            account=self.accounts["owner"],
            binding=self.binding,
            ordinary=self.principals["ordinary"],
        )
        case, body = row["case"], None
        if row["method"] != "GET":
            body = self.body_for(case)
        return path, body

    def body_for(self, case):
        if case.startswith("user_"):
            user = self.users.get("owner.local", self.target)
            body = {"expected_revision": user["revision"]}
            if case == "user_update":
                body.update(
                    {key: user[key] for key in ("username", "display_name", "role", "status")}
                )
                body["display_name"] = "Resource target edited"
            elif case == "user_reset":
                body["password"] = "Resource target replacement passphrase"
            return body
        if case.startswith("connector_"):
            item = self.connectors.get("owner.local", self.connector)
            body = {"expected_revision": item["revision"]}
            if case == "connector_update":
                body.update(
                    display_name="Resource connector edited",
                    kind="ollama",
                    base_url="http://localhost:11434",
                )
            elif case == "connector_models":
                body.update(selected_models=["llama3.2:latest"], enabled=True)
            elif case == "connector_check":
                body = {"connector_ids": [self.connector], "force": False}
            elif case == "connector_find":
                body = {"force": False}
            return body
        if case == "dataset_create":
            return deepcopy(self.dataset_bodies["owner"])
        if case == "account_create":
            return deepcopy(self.account_bodies["owner"])
        if case in ("account_state", "account_permissions"):
            item = self.registry.integration.accounts(
                self.registry.principal("owner.local"), self.datasets["owner"]
            )["items"]
            item = next(value for value in item if value["account_id"] == self.accounts["owner"])
            body = {"dataset_id": self.datasets["owner"], "expected_revision": item["revision"]}
            body.update(
                {"state": "disabled"}
                if case == "account_state"
                else {"allowed_models": ["model.synthetic"], "allowed_operations": ["speech_input"]}
            )
            return body
        if case == "credential_connect":
            return {**self.connect_body(), "operation_id": "op.resource.connect.fresh"}
        if case.startswith("credential_"):
            item = self.credentials._binding(self.binding)
            body = {"dataset_id": self.datasets["owner"], "expected_revision": item["revision"]}
            if case == "credential_save":
                return self.selection(item)
            if case == "credential_replace":
                body["api_key"] = SECRET
            elif case == "credential_retire":
                body.update(version=1, acknowledged_version=item["selected_version"])
            return body
        if case.startswith("demo_"):
            return {"operation_id": "op.resource." + case}
        raise AssertionError("unreviewed request body: " + case)
