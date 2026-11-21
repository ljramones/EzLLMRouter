"""Installed 0.2.2 clients and service; predecessor 0.2.0 HTTP history."""

from __future__ import annotations

import csv
from decimal import Decimal
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from urllib.parse import urlsplit

from ezllmrouter_client import IntegrationClient, IntegrationClientError, __version__


ROOT = Path(__file__).resolve().parents[3]
NODE = "/Users/larrymitchell/.nvm/versions/node/v24.22.1/bin/node"
DID = "dataset.c03.historical"
ACCOUNT = "account:c03:historical"
AT = "2099-01-01T00:00:10Z"
OLD_EVENTS = ("event.old.link", "event.old.start", "event.old.usage", "event.old.before")
OLD_ATTEMPTS = ("attempt.old", "attempt.before")


def dataset(did):
    return {
        "dataset_id": did,
        "platform_id": "platform.synthetic",
        "environment_id": "env.synthetic",
        "owner_id": "owner.local",
        "ingest_principal_id": "svc.integration",
        "activated_at": "2026-10-27T00:00:00Z",
    }


def account(did, aid):
    return {
        "account_id": aid,
        "dataset_id": did,
        "provider_id": "provider.synthetic",
        "credential_ref": "manager.synthetic",
        "allowed_models": ["model.synthetic"],
        "state": "usable",
    }


def start(did, aid, account_id, task, logical, role="initial", predecessor=None):
    result = {
        "integration_version": "2",
        "event_id": "event." + aid,
        "dataset_id": did,
        "kind": "attempt_started",
        "occurred_at": AT,
        "attempt_id": aid,
        "started_at": AT,
        "task_id": task,
        "step_id": "step.c03",
        "run_id": "run." + task,
        "root_run_id": "run." + task,
        "actor_kind": "agent",
        "actor_id": "agent.synthetic",
        "provider_account_id": account_id,
        "model_id": "model.synthetic",
        "context_ref": "feature." + aid,
        "operation_family_version": "1",
        "operation_family": "generation",
        "model_identity_state": "known",
        "logical_operation_id": logical,
        "attempt_role": role,
    }
    if predecessor:
        result["predecessor_attempt_id"] = predecessor
    return result


def old_start():
    value = start(DID, "attempt.old", ACCOUNT, "task.old", "logical.conflicting", "unknown")
    value["event_id"] = "event.old.start"
    return value


def history_hash(path):
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
        events = list(
            db.execute(
                "SELECT event_id,digest,record FROM integration_events "
                "WHERE dataset_id=? AND event_id IN (?,?,?,?) ORDER BY event_id",
                (DID, *OLD_EVENTS),
            )
        )
        attempts = list(
            db.execute(
                "SELECT attempt_id,record FROM integration_attempts "
                "WHERE dataset_id=? AND attempt_id IN (?,?) ORDER BY attempt_id",
                (DID, *OLD_ATTEMPTS),
            )
        )
    assert len(events) == 4 and len(attempts) == 2
    return hashlib.sha256(
        json.dumps(
            {"events": events, "attempts": attempts}, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def rejected(call):
    try:
        call()
    except IntegrationClientError as error:
        assert error.code == "EVENT_CONFLICT", error.code
        assert error.http_status == 409 and error.retry_guidance == "never"
        return {
            "http_status": error.http_status,
            "code": error.code,
            "retry_guidance": error.retry_guidance,
        }
    raise AssertionError("expected EVENT_CONFLICT")


def csv_report(base, token, did):
    address = urlsplit(base)
    conn = http.client.HTTPConnection(address.hostname, address.port, timeout=5)
    try:
        conn.request(
            "GET",
            "/integration/v2/reports/usage?dataset_id=" + did + "&export=csv",
            headers={"Authorization": "Bearer " + token, "EzLLMRouter-Integration-Version": "2"},
        )
        response = conn.getresponse()
        assert response.status == 200
        return response.read().decode()
    finally:
        conn.close()


def node_actor(base, token_file, package, mode, evidence):
    run = subprocess.run(
        (
            NODE,
            str(ROOT / "tools/accounting/evidence/correction03_js_actor.cjs"),
            base,
            str(token_file),
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
    result = json.loads(run.stdout)
    assert result["result"] == "PASS"
    (evidence / ("node-" + mode + ".json")).write_text(run.stdout)
    return result


def check_historical(owner, sender, base, admin_token, db, expected_hash, expected_count):
    assert history_hash(db) == expected_hash
    report = owner.report(DID)
    exported = owner.export_dataset(DID)
    rows = list(csv.DictReader(io.StringIO(csv_report(base, admin_token, DID))))
    assert report["attempt_count"] == len(rows) == len(exported["attempts"]) == expected_count
    assert report["known_total_by_currency"] == {"USD": "0.010000000"}
    assert sum(
        (Decimal(row["amount_decimal"]) for row in rows if row["amount_decimal"]), Decimal(0)
    ) == Decimal("0.010000000")
    assert report["unknown_cost_attempts"] == expected_count - 1
    by_id = {row["attempt_id"]: row for row in report["attempts"]}
    assert by_id["attempt.old"]["lineage_status"] == "binding_conflict"
    assert by_id["attempt.old"]["attempt_role"] == "unknown"
    assert by_id["attempt.old"]["predecessor_attempt_id"] is None
    assert {event["event_id"] for event in exported["events"]}.issuperset(OLD_EVENTS)
    assert sender.recover_receipt(DID, "event.old.start")["event_id"] == "event.old.start"
    return report, exported, rows


def main():
    root, base, mode = Path(sys.argv[1]).resolve(), sys.argv[2], sys.argv[3]
    assert mode in {"seed_old", "seed_corrected", "verify_corrected", "probe_conflicts"}
    assert __version__ == "0.2.2" and "site-packages" in str(
        Path(sys.modules["ezllmrouter_client"].__file__).resolve()
    )
    evidence = root / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    instance = root / ("historical" if mode == "seed_old" else "corrected")
    secrets = instance / "secrets"
    admin_token = (secrets / "admin.token").read_text().strip()
    ingest_token = (secrets / "ingest.token").read_text().strip()
    with (
        IntegrationClient(base, admin_token, version="2") as owner,
        IntegrationClient(base, ingest_token, version="2") as sender,
    ):
        if mode == "seed_old":
            assert owner.create_dataset(dataset(DID))["dataset_id"] == DID
            assert owner.register_account(account(DID, ACCOUNT))["revision"] == 1
            link = {
                "integration_version": "2",
                "event_id": "event.old.link",
                "dataset_id": DID,
                "kind": "lineage",
                "occurred_at": AT,
                "attempt_id": "attempt.old",
                "logical_operation_id": "logical.original",
                "attempt_role": "fallback",
                "predecessor_attempt_id": "attempt.pending",
            }
            assert sender.submit_observation(link)["membership_at_receipt"] == "pending_start"
            assert sender.submit_observation(old_start())["kind"] == "attempt_started"
            assert (
                sender.submit_observation(
                    {
                        "integration_version": "2",
                        "event_id": "event.old.usage",
                        "dataset_id": DID,
                        "kind": "usage",
                        "occurred_at": AT,
                        "attempt_id": "attempt.old",
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
            before = start(DID, "attempt.before", ACCOUNT, "task.before", "logical.before")
            before["event_id"] = "event.old.before"
            assert sender.submit_observation(before)["kind"] == "attempt_started"
            report = owner.report(DID)
            assert report["attempt_count"] == 2
            assert report["known_total_by_currency"] == {"USD": "0.010000000"}
            digest = history_hash(instance / "accounting.sqlite")
            summary = {
                "mode": mode,
                "result": "PASS",
                "old_events": 4,
                "old_attempts": 2,
                "known_usd": "0.010000000",
                "old_history_sha256": digest,
            }
            (evidence / "old-seed-summary.json").write_text(
                json.dumps(summary, indent=2, sort_keys=True) + "\n"
            )
            (evidence / "old-report.json").write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n"
            )
            print(json.dumps(summary, sort_keys=True))
            return
        expected = json.loads((evidence / "old-seed-summary.json").read_text())[
            "old_history_sha256"
        ]
        db = instance / "accounting.sqlite"
        if mode == "probe_conflicts":
            check_historical(owner, sender, base, admin_token, db, expected, 3)
            related = start(
                DID,
                "attempt.related",
                ACCOUNT,
                "task.old",
                "logical.original",
                "fallback",
                "attempt.old",
            )
            related_error = rejected(lambda: sender.submit_observation(related))
            reverse_error = rejected(
                lambda: sender.submit_observation(
                    {
                        "integration_version": "2",
                        "event_id": "link.reverse",
                        "dataset_id": "dataset.c03.mixed.startfirst",
                        "kind": "lineage",
                        "occurred_at": AT,
                        "attempt_id": "attempt.reverse.legacy",
                        "logical_operation_id": "logical.reverse",
                        "attempt_role": "fallback",
                        "predecessor_attempt_id": "attempt.reverse.pending",
                    }
                )
            )
            node = node_actor(
                base,
                secrets / "ingest.token",
                instance / "consumer-node24/node_modules/@cognitivedynamics/ezllmrouter-client",
                "probe",
                evidence,
            )
            assert history_hash(db) == expected
            summary = {
                "mode": mode,
                "result": "PASS",
                "related_error": related_error,
                "reverse_error": reverse_error,
                "node_link_first_error": node["rejected_v1_after_v2_lineage"],
                "old_history_sha256": expected,
                "new_accepted_events": 0,
            }
            (evidence / "probe-conflicts-summary.json").write_text(
                json.dumps(summary, indent=2, sort_keys=True) + "\n"
            )
            print(json.dumps(summary, sort_keys=True))
            return
        if mode == "seed_corrected":
            _seed_corrected_accounting_history(
                admin_token,
                base,
                db,
                evidence,
                expected,
                ingest_token,
                instance,
                owner,
                secrets,
                sender,
            )
        report, exported, rows = check_historical(owner, sender, base, admin_token, db, expected, 3)
        assert len(exported["events"]) == 5
        assert owner.report("dataset.c03.mixed.linkfirst")["attempt_count"] == 1
        assert owner.report("dataset.c03.mixed.startfirst")["attempt_count"] == 2
        pure = owner.report("dataset.c03.pure")
        assert pure["attempt_count"] == 2
        assert (
            next(row for row in pure["attempts"] if row["attempt_id"] == "attempt.pure.child")[
                "lineage_status"
            ]
            == "linked"
        )
        node_actor(
            base,
            secrets / "ingest.token",
            instance / "consumer-node24/node_modules/@cognitivedynamics/ezllmrouter-client",
            "verify",
            evidence,
        )
        if mode == "seed_corrected":
            (evidence / "corrected-report.json").write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n"
            )
            (evidence / "corrected-export.json").write_text(
                json.dumps(exported, indent=2, sort_keys=True) + "\n"
            )
            (evidence / "corrected-report.csv").write_text(csv_report(base, admin_token, DID))
        summary = {
            "mode": mode,
            "result": "PASS",
            "old_history_sha256": expected,
            "old_history_unchanged": history_hash(db) == expected,
            "historical_attempts_after": 3,
            "historical_events_after": 5,
            "known_usd": "0.010000000",
            "unknown_cost_attempts": 2,
            "mixed_link_first_attempts": 1,
            "mixed_start_first_attempts": 2,
            "pure_v2_attempts": 2,
        }
        (evidence / (mode + "-summary.json")).write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n"
        )
        print(json.dumps(summary, sort_keys=True))


def _seed_corrected_accounting_history(
    admin_token, base, db, evidence, expected, ingest_token, instance, owner, secrets, sender
):
    check_historical(owner, sender, base, admin_token, db, expected, 2)
    related = start(
        DID,
        "attempt.related",
        ACCOUNT,
        "task.old",
        "logical.original",
        "fallback",
        "attempt.old",
    )
    rejected(lambda: sender.submit_observation(related))
    unrelated = start(DID, "attempt.after", ACCOUNT, "task.after", "logical.after")
    receipt = sender.submit_observation(unrelated)
    assert sender.submit_observation(unrelated) == receipt
    assert sender.recover_receipt(DID, unrelated["event_id"]) == receipt
    assert history_hash(db) == expected
    for did in (
        "dataset.c03.mixed.linkfirst",
        "dataset.c03.mixed.startfirst",
        "dataset.c03.pure",
    ):
        assert owner.create_dataset(dataset(did))["dataset_id"] == did
        assert owner.register_account(account(did, "account:" + did))["revision"] == 1
    package = instance / "consumer-node24/node_modules/@cognitivedynamics/ezllmrouter-client"
    assert package.is_dir()
    node_actor(base, secrets / "ingest.token", package, "seed", evidence)
    did = "dataset.c03.mixed.startfirst"
    legacy = {
        "integration_version": "1",
        "event_id": "event.reverse.legacy",
        "dataset_id": did,
        "kind": "attempt_started",
        "occurred_at": AT,
        "attempt_id": "attempt.reverse.legacy",
        "started_at": AT,
        "task_id": "task.reverse",
        "step_id": "step.c03",
        "run_id": "run.reverse",
        "root_run_id": "run.reverse",
        "actor_kind": "agent",
        "actor_id": "agent.synthetic",
        "provider_account_id": "account:" + did,
        "model_id": "model.synthetic",
        "context_ref": "context.reverse",
    }
    with IntegrationClient(base, ingest_token, version="1") as v1:
        accepted = v1.submit_observation(legacy)
        assert v1.submit_observation(legacy) == accepted
        assert v1.recover_receipt(did, legacy["event_id"]) == accepted
    rejected(
        lambda: sender.submit_observation(
            {
                "integration_version": "2",
                "event_id": "link.reverse",
                "dataset_id": did,
                "kind": "lineage",
                "occurred_at": AT,
                "attempt_id": "attempt.reverse.legacy",
                "logical_operation_id": "logical.reverse",
                "attempt_role": "fallback",
                "predecessor_attempt_id": "attempt.reverse.pending",
            }
        )
    )
    sender.submit_observation(
        start(
            did,
            "attempt.reverse.unrelated",
            "account:" + did,
            "task.reverse.unrelated",
            "logical.reverse.unrelated",
        )
    )


if __name__ == "__main__":
    main()
