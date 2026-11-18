"""Installed 0.2.0 clients against packaged service; synthetic accounting only."""
from __future__ import annotations

import csv
from decimal import Decimal
import http.client
import io
import json
import os
from pathlib import Path
import subprocess
import sys

from duranki_client import IntegrationClient, __version__

ROOT = Path(__file__).resolve().parents[2]
DID = "dataset.integration.correction.v2"
ACCOUNT = "account:correct:01"
BASE = "http://127.0.0.1:48760"


def csv_report(token):
    connection = http.client.HTTPConnection("127.0.0.1", 48760, timeout=5)
    try:
        connection.request("GET", "/integration/v2/reports/usage?dataset_id=" + DID + "&export=csv",
                           headers={"Authorization": "Bearer " + token, "Duranki-Integration-Version": "2"})
        response = connection.getresponse()
        assert response.status == 200
        return response.read().decode("utf-8")
    finally:
        connection.close()


def main():
    root = Path(sys.argv[1]).resolve()
    mode = sys.argv[2]
    assert __version__ == "0.2.0" and "site-packages" in str(Path(sys.modules["duranki_client"].__file__).resolve())
    package = root / "consumer-js24/node_modules/@mach33/duranki-client"
    assert package.resolve().is_dir() and str(package.resolve()).startswith(str(root))
    secrets = Path(sys.argv[3]) if len(sys.argv) > 3 else root / "secrets"
    admin_token = (secrets / "admin.token").read_text().strip()
    ingest_token = (secrets / "ingest.token").read_text().strip()
    node = "/Users/larrymitchell/.nvm/versions/node/v24.22.1/bin/node"
    root.mkdir(parents=True, exist_ok=True)
    evidence = root / "evidence"
    evidence.mkdir(exist_ok=True)
    with IntegrationClient(BASE, admin_token, version="2") as owner, \
         IntegrationClient(BASE, ingest_token, version="2") as sender:
        if mode == "seed":
            dataset = {"dataset_id": DID, "platform_id": "platform.synthetic", "environment_id": "env.synthetic",
                "owner_id": "owner.local", "ingest_principal_id": "svc.integration",
                "activated_at": "2099-01-01T00:00:00Z"}
            assert owner.create_dataset(dataset)["dataset_id"] == DID
            account = {"account_id": ACCOUNT, "dataset_id": DID, "provider_id": "provider.synthetic",
                "credential_ref": "manager.synthetic", "allowed_models": ["model.synthetic"], "state": "usable"}
            assert owner.register_account(account)["revision"] == 1
            actor = subprocess.run((node, str(ROOT / "tests/integration_readiness/correction_js_actor.cjs"), BASE,
                str(secrets / "ingest.token"), str(package), "seed"), capture_output=True, text=True,
                env={**os.environ, "PATH": str(Path(node).parent) + ":" + os.environ.get("PATH", "")})
            if actor.returncode:
                (evidence / "node-seed-failure.log").write_text(actor.stdout + actor.stderr)
                raise RuntimeError("installed Node seed failed: " + actor.stderr)
            (evidence / "node-seed.json").write_text(actor.stdout)
            start = {"integration_version": "2", "event_id": "event.search.start", "dataset_id": DID,
                "kind": "attempt_started", "occurred_at": "2099-01-01T00:00:11Z", "attempt_id": "attempt.search",
                "started_at": "2099-01-01T00:00:11Z", "task_id": "task.synthetic", "step_id": "step.synthetic",
                "run_id": "run.synthetic", "root_run_id": "run.synthetic", "actor_kind": "service",
                "actor_id": "service.synthetic", "provider_account_id": "account.unregistered",
                "model_identity_state": "not_applicable", "context_ref": "feature.search",
                "operation_family_version": "1", "operation_family": "search", "logical_operation_id": "logical.search",
                "attempt_role": "fanout"}
            assert sender.submit_observation(start)["membership_at_receipt"] == "included"
            known_cost = {"integration_version": "2", "event_id": "event.search.usage", "dataset_id": DID,
                "kind": "usage", "occurred_at": "2099-01-01T00:00:21Z", "attempt_id": "attempt.search",
                "usage_revision": 1, "usage_state": "unknown", "cost_state": "known", "currency": "USD",
                "amount_decimal": "0.010000000", "cost_basis": "provider_reported",
                "price_ref": "tariff.synthetic", "price_version": "v1"}
            sender.submit_observation(known_cost)
            fallback = {**start, "event_id": "event.fallback.start", "attempt_id": "attempt.fallback",
                "started_at": "2099-01-01T00:00:12Z", "occurred_at": "2099-01-01T00:00:12Z",
                "actor_kind": "agent", "actor_id": "agent.synthetic.other", "provider_account_id": ACCOUNT,
                "model_id": "model.synthetic", "model_identity_state": "known",
                "context_ref": "feature.fallback", "operation_family": "generation",
                "logical_operation_id": "logical.synthetic", "attempt_role": "fallback",
                "predecessor_attempt_id": "attempt.base"}
            sender.submit_observation(fallback)
            sender.submit_observation({"integration_version": "2", "event_id": "event.fallback.usage",
                "dataset_id": DID, "kind": "usage", "occurred_at": "2099-01-01T00:00:22Z",
                "attempt_id": "attempt.fallback", "usage_revision": 1, "usage_state": "known",
                "cost_state": "unknown", "native_units": [{"unit": "input_tokens", "quantity_decimal": "8"}],
                "usage_provenance": "provider_reported"})
            sender.submit_observation({"integration_version": "2", "event_id": "event.result.base", "dataset_id": DID,
                "kind": "result", "occurred_at": "2099-01-01T00:00:23Z", "attempt_id": "attempt.base",
                "result_state": "completed"})
            sender.submit_observation({"integration_version": "2", "event_id": "event.outcome", "dataset_id": DID,
                "kind": "activity", "activity_kind": "outcome", "occurred_at": "2099-01-01T00:00:30Z",
                "task_id": "task.synthetic", "run_id": "run.synthetic", "root_run_id": "run.synthetic",
                "actor_kind": "human", "actor_id": "user.synthetic", "outcome": "accepted"})
            # Resolve the *same* previously unregistered reported ID; do not rewrite the start.
            owner.register_account({"account_id": "account.unregistered", "dataset_id": DID,
                "provider_id": "provider.synthetic", "credential_ref": "manager.synthetic.other",
                "allowed_models": ["model.synthetic"], "state": "disabled"})
            sender.submit_observation({"integration_version": "2", "event_id": "event.search.resolution",
                "dataset_id": DID, "kind": "account_resolution", "occurred_at": "2099-01-01T00:00:31Z",
                "attempt_id": "attempt.search", "resolved_account_id": "account.unregistered"})
            owner.set_account_state(ACCOUNT, {"dataset_id": DID, "expected_revision": 1, "state": "disabled"})
            assert sender.eligibility(DID, ACCOUNT, "model.synthetic")["reason"] == "account_disabled"
            # Financial evidence arrives after disable; one effective amount replaces unknown.
            sender.submit_observation({"integration_version": "2", "event_id": "event.usage.base.2",
                "dataset_id": DID, "kind": "usage", "occurred_at": "2099-01-01T00:00:40Z",
                "attempt_id": "attempt.base", "usage_revision": 2, "usage_state": "known", "cost_state": "known",
                "native_units": [{"unit": "input_tokens", "quantity_decimal": "10"}],
                "usage_provenance": "provider_reported", "currency": "USD", "amount_decimal": "0.020000000",
                "cost_basis": "provider_reported", "price_ref": "tariff.synthetic", "price_version": "v1"})
        report = owner.report(DID)
        rows = list(csv.DictReader(io.StringIO(csv_report(admin_token))))
        exported = owner.export_dataset(DID)
        expected = Decimal("0.020000000") + Decimal("0.010000000")
        assert report["attempt_count"] == len(rows) == len(exported["attempts"]) == 3
        assert report["unknown_cost_attempts"] == 1
        assert report["known_total_by_currency"] == {"USD": format(expected, ".9f")}
        assert sum((Decimal(row["amount_decimal"]) for row in rows if row["amount_decimal"]), Decimal(0)) == expected
        assert sum((Decimal(row["amount_decimal"]) for row in report["attempts"] if row["amount_decimal"]),
                   Decimal(0)) == expected
        assert report["by_root_workflow"]["run.synthetic"]["USD"] == format(expected, ".9f")
        assert report["by_run_including_descendants"]["run.synthetic"]["USD"] == format(expected, ".9f")
        by_id = {row["attempt_id"]: row for row in report["attempts"]}
        assert by_id["attempt.base"]["eligibility_evidence_status"] == "verified"
        assert by_id["attempt.base"]["feature_snapshot_status"] == "captured"
        assert by_id["attempt.search"]["account_resolution_status"] == "resolved"
        assert by_id["attempt.search"]["model_id"] is None
        assert by_id["attempt.fallback"]["lineage_status"] == "linked"
        assert by_id["attempt.fallback"]["cost_status"] == "unknown"
        assert sender.recover_receipt(DID, "event.TimeZ")["event_id"] == "event.TimeZ"
        assert len(exported["eligibility_reads"]) == 1 and len(exported["snapshots"]) == 2
        if mode == "seed":
            (evidence / "final-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
            (evidence / "final-report.csv").write_text(csv_report(admin_token))
            (evidence / "final-export.json").write_text(json.dumps(exported, indent=2, sort_keys=True) + "\n")
        actor = subprocess.run((node, str(ROOT / "tests/integration_readiness/correction_js_actor.cjs"), BASE,
            str(secrets / "ingest.token"), str(package), "verify"), capture_output=True, text=True,
            env={**os.environ, "PATH": str(Path(node).parent) + ":" + os.environ.get("PATH", "")})
        if actor.returncode:
            (evidence / ("node-" + mode + "-verify-failure.log")).write_text(actor.stdout + actor.stderr)
            raise RuntimeError("installed Node verify failed: " + actor.stderr)
        (evidence / ("node-" + mode + "-verify.json")).write_text(actor.stdout)
        summary = {"mode": mode, "result": "PASS", "attempt_count": 3, "unknown_cost_attempts": 1,
                   "known_usd": format(expected, ".9f"), "event_count": len(exported["events"]),
                   "snapshot_count": len(exported["snapshots"])}
        (evidence / (mode + "-summary.json")).write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
