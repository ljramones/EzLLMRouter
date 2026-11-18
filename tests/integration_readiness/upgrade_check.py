"""Seed an isolated 0.0.0 registry, then verify its data after the 0.1.0 migration."""
from __future__ import annotations

import importlib.metadata
from pathlib import Path
import sqlite3
import sys
import threading

from duranki_server.registry import Registry
from duranki_server.store import SQLiteStore


class Authority:
    def __init__(self):
        self.gate = threading.RLock()
        self.epoch = 0
        self.revoked = True


DEST = {"configuration_ref": "cfg.integration.upgrade", "service": "litellm.dev04",
        "endpoint": "127.0.0.1", "model": "model.demo", "model_version": "v1",
        "processing_region": "local"}


def main():
    mode, path = sys.argv[1], Path(sys.argv[2])
    assert path.is_absolute()
    store = SQLiteStore(path)
    try:
        if mode == "seed":
            assert importlib.metadata.version("mach33-duranki-server") == "0.0.0"
            registry = Registry(store, Authority(), legacy_destination=DEST,
                legacy_token="synthetic-upgrade-legacy-token-000000000000000",
                legacy_trusted={"principal_id": "svc.upgrade", "charging_owner_id": "team.upgrade"})
            registry.mutate("owner.local", {"operation_id": "op.upgrade.reader",
                "action": "create_principal", "subject": "user.upgrade.reader", "expected_revision": 0,
                "data": {"display_name": "Retained synthetic reader", "kind": "human",
                         "owner": "owner.local", "role": "ordinary"}})
            assert registry.principal("user.upgrade.reader")["revision"] == 1
            assert not store.db.execute("SELECT name FROM sqlite_master WHERE name='integration_meta'").fetchone()
        elif mode == "verify":
            assert importlib.metadata.version("mach33-duranki-server") == "0.1.0"
            registry = Registry(store, Authority())
            assert registry.principal("user.upgrade.reader")["display_name"] == "Retained synthetic reader"
            assert registry.principal("user.upgrade.reader")["revision"] == 1
            assert store.db.execute("SELECT value FROM integration_meta WHERE key='schema_version'").fetchone() == ("1",)
            assert registry.integration.datasets(registry.principal("owner.local"))["items"] == []
        else:
            raise ValueError("expected seed or verify")
        assert sqlite3.connect(path).execute("PRAGMA integrity_check").fetchone() == ("ok",)
        print("isolated service upgrade", mode, "PASS")
    finally:
        store.close()


if __name__ == "__main__":
    main()
