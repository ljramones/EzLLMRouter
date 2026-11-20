"""Installed-client synthetic release check; never calls an LLM or sender."""

from __future__ import annotations

import csv
from decimal import Decimal
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.request import Request, urlopen

from ezllmrouter_client import IntegrationClient

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_PATH = ROOT / "tests/fixtures/contracts/integration-readiness-v1/examples.json"
EXAMPLES = json.loads(EXAMPLES_PATH.read_text())


def main():
    artifacts = Path(sys.argv[1])
    base = "http://127.0.0.1:48760"
    secret_dir = artifacts / "secrets"
    admin = (secret_dir / "admin.token").read_text().strip()
    ingest = (secret_dir / "ingest.token").read_text().strip()
    node = "/Users/larrymitchell/.nvm/versions/node/v24.22.1/bin/node"
    package = artifacts / "consumer-js/node_modules/@cognitivedynamics/ezllmrouter-client"
    assert "site-packages" in str(Path(sys.modules["ezllmrouter_client"].__file__).resolve())
    assert str(package.resolve()).startswith(str(artifacts.resolve()))
    mode = sys.argv[2] if len(sys.argv) > 2 else "seed"
    with IntegrationClient(base, admin) as owner, IntegrationClient(base, ingest) as sender:
        if mode == "seed":
            dataset = {**EXAMPLES["dataset"], "ingest_principal_id": "svc.integration"}
            assert owner.create_dataset(dataset)["dataset_id"] == dataset["dataset_id"]
            assert owner.register_account(EXAMPLES["account"])["revision"] == 1
            assert sender.eligibility(
                dataset["dataset_id"], EXAMPLES["account"]["account_id"], "model.synthetic"
            )["usable"]
            subprocess.run(
                (
                    node,
                    str(ROOT / "tools/accounting/evidence/js_actor.cjs"),
                    base,
                    str(secret_dir / "ingest.token"),
                    str(EXAMPLES_PATH),
                    str(package),
                    "seed",
                ),
                check=True,
                env={
                    **os.environ,
                    "PATH": str(Path(node).parent) + ":" + os.environ.get("PATH", ""),
                },
            )
            for event in EXAMPLES["events"][6:]:
                sender.submit_observation(event)
            old = {
                **EXAMPLES["events"][2],
                "event_id": "event.before.activation",
                "attempt_id": "attempt.before.activation",
                "started_at": "2026-10-26T23:59:59Z",
                "occurred_at": "2026-10-26T23:59:59Z",
            }
            assert (
                sender.submit_observation(old)["membership_at_receipt"]
                == "excluded_before_activation"
            )
            sender.submit_observation(
                {
                    "integration_version": "1",
                    "event_id": "event.child.2",
                    "dataset_id": dataset["dataset_id"],
                    "kind": "activity",
                    "occurred_at": "2026-10-27T00:01:27Z",
                    "activity_kind": "delegation",
                    "task_id": "task.01",
                    "run_id": "run.child2",
                    "root_run_id": "run.root",
                    "parent_run_id": "run.root",
                    "actor_kind": "agent",
                    "actor_id": "agent.synthetic.other",
                }
            )
            unknown = {
                **EXAMPLES["events"][7],
                "event_id": "event.start.unknown",
                "attempt_id": "attempt.unknown",
                "started_at": "2026-10-27T00:01:30Z",
                "occurred_at": "2026-10-27T00:01:30Z",
                "run_id": "run.child2",
                "actor_id": "agent.synthetic.other",
            }
            sender.submit_observation(unknown)
            sender.submit_observation(
                {
                    "integration_version": "1",
                    "event_id": "event.result.unknown",
                    "dataset_id": dataset["dataset_id"],
                    "kind": "result",
                    "occurred_at": "2026-10-27T00:01:40Z",
                    "attempt_id": "attempt.unknown",
                    "result_state": "unknown",
                }
            )
            assert (
                owner.set_account_state(
                    EXAMPLES["account"]["account_id"],
                    {
                        "dataset_id": dataset["dataset_id"],
                        "expected_revision": 1,
                        "state": "disabled",
                    },
                )["revision"]
                == 2
            )
            subprocess.run(
                (
                    node,
                    str(ROOT / "tools/accounting/evidence/js_actor.cjs"),
                    base,
                    str(secret_dir / "ingest.token"),
                    str(EXAMPLES_PATH),
                    str(package),
                    "verify",
                ),
                check=True,
                env={
                    **os.environ,
                    "PATH": str(Path(node).parent) + ":" + os.environ.get("PATH", ""),
                },
            )
            # A correction received after disable still counts once.
            sender.submit_observation(
                {
                    "integration_version": "1",
                    "event_id": "event.usage.2.2",
                    "dataset_id": dataset["dataset_id"],
                    "kind": "usage",
                    "occurred_at": "2026-10-27T00:02:00Z",
                    "attempt_id": "attempt.2",
                    "usage_revision": 2,
                    "usage_state": "known",
                    "currency": "USD",
                    "amount_decimal": "0.025000000",
                    "cost_basis": "provider_reported",
                    "price_ref": "tariff.synthetic",
                    "price_version": "v1",
                    "native_units": [
                        {"unit": "input_tokens", "quantity_decimal": "80"},
                        {"unit": "output_tokens", "quantity_decimal": "40"},
                    ],
                }
            )
        report = owner.report(EXAMPLES["dataset"]["dataset_id"])
        expected = Decimal("0.030000000") + Decimal("0.025000000")
        assert report["attempt_count"] == 3
        assert report["unknown_cost_attempts"] == 1
        assert report["known_total_by_currency"] == {"USD": format(expected, ".9f")}
        assert (
            sum(
                (
                    Decimal(item["amount_decimal"])
                    for item in report["attempts"]
                    if item["cost_status"] == "known"
                ),
                Decimal(0),
            )
            == expected
        )
        assert report["by_root_workflow"]["run.root"]["USD"] == format(expected, ".9f")
        assert report["by_run_including_descendants"]["run.root"]["USD"] == format(expected, ".9f")
        assert {item["actor_id"] for item in report["attempts"]} == {
            "agent.synthetic",
            "agent.synthetic.other",
        }
        assert all(item["task_outcome"] == "accepted" for item in report["attempts"])
        assert (
            owner.report(EXAMPLES["dataset"]["dataset_id"])["known_total_by_currency"]
            == report["known_total_by_currency"]
        )
        assert (
            sender.recover_receipt(EXAMPLES["dataset"]["dataset_id"], "event.usage.2.2")["kind"]
            == "usage"
        )
        request = Request(
            base
            + "/integration/v1/reports/usage?dataset_id="
            + EXAMPLES["dataset"]["dataset_id"]
            + "&export=csv",
            headers={"Authorization": "Bearer " + admin, "EzLLMRouter-Integration-Version": "1"},
        )
        with urlopen(request, timeout=5) as response:
            rows = list(csv.DictReader(io.StringIO(response.read().decode())))
        assert len(rows) == report["attempt_count"]
        assert (
            sum(
                (Decimal(row["amount_decimal"]) for row in rows if row["cost_status"] == "known"),
                Decimal(0),
            )
            == expected
        )
        print(
            "installed combined release",
            mode,
            "PASS: 3 included attempts, 1 unknown, known USD",
            format(expected, ".9f"),
        )


if __name__ == "__main__":
    main()
