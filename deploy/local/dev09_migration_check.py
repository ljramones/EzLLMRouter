#!/usr/bin/env python3
"""Migrate only a disposable copy of the consistent owner-profile backup."""
from __future__ import annotations

import json
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import sys
import threading
import uuid

from ezllmrouter_server.registry import Registry
from ezllmrouter_server.reporting import usage_costs
from ezllmrouter_server.store import SQLiteStore


TABLES = ("submissions", "intents", "guard_dispatches", "usage_revisions", "registry_models",
          "registry_principals", "registry_grants", "registry_prices", "registry_connections",
          "registry_source_permissions", "registry_credentials", "registry_audit")
NEW_TABLES = ("registry_agents", "registry_agent_permissions", "registry_outcome_authorities",
              "attribution_runs", "attribution_outcomes")


class SendAuthority:
    def __init__(self):
        self.gate = threading.RLock()
        self.epoch = 0


def counts(db, names):
    return {name: db.execute("SELECT COUNT(*) FROM " + name).fetchone()[0] for name in names}


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: dev09_migration_check.py /backup/store.sqlite")
    source_path = Path(sys.argv[1])
    if not source_path.is_file():
        raise RuntimeError("read-only backup missing")
    if not os.access(source_path, os.R_OK):
        raise RuntimeError("mounted backup unreadable by migration user")
    copy_path = Path("/tmp/dev09-disposable-migration-" + uuid.uuid4().hex + ".sqlite")
    if copy_path.exists():
        raise RuntimeError("disposable migration copy already exists")
    # The owner-created backup is a complete, host-checked snapshot. Only its
    # main file is mounted read-only; SQLite must not create WAL sidecars in
    # the container's non-writable /backup directory.
    with sqlite3.connect(f"file:{source_path}?mode=ro&immutable=1", uri=True) as source:
        if source.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("backup quick_check failed")
        before = counts(source, TABLES)
        existing = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        before_new = counts(source, [name for name in NEW_TABLES if name in existing])
        cutoffs = [datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")]
        for table, field in (("submissions", "record"), ("usage_revisions", "usage")):
            maximum = source.execute("SELECT MAX(json_extract(" + field + ",'$." +
                ("created_at" if table == "submissions" else "recorded_at") + "')) FROM " + table).fetchone()[0]
            if maximum:
                cutoffs.append(maximum)
        legacy = source.execute("SELECT COUNT(*) FROM submissions "
            "WHERE json_extract(record,'$.attribution') IS NULL").fetchone()[0]
        with sqlite3.connect(copy_path) as target:
            source.backup(target)
    store = SQLiteStore(copy_path)
    try:
        registry = Registry(store, SendAuthority())
        migrated = counts(store.db, TABLES)
        new = counts(store.db, NEW_TABLES)
        if before != migrated or any(new[name] != before_new.get(name, 0) for name in NEW_TABLES):
            raise RuntimeError("disposable migration changed historical counts")
        report = usage_costs(registry, {"role": "registry_admin", "principal_id": "owner.local"},
            {"cutoff": max(cutoffs)})
        if report["total"]["attempts"] != before["submissions"] or \
                report["attribution_coverage"]["unknown_agent_attempts"] < legacy:
            raise RuntimeError("legacy attempts disappeared from disposable report")
    finally:
        store.close()
    reopened = SQLiteStore(copy_path)
    try:
        registry = Registry(reopened, SendAuthority())
        if counts(reopened.db, TABLES) != before or counts(reopened.db, NEW_TABLES) != new or \
                reopened.db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("disposable restart readback changed counts")
        print(json.dumps({"status": "PASS", "historical_table_counts": before,
            "new_table_counts": new, "legacy_unattributed_attempts": legacy,
            "reported_attempts": report["total"]["attempts"],
            "registry_authority_revision": registry.version()}, sort_keys=True))
    finally:
        reopened.close()


if __name__ == "__main__":
    main()
