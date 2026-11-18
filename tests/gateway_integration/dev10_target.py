"""Disposable personal allowance proof through installed client, guard and controlled TLS."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time

from cryptography.hazmat.primitives.asymmetric import ed25519
from duranki_client import DurankiClient, DurankiError
from duranki_server.core import Coordinator
from duranki_server.personal_campaign import PersonalCampaign
from duranki_server.plans import PlanAuthority
from duranki_server.provider_vault import ProviderVault
from duranki_server.registry import Registry
from duranki_server.store import SQLiteStore
from duranki_server.web import serve
from choice_b_sender import ChoiceBSenderAdapter
from dev08_integrated import (TEST_KEY, TEST_TOKEN, certificate, fixture_paths,
                              prepare_registry, rows)
from proxy_recipe import GatewayProxyRecipe, proxy_policy, public_destination
from owned_sender_transport import LocalSendAuthority
from worker_ready import probe


def require(condition, label):
    if not condition:
        raise AssertionError(label)


def request_for(base, config, step, *, unknown=False):
    request = json.loads(json.dumps(base))
    request["requested_configuration_ref"] = config["configuration_ref"]
    request["step_id"] = "step.dev10." + step
    request["execution_generation"] = "gen.dev10." + step
    request["generation_settings"]["total_timeout_ms"] = 10000
    if unknown:
        request["messages"][1]["blocks"][0]["text"] = "DEV10_TRANSPORT_UNKNOWN"
    return request


def scenario(root, fixture, base, receiver_log, name, action):
    work = root / name
    work.mkdir()
    cert = (root / "cert.pem").read_text()
    store, authority, registry, config = prepare_registry(
        work, fixture, "https://localhost:8766", cert, funding_kind="personal_testing")
    adapter = wire = coordinator = None
    try:
        registry.mutate("owner.local", {"operation_id": "op.dev10.target.owner.grant", "action": "set_grant",
            "subject": "owner.local", "expected_revision": 0,
            "data": {"configuration_ref": config["configuration_ref"], "status": "active",
                     "purposes": ["execution"], "task_classes": ["class.demo"]}})
        registry.controlled_provider_proof = False
        campaign = PersonalCampaign(store, registry)
        registry.personal_campaign = campaign
        limit = {"connection_id": "conn.dev08-controlled", "configuration_ref": config["configuration_ref"],
            "principal_id": "owner.local", "currency": "USD", "allowance_decimal": "0.03",
            "per_request_decimal": "0.01", "max_requests": 2, "max_input_bytes": 4096,
            "max_output_tokens": 32, "expires_at": (datetime.now(timezone.utc) +
                timedelta(hours=1)).isoformat().replace("+00:00", "Z")}
        campaign.configure("owner.local", limit)
        require(campaign.summary()["state"] == "draft", name + " automatically activated")
        campaign.transition("owner.local", "active")
        token = registry.issue_local_operator_token("owner.local")
        adapter = ChoiceBSenderAdapter(authority, registry=registry, controlled_provider_proof=True)
        coordinator = Coordinator(store, {TEST_TOKEN: fixture["trusted_context"]},
            public_destination(fixture), fixture["prompt_blocks"], fixture["allowed_lineages"],
            PlanAuthority(ed25519.Ed25519PrivateKey.generate(), proxy_policy(fixture), registry),
            adapter, fixture["retention"], fixture["classification"],
            GatewayProxyRecipe(controlled_provider_proof=True),
            trusted_source_labels=fixture["trusted_source_labels"], registry=registry)
        wire = serve("127.0.0.1", 8773, coordinator)
        threading.Thread(target=wire.serve_forever, daemon=True).start()
        before = len(rows(receiver_log))
        result = action(store, authority, registry, config, campaign, coordinator, adapter,
                        token, before, receiver_log, base)
    finally:
        if wire:
            wire.shutdown()
            wire.server_close()
        if coordinator:
            coordinator.pool.shutdown(wait=True)
        if adapter:
            adapter.close()
        store.close()
    if name == "unknown":
        reopened_store = SQLiteStore(work / "store.sqlite")
        try:
            reopened_registry = Registry(reopened_store, LocalSendAuthority(),
                legacy_destination=public_destination(fixture), legacy_token=TEST_TOKEN,
                legacy_trusted=fixture["trusted_context"],
                provider_vault=ProviderVault(work / "vault", require_existing=True),
                provider_execution_ready=True)
            recovered = PersonalCampaign(reopened_store, reopened_registry).summary()
            require(recovered["state"] == "paused" and
                    recovered["attempts"][0]["state"] == "unknown" and
                    recovered["outstanding_decimal"] == result["outstanding_decimal"],
                    "SQLite reopen lost unknown exposure")
            result["sqlite_reopen_preserved"] = True
        finally:
            reopened_store.close()
    return result


def send(client, request, wait=10000):
    return client.submit(request, {"wait_ms": wait})


def denied(client, request, label):
    try:
        send(client, request)
    except DurankiError as exc:
        require(exc.code == "FINANCIAL_AUTH_REQUIRED", label + " wrong denial: " + exc.code)
        return
    raise AssertionError(label + " unexpectedly admitted")


def settled(store, authority, registry, config, campaign, coordinator, adapter,
            token, before, receiver_log, base):
    first = request_for(base, config, "first")
    with DurankiClient("http://127.0.0.1:8773", token) as client:
        reply = send(client, first)
        require(reply["state"] == "delivered", "first send did not deliver")
        attempt = reply["candidate"]["attempt_id"]
        sid = reply["handle"]["submission_id"]
        require(store.intent_count(sid) == 1 and store.guard_record(attempt), "intent/guard absent")
        require(len(rows(receiver_log)) == before + 1, "first receiver arrival")
        require(send(client, first)["handle"]["submission_id"] == sid, "duplicate changed handle")
        require(len(rows(receiver_log)) == before + 1, "duplicate sent again")
        summary = campaign.summary()
        require(summary["incurred_decimal"] == "0.000009000", "first cost settlement")
        require(summary["attempts"][0]["state"] == "settled", "first attempt not settled")
        require(summary["outstanding_decimal"] == "0", "settled amount still outstanding")
        # A held dispatch keeps its reservation open while a competing work key arrives.
        entered, release = threading.Event(), threading.Event()
        original = adapter.send_with_context
        def held(*args):
            entered.set()
            require(release.wait(8), "held dispatch timeout")
            return original(*args)
        adapter.send_with_context = held
        second = request_for(base, config, "second")
        competing = request_for(base, config, "competing")
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(send, client, second)
            require(entered.wait(5), "competing dispatch did not queue")
            denied(client, competing, "competing reservation")
            require(len(rows(receiver_log)) == before + 1, "competing reservation sent")
            release.set()
            second_reply = future.result(timeout=15)
        adapter.send_with_context = original
        require(second_reply["state"] == "delivered", "second send did not deliver")
        require(len(rows(receiver_log)) == before + 2, "second receiver arrival")
        denied(client, request_for(base, config, "exhausted"), "request count exhaustion")
        require(len(rows(receiver_log)) == before + 2, "exhausted work sent")
        summary = campaign.summary()
        require(summary["request_count"] == 2 and summary["incurred_decimal"] == "0.000018000",
                "settled total or count")
        require(store.db.execute("SELECT COUNT(*) FROM usage_revisions").fetchone()[0] == 2,
                "usage revisions did not reconcile")
        require(len(rows(Path(os.environ["DURANKI_DEV04_SEND_EVENTS"]))) == 2, "sender count")
        return {"arrivals": 2, "duplicate_arrivals": 0, "competing_denied": True,
                "exhaustion_denied": True, "incurred_decimal": summary["incurred_decimal"],
                "attempts": summary["request_count"]}


def unknown(store, authority, registry, config, campaign, coordinator, adapter,
            token, before, receiver_log, base):
    with DurankiClient("http://127.0.0.1:8773", token) as client:
        reply = send(client, request_for(base, config, "unknown", unknown=True))
        require(reply["state"] == "pending", "unknown transport outcome was treated as delivered")
        require(len(rows(receiver_log)) == before + 1, "unknown receiver arrival")
        require(store.get(reply["handle"]["submission_id"])["submission_state"] == "outcome_unknown",
                "possible send outcome not recorded as unknown")
        summary = campaign.summary()
        require(summary["state"] == "paused" and summary["attempts"][0]["state"] == "unknown",
                "unknown exposure did not pause")
        outstanding = Decimal(summary["outstanding_decimal"])
        require(outstanding > 0, "unknown exposure not retained")
        denied(client, request_for(base, config, "after-unknown"), "unknown exposure")
        reopened = PersonalCampaign(store, registry)
        registry.personal_campaign = reopened
        require(reopened.summary()["attempts"][0]["state"] == "unknown" and
                reopened.summary()["outstanding_decimal"] == summary["outstanding_decimal"],
                "restart lost unknown exposure")
        require(len(rows(receiver_log)) == before + 1, "restart replayed provider work")
        return {"arrivals": 1, "state": "paused", "outstanding_decimal":
                summary["outstanding_decimal"], "restart_preserved": True}


def queued(kind):
    def exercise(store, authority, registry, config, campaign, coordinator, adapter,
                 token, before, receiver_log, base):
        entered, release = threading.Event(), threading.Event()
        original = adapter.send_with_context
        def held(*args):
            entered.set()
            require(release.wait(8), "queued dispatch timeout")
            return original(*args)
        adapter.send_with_context = held
        with DurankiClient("http://127.0.0.1:8773", token) as client:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(send, client, request_for(base, config, kind))
                require(entered.wait(5), kind + " dispatch did not queue")
                if kind == "pause":
                    campaign.transition("owner.local", "paused")
                elif kind == "disable":
                    registry.mutate("owner.local", {"operation_id": "op.dev10.target.disable",
                        "action": "connection_state", "subject": "conn.dev08-controlled",
                        "expected_revision": 4,
                        "data": {"status": "disabled", "reason": "Controlled queued check"}})
                elif kind == "revocation":
                    registry.mutate("owner.local", {"operation_id": "op.dev10.target.revoke",
                        "action": "set_grant", "subject": "owner.local", "expected_revision": 1,
                        "data": {"configuration_ref": config["configuration_ref"], "status": "removed",
                                 "purposes": ["execution"], "task_classes": ["class.demo"]}})
                release.set()
                try:
                    reply = future.result(timeout=15)
                    require(reply["state"] == "failed", kind + " queued work unexpectedly delivered")
                except DurankiError as exc:
                    require(exc.failure_stage == "before_transmit", kind + " wrong failure stage")
        require(len(rows(receiver_log)) == before, kind + " reached receiver")
        record = store.db.execute("SELECT record FROM submissions").fetchone()
        require(record is not None and json.loads(record[0])["submission_state"] == "failed_before_transmit",
                kind + " missing durable failure")
        require(campaign.summary()["attempts"][0]["state"] == "released", kind + " bound not released")
        return {"arrivals": 0, "failed_before_transmit": True, "bound_released": True}
    return exercise


def commonjs(store, authority, registry, config, campaign, coordinator, adapter,
             token, before, receiver_log, base):
    input_path = Path("/link/dev10-js-input.json")
    result_path = Path("/link/dev10-js-result.json")
    require(not input_path.exists() and not result_path.exists(), "CommonJS fixture collision")
    input_path.write_text(json.dumps({"base_url": "http://127.0.0.1:8773", "token": token,
                                      "request": request_for(base, config, "commonjs")}))
    input_path.chmod(0o644)
    result_path.write_text("")
    result_path.chmod(0o666)
    try:
        for _ in range(300):
            if result_path.stat().st_size:
                break
            time.sleep(.1)
        else:
            raise AssertionError("installed CommonJS result deadline")
        result = json.loads(result_path.read_text())
        require(result["installed_package"].startswith("/app/consumer/node_modules/"),
                "CommonJS package not installed")
        require(result["duplicate_same_submission"] and result["status"] == "completed",
                "CommonJS duplicate/status failure")
        require(len(rows(receiver_log)) == before + 1, "CommonJS duplicate sent")
        require(store.intent_count(result["submission_id"]) == 1 and
                store.guard_record(result["attempt_id"]), "CommonJS intent/guard absent")
        require(campaign.summary()["incurred_decimal"] == "0.000009000",
                "CommonJS cost settlement")
        return {"arrivals": 1, "incurred_decimal": "0.000009000",
                "duplicate_arrivals": 0, "status": "completed", "installed_commonjs": True}
    finally:
        input_path.unlink(missing_ok=True)
        result_path.unlink(missing_ok=True)


def main():
    commonjs_mode = sys.argv[1:] == ["--commonjs"]
    require(not sys.argv[1:] or commonjs_mode, "unsupported target mode")
    fixture_path, request_path = fixture_paths()
    fixture, base = json.loads(fixture_path.read_text()), json.loads(request_path.read_text())
    worker = probe(Path("/link/worker.sock"), deadline_seconds=50,
                   require_empty=not commonjs_mode)
    prior_worker_attempts = len(worker["relay_attempt_counts"])
    if commonjs_mode:
        require(prior_worker_attempts >= 3 and
                all(count == 1 for count in worker["relay_attempt_counts"].values()),
                "prior Python target worker attempts changed before CommonJS proof")
    with tempfile.TemporaryDirectory(prefix="dev10-target-") as scratch:
        root = Path(scratch)
        cert, key = certificate(root)
        receiver_log = root / "receiver.jsonl"
        os.environ["DURANKI_DEV04_PROVIDER_KEY"] = "sk-" + "s" * 40
        os.environ["DURANKI_DEV04_GUARD_EVENTS"] = str(root / "guard.jsonl")
        os.environ["DURANKI_DEV04_SEND_EVENTS"] = str(root / "send.jsonl")
        with (root / "receiver.stderr").open("w") as err:
            receiver = subprocess.Popen([sys.executable, "-B",
                str(Path(__file__).with_name("dev08_tls_receiver.py")), str(cert), str(key),
                str(receiver_log), "--dev10"], stdout=subprocess.DEVNULL, stderr=err)
        try:
            for _ in range(50):
                if receiver.poll() is not None:
                    raise RuntimeError("controlled receiver exited")
                try:
                    with socket.create_connection(("127.0.0.1", 8766), timeout=.1):
                        break
                except OSError:
                    time.sleep(.1)
            else:
                raise RuntimeError("controlled receiver readiness deadline")
            cases = {}
            actions = (("commonjs", commonjs),) if commonjs_mode else (
                ("settled", settled), ("unknown", unknown),
                ("pause", queued("pause")), ("disable", queued("disable")),
                ("revocation", queued("revocation")))
            for name, action in actions:
                cases[name] = scenario(root, fixture, base, receiver_log, name, action)
            arrivals = rows(receiver_log)
            sends, guards = rows(root / "send.jsonl"), rows(root / "guard.jsonl")
            expected = 1 if commonjs_mode else 3
            require(len(arrivals) == expected and all(row["request_valid"] for row in arrivals),
                    "controlled TLS arrival reconciliation")
            require(len([row for row in sends if row["first_bytes_accepted_by_local_socket"]]) == expected,
                    "first-byte send reconciliation")
            require(len([row for row in guards if row.get("stage") == "commit_acknowledged"]) == expected,
                    "guard commit reconciliation")
            after_worker = probe(Path("/link/worker.sock"), deadline_seconds=5,
                                 require_empty=False)["relay_attempt_counts"]
            require(all(count == 1 for count in after_worker.values()),
                    "worker attempted a replay")
            if commonjs_mode:
                require(len(after_worker) == prior_worker_attempts + 1,
                        "CommonJS worker attempt not unique")
            print(json.dumps({"kind": "DEV-10 isolated installed client controlled TLS target",
                "status": "PASS", "cases": cases, "receiver_arrivals": len(arrivals),
                "first_byte_sends": expected, "guard_commits": expected,
                "prior_worker_attempts": prior_worker_attempts,
                "worker_attempts_after": len(after_worker),
                "real_provider_calls": 0}, sort_keys=True))
        finally:
            receiver.terminate()
            try:
                receiver.wait(timeout=5)
            except subprocess.TimeoutExpired:
                receiver.kill()
                receiver.wait(timeout=5)


if __name__ == "__main__":
    main()
