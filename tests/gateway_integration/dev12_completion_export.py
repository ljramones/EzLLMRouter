"""Read-only, secret-excluding export of the synthetic DEV-12 target.

Run with isolated Python against an owned artifact root. The source database is
opened read-only in one transaction; this never opens the owner profile.
"""
from __future__ import annotations

import argparse
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import sqlite3


SUCCESSOR_TABLES = (
    "dev12_campaigns", "dev12_campaign_attempts", "dev12_campaign_audit",
    "dev12_submissions", "dev12_send_ownership", "dev12_usage_revisions",
    "dev12_evidence_events", "dev12_authority", "dev12_authority_audit",
)
LEGACY_TABLES = ("submissions", "intents", "guard_dispatches",
                 "usage_revisions", "work_key_owners")
TABLES = SUCCESSOR_TABLES + LEGACY_TABLES
ROOT_FILES = (
    "case-journal.jsonl", "guard.jsonl", "receiver.jsonl",
    "receiver-receipts.jsonl", "release-gate.jsonl",
    "release-identity.jsonl", "preflight-write-probe.json",
    "operator-browser-evidence.json", "preview-browser-evidence.json",
    "recovery-chain-reference.json", "cert.pem", "send-events.jsonl",
)
SECRET_KEYS = {"password", "secret", "token", "authorization", "private_key",
               "bearer", "credential_secret", "signing_key"}


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def assert_public_json(value, location="$"):
    if isinstance(value, dict):
        for key, child in value.items():
            # This sole test label names the request-header mutation. Its value
            # contains before/after counters and a rejected response, no header.
            test_label = (location == "$.payload.observations" and key == "authorization"
                          and isinstance(child, dict) and
                          set(child) == {"before", "after", "guard_delta",
                                         "receiver_delta", "response"})
            if key.casefold() in SECRET_KEYS and not test_label:
                raise ValueError(f"sensitive field at {location}.{key}")
            assert_public_json(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_public_json(child, f"{location}[{index}]")
    elif isinstance(value, str) and "-----BEGIN PRIVATE KEY-----" in value:
        raise ValueError(f"private key content at {location}")


def copy_public(source, dest):
    if not source.is_file() or source.is_symlink():
        raise ValueError(f"missing or linked source: {source}")
    if source.suffix == ".json":
        contents = source.read_text()
        if source.name == "preflight-write-probe.json":
            for line in contents.splitlines():
                assert_public_json(json.loads(line))
        else:
            assert_public_json(json.loads(contents))
    elif source.suffix == ".jsonl":
        for line in source.read_text().splitlines():
            assert_public_json(json.loads(line))
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("xb") as stream:
        stream.write(source.read_bytes())


def logical_tables(source_db):
    connection = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("BEGIN")
    table_export = {}
    for table in TABLES:
        schema_row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if schema_row is None:
            continue
        rows = [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid")]
        for row in rows:
            for key, item in row.items():
                if key in {"record", "usage", "evidence", "guard_receipt",
                           "intent", "receipt", "work_key"} or (
                    key == "state" and item[:1] in {"{", "["}
                ):
                    assert_public_json(json.loads(item), f"{table}.{key}")
        table_export[table] = {"schema": schema_row["sql"],
            "columns": [key for key in rows[0]] if rows else
            [row[1] for row in connection.execute(f"PRAGMA table_info({table})")],
            "rows": rows}
    connection.execute("COMMIT")
    connection.close()
    return table_export


def export(root: Path, out: Path, packages: Path):
    if out.exists():
        raise ValueError("export directory already exists; retained evidence is immutable")
    if root.resolve() == out.resolve() or root.resolve() in out.resolve().parents:
        raise ValueError("export must be outside mutable target root")
    out.mkdir(parents=True)
    source_db = root / "campaign.sqlite"
    table_export = logical_tables(source_db)
    if set(table_export) != set(TABLES):
        raise ValueError("main target database lacks required review tables")
    (out / "ledger.json").write_text(json.dumps(table_export, sort_keys=True,
        indent=2, ensure_ascii=True) + "\n")
    historical_db = root / "cases" / "case.t50_e.composed-historical.sqlite"
    if historical_db.exists():
        historical = {"transformation": "read-only logical export of selected public dev12 tables",
            "source_path": "cases/case.t50_e.composed-historical.sqlite",
            "source_sha256": digest(historical_db),
            "tables": logical_tables(historical_db)}
        (out / "historical-underbound-ledger.json").write_text(json.dumps(
            historical, sort_keys=True, indent=2, ensure_ascii=True) + "\n")
    for name in ROOT_FILES:
        path = root / name
        if path.exists():
            copy_public(path, out / "target" / name)
    for path in sorted(root.glob("receiver.continue*.cert.pem")):
        copy_public(path, out / "target" / path.name)
    for path in sorted(root.glob("plan*.json")) + sorted(root.glob("preflight-receipt*.json")):
        copy_public(path, out / "target" / path.name)
    omitted = []
    for path in sorted((root / "cases").glob("*.json")):
        if path.name.endswith("-private-input.json"):
            omitted.append({"path": str(path.relative_to(root)),
                            "original_sha256": digest(path),
                            "reason": "synthetic credential input; excluded from public review"})
            continue
        copy_public(path, out / "target" / "cases" / path.name)
    (out / "OMISSIONS.json").write_text(json.dumps(omitted, sort_keys=True,
        indent=2) + "\n")
    for path in sorted((root / "screenshots").glob("*.png")):
        copy_public(path, out / "target" / "screenshots" / path.name)
    for name, expected in (
        ("cognitivedynamics_ezllmrouter_client-0.3.0-py3-none-any.whl",
         "d4cdea6ffabd7aa62985040e4a92a4870d73dc8e4240f43d4472d86ce595bb98"),
        ("cognitivedynamics-ezllmrouter-client-0.3.0.tgz",
         "b871b64c98e299e031e4a6e11766a06e7a494f6e4b8b787fd70bfb8144694a3f"),
    ):
        source = packages / name
        if digest(source) != expected:
            raise ValueError(f"installed package identity mismatch: {name}")
        copy_public(source, out / "packages" / name)
    campaigns = [json.loads(row["record"]) for row in table_export["dev12_campaigns"]["rows"]]
    if len(campaigns) != 1:
        raise ValueError("expected one isolated campaign")
    campaign = campaigns[0]
    revisions = {}
    for row in table_export["dev12_usage_revisions"]["rows"]:
        usage = json.loads(row["usage"])
        prior = revisions.get(row["attempt_id"])
        if prior is None or row["revision"] > prior["revision"]:
            revisions[row["attempt_id"]] = usage
    known = sum((Decimal(row["amount_decimal"]) for row in revisions.values()
                 if row["cost_status"] in {"calculated", "over_bound"}), Decimal(0))
    records = [json.loads(row["record"]) for row in table_export["dev12_submissions"]["rows"]]
    audit = {"campaign_id": campaign["campaign_id"], "campaign": campaign,
        "source_database_sha256": digest(source_db),
        "export_kind": "exact public rows and files; private key and credential inputs excluded",
        "admissions": len(records),
        "possible_sends": len(table_export["dev12_send_ownership"]["rows"]),
        "usage_revision_rows": len(table_export["dev12_usage_revisions"]["rows"]),
        "latest_effective_attempts": len(revisions),
        "latest_known_amount_decimal": str(known),
        "exposure_states": {state: sum(row["exposure_state"] == state for row in records)
                             for state in sorted({row["exposure_state"] for row in records})},
        "receiver_arrivals": len((root / "receiver.jsonl").read_text().splitlines()),
        "journal_rows": len((root / "case-journal.jsonl").read_text().splitlines())}
    audit["legacy_primary"] = {name: len(table_export[name]["rows"])
                               for name in LEGACY_TABLES if name != "work_key_owners"}
    audit["shared_work_key_owners"] = len(table_export["work_key_owners"]["rows"])
    audit["mixed_admissions"] = audit["admissions"] + audit["legacy_primary"]["submissions"]
    legacy_possible = {row["attempt_id"] for name in ("intents", "guard_dispatches")
                       for row in table_export[name]["rows"]}
    audit["mixed_possible_send_conservative_upper_count"] = (
        audit["possible_sends"] + len(legacy_possible))
    audit["legacy_cost_basis"] = "unobserved; no native usage row or admitted finite reservation"
    (out / "AUDIT.json").write_text(json.dumps(audit, sort_keys=True, indent=2) + "\n")
    manifest = []
    for path in sorted(out.rglob("*")):
        if path.is_file():
            manifest.append(f"{digest(path)}  {path.relative_to(out)}")
    (out / "MANIFEST.sha256").write_text("\n".join(manifest) + "\n")
    return audit, len(manifest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target_root", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("packages_dir", type=Path)
    args = parser.parse_args()
    audit, files = export(args.target_root, args.output_dir, args.packages_dir)
    print(json.dumps({"files": files, "audit": audit}, sort_keys=True))


if __name__ == "__main__":
    main()
