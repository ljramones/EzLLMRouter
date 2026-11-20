"""Read-only authenticated report check over a copy of the retained campaign."""

from __future__ import annotations

if not __package__:
    import sys
    from pathlib import Path

    for _parent in Path(__file__).resolve().parents:
        if (_parent / "tools/gateway/__init__.py").is_file():
            sys.path.insert(0, str(_parent))
            break
        if (_parent / "server/tools/gateway/__init__.py").is_file():
            sys.path.insert(0, str(_parent / "server"))
            break


from tools.gateway.paths import source_root

import csv
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import socket
import sys
from tempfile import TemporaryDirectory
import threading

import httpx

ROOT = source_root(__file__)
from ezllmrouter_server.operator_projection import OperatorProjection  # noqa: E402
from ezllmrouter_server.operator_web import serve  # noqa: E402
from ezllmrouter_server.store import SQLiteStore  # noqa: E402


def run():
    root = Path(os.environ["DEV12_TARGET_DIR"])
    campaign_file = root / "campaign.sqlite"
    before = hashlib.sha256(campaign_file.read_bytes()).hexdigest()
    arrivals_before = len((root / "receiver.jsonl").read_text().splitlines())
    audit = json.loads((root / "audit.json").read_text())
    with TemporaryDirectory(prefix="dev12-report-copy-") as temporary:
        copy = Path(temporary) / "report.sqlite"
        shutil.copy2(campaign_file, copy)
        store = SQLiteStore(copy)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        server = serve(
            "127.0.0.1",
            port,
            projection=OperatorProjection(store, "user.demo", str(Path(temporary) / "send.jsonl")),
            runner=None,
            password="dev12.synthetic.operator." + "x" * 32,
            fixture={},
            build={"commit": audit["campaign_id"], "dirty": False},
            web_root=ROOT / "web",
            worker_probe=lambda: {"state": "not_attached"},
            sender_status=lambda: {"state": "not_attached"},
            successor_store=store,
        )
        threading.Thread(target=server.serve_forever, daemon=True).start()
        origin = f"http://127.0.0.1:{port}"
        try:
            with httpx.Client(
                base_url=origin, trust_env=False, headers={"Origin": origin}, timeout=10
            ) as client:
                login = client.post(
                    "/operator/v1/login", json={"password": "dev12.synthetic.operator." + "x" * 32}
                )
                login.raise_for_status()
                report_response = client.get("/operator/v1/retrieval-usage")
                report_response.raise_for_status()
                report = report_response.json()
                csv_response = client.get("/operator/v1/retrieval-usage?export=csv")
                csv_response.raise_for_status()
                rows = list(csv.DictReader(io.StringIO(csv_response.text)))
                filtered_response = client.get(
                    "/operator/v1/retrieval-usage", params={"actor_id": "agent.vega"}
                )
                filtered_response.raise_for_status()
                filtered = filtered_response.json()
            if (
                report["total"]["attempts"] != audit["attempts"]
                or report["total"]["known_usd"] != audit["fictional_known_usd"]
                or len(rows) != audit["attempts"]
                or {row["attempt_id"] for row in rows}
                != {row["attempt_id"] for row in report["attempts"]}
                or report["total"]["current_held_reservations"] != 3
                or report["operational_state_basis"]
                != "current; independent of historical usage cutoff"
                or any(
                    item["exposure_state_as_of"] != report["operational_as_of"]
                    for item in report["attempts"]
                )
                or any(item["actor_id"] != "agent.vega" for item in filtered["attempts"])
            ):
                raise AssertionError("authenticated synthetic report/CSV reconciliation failed")
            (root / "report-snapshot.json").write_text(
                json.dumps(report, sort_keys=True, indent=2) + "\n"
            )
            (root / "report-snapshot.csv").write_text(csv_response.text)
            result = {
                "status": "PASS",
                "attempts": len(rows),
                "known_usd": report["total"]["known_usd"],
                "current_held_reservations": report["total"]["current_held_reservations"],
                "current_held_bound_usd": report["total"]["current_held_bound_usd"],
                "actor_filtered_attempts": filtered["total"]["attempts"],
                "local_read_gets": 3,
                "synthetic_sends": 0,
            }
            (root / "report-check.json").write_text(
                json.dumps(result, sort_keys=True, indent=2) + "\n"
            )
        finally:
            server.shutdown()
            server.server_close()
            server.operator_jobs.shutdown(wait=True)
            store.close()
    if (
        hashlib.sha256(campaign_file.read_bytes()).hexdigest() != before
        or len((root / "receiver.jsonl").read_text().splitlines()) != arrivals_before
    ):
        raise AssertionError("read-only report changed retained campaign or receiver arrivals")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    run()
