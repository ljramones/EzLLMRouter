"""Exact installed 0.2.1 consumers against packaged accounting-only local service."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta
from decimal import Decimal
import http.client
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit

from ezllmrouter_client import IntegrationClient, IntegrationClientError, __version__


ROOT = Path(__file__).resolve().parents[3]
DID = "dataset.integration.c02"
ACCOUNT = "account:c02:01"
NODE = "/Users/larrymitchell/.nvm/versions/node/v24.22.1/bin/node"


def later(stamp, seconds):
    return (
        datetime.fromisoformat(stamp.replace("Z", "+00:00")) + timedelta(seconds=seconds)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")


def csv_report(base, token):
    address = urlsplit(base)
    connection = http.client.HTTPConnection(address.hostname, address.port, timeout=5)
    try:
        connection.request(
            "GET",
            "/integration/v2/reports/usage?dataset_id=" + DID + "&export=csv",
            headers={"Authorization": "Bearer " + token, "EzLLMRouter-Integration-Version": "2"},
        )
        response = connection.getresponse()
        assert response.status == 200
        return response.read().decode("utf-8")
    finally:
        connection.close()


def actor(base, secret_file, package, mode, evidence):
    run = subprocess.run(
        (
            NODE,
            str(ROOT / "tools/accounting/evidence/correction02_js_actor.cjs"),
            base,
            str(secret_file),
            str(package),
            mode,
        ),
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": str(Path(NODE).parent) + ":" + os.environ.get("PATH", "")},
    )
    if run.returncode:
        (evidence / ("node-" + mode + "-failure.log")).write_text(run.stdout + run.stderr)
        raise RuntimeError("installed Node actor failed: " + run.stderr)
    parsed = json.loads(run.stdout)
    assert parsed["result"] == "PASS"
    (evidence / ("node-" + mode + ".json")).write_text(run.stdout)
    return parsed


def main():
    instance, base, mode = Path(sys.argv[1]).resolve(), sys.argv[2], sys.argv[3]
    secrets = Path(sys.argv[4]).resolve() if len(sys.argv) > 4 else instance / "secrets"
    evidence = instance / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    assert __version__ == "0.2.1" and "site-packages" in str(
        Path(sys.modules["ezllmrouter_client"].__file__).resolve()
    )
    package = instance / "consumer-node24/node_modules/@cognitivedynamics/ezllmrouter-client"
    assert package.is_dir() and str(package.resolve()).startswith(str(instance))
    admin_token = (secrets / "admin.token").read_text().strip()
    ingest_token = (secrets / "ingest.token").read_text().strip()
    with (
        IntegrationClient(base, admin_token, version="2") as owner,
        IntegrationClient(base, ingest_token, version="2") as sender,
    ):
        if mode == "seed":
            _seed_snapshot_correction_release(base, evidence, owner, package, secrets, sender)
        report = owner.report(DID)
        exported = owner.export_dataset(DID)
        rows = list(csv.DictReader(io.StringIO(csv_report(base, admin_token))))
        expected = Decimal("0.020000000") + Decimal("0.010000000")
        assert report["attempt_count"] == len(rows) == len(exported["attempts"]) == 3
        assert report["unknown_cost_attempts"] == 1
        assert report["known_total_by_currency"] == {"USD": format(expected, ".9f")}
        assert (
            sum(
                (Decimal(row["amount_decimal"]) for row in rows if row["amount_decimal"]),
                Decimal(0),
            )
            == expected
        )
        assert (
            sum(
                (
                    Decimal(row["amount_decimal"])
                    for row in report["attempts"]
                    if row["amount_decimal"]
                ),
                Decimal(0),
            )
            == expected
        )
        by_id = {row["attempt_id"]: row for row in report["attempts"]}
        assert {aid: row["usage_state"] for aid, row in by_id.items()} == {
            "attempt.base": "known",
            "attempt.fallback": "known",
            "attempt.search": "unknown",
        }
        assert {row["attempt_id"]: row["usage_state"] for row in rows} == {
            aid: row["usage_state"] for aid, row in by_id.items()
        }
        assert by_id["attempt.base"]["eligibility_evidence_status"] == "verified"
        assert by_id["attempt.base"]["eligibility_assessment"] == "indeterminate"
        assert by_id["attempt.fallback"]["lineage_status"] == "linked"
        assert by_id["attempt.base"]["feature_snapshot_status"] == "captured"
        assert by_id["attempt.base"]["decision_snapshot_status"] == "captured"
        assert by_id["attempt.search"]["feature_snapshot_status"] == "missing"
        assert by_id["attempt.search"]["model_id"] is None
        assert exported["eligibility_assessments"][0]["assessment"] == "indeterminate"
        assert {
            item["status"]
            for item in exported["snapshot_reference_assessments"]
            if item["attempt_id"] == "attempt.base"
        } == {"captured"}
        assert sender.recover_receipt(DID, "event.TimeZ")["event_id"] == "event.TimeZ"
        assert len(exported["snapshots"]) == 2
        if mode == "seed":
            (evidence / "final-report.json").write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n"
            )
            (evidence / "final-report.csv").write_text(csv_report(base, admin_token))
            (evidence / "final-export.json").write_text(
                json.dumps(exported, indent=2, sort_keys=True) + "\n"
            )
        actor(base, secrets / "ingest.token", package, "verify", evidence)
        summary = {
            "mode": mode,
            "result": "PASS",
            "attempt_count": 3,
            "known_usd": format(expected, ".9f"),
            "unknown_cost_attempts": 1,
            "event_count": len(exported["events"]),
            "snapshot_count": len(exported["snapshots"]),
            "eligibility_assessment": by_id["attempt.base"]["eligibility_assessment"],
        }
        (evidence / (mode + "-summary.json")).write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n"
        )
        print(json.dumps(summary, sort_keys=True))


def _seed_snapshot_correction_release(base, evidence, owner, package, secrets, sender):
    dataset = {
        "dataset_id": DID,
        "platform_id": "platform.synthetic",
        "environment_id": "env.synthetic",
        "owner_id": "owner.local",
        "ingest_principal_id": "svc.integration",
        "activated_at": "2026-10-27T00:00:00Z",
    }
    assert owner.create_dataset(dataset)["dataset_id"] == DID
    assert (
        owner.register_account(
            {
                "account_id": ACCOUNT,
                "dataset_id": DID,
                "provider_id": "provider.synthetic",
                "credential_ref": "manager.synthetic",
                "allowed_models": ["model.synthetic"],
                "state": "usable",
            }
        )["revision"]
        == 1
    )
    node = actor(base, secrets / "ingest.token", package, "seed", evidence)
    start_at = node["start_at"]
    root = {"integration_version": "2", "dataset_id": DID}
    lineage = {
        **root,
        "event_id": "event.fallback.lineage",
        "kind": "lineage",
        "occurred_at": later(start_at, 1),
        "attempt_id": "attempt.fallback",
        "logical_operation_id": "logical.synthetic",
        "attempt_role": "fallback",
        "predecessor_attempt_id": "attempt.base",
    }
    assert sender.submit_observation(lineage)["membership_at_receipt"] == "pending_start"
    fallback = {
        **root,
        "event_id": "event.fallback.start",
        "kind": "attempt_started",
        "occurred_at": later(start_at, 1),
        "attempt_id": "attempt.fallback",
        "started_at": later(start_at, 1),
        "task_id": "task.synthetic",
        "step_id": "step.synthetic",
        "run_id": "run.synthetic",
        "root_run_id": "run.synthetic",
        "actor_kind": "agent",
        "actor_id": "agent.synthetic.other",
        "provider_account_id": ACCOUNT,
        "model_id": "model.synthetic",
        "model_identity_state": "known",
        "context_ref": "feature.fallback",
        "operation_family_version": "1",
        "operation_family": "generation",
        "logical_operation_id": "logical.synthetic",
        "attempt_role": "unknown",
    }
    assert sender.submit_observation(fallback)["membership_at_receipt"] == "included"
    search = {
        **fallback,
        "event_id": "event.search.start",
        "attempt_id": "attempt.search",
        "occurred_at": later(start_at, 2),
        "started_at": later(start_at, 2),
        "actor_kind": "service",
        "actor_id": "service.synthetic",
        "provider_account_id": "account.unregistered",
        "context_ref": "feature.search",
        "operation_family": "search",
        "model_identity_state": "not_applicable",
        "logical_operation_id": "logical.search",
        "attempt_role": "fanout",
    }
    search.pop("model_id")
    assert sender.submit_observation(search)["membership_at_receipt"] == "included"
    for bad in (
        {
            **search,
            "event_id": "event.search.wrong.feature",
            "attempt_id": "attempt.wrong",
            "context_ref": "feature.base",
        },
        {
            **root,
            "event_id": "event.search.wrong.decision",
            "kind": "decision",
            "occurred_at": search["started_at"],
            "attempt_id": "attempt.search",
            "decision_ref": "feature.base",
            "selected_account_id": "account.unregistered",
            "policy_version": "policy.synthetic",
            "eligibility_evidence": {"status": "unavailable"},
        },
    ):
        try:
            sender.submit_observation(bad)
        except IntegrationClientError as error:
            assert error.code == "EVENT_CONFLICT"
        else:
            raise AssertionError("incompatible snapshot reference accepted")
    units = [{"unit": "input_tokens", "quantity_decimal": "8"}]
    assert (
        sender.submit_observation(
            {
                **root,
                "event_id": "event.fallback.usage",
                "kind": "usage",
                "occurred_at": later(start_at, 3),
                "attempt_id": "attempt.fallback",
                "usage_revision": 1,
                "usage_state": "known",
                "cost_state": "unknown",
                "native_units": units,
                "usage_provenance": "provider_reported",
            }
        )["kind"]
        == "usage"
    )
    assert (
        sender.submit_observation(
            {
                **root,
                "event_id": "event.search.usage",
                "kind": "usage",
                "occurred_at": later(start_at, 3),
                "attempt_id": "attempt.search",
                "usage_revision": 1,
                "usage_state": "unknown",
                "cost_state": "known",
                "currency": "USD",
                "amount_decimal": "0.010000000",
                "cost_basis": "provider_reported",
                "price_ref": "tariff.synthetic",
                "price_version": "v1",
            }
        )["kind"]
        == "usage"
    )
    assert (
        sender.submit_observation(
            {
                **root,
                "event_id": "event.base.usage.2",
                "kind": "usage",
                "occurred_at": later(start_at, 4),
                "attempt_id": "attempt.base",
                "usage_revision": 2,
                "usage_state": "known",
                "cost_state": "known",
                "native_units": [{"unit": "input_tokens", "quantity_decimal": "10"}],
                "usage_provenance": "provider_reported",
                "currency": "USD",
                "amount_decimal": "0.020000000",
                "cost_basis": "provider_reported",
                "price_ref": "tariff.synthetic",
                "price_version": "v1",
            }
        )["kind"]
        == "usage"
    )
    assert (
        owner.set_account_state(
            ACCOUNT, {"dataset_id": DID, "expected_revision": 1, "state": "disabled"}
        )["revision"]
        == 2
    )
    assert sender.eligibility(DID, ACCOUNT, "model.synthetic")["reason"] == "account_disabled"


if __name__ == "__main__":
    main()
