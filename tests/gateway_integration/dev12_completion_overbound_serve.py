"""Bounded report-only browser fixture over an imported zero-send DB copy."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/src"))
from ezllmrouter_server.operator_projection import OperatorProjection
from ezllmrouter_server.operator_web import serve
from ezllmrouter_server.store import SQLiteStore

PORT = 8769
PASSWORD = "dev12.report.only.synthetic." + "x" * 32


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def main(source, output):
    if output.exists() or not source.is_file() or source.is_symlink():
        raise ValueError("fresh owned output and retained imported fixture required")
    source_hash = digest(source)
    output.mkdir(parents=True)
    copy = output / "private-report-copy.sqlite"
    shutil.copyfile(source, copy)
    store = SQLiteStore(copy)
    with store._lock:
        campaign = json.loads(
            store.db.execute(
                "SELECT record FROM dev12_campaigns WHERE "
                "campaign_id='campaign.fixture.imported.underbound'"
            ).fetchone()[0]
        )
        counts = {
            name: store.db.execute("SELECT COUNT(*) FROM " + name).fetchone()[0]
            for name in (
                "dev12_submissions",
                "dev12_send_ownership",
                "dev12_campaign_attempts",
                "submissions",
                "intents",
            )
        }
    if (
        not campaign["paused"]
        or campaign["attempt_count"] != 0
        or campaign["possible_send_count"] != 0
        or counts["dev12_submissions"] != 1
        or any(counts[name] for name in counts if name != "dev12_submissions")
    ):
        raise AssertionError("imported fixture is not paused and zero-send")
    server = serve(
        "0.0.0.0",
        PORT,
        projection=OperatorProjection(store, "user.demo", str(output / "no-send-events.jsonl")),
        runner=None,
        password=PASSWORD,
        fixture={"destination": {}, "policy": {}},
        build={"commit": "imported-historical-fixture", "dirty": False, "fingerprint": source_hash},
        web_root=ROOT / "web",
        worker_probe=lambda: {"state": "absent"},
        sender_status=lambda: {"state": "absent"},
        successor_store=store,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        (output / "READY.json").write_text(
            json.dumps(
                {
                    "kind": "dev12_report_only_browser_fixture",
                    "origin": f"http://127.0.0.1:{PORT}",
                    "source_sha256": source_hash,
                    "campaign_id": campaign["campaign_id"],
                    "counts": counts,
                    "sender_worker_receiver_started": False,
                },
                sort_keys=True,
                indent=2,
            )
            + "\n"
        )
        print(
            json.dumps({"status": "READY", "port": PORT, "fixture_sha256": source_hash}), flush=True
        )
        stop = output / "STOP"
        until = time.monotonic() + 600
        while not stop.exists() and time.monotonic() < until:
            time.sleep(0.1)
        if not stop.exists():
            raise TimeoutError("bounded browser check did not signal completion")
        with store._lock:
            after = {
                name: store.db.execute("SELECT COUNT(*) FROM " + name).fetchone()[0]
                for name in counts
            }
            retained = json.loads(
                store.db.execute(
                    "SELECT record FROM dev12_campaigns WHERE campaign_id=?",
                    (campaign["campaign_id"],),
                ).fetchone()[0]
            )
        if after != counts or retained != campaign or digest(source) != source_hash:
            raise AssertionError("report-only browser changed imported source/financial rows")
        (output / "FINAL.json").write_text(
            json.dumps(
                {
                    "status": "PASS",
                    "source_unchanged": True,
                    "copy_campaign_unchanged": True,
                    "copy_admissions_ownership_unchanged": True,
                    "sender_worker_receiver_started": False,
                },
                sort_keys=True,
                indent=2,
            )
            + "\n"
        )
    finally:
        server.shutdown()
        server.server_close()
        server.operator_jobs.shutdown(wait=True)
        thread.join(timeout=5)
        store.close()


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
