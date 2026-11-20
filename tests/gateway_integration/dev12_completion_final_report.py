"""Authenticated report-only check against a copy of the final synthetic target.

The disposable server has no runner, worker, guard, sender or receiver.
The copied SQLite file is private local test material and is excluded from
the portable export. HTTP JSON/CSV observations are safe review evidence.
"""

from __future__ import annotations

import csv
from decimal import Decimal
from hashlib import sha256
import io
import json
from pathlib import Path
import shutil
import socket
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server/src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import httpx

from ezllmrouter_server.operator_projection import OperatorProjection
from ezllmrouter_server.operator_web import serve
from ezllmrouter_server.store import SQLiteStore
from dev12_completion_operator_handlers import _csv_finance_reconcile


def census(path):
    import sqlite3

    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return {
            table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "dev12_submissions",
                "dev12_send_ownership",
                "dev12_usage_revisions",
                "dev12_campaign_audit",
            )
        }
    finally:
        db.close()


def main():
    source, output = map(Path, sys.argv[1:3])
    if output.exists() or source.is_symlink() or not source.is_file():
        raise ValueError("distinct existing target and new report-only directory required")
    before = census(source)
    source_hash = sha256(source.read_bytes()).hexdigest()
    output.mkdir(parents=True)
    copy = output / "report-only.sqlite"
    shutil.copyfile(source, copy)
    assert census(copy) == before
    store = SQLiteStore(copy)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    password = "dev12.report.only.synthetic." + "x" * 32
    server = serve(
        "127.0.0.1",
        port,
        projection=OperatorProjection(store, "user.demo", str(output / "no-send-events.jsonl")),
        runner=None,
        password=password,
        fixture={"destination": {}, "policy": {}},
        build={"commit": "final-synthetic-report-copy", "dirty": False, "fingerprint": source_hash},
        web_root=Path(__file__).resolve().parents[2] / "web",
        worker_probe=lambda: {"state": "absent"},
        sender_status=lambda: {"state": "absent"},
        successor_store=store,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with httpx.Client(
            base_url=origin, timeout=10, trust_env=False, headers={"Origin": origin}
        ) as client:
            denied = client.get("/operator/v1/dev12-usage")
            login = client.post("/operator/v1/login", json={"password": password})
            report_response = client.get("/operator/v1/dev12-usage?export=json")
            csv_response = client.get("/operator/v1/dev12-usage?export=csv")
            ui_response = client.get("/usage_costs_view.js")
        assert (
            denied.status_code,
            login.status_code,
            report_response.status_code,
            csv_response.status_code,
            ui_response.status_code,
        ) == (401, 200, 200, 200, 200)
        report = report_response.json()
        csv_rows = list(csv.DictReader(io.StringIO(csv_response.text)))
        good, finance = _csv_finance_reconcile(csv_rows, report["attempts"], report["total"])
        assert good, finance
        assert len(csv_rows) == report["total"]["attempts"] == before["dev12_submissions"]
        assert report["total"]["current_held_reservations"] == 3
        assert Decimal(report["total"]["current_held_bound_usd"]) == Decimal("0.000600000")
        assert "over_bound" in ui_response.text
        assert census(source) == before
        assert sha256(source.read_bytes()).hexdigest() == source_hash
        assert not (output / "no-send-events.jsonl").exists()
        observation = {
            "kind": "dev12_final_synthetic_report_only_http_v1",
            "source_database_sha256": source_hash,
            "http": {
                "unauthenticated": denied.status_code,
                "login": login.status_code,
                "json": report_response.status_code,
                "csv": csv_response.status_code,
                "ui_asset": ui_response.status_code,
            },
            "census_before_after": before,
            "csv_finance_reconciliation": finance,
            "sender_worker_receiver": "absent",
            "local_read_get_count": 4,
            "report_total": report["total"],
        }
        (output / "HTTP-OBSERVATION.json").write_text(
            json.dumps(observation, sort_keys=True, indent=2) + "\n"
        )
        (output / "REPORT.json").write_bytes(report_response.content)
        (output / "REPORT.csv").write_bytes(csv_response.content)
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "attempts": len(csv_rows),
                    "known_usd": report["total"]["known_usd"],
                    "held_usd": report["total"]["current_held_bound_usd"],
                    "source_sha256": source_hash,
                },
                sort_keys=True,
            )
        )
    finally:
        server.shutdown()
        server.server_close()
        server.operator_jobs.shutdown(wait=True)
        thread.join(timeout=5)
        store.close()


if __name__ == "__main__":
    main()
