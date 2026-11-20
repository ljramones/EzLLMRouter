"""Disposable report-only preview over a copy of the synthetic campaign."""

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

import os
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory

ROOT = source_root(__file__)
from ezllmrouter_server.operator_projection import OperatorProjection  # noqa: E402
from ezllmrouter_server.operator_web import serve  # noqa: E402
from ezllmrouter_server.store import SQLiteStore  # noqa: E402


def run():
    source = Path(os.environ["DEV12_TARGET_DIR"]) / "campaign.sqlite"
    with TemporaryDirectory(prefix="dev12-readonly-preview-") as temporary:
        copy = Path(temporary) / "preview.sqlite"
        shutil.copy2(source, copy)
        store = SQLiteStore(copy)
        server = serve(
            "0.0.0.0",
            18780,
            projection=OperatorProjection(store, "user.demo", str(Path(temporary) / "send.jsonl")),
            runner=None,
            password="dev12.synthetic.operator." + "x" * 32,
            fixture={},
            build={
                "commit": os.environ["DEV12_SOURCE_COMMIT"],
                "dirty": False,
                "fingerprint": "report-only-synthetic-copy",
            },
            web_root=ROOT / "web",
            worker_probe=lambda: {"state": "not_attached"},
            sender_status=lambda: {"state": "not_attached"},
            successor_store=store,
            allowed_hosts={"127.0.0.1:18780", "localhost:18780"},
        )
        try:
            server.serve_forever()
        finally:
            server.server_close()
            server.operator_jobs.shutdown(wait=True)
            store.close()


if __name__ == "__main__":
    run()
