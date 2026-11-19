"""Report-only HTTP qualification of the retained imported underbound fixture.

This copies a zero-send fixture to an owned disposable directory. It starts no
Coordinator, model worker, guard, sender or receiver.
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
import httpx

from ezllmrouter_server.operator_projection import OperatorProjection
from ezllmrouter_server.operator_web import serve
from ezllmrouter_server.store import SQLiteStore


def main():
    source, output = map(Path, sys.argv[1:3])
    if output.exists() or source.is_symlink() or not source.is_file():
        raise ValueError("distinct retained source and new report-only output required")
    output.mkdir(parents=True)
    copy = output / "imported-historical.sqlite"
    shutil.copyfile(source, copy)
    store = SQLiteStore(copy)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    secret = "dev12.report.only.synthetic." + "x" * 32
    server = serve("127.0.0.1", port,
        projection=OperatorProjection(store, "user.demo", str(output / "no-send-events.jsonl")),
        runner=None, password=secret, fixture={"destination": {}, "policy": {}},
        build={"commit": "imported-historical-fixture", "dirty": False,
               "fingerprint": sha256(source.read_bytes()).hexdigest()},
        web_root=Path(__file__).resolve().parents[2] / "web",
        worker_probe=lambda: {"state": "absent"},
        sender_status=lambda: {"state": "absent"}, successor_store=store)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with httpx.Client(base_url=origin, timeout=5, trust_env=False,
                          headers={"Origin": origin}) as client:
            denied = client.get("/operator/v1/dev12-usage")
            login = client.post("/operator/v1/login", json={"password": secret})
            report_response = client.get("/operator/v1/dev12-usage?export=json")
            csv_response = client.get("/operator/v1/dev12-usage?export=csv")
            ui_response = client.get("/usage_costs_view.js")
        report = report_response.json()
        rows = list(csv.DictReader(io.StringIO(csv_response.text)))
        if (denied.status_code != 401 or login.status_code != 200 or
                report_response.status_code != 200 or csv_response.status_code != 200 or
                ui_response.status_code != 200 or len(rows) != 1 or
                report["total"]["over_bound_attempts"] != 1 or
                report["total"]["attempts"] != 1):
            raise AssertionError("report-only HTTP auth, CSV/JSON, or UI asset failed")
        row = report["attempts"][0]
        csv_row = rows[0]
        if (row["cost_status"] != "over_bound" or
                csv_row["cost_status"] != "over_bound" or
                row["amount_decimal"] != csv_row["amount_decimal"] or
                Decimal(row["amount_decimal"]) <= Decimal(row["reservation_decimal"]) or
                Decimal(report["total"]["known_usd"]) != Decimal(row["amount_decimal"]) or
                "over_bound" not in ui_response.text):
            raise AssertionError("unclamped historical over-bound projection absent")
        with store._lock:
            saved = store.db.execute("SELECT record FROM dev12_campaigns WHERE campaign_id=?",
                ("campaign.fixture.imported.underbound",)).fetchone()
        campaign = json.loads(saved[0]) if saved else None
        if (not campaign or not campaign["paused"] or
                campaign["possible_send_count"] != 0 or campaign["attempt_count"] != 0):
            raise AssertionError("imported affected scope must remain paused and zero-send")
        evidence = {"kind": "dev12_report_only_imported_overbound_http_v1",
            "fixture_source_sha256": sha256(source.read_bytes()).hexdigest(),
            "fixture_copy_sha256": sha256(copy.read_bytes()).hexdigest(),
            "denied_http": denied.status_code,
            "authorized_login_http": login.status_code,
            "json_http": report_response.status_code,
            "csv_http": csv_response.status_code,
            "ui_asset_http": ui_response.status_code,
            "report": report, "csv_rows": rows, "campaign": campaign,
            "no_sender_or_receiver_started": True}
        (output / "HTTP-OBSERVATION.json").write_text(json.dumps(evidence,
            sort_keys=True, indent=2, ensure_ascii=True) + "\n")
        print(json.dumps({"status": "PASS", "amount_decimal": row["amount_decimal"],
            "denied_http": denied.status_code, "attempts": report["total"]["attempts"]}))
    finally:
        server.shutdown()
        server.server_close()
        server.operator_jobs.shutdown(wait=True)
        thread.join(timeout=5)
        store.close()


if __name__ == "__main__":
    main()
