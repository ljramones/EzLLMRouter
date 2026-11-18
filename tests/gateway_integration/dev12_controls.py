"""Selected final-guard, no-send, revocation and unknown controls in one campaign."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "server/src"), str(Path(__file__).resolve().parent),
                str(ROOT / "tests/development_slice")]

import httpx
from cryptography.hazmat.primitives import serialization
from duranki_server.core import Coordinator
from duranki_server.store import SQLiteStore
from duranki_server.successor_authority import SyntheticSuccessorAuthority
from duranki_server.successor_campaign import FiniteSuccessorCampaign
from duranki_server.successor_service import SuccessorService
from duranki_server.web import serve
from dev12_executor import Dev12SyntheticExecutor
from dev12_integrated import fixture, observations, runtime_source_identity
from dev12_tls_receiver import TEST_KEY


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run():
    root = Path(os.environ["DEV12_TARGET_DIR"])
    inventory = json.loads((root / "inventory.json").read_text())
    receiver_port = int(inventory["receiver"].rsplit(":", 1)[1])
    service_port = int(inventory["service"].rsplit(":", 1)[1])
    store = SQLiteStore(root / "campaign.sqlite")
    signer = serialization.load_pem_private_key((root / "signing-key.pem").read_bytes(), password=None)
    authority = SyntheticSuccessorAuthority(store, signer, "key.synthetic.dev12", "v1")
    allowance = FiniteSuccessorCampaign(store, inventory["campaign_id"],
        inventory["budget_account_id"], financial_owner_id=inventory["financial_owner_id"])
    before = allowance.inspect()
    if (before["attempt_count"] != len(inventory["cases"]) or
            before["possible_send_count"] != len(inventory["cases"]) or before["paused"]):
        raise RuntimeError("unexpected campaign checkpoint before controls")
    control_inventory = {"campaign_id": inventory["campaign_id"],
        "starting_attempt_count": before["attempt_count"],
        "starting_possible_send_count": before["possible_send_count"],
        "cases": ["pre_admission_rejection", "duplicate_recovery", "mutated_final_body_no_send",
                  "positive_after_rejection", "revoked_after_lower_wait_no_send",
                  "positive_after_plan_revocation", "failed_delivery_known_usage",
                  "receiver_arrival_unknown_outcome", "restart_without_replay"],
        "maximum_new_attempts": 6, "maximum_new_possible_sends": 5,
        "real_provider_calls": 0,
        "source_commit": os.environ["DEV12_SOURCE_COMMIT"],
        "source_tree": os.environ["DEV12_SOURCE_TREE"],
        "mounted_source_identity": runtime_source_identity()}
    (root / "controls-inventory.json").write_text(json.dumps(control_inventory, indent=2) + "\n")
    existing = store.db.execute("SELECT record FROM dev12_submissions WHERE "
        "json_extract(record,'$.work_key.step_id')='step.domain.document.1'").fetchone()
    if not existing:
        raise RuntimeError("recovery source record absent")
    prior = json.loads(existing[0])
    context = prior["trusted_context"]
    token = "dev12.synthetic.token.0." + "x" * 32
    trusted = {**context["identity"], "task_id": prior["work_key"]["task_id"],
               "expires_at": context["expires_at"]}
    permitted = lambda current, record: (
        current["principal_id"] == record["work_key"]["principal_id"] and
        current["source_authority_id"] == record["trusted_identity"]["source_authority_id"] and
        current["identity_binding_id"] == record["trusted_identity"]["identity_binding_id"])
    receiver = subprocess.Popen([sys.executable, "-I", "-B", str(Path(__file__).with_name("dev12_tls_receiver.py")),
                                 str(root / "cert.pem"), str(root / "key.pem"),
                                 str(root / "receiver.jsonl"), str(receiver_port)],
                                stdout=subprocess.DEVNULL, stderr=(root / "receiver-controls.stderr").open("w"))
    wire = None
    coordinator = None
    try:
        for _ in range(100):
            if receiver.poll() is not None:
                raise RuntimeError("controlled receiver failed restart")
            try:
                with socket.create_connection(("127.0.0.1", receiver_port), timeout=.1):
                    break
            except OSError:
                time.sleep(.05)
        else:
            raise RuntimeError("controlled receiver readiness deadline")
        executor = Dev12SyntheticExecutor("/link/dev12-worker.sock", receiver_port,
                                          (root / "cert.pem").read_text(), TEST_KEY)
        coordinator = Coordinator(store, {token: trusted}, {}, {}, {}, None, None, {}, {}, None)
        from duranki_server.successor_assembly import attach_standalone_synthetic
        successor = attach_standalone_synthetic(coordinator, store=store,
            contexts_by_credential={token: context}, authority=authority, executor=executor,
            allowance=allowance, read_allowed=permitted, usage_write_allowed=permitted)
        successor.recover_incomplete()
        wire = serve("127.0.0.1", service_port, coordinator)
        threading.Thread(target=wire.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{service_port}"
        headers = {"Authorization": "Bearer " + token, "Duranki-Contract-Version": "0.3",
                   "Content-Type": "application/json", "Duranki-Wait-Ms": "5000"}
        baseline_arrivals = len(observations(root / "receiver.jsonl"))
        if baseline_arrivals != len(inventory["cases"]):
            raise RuntimeError("receiver baseline differs")
        outcomes = []
        with httpx.Client(base_url=url, trust_env=False, timeout=10) as client:
            invalid = deepcopy(prior["request"])
            invalid["work_selector"]["step_id"] = "step.control.unsupported"
            invalid["capability_profile"] = "unsupported@1"
            rejected = client.post("/v1/submissions", headers=headers, json=invalid)
            if rejected.status_code != 422 or rejected.json()["code"] != "CAPABILITY_UNSUPPORTED":
                raise AssertionError("unsupported capability did not reject before admission")
            duplicate = client.post("/v1/submissions", headers=headers, json=prior["request"])
            if duplicate.status_code != 200 or duplicate.json()["handle"]["submission_id"] != prior["submission_id"]:
                raise AssertionError("full-key recovery created a new submission")
            outcomes.append({"case": "duplicate_recovery", "submission_id": prior["submission_id"]})

            def submit(step, *, item_id="doc.positive"):
                request = deepcopy(prior["request"])
                request["work_selector"]["step_id"] = step
                request["deadline"] = fixture("DIRECT_DOCUMENT")[0]["deadline"]
                request["input"]["items"] = [{"item_id": item_id,
                                               "text": "Sky"}]
                response = client.post("/v1/submissions", headers=headers, json=request)
                value = response.json()
                if "handle" not in value:
                    raise AssertionError(f"{step} admission failed: {response.status_code} {value}")
                status = client.get("/v1/submissions/" + value["handle"]["submission_id"],
                                    headers={"Authorization": headers["Authorization"],
                                             "Duranki-Contract-Version": "0.3"})
                status.raise_for_status()
                for _ in range(100):
                    if status.json()["submission_state"] != "pending":
                        break
                    time.sleep(.05)
                    status = client.get("/v1/submissions/" + value["handle"]["submission_id"],
                                        headers={"Authorization": headers["Authorization"],
                                                 "Duranki-Contract-Version": "0.3"})
                    status.raise_for_status()
                return response.status_code, value, status.json()

            executor.proposal_transform = lambda proposal, body: (proposal, body + b" ")
            _code, _reply, mutated = submit("step.control.mutated")
            executor.proposal_transform = None
            if mutated["submission_state"] != "failed" or len(observations(root / "receiver.jsonl")) != baseline_arrivals:
                raise AssertionError("mutated final body was not blocked before send")
            outcomes.append({"case": "mutated_final_body_no_send", "status": mutated})

            _code, _reply, positive = submit("step.control.positive")
            if positive["submission_state"] != "completed" or len(observations(root / "receiver.jsonl")) != baseline_arrivals + 1:
                raise AssertionError("post-rejection positive control failed")
            outcomes.append({"case": "positive_after_rejection", "status": positive})

            fired = False
            async def revoke_after_lower_wait():
                nonlocal fired
                if not fired:
                    fired = True
                    record = store.successor_by_work({**prior["work_key"], "step_id": "step.control.revoked"})
                    authority.revoke_plan(record["signed_plan"]["plan_id"], now())
            executor.first_write_wait = revoke_after_lower_wait
            _code, _reply, revoked = submit("step.control.revoked")
            executor.first_write_wait = None
            if (not fired or revoked["submission_state"] != "failed" or
                    len(observations(root / "receiver.jsonl")) != baseline_arrivals + 1):
                raise AssertionError("lower-wait plan revocation did not prevent first write")
            outcomes.append({"case": "revoked_after_lower_wait_no_send", "status": revoked})

            _code, _reply, after_revoke = submit("step.control.afterrevocation")
            if (after_revoke["submission_state"] != "completed" or
                    len(observations(root / "receiver.jsonl")) != baseline_arrivals + 2):
                raise AssertionError("new eligible plan after individual revocation failed")
            outcomes.append({"case": "positive_after_plan_revocation", "status": after_revoke})

            _code, _reply, failed_known = submit("step.control.failure.known",
                                                 item_id="doc.failure.known")
            if (failed_known["submission_state"] != "failed" or
                    failed_known["attempts"][0]["usage_revision"]["cost_status"] != "calculated" or
                    allowance.inspect()["paused"] or
                    len(observations(root / "receiver.jsonl")) != baseline_arrivals + 3):
                raise AssertionError("failed delivery lost independently reported native usage")
            outcomes.append({"case": "failed_delivery_known_usage", "status": failed_known})

            _code, _reply, unknown = submit("step.control.unknown", item_id="doc.unknown")
            if (unknown["submission_state"] != "unknown" or
                    len(observations(root / "receiver.jsonl")) != baseline_arrivals + 4 or
                    not allowance.inspect()["paused"]):
                raise AssertionError("receiver-arrived unknown outcome did not retain exposure and pause")
            outcomes.append({"case": "receiver_arrival_unknown_outcome", "status": unknown})
        final = allowance.inspect()
        result = {"inventory": control_inventory, "before": before, "after": final,
                  "arrivals_before": baseline_arrivals,
                  "arrivals_after": len(observations(root / "receiver.jsonl")),
                  "outcomes": outcomes,
                  "real_provider_calls": 0}
        (root / "controls-result.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
        if final["attempt_count"] != 84 or final["possible_send_count"] != 83:
            raise AssertionError("finite campaign attempt/send counters differ")
        print(json.dumps({"status": "PASS", "campaign_id": inventory["campaign_id"],
                          "attempts": final["attempt_count"], "possible_sends": final["possible_send_count"],
                          "receiver_arrivals": result["arrivals_after"], "paused": final["paused"]}, sort_keys=True))
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
