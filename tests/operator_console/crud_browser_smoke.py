#!/usr/bin/env python3
"""Disposable actual-browser CRUD proof against the current source and a temporary SQLite store."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/src"))
sys.path.insert(0, str(ROOT / "deploy/local"))

from crud_browser import run_browser
from duranki_server.operator_projection import OperatorProjection
from duranki_server.operator_web import serve
from duranki_server.registry import Registry
from duranki_server.store import SQLiteStore


class Authority:
    def __init__(self):
        self.gate = threading.RLock()
        self.epoch = 0


class NeverRun:
    def run(self, *_):
        raise AssertionError("CRUD browser proof must not launch a model request")


def counters(store):
    db = store.db
    names = ("submissions", "intents", "guard_dispatches")
    result = {name: db.execute("SELECT COUNT(*) FROM " + name).fetchone()[0] for name in names}
    result["caller_lookups"] = db.execute(
        "SELECT COALESCE(SUM(caller_lookups),0) FROM operator_launches").fetchone()[0]
    return result


def main():
    if len(sys.argv) > 2 or (len(sys.argv) == 2 and sys.argv[1] not in ("02", "03")):
        raise SystemExit("usage: crud_browser_smoke.py [02|03]")
    suffix = "-" + sys.argv[1] if len(sys.argv) == 2 else ""
    identity = "crud-local-proof" + suffix
    evidence = ROOT / ".artifacts/browser/dev-07/screenshots"
    result_path = ROOT / (".artifacts/browser/dev-07/CRUD-LOCAL-BROWSER-RESULT" + suffix + ".json")
    if result_path.exists():
        raise SystemExit("local browser result already exists; preserve prior proof")
    with tempfile.TemporaryDirectory(prefix="duranki-crud-browser-") as scratch:
        location = Path(scratch)
        store_path = location / "metadata.sqlite"
        store = SQLiteStore(store_path)
        fixture = json.loads((ROOT / "tests/gateway_integration/dev05_fixture.json").read_text())
        destination = {**fixture["destination"], "service": "litellm.dev04", "endpoint": "127.0.0.1"}
        authority = Authority()
        registry = Registry(store, authority, legacy_destination=destination,
            legacy_token="local-browser-test-token-00000000000000000000",
            legacy_trusted=fixture["trusted_context"])
        projection = OperatorProjection(store, "svc.demo")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        server = serve("127.0.0.1", port, projection=projection, runner=NeverRun(),
            password="p" * 40, fixture=fixture, build={"commit": "local-disposable-proof"},
            web_root=ROOT / "web", worker_probe=lambda: {"state": "live"},
            sender_status=lambda: {"state": "live"}, registry=registry)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        before = counters(store)
        run = location / "browser"
        run.mkdir(mode=0o700)
        try:
            result = run_browser(run, "p" * 40, "catalogue.operator." + identity,
                "user." + identity, "cfg.demo", f"http://127.0.0.1:{port}/")
            after = counters(store)
            if before != after:
                raise RuntimeError("browser CRUD created model traffic")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            server.operator_jobs.shutdown(wait=True)
            store.close()
        reopened = SQLiteStore(store_path)
        try:
            persisted = Registry(reopened, Authority(), legacy_destination=destination,
                legacy_token="local-browser-test-token-00000000000000000000",
                legacy_trusted=fixture["trusted_context"])
            model = persisted.model("catalogue.operator." + identity)
            user = persisted.principal("user." + identity)
            grant = persisted.grant("user." + identity, "cfg.demo")
            if (model["status"] != "archived" or user["status"] != "revoked" or
                    grant["status"] != "removed" or
                    model["catalogue"]["price_reference"]["snapshot_id"] != "test.reference.v2" or
                    model["reference_price_history"][0]["price"]["snapshot_id"] != "test.reference.v1"):
                raise RuntimeError("disposable SQLite reopen readback failed")
            after_reopen = counters(reopened)
            if after_reopen != before:
                raise RuntimeError("SQLite reopen changed model traffic")
        finally:
            reopened.close()
        evidence.mkdir(parents=True, exist_ok=True)
        screenshots = []
        for item in result["screenshots"]:
            target = evidence / ("crud-local" + suffix + "-" + item["file"])
            if target.exists():
                raise RuntimeError("screenshot evidence path already exists")
            shutil.copy2(run / item["file"], target)
            screenshots.append({"path": str(target.relative_to(ROOT)), "sha256": item["sha256"]})
        safe = {"status": "PASS", "scope": "temporary SQLite and actual local headless Chrome; target profile pending",
            "model": "catalogue.operator." + identity, "user": "user." + identity,
            "model_status_after_reopen": model["status"], "user_status_after_reopen": user["status"],
            "grant_status_after_reopen": grant["status"],
            "price_snapshots": ["test.reference.v1", "test.reference.v2"],
            "traffic_before_after": before, "screenshots": screenshots,
            "confirmed_dialogs": result["confirmed_dialogs"], "keyboard_tab": result["keyboard_tab"],
            "sign_out_http": result["sign_out_http"],
            "crud_source_sha256": hashlib.sha256((ROOT / "web/crud_view.js").read_bytes()).hexdigest(),
            "registry_source_sha256": hashlib.sha256((ROOT / "server/src/duranki_server/registry.py").read_bytes()).hexdigest()}
        result_path.write_text(json.dumps(safe, indent=2, sort_keys=True) + "\n")
        print(json.dumps(safe, sort_keys=True))


if __name__ == "__main__":
    main()
