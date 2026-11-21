"""Rebuild public synthetic release databases; never check database files into Git.

Explicit maintenance command: python -m tests.fixtures.schema_upgrades --write
Review the seed and every changed golden value before committing regenerated manifests.
"""

import argparse
import base64
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ezllmrouter_server import schema
from ezllmrouter_server.integration_accounting import ExternalAccounting
from ezllmrouter_server.operator_projection import OperatorProjection
from ezllmrouter_server.store import SQLiteStore

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/schema-upgrades"
AT = "2026-11-01T00:00:00Z"
PRINCIPAL = "svc.synthetic.upgrade"


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def seed_rows():
    """Fixed public data, including historical corrections and erased content."""
    rows = {
        "registry_meta": [["authority_revision", "17"]],
        "registry_principals": [[PRINCIPAL, {"id": PRINCIPAL, "revision": 3, "status": "active"}]],
        "registry_models": [
            ["cfg.synthetic", {"revision": 4, "status": "active", "model": "model.é"}]
        ],
        "registry_prices": [
            [
                "cfg.synthetic",
                "price.old",
                {"amount_decimal": "0.000000000000123456789", "revision": 1},
            ],
            [
                "cfg.synthetic",
                "price.new",
                {"amount_decimal": "0.000000000000987654321", "revision": 2},
            ],
        ],
        "registry_grants": [[PRINCIPAL, "cfg.synthetic", {"revision": 7, "status": "revoked"}]],
        "registry_audit": [[42, "owner.synthetic", "set_grant", PRINCIPAL, 6, 7, 17, AT]],
        "registry_audit_values": [[42, {"status": "active"}, {"status": "revoked"}]],
        "submissions": [],
        "work_key_owners": [],
        "intents": [],
        "guard_dispatches": [],
        "usage_revisions": [],
        "personal_campaigns": [
            ["campaign.synthetic", {"state": "closed", "allowance_decimal": "1.000000001"}]
        ],
        "personal_campaign_attempts": [
            [
                "attempt.0",
                "submission.0",
                "campaign.synthetic",
                "0.500000000",
                "0.125000001",
                "settled",
                2,
            ]
        ],
        "registry_observations": [],
    }
    for index, state in enumerate(("completed", "completed", "outcome_unknown")):
        submission, attempt = f"submission.{index}", f"attempt.{index}"
        key = {
            "principal_id": PRINCIPAL,
            "task_id": "task.synthetic",
            "step_id": f"step.{index}",
            "step_revision": 1,
            "execution_generation": "gen.synthetic",
        }
        key_json = encoded(key)
        record = {
            "submission_id": submission,
            "attempt_id": attempt,
            "principal_id": PRINCIPAL,
            "task_id": "task.synthetic",
            "work_key": key,
            "work_digest": "sha256:" + str(index) * 64,
            "submission_state": state,
            "dispatch_state": "response_observed" if index < 2 else "outcome_unknown",
            "candidate_access": "expired",
            "content_store_allowed": False,
            "candidate": None,
            "status_revision": 4,
            "updated_at": AT,
        }
        rows["submissions"].append(
            [submission, PRINCIPAL, "task.synthetic", key_json, record["work_digest"], record]
        )
        rows["work_key_owners"].append([PRINCIPAL, key_json, "0.2", submission])
        rows["intents"].append(
            [
                attempt,
                submission,
                {
                    "attempt_id": attempt,
                    "plan_id": f"plan.{index}",
                    "committed_at": AT,
                    "destination": {
                        "configuration_ref": "cfg.synthetic",
                        "model": "model.synthetic",
                    },
                },
            ]
        )
        rows["guard_dispatches"].append(
            [
                attempt,
                submission,
                {
                    "attempt_id": attempt,
                    "plan_id": f"plan.{index}",
                    "body_sha256": "a" * 64,
                    "body_bytes": 123,
                    "committed_at": AT,
                },
            ]
        )
    for attempt, revision, amount in (
        (0, 1, "9.999999999"),
        (0, 2, "0.125000001"),
        (1, 1, "0.200000000"),
    ):
        rows["usage_revisions"].append(
            [
                f"attempt.{attempt}",
                revision,
                f"submission.{attempt}",
                {
                    "revision": revision,
                    "price_version": "price.old",
                    "cost": {"status": "calculated", "currency": "USD", "amount_decimal": amount},
                    "normalized_usage": {
                        "input_uncached": {"state": "known", "count": 12},
                        "output_text": {"state": "known", "count": 8},
                    },
                },
            ]
        )
    external_rows(rows)
    for index in range(30):
        observation = {
            "operation_id": f"probe.{index:02}",
            "connection_id": "connection.synthetic",
            "operation": "inventory" if index < 3 else "readiness",
            "state": ("observed", "partial", "failed")[min(index, 2)],
            "models": ["model.retained"] if index == 0 else [],
            "observed_at": AT,
        }
        rows["registry_observations"].append(
            [observation["operation_id"], observation["connection_id"], observation]
        )
    return rows


def external_rows(rows):
    examples = json.loads(
        (ROOT / "tests/fixtures/contracts/integration-readiness-v2/examples.json").read_text()
    )
    dataset = dict(examples["dataset"], dataset_id="dataset.synthetic")
    account = dict(
        examples["account"],
        dataset_id=dataset["dataset_id"],
        registered_at=dataset["activated_at"],
        revision=1,
    )
    rows["integration_datasets"] = [[dataset["dataset_id"], dataset]]
    rows["integration_accounts"] = [[account["account_id"], dataset["dataset_id"], account]]
    rows["integration_account_history"] = [
        [
            account["account_id"],
            dataset["dataset_id"],
            revision,
            dict(account, revision=revision, state="disabled" if revision == 2 else "usable"),
        ]
        for revision in (1, 2)
    ]
    start = dict(examples["events"][0], dataset_id=dataset["dataset_id"])
    rows["integration_attempts"] = [
        [dataset["dataset_id"], start["attempt_id"], start["event_id"], start, 1]
    ]
    rows["integration_runs"] = [
        [dataset["dataset_id"], start["run_id"], start["root_run_id"], None, start["task_id"]]
    ]
    snapshot = dict(
        examples["snapshots"][0],
        dataset_id=dataset["dataset_id"],
        retention_until="2026-10-30T00:00:00Z",
        source_expires_at="2026-10-30T00:00:00Z",
    )
    snapshot.pop("features")
    rows["integration_snapshots"] = [
        [
            dataset["dataset_id"],
            snapshot["snapshot_id"],
            snapshot["attempt_id"],
            "feature",
            "sha256:" + "b" * 64,
            snapshot,
            None,
        ]
    ]
    rows["integration_events"] = []
    for original in examples["events"][:3]:
        event = dict(original, dataset_id=dataset["dataset_id"])
        rows["integration_events"].append(
            [
                "dataset.synthetic",
                event["event_id"],
                event["kind"],
                event["attempt_id"],
                event.get("usage_revision"),
                "sha256:" + digest(event),
                event,
                {"accepted": True, "event_id": event["event_id"]},
            ]
        )


def apply_sql(connection, source):
    statement = ""
    for line in source.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ""
    if statement.strip():
        raise ValueError("incomplete fixture SQL")


def build(path, version):
    """Use immutable SQL resources, not today's application constructors, for old releases."""
    with closing(sqlite3.connect(path, isolation_level=None)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        for number in range(1, version + 1):
            source, checksum = schema.migration(number)
            apply_sql(connection, source)
            connection.execute("INSERT INTO schema_revisions VALUES (?,?)", (number, checksum))
            if number == 1:
                for table, rows in seed_rows().items():
                    for row in rows:
                        values = [
                            encoded(cell) if isinstance(cell, (dict, list)) else cell
                            for cell in row
                        ]
                        connection.execute(
                            f'INSERT INTO "{table}" VALUES ({",".join("?" for _ in values)})',
                            values,
                        )
        connection.execute(f"PRAGMA application_id={schema.APPLICATION_ID}")
        connection.execute(f"PRAGMA user_version={version}")
        connection.execute("COMMIT")


def table_manifest(connection):
    tables = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return {
        table: {"rows": len(rows), "sha256": digest(rows)}
        for (table,) in tables
        if table != "schema_revisions"
        for rows in [connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()]
    }


def report(store):
    projection = OperatorProjection(store, PRINCIPAL)
    with patch("ezllmrouter_server.integration_accounting._time", return_value=AT):
        external = ExternalAccounting(SimpleNamespace(store=store))
        external_report = external.report(
            {"principal_id": "owner.local", "owner": "owner.local", "role": "registry_admin"},
            "dataset.synthetic",
            version="2",
        )
    return {
        "usage": projection.usage(),
        "overview": projection.overview_counts(),
        "activity": projection.activity(),
        "external": external_report,
    }


def keyring_vector():
    """Public AES test key/nonce; deliberately deterministic, never a usable credential."""
    purpose, context = "synthetic-upgrade-only", b"fixture.account:1"
    key, nonce = bytes(range(32)), bytes(range(12))
    key_id = "key." + hashlib.sha256(purpose.encode() + b"\0" + key).hexdigest()[:32]
    aad = encoded(
        {
            "version": 1,
            "purpose": purpose,
            "key_id": key_id,
            "context": base64.b64encode(context).decode(),
        }
    ).encode()
    ciphertext = AESGCM(key).encrypt(nonce, b"PUBLIC_SYNTHETIC_VECTOR_ONLY", aad)
    return {
        "notice": "Public synthetic AES vector; never production material",
        "keyring": {
            "version": 1,
            "purpose": purpose,
            "active_key_id": key_id,
            "mac_key": base64.b64encode(bytes(range(32, 64))).decode(),
            "keys": {key_id: base64.b64encode(key).decode()},
        },
        "envelope": {
            "version": 1,
            "purpose": purpose,
            "key_id": key_id,
            "nonce": base64.b64encode(nonce).decode(),
            "ciphertext": base64.b64encode(ciphertext).decode(),
        },
        "context": context.decode(),
        "plaintext": "PUBLIC_SYNTHETIC_VECTOR_ONLY",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", required=True)
    parser.parse_args()
    FIXTURES.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        for version in range(1, schema.VERSION + 1):
            path = Path(temporary) / f"v{version}.sqlite"
            build(path, version)
            with closing(sqlite3.connect(path)) as connection:
                source = table_manifest(connection)
            with closing(SQLiteStore(path)) as store:
                payload = {
                    "format": "ezllmrouter-synthetic-upgrade-v1",
                    "version": version,
                    "seed_sha256": digest(seed_rows()),
                    "migrations": {
                        name: schema.migration(i)[1]
                        for i, name in enumerate(schema.MIGRATIONS[:version], 1)
                    },
                    "source_tables": source,
                    "head_tables": table_manifest(store.db),
                    "head_report": report(store),
                }
            (FIXTURES / f"v{version:03}.json").write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
            )
    (FIXTURES / "keyring-v001.json").write_text(json.dumps(keyring_vector(), indent=2) + "\n")


if __name__ == "__main__":
    main()
