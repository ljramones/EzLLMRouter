"""Resume the same durable campaign after a harness label error; one JS rerank."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [
    str(ROOT / "server/src"),
    str(Path(__file__).resolve().parent),
    str(ROOT / "tests/development_slice"),
]

from cryptography.hazmat.primitives import serialization
from ezllmrouter_server.core import Coordinator
from ezllmrouter_server.store import SQLiteStore
from tools.synthetic.successor_authority import SyntheticSuccessorAuthority
from tools.synthetic.successor_campaign import FiniteSuccessorCampaign
from tools.synthetic.successor_service import SuccessorService
from ezllmrouter_server.successor_reporting import usage_report
from ezllmrouter_server.web import serve
from dev12_executor import Dev12SyntheticExecutor
from dev12_integrated import fixture, observations, independent_amount
from dev12_tls_receiver import TEST_KEY


def run():
    root = Path(os.environ["DEV12_TARGET_DIR"])
    inventory = json.loads((root / "inventory.json").read_text())
    receiver_port = int(inventory["receiver"].rsplit(":", 1)[1])
    service_port = int(inventory["service"].rsplit(":", 1)[1])
    store = SQLiteStore(root / "campaign.sqlite")
    signing_key = serialization.load_pem_private_key(
        (root / "signing-key.pem").read_bytes(), password=None
    )
    authority = SyntheticSuccessorAuthority(store, signing_key, "key.synthetic.dev12", "v1")
    allowance = FiniteSuccessorCampaign(store, inventory["campaign_id"], "budget.synthetic.dev12")
    before = allowance.inspect()
    arrivals_before = observations(root / "receiver.jsonl")
    if (
        before["attempt_count"] != 78
        or before["possible_send_count"] != 78
        or len(arrivals_before) != 78
    ):
        raise RuntimeError("expected durable 78-attempt checkpoint absent")
    request, context = fixture("DELEGATED_RERANK")
    request["work_selector"]["step_id"] = "step.js.rerank.resumed"
    token = "dev12.synthetic.token.resumed." + "x" * 32
    trusted = {
        **context["identity"],
        "task_id": request["work_selector"]["task_id"],
        "expires_at": context["expires_at"],
    }
    permitted = lambda current, record: (
        current["principal_id"] == record["work_key"]["principal_id"]
        and current["source_authority_id"] == record["trusted_identity"]["source_authority_id"]
        and current["identity_binding_id"] == record["trusted_identity"]["identity_binding_id"]
    )
    receiver = subprocess.Popen(
        [
            sys.executable,
            "-I",
            "-B",
            str(Path(__file__).with_name("dev12_tls_receiver.py")),
            str(root / "cert.pem"),
            str(root / "key.pem"),
            str(root / "receiver.jsonl"),
            str(receiver_port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=(root / "receiver-resume.stderr").open("w"),
    )
    wire = None
    coordinator = None
    try:
        for _ in range(100):
            if receiver.poll() is not None:
                raise RuntimeError("controlled receiver restart failed")
            try:
                with socket.create_connection(("127.0.0.1", receiver_port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.05)
        else:
            raise RuntimeError("controlled receiver restart deadline")
        executor = Dev12SyntheticExecutor(
            "/link/dev12-worker.sock", receiver_port, (root / "cert.pem").read_text(), TEST_KEY
        )
        successor = SuccessorService(
            store,
            {token: context},
            authority,
            executor,
            allowance,
            read_allowed=permitted,
            usage_write_allowed=permitted,
        )
        successor.recover_incomplete()
        coordinator = Coordinator(store, {token: trusted}, {}, {}, {}, None, None, {}, {}, None)
        coordinator.successor = successor
        wire = serve("127.0.0.1", service_port, coordinator)
        threading.Thread(target=wire.serve_forever, daemon=True).start()
        input_path = root / "js-rerank-resume-input.json"
        input_path.write_text(
            json.dumps(
                {"base_url": f"http://127.0.0.1:{service_port}", "token": token, "request": request}
            )
        )
        process = subprocess.run(
            ["/dev12-node", str(Path(__file__).with_name("dev12_js_actor.cjs")), str(input_path)],
            capture_output=True,
            text=True,
            check=True,
        )
        value = json.loads(process.stdout)
        amount = value["status"]["attempts"][0]["usage_revision"]["amount_decimal"]
        expected = independent_amount("DELEGATED_RERANK", request)
        if amount != expected:
            raise AssertionError(f"installed JS rerank native amount {amount} != {expected}")
        after = allowance.inspect()
        arrivals = observations(root / "receiver.jsonl")
        report = usage_report(store, {"role": "registry_admin", "principal_id": "owner.local"})
        if (
            after["attempt_count"] != 79
            or after["possible_send_count"] != 79
            or len(arrivals) != 79
            or report["total"]["attempts"] != 79
            or arrivals[-1]["attempt_id"] != value["status"]["attempts"][0]["attempt_id"]
        ):
            raise AssertionError("same-campaign restart/receiver/report reconciliation failed")
        supplement = {
            "checkpoint_attempts": before["attempt_count"],
            "after_attempts": after["attempt_count"],
            "receiver_arrivals": len(arrivals),
            "case": "installed_js.rerank.resumed",
            "reply": value["reply"],
            "status": value["status"],
            "report_total": report["total"],
            "real_provider_calls": 0,
        }
        (root / "resume-result.json").write_text(
            json.dumps(supplement, sort_keys=True, indent=2) + "\n"
        )
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "campaign_id": inventory["campaign_id"],
                    "attempts": after["attempt_count"],
                    "arrivals": len(arrivals),
                    "js_rerank_amount": amount,
                },
                sort_keys=True,
            )
        )
    finally:
        if wire is not None:
            wire.shutdown()
            wire.server_close()
        if coordinator is not None:
            coordinator.pool.shutdown(wait=True)
            coordinator.successor.pool.shutdown(wait=True)
        receiver.terminate()
        receiver.wait(timeout=5)
        store.close()


if __name__ == "__main__":
    run()
