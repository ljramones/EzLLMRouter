"""Authenticated synthetic report and export stay separate from legacy totals."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]

from ezllmrouter_server.operator_projection import OperatorProjection  # noqa: E402
from ezllmrouter_server.operator_web import serve  # noqa: E402
from ezllmrouter_server.store import SQLiteStore  # noqa: E402


class SyntheticOperatorHTTPTests(unittest.TestCase):
    def test_authenticated_empty_report_and_csv(self):
        with TemporaryDirectory() as temporary:
            store = SQLiteStore(Path(temporary) / "store.sqlite")
            port = 0
            server = serve(
                "127.0.0.1",
                port,
                projection=OperatorProjection(
                    store, "user.demo", str(Path(temporary) / "send.jsonl")
                ),
                runner=None,
                password="dev12.synthetic.operator." + "x" * 32,
                fixture={},
                build={},
                web_root=ROOT / "web",
                worker_probe=lambda: {},
                sender_status=lambda: {},
                successor_store=store,
            )
            port = server.server_port
            threading.Thread(target=server.serve_forever, daemon=True).start()
            origin = f"http://127.0.0.1:{port}"
            try:
                login = Request(
                    origin + "/operator/v1/login",
                    method="POST",
                    data=json.dumps({"password": "dev12.synthetic.operator." + "x" * 32}).encode(),
                    headers={"Content-Type": "application/json", "Origin": origin},
                )
                with urlopen(login, timeout=5) as response:
                    cookie = response.headers["Set-Cookie"].split(";", 1)[0]
                    self.assertEqual(json.load(response)["role"], "registry_admin")
                headers = {"Cookie": cookie, "Origin": origin}
                with urlopen(
                    Request(origin + "/operator/v1/retrieval-usage", headers=headers), timeout=5
                ) as response:
                    self.assertEqual(json.load(response)["total"]["attempts"], 0)
                with urlopen(
                    Request(origin + "/operator/v1/retrieval-usage?export=csv", headers=headers),
                    timeout=5,
                ) as response:
                    self.assertTrue(response.read().startswith(b"attempt_id,submission_id"))
            finally:
                server.shutdown()
                server.server_close()
                server.operator_jobs.shutdown(wait=True)
                store.close()


if __name__ == "__main__":
    unittest.main()
