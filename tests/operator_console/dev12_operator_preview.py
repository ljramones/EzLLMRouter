"""Read-only synthetic operator preview from a disposable DB copy."""
from pathlib import Path
import os
import signal
import sys
import threading

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/src"))

from ezllmrouter_server.operator_projection import OperatorProjection
from ezllmrouter_server.operator_web import serve
from ezllmrouter_server.store import SQLiteStore


def main():
    db = Path(os.environ["DEV12_PREVIEW_DB"])
    if not db.is_file():
        raise RuntimeError("disposable synthetic DB copy absent")
    store = SQLiteStore(db)
    server = serve("0.0.0.0", 18780,
        projection=OperatorProjection(store, "user.demo", str(db.parent / "unused-send.jsonl")),
        runner=None, password="dev12.synthetic.operator." + "x" * 32,
        fixture={"destination": {}, "policy": {}},
        build={"commit": "disposable.dev12", "dirty": True, "fingerprint": "controlled.synthetic"},
        web_root=ROOT / "web", worker_probe=lambda: {"state": "not started"},
        sender_status=lambda: {"state": "not started"}, successor_store=store)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        stop.wait()
    finally:
        server.shutdown()
        server.server_close()
        server.operator_jobs.shutdown(wait=True)
        store.close()


if __name__ == "__main__":
    main()
