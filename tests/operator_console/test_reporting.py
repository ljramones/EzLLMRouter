"""Map the independent arithmetic fixture into disposable authoritative tables."""

from pathlib import Path
import hashlib
import json
import tempfile
import threading
import unittest

from ezllmrouter_server.registry import Registry
from ezllmrouter_server.reporting import usage_costs
from ezllmrouter_server.store import SQLiteStore, encode


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((ROOT / "tests/operator_console/dev09_accounting_fixture.json").read_text())
DEST = {
    "configuration_ref": "cfg.demo",
    "service": "litellm.dev04",
    "endpoint": "127.0.0.1",
    "model": "model.demo",
    "model_version": "v1",
    "processing_region": "local",
}


class Authority:
    def __init__(self):
        self.gate = threading.RLock()
        self.epoch = 0


class ReportingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = SQLiteStore(Path(tmp.name) / "metadata.sqlite")
        self.addCleanup(self.store.close)
        self.registry = Registry(
            self.store,
            Authority(),
            legacy_destination=DEST,
            legacy_token="synthetic-report-token-0000000000000000000",
            legacy_trusted={"principal_id": "svc.demo", "charging_owner_id": "team.demo"},
        )
        self.task = {task["id"]: task for task in FIXTURE["tasks"]}
        self.run = {run["id"]: run for run in FIXTURE["runs"]}
        for index, agent in enumerate(FIXTURE["agents"]):
            self.registry.mutate(
                "owner.local",
                {
                    "operation_id": f"op.agent.fixture.{index}",
                    "action": "register_agent",
                    "subject": agent["id"],
                    "expected_revision": 0,
                    "data": {
                        "display_name": agent["name"],
                        "owner": "team.fixture",
                        "versions": [agent["version"]],
                    },
                },
            )
            if agent["instrumentation"] == "instrumented":
                self.registry.mutate(
                    "owner.local",
                    {
                        "operation_id": f"op.agent.instrument.{index}",
                        "action": "agent_instrumentation",
                        "subject": agent["id"],
                        "expected_revision": 1,
                        "data": {"status": "instrumented", "evidence_ref": "fixture.instrumented"},
                    },
                )
        at = "2030-01-01T00:00:00Z"
        for run in FIXTURE["runs"]:
            task = self.task[run["task_id"]]
            record = {
                "run_id": run["id"],
                "principal_id": run["initiating_user_id"]
                if run["agent_id"] is None
                else "svc.fixture",
                "charging_owner_id": run["charging_owner_id"],
                "initiating_user_id": run["initiating_user_id"],
                "agent_id": run["agent_id"],
                "agent_version": "v1" if run["agent_id"] else None,
                "parent_run_id": run["parent_run_id"],
                "root_run_id": task["root_run_id"],
                "task_id": run["task_id"],
                "task_class": task["task_class"],
                "evaluation_ref": task["acceptance_protocol"],
                "mode": run["initiation_mode"],
                "created_at": at,
                "status": task["outcome"] if run["parent_run_id"] is None else "running",
            }
            self.store.db.execute(
                "INSERT INTO attribution_runs VALUES (?,?)", (run["id"], encode(record))
            )
            if run["parent_run_id"] is None:
                event = {
                    "kind": "task_outcome",
                    "run_id": run["id"],
                    "verdict": task["outcome"],
                    "evaluator_version": task["acceptance_protocol"],
                    "subject_revision": 1,
                }
                self.store.db.execute(
                    "INSERT INTO attribution_outcomes VALUES (?,?,?,?,?,?,?,?)",
                    (
                        "evaluator.fixture",
                        "event." + run["id"],
                        encode([run["id"], "task_outcome"]),
                        1,
                        "digest.fixture",
                        encode(event),
                        "2030-01-01T00:00:12Z",
                        encode({"event_id": "event." + run["id"]}),
                    ),
                )
        for attempt in FIXTURE["attempts"]:
            run = self.run[attempt["run_id"]]
            task = self.task[run["task_id"]]
            number = attempt["id"]
            record = {
                "submission_id": "submission." + number,
                "attempt_id": number,
                "principal_id": run["initiating_user_id"]
                if run["agent_id"] is None
                else "svc.fixture",
                "task_id": run["task_id"],
                "task_class": task["task_class"],
                "purpose": "execution",
                "created_at": at,
                "provenance": "synthetic_fixture",
                "status_revision": 1,
                "work_key": {
                    "principal_id": "svc.fixture",
                    "task_id": run["task_id"],
                    "step_id": "step." + number,
                    "step_revision": 1,
                    "execution_generation": "gen.fixture",
                },
                "work_digest": "sha256:" + hashlib.sha256(number.encode()).hexdigest(),
                "submission_state": "failed_before_transmit" if number == "a10" else "completed",
                "dispatch_state": "failed_before_dispatch"
                if number == "a10"
                else "response_observed",
                "attribution": {
                    "run_id": run["id"],
                    "root_run_id": task["root_run_id"],
                    "parent_run_id": run["parent_run_id"],
                    "agent_id": run["agent_id"],
                    "agent_version": "v1" if run["agent_id"] else None,
                    "initiating_user_id": run["initiating_user_id"],
                    "charging_owner_id": run["charging_owner_id"],
                    "task_class": task["task_class"],
                    "mode": run["initiation_mode"],
                },
            }
            self.store.create(record)
            if number != "a10":
                self.store.db.execute(
                    "INSERT INTO intents VALUES (?,?,?)",
                    (
                        number,
                        record["submission_id"],
                        encode(
                            {
                                "destination": {
                                    "configuration_ref": attempt["deployment_id"],
                                    "service": attempt["provider_id"],
                                    "connection_id": attempt["api_setup_id"],
                                    "model": attempt["model_id"],
                                }
                            }
                        ),
                    ),
                )
            else:
                # The fixture's explicit zero-cost revision still has its provider/model identity.
                # Store it in the trusted record, while retaining absence of a send intent.
                record["fixture_destination"] = {
                    "configuration_ref": attempt["deployment_id"],
                    "service": attempt["provider_id"],
                    "connection_id": attempt["api_setup_id"],
                    "model": attempt["model_id"],
                }
                self.store.db.execute(
                    "UPDATE submissions SET record=? WHERE submission_id=?",
                    (encode(record), record["submission_id"]),
                )
        seen = set()
        for revision in FIXTURE["cost_revision_observations"]:
            key = (revision["attempt_id"], revision["revision"])
            if key in seen:
                continue  # Exact duplicated observation is one durable replacement.
            seen.add(key)
            cost = {"status": revision["cost_status"], "currency": revision["currency"]}
            if "amount" in revision:
                cost.update(amount_decimal=revision["amount"], source_ref="fixture.price")
            usage = {
                "attempt_id": revision["attempt_id"],
                "revision": revision["revision"],
                "recorded_at": f"2030-01-01T00:00:{revision['sequence']:02d}Z",
                "price_version": "fixture.price",
                "cost": cost,
                "normalized_usage": {},
            }
            self.store.db.execute(
                "INSERT INTO usage_revisions VALUES (?,?,?,?)",
                (
                    revision["attempt_id"],
                    revision["revision"],
                    "submission." + revision["attempt_id"],
                    encode(usage),
                ),
            )

    def report(self, filters=None, scope=None):
        selected = {"cutoff": "2030-01-01T00:00:20Z", **(filters or {})}
        return usage_costs(
            self.registry,
            scope or {"role": "registry_admin", "principal_id": "owner.local"},
            selected,
        )

    def test_attempt_pages_preserve_complete_totals_and_cohorts(self):
        full = self.report()
        pages = [
            usage_costs(
                self.registry,
                {"role": "registry_admin", "principal_id": "owner.local"},
                {"cutoff": full["cutoff"]},
                attempt_page=page,
                attempt_limit=3,
            )
            for page in range(1, 5)
        ]
        self.assertEqual([row for page in pages for row in page["attempts"]], full["attempts"])
        for page in pages:
            self.assertLessEqual(len(page["attempts"]), 3)
            self.assertEqual(page["total"], full["total"])
            self.assertEqual(page["cohorts"], full["cohorts"])
            self.assertEqual(page["attempt_pagination"]["total"], 10)

    def test_fixture_conservation_replacement_and_cohorts(self):
        report = self.report()
        self.assertEqual(report["total"]["attempts"], 10)
        self.assertEqual(report["total"]["known_subtotals"], {"EUR": "4", "USD": "32"})
        self.assertEqual(report["total"]["unknown_cost_attempts"], 1)
        usd = self.report({"currency": "USD"})
        self.assertEqual(usd["total"]["known_subtotals"], {"USD": "32"})
        self.assertEqual(usd["total"]["unknown_cost_attempts"], 1)
        provider = {row["id"]: row for row in report["groupings"]["provider"]}
        self.assertEqual(provider["provider.a"]["known_subtotals"]["USD"], "20")
        self.assertEqual(provider["provider.a"]["unknown_cost_attempts"], 1)
        self.assertEqual(provider["provider.b"]["known_subtotals"], {"EUR": "4", "USD": "12"})
        actors = {row["id"]: row for row in report["groupings"]["agent_id"]}
        self.assertEqual(actors["agent.coordinator"]["known_subtotals"]["USD"], "17")
        self.assertEqual(actors["agent.researcher"]["known_subtotals"]["USD"], "9")
        self.assertEqual(actors["agent.reviewer"]["unknown_cost_attempts"], 1)
        root = {row["agent_id"]: row for row in report["agents"]["items"]}["agent.coordinator"]
        self.assertEqual(root["direct"]["known_subtotals"]["USD"], "17")
        # Root run itself is 10 direct + two descendants 6 and 4.
        root_run = next(row for row in report["workflows"] if row["run_id"] == "run.root")
        self.assertEqual(root_run["direct"]["known_subtotals"]["USD"], "10")
        self.assertEqual(root_run["delegated"]["known_subtotals"]["USD"], "10")
        self.assertEqual(root_run["inclusive_workflow"]["known_subtotals"]["USD"], "20")
        root_cohort = next(
            row for row in report["cohorts"] if row["task_class"] == "fixture.workflow"
        )
        self.assertEqual((root_cohort["total_tasks"], root_cohort["accepted"]), (2, 1))
        self.assertEqual(root_cohort["attempt_cost"]["known_subtotals"]["USD"], "27")
        self.assertEqual(root_cohort["efficiency"]["cost_per_accepted_task"], "27")
        self.assertEqual(root_cohort["performance"]["acceptance_rate_percent"], "50")
        self.assertEqual(root_cohort["performance"]["calls_per_accepted_task"], "6")
        self.assertIsNone(root_cohort["performance"]["median_seconds_to_accepted"])
        self.assertEqual(root_cohort["performance"]["human_intervention_rate"], "not_measured")
        background = next(
            row for row in report["cohorts"] if row["task_class"] == "fixture.background"
        )
        self.assertEqual(background["efficiency"]["state"], "no_accepted_tasks")
        unknown = next(row for row in report["cohorts"] if row["task_class"] == "fixture.review")
        self.assertEqual(unknown["efficiency"]["state"], "incomplete")
        inventory = {row["agent_id"]: row for row in report["agents"]["items"]}
        self.assertEqual(inventory["agent.idle"]["activity"], "no_activity_recorded")
        self.assertEqual(inventory["agent.idle"]["instrumentation"], "instrumented")
        self.assertEqual(inventory["agent.external"]["instrumentation"], "not_instrumented")
        earlier = self.report({"cutoff": "2030-01-01T00:00:10Z"})
        self.assertEqual(earlier["total"]["known_subtotals"]["USD"], "33")
        self.assertEqual(
            self.report({"from": "2030-01-01T00:00:00Z", "to": "2030-01-01T00:00:01Z"})["total"][
                "attempts"
            ],
            10,
        )
        self.assertEqual(self.report({"to": "2030-01-01T00:00:00Z"})["total"]["attempts"], 0)
        for field in ("provider", "model", "agent_id", "initiating_user_id", "charging_owner_id"):
            for currency, amount in report["total"]["known_subtotals"].items():
                self.assertEqual(
                    sum(
                        __import__("decimal").Decimal(row["known_subtotals"].get(currency, "0"))
                        for row in report["groupings"][field]
                    ),
                    __import__("decimal").Decimal(amount),
                )
            self.assertEqual(
                sum(row["unknown_cost_attempts"] for row in report["groupings"][field]), 1
            )
        search = self.report({"agent_search": "Coordinator"})
        self.assertEqual(search["agents"]["total"], 1)
        self.assertEqual(search["total"], report["total"])
        paged = usage_costs(
            self.registry,
            {"role": "registry_admin", "principal_id": "owner.local"},
            {"cutoff": "2030-01-01T00:00:20Z"},
            page=2,
            limit=2,
        )
        self.assertEqual(paged["agents"]["total"], len(FIXTURE["agents"]))
        self.assertEqual(len(paged["agents"]["items"]), 2)

    def test_scope_before_counts_and_exports(self):
        alpha = self.report(scope={"role": "ordinary", "principal_id": "user.alpha"})
        self.assertFalse(
            any(item["initiating_user_id"] == "user.beta" for item in alpha["attempts"])
        )
        self.assertFalse(
            any(item["agent_id"] == "agent.external" for item in alpha["agents"]["items"])
        )
        self.assertEqual(alpha["total"]["unknown_cost_attempts"], 1)


if __name__ == "__main__":
    unittest.main()
