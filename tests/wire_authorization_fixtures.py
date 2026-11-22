"""Disposable identities, owned records and controlled execution for wire tests."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ezllmrouter_server.integration_credentials import DatabaseCredentialStore
from ezllmrouter_server.web import serve
from ezllmrouter_server.wire_http.transport import WireApplication
from tests.operator_console.test_registry_core import RegistryCoordinatorTests, TOKEN
from tests.operator_console.test_user_management_web import MemoryServer
from tests.development_slice.test_retrieval_service_states import RecordedOutcomeExecutor, VECTORS
from tools.synthetic.successor_authority import SyntheticSuccessorAuthority
from tools.synthetic.successor_campaign import FiniteSuccessorCampaign
from tools.synthetic.successor_service import SuccessorService

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = {
    version: json.loads(
        (
            ROOT / f"tests/fixtures/contracts/integration-readiness-v{version}/examples.json"
        ).read_text()
    )
    for version in ("1", "2")
}
RESULT_CANARY = "wire-owned-result-canary"
FIXTURE_KEY = "wire-only-fixture-key"
ACTORS = ("work_owner", "owner", "ingest", "reader", "other", "foreign", "consumer", "evaluator")


class CountedExecutor(RecordedOutcomeExecutor):
    def __init__(self):
        self.calls = 0

    def execute(self, *args):
        self.calls += 1
        result = super().execute(*args)
        result["usage_component"] = {
            "component": "document_units",
            "presence": "known",
            "quantity": 3,
            "evidence": "reported",
            "source_ref": "receiver.wire-fixture",
        }
        return result


class WireFixture:
    def setUp(self):
        RegistryCoordinatorTests.setUp(self)
        self.enterContext(
            patch(
                "ezllmrouter_server.integration_accounting._time",
                return_value="2026-11-21T12:00:00Z",
            )
        )
        self.tokens = {
            "work_owner": TOKEN,
            "owner": self.registry.issue_local_operator_token("owner.local"),
        }
        self.principals = {"work_owner": "svc.demo", "owner": "owner.local"}
        for actor, kind, role, owner in (
            ("ingest", "service", "ordinary", "owner.local"),
            ("reader", "human", "read_only_operator", "owner.local"),
            ("other", "human", "ordinary", "owner.local"),
            ("foreign", "human", "registry_admin", "team.foreign"),
            ("consumer", "service", "ordinary", "owner.local"),
            ("evaluator", "service", "ordinary", "team.demo"),
            ("suspended", "service", "ordinary", "owner.local"),
            ("revoked", "service", "ordinary", "owner.local"),
        ):
            subject = (
                self.registry.identity.credential_consumer_id
                if actor == "consumer"
                else "principal.wire." + actor
            )
            self.change(
                "create_principal",
                subject,
                0,
                {"display_name": actor, "kind": kind, "role": role, "owner": owner},
            )
            _, token = self.registry.provision_credential(
                "owner.local", subject, 1, "op.wire.credential." + actor
            )
            self.change(
                "principal_state", subject, 2, {"status": "active", "reason": "wire fixture"}
            )
            self.tokens[actor], self.principals[actor] = token, subject
        self.change(
            "principal_state",
            self.principals["suspended"],
            3,
            {"status": "suspended", "reason": "wire fixture"},
        )
        self.registry.provision_credential(
            "owner.local", self.principals["revoked"], 3, "op.wire.rotate"
        )
        self._setup_accounting()
        self._setup_work()
        self._setup_attribution()
        with patch("ezllmrouter_server.web.BoundedHTTPServer", MemoryServer):
            self.wire = serve("127.0.0.1", 48760, self.coordinator)

    def change(self, action, subject, expected, data):
        return self.registry.mutate(
            "owner.local",
            {
                "operation_id": f"op.wire.{action}.{subject}.{expected}",
                "action": action,
                "subject": subject,
                "expected_revision": expected,
                "data": data,
            },
        )

    def mode(self, integration_only):
        self.wire.handler.keywords["application"] = WireApplication(
            self.coordinator, integration_only
        )

    def footprint(self):
        return (
            self.store.db.total_changes,
            self.registry.version(),
            len(self.adapter.sent),
            self.executor.calls,
        )

    def _setup_accounting(self):
        self.data = {}
        owner = self.registry.principal("owner.local")
        ingest = self.registry.credential_principal(self.tokens["ingest"])
        for version in ("1", "2", "3"):
            examples = EXAMPLES["1" if version == "1" else "2"]
            dataset = {
                **examples["dataset"],
                "dataset_id": "dataset.wire.v" + version,
                "ingest_principal_id": self.principals["ingest"],
            }
            account = {
                **examples["account"],
                "dataset_id": dataset["dataset_id"],
                "account_id": "account.wire.v" + version,
            }
            if version == "3":
                account["allowed_operations"] = []
            self.registry.integration.create_dataset(owner, dataset, version)
            self.registry.integration.create_account(owner, account, version)
            event = deepcopy(examples["events"][0])
            event.update(
                integration_version=version,
                dataset_id=dataset["dataset_id"],
                event_id="event.wire.v" + version,
            )
            if version != "1":
                event.update(
                    provider_account_id=account["account_id"],
                    context_ref="snapshot.wire.v" + version,
                )
            self.registry.integration.append_event(ingest, event, version)
            snapshot = None
            if version != "1":
                snapshot = {
                    **EXAMPLES["2"]["snapshots"][0],
                    "integration_version": version,
                    "dataset_id": dataset["dataset_id"],
                    "snapshot_id": "snapshot.wire.v" + version,
                    "attempt_id": event["attempt_id"],
                }
                self.registry.integration.append_snapshot(ingest, snapshot)
            self.data[version] = {
                "dataset": dataset,
                "account": account,
                "event": event,
                "snapshot": snapshot,
            }

        def discover(*_args, **_kwargs):
            return {
                "state": "observed",
                "reason": "controlled inventory",
                "models": ["model.synthetic"],
                "has_more": False,
            }

        self.credentials = DatabaseCredentialStore(
            self.registry,
            Path(self.tmp.name) / "wire.keys.json",
            discover=discover,
            controlled=True,
        )
        self.registry.integration_credentials = self.credentials
        pending = self.credentials.connect(
            owner,
            {
                "dataset_id": self.data["3"]["dataset"]["dataset_id"],
                "provider": "xai",
                "api_key": FIXTURE_KEY,
                "friendly_name": "Wire fixture",
                "operation_id": "op.wire.connect",
            },
        )
        self.credential_account = pending["account_id"]
        self.credentials.save(
            owner,
            pending["account_id"],
            {
                "dataset_id": self.data["3"]["dataset"]["dataset_id"],
                "expected_revision": pending["revision"],
                "selected_models": ["model.synthetic"],
                "allowed_operations": [],
            },
        )

    def _setup_work(self):
        from tests.operator_console.test_registry_core import REQUEST

        original = self.adapter.send

        def send(*args):
            result = original(*args)
            result["body"]["text"] = RESULT_CANARY
            return result

        self.adapter.send = send
        self.requests = {"0.2": deepcopy(REQUEST)}
        status, reply = self.coordinator.submit(
            self.requests["0.2"], self.coordinator.authenticate(TOKEN), 3000, credential=TOKEN
        )
        self.assertEqual(status, 200, reply)
        self.handles = {"0.2": reply["handle"]}
        example = next(row for row in VECTORS["examples"] if row["id"] == "DIRECT_DOCUMENT")
        context = deepcopy(example["trusted_context"])
        now = datetime.now(timezone.utc).replace(microsecond=0)
        stamp = lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ")
        context.update(
            authenticated_at=stamp(now - timedelta(minutes=1)),
            expires_at=stamp(now + timedelta(hours=1)),
        )
        trusted = self.coordinator.authenticate(TOKEN)
        context["identity"].update(
            {
                key: trusted[key]
                for key in ("principal_id", "charging_owner_id", "source_authority_id")
            }
        )
        self.coordinator.identity[TOKEN] = {
            **self.coordinator.identity[TOKEN],
            "identity_binding_id": context["identity"]["identity_binding_id"],
        }
        trusted = self.coordinator.authenticate(TOKEN)
        authority = SyntheticSuccessorAuthority(
            self.store, Ed25519PrivateKey.generate(), "key.wire-fixture", "v1"
        )
        authority.set_historical_access(
            context["identity"], read=True, write=True, resume=True, observed_at=stamp(now)
        )
        campaign = FiniteSuccessorCampaign(
            self.store,
            "campaign.wire-fixture",
            "budget.wire-fixture",
            financial_owner_id=trusted["charging_owner_id"],
        )
        campaign.start({}, [], max_attempts=20, ceiling_decimal="0.100000000")
        self.executor = CountedExecutor()
        successor = SuccessorService(
            self.store,
            {TOKEN: context},
            authority,
            self.executor,
            campaign,
            read_allowed=lambda _trusted, _record: True,
            usage_write_allowed=lambda _trusted, _record: True,
        )
        self.addCleanup(successor.close)
        self.coordinator.successor = successor
        request = deepcopy(example["request"])
        request["deadline"] = stamp(now + timedelta(minutes=30))
        request["work_selector"]["step_id"] = "step.wire.seed"
        self.requests["0.3"] = request
        status, reply = successor.submit(request, trusted, 5000, credential=TOKEN)
        self.assertEqual(status, 200, reply)
        self.handles["0.3"] = reply["handle"]

    def _setup_attribution(self):
        self.change(
            "register_agent",
            "agent.wire",
            0,
            {"display_name": "Wire fixture", "owner": "team.demo", "versions": ["v1"]},
        )
        self.change(
            "set_agent_permission",
            "permission.wire",
            0,
            {
                "caller_principal_id": "svc.demo",
                "agent_id": "agent.wire",
                "charging_owner_id": "team.demo",
                "task_classes": ["class.demo"],
                "status": "active",
            },
        )
        self.change(
            "set_outcome_authority",
            self.principals["evaluator"],
            0,
            {"status": "active", "task_classes": ["class.demo"]},
        )
        self.run_body = {
            "version": "1",
            "run_id": "run.wire.seed",
            "task_id": "task.demo",
            "task_class": "class.demo",
            "evaluation_ref": "rubric.wire",
            "mode": "autonomous_agent",
            "agent_id": "agent.wire",
            "agent_version": "v1",
        }
        self.registry.attribution.start_run(self.coordinator.authenticate(TOKEN), self.run_body)
        self.outcome = {
            "version": "1",
            "event_id": "event.wire.outcome",
            "run_id": "run.wire.seed",
            "kind": "task_outcome",
            "subject_revision": 1,
            "verdict": "accepted",
            "evaluator_version": "rubric.wire",
            "evidence_ref": "evidence.wire",
        }
        self.registry.attribution.append_outcome(
            self.coordinator.authenticate(self.tokens["evaluator"]), self.outcome
        )

    def request_for(self, row, actor="work_owner"):
        version, case = row["version"], row["case"]
        if row["family"] == "work":
            key = self.handles[version]["work_key"]
            values = {
                "submission": self.handles[version]["submission_id"],
                "task": key["task_id"],
                "step": key["step_id"],
                "revision": key["step_revision"],
                "generation": key["execution_generation"],
                "run": "run.wire.seed",
                "outcome": "event.wire.outcome",
            }
            body = deepcopy(self.requests[version]) if case == "submit" else None
            if case == "run_create":
                body = {
                    "version": "1",
                    "run_id": "run.wire.human." + actor,
                    "task_id": "task.demo",
                    "task_class": "class.demo",
                    "evaluation_ref": "rubric.wire",
                    "mode": "direct_human",
                }
            if case == "outcome_create":
                body = deepcopy(self.outcome)
            return row["path"].format(**values), body
        data = self.data[version]
        did, aid = data["dataset"]["dataset_id"], data["account"]["account_id"]
        path = row["path"].format(
            version=version,
            account=aid,
            event=data["event"]["event_id"],
            snapshot="snapshot.wire.v" + version,
            credential_account=self.credential_account,
        )
        bodies = {
            "dataset_create": data["dataset"],
            "account_create": data["account"],
            "event_create": data["event"],
            "snapshot_create": data["snapshot"],
        }
        body = deepcopy(bodies.get(case))
        if case in ("account_state", "account_permissions"):
            raw = self.store.db.execute(
                "SELECT record FROM integration_accounts WHERE dataset_id=? AND id=?", (did, aid)
            ).fetchone()[0]
            current = json.loads(raw)
            body = {"dataset_id": did, "expected_revision": current["revision"]}
            body.update(
                {"state": "usable"}
                if case == "account_state"
                else {"allowed_models": data["account"]["allowed_models"], "allowed_operations": []}
            )
        if row["method"] == "GET":
            path += "?dataset_id=" + did
            if case == "eligibility":
                path += "&model_id=model.synthetic"
                if version == "3":
                    path += "&operation_family=generation&capability=generation&selection_kind=known_model"
            if case == "resolve":
                path += (
                    "&model_id=model.synthetic&operation_family=generation&purpose="
                    + self.registry.identity.credential_release_purpose
                )
        return path, body
