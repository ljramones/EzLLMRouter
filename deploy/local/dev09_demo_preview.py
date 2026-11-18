#!/usr/bin/env python3
"""Run the DEV-09 scripted UI against a disposable local registry."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import secrets
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/src"))

from duranki_server.operator_projection import OperatorProjection
from duranki_server.operator_web import serve
from duranki_server.registry import Registry
from duranki_server.store import SQLiteStore


class Authority:
    def __init__(self):
        self.gate = threading.RLock()
        self.epoch = 0


class NoModelWork:
    def run(self, *_):
        raise RuntimeError("DISPOSABLE_DEMO_HAS_NO_MODEL_WORKER")


def main():
    parser = argparse.ArgumentParser(description="Disposable DEV-09 scripted console preview")
    parser.add_argument("--port", type=int, default=8799)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    credential = secrets.token_urlsafe(36)
    fixture = json.loads((ROOT / "tests/gateway_integration/dev05_fixture.json").read_text())
    with tempfile.TemporaryDirectory(prefix="duranki-dev09-demo-preview-") as temporary:
        store = SQLiteStore(Path(temporary) / "preview.sqlite")
        server = None
        try:
            registry = Registry(store, Authority(), legacy_destination={
                "configuration_ref": "cfg.demo", "service": "litellm.dev04", "endpoint": "127.0.0.1",
                "model": "model.demo", "model_version": "v1", "processing_region": "local"},
                legacy_token="disposable-preview-token-00000000000000000",
                legacy_trusted={"principal_id": "svc.demo", "charging_owner_id": "demo.team.mach33"})
            server = serve("127.0.0.1", args.port, projection=OperatorProjection(store, "svc.demo"),
                runner=NoModelWork(), password=credential, fixture=fixture,
                build={"commit": "source-preview", "dirty": True}, web_root=ROOT / "web",
                worker_probe=lambda: {"state": "not configured"},
                sender_status=lambda: {"state": "not configured"}, registry=registry)
            print(f"Disposable scripted demo: http://127.0.0.1:{args.port}/#/usage", flush=True)
            print(f"Temporary operator credential: {credential}", flush=True)
            print("Open Usage & Costs, then Open demo workspace. Ctrl-C removes the temporary database.",
                  flush=True)
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            if server:
                server.server_close()
                server.operator_jobs.shutdown(wait=True)
            store.close()


if __name__ == "__main__":
    main()
