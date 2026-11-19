"""Disposable DEV-11 normal console with one cache-bearing controlled TLS send."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time

from cryptography.hazmat.primitives.asymmetric import ed25519
from ezllmrouter_server.core import Coordinator
from ezllmrouter_server.operator_demo import DemoRunner, ProviderValidationRunner
from ezllmrouter_server.operator_projection import OperatorProjection
from ezllmrouter_server.operator_web import serve as serve_operator
from ezllmrouter_server.personal_campaign import PersonalCampaign
from ezllmrouter_server.plans import PlanAuthority
from ezllmrouter_server.web import serve as serve_wire
from choice_b_sender import ChoiceBSenderAdapter
from dev08_integrated import (TEST_TOKEN, certificate, fixture_paths,
                              prepare_registry, rows)
from proxy_recipe import GatewayProxyRecipe, proxy_policy, public_destination
from worker_ready import probe


ROOT = Path("/tmp/dev11-browser")
PASSWORD = "dev11-synthetic-browser-password-000000000000"


def audit():
    database = sqlite3.connect(f"file:{ROOT / 'store.sqlite'}?mode=ro", uri=True)
    try:
        submissions = [json.loads(row[0]) for row in database.execute("SELECT record FROM submissions")]
        intents = [row[0] for row in database.execute("SELECT attempt_id FROM intents")]
        dispatches = [(row[0], json.loads(row[1])) for row in database.execute(
            "SELECT attempt_id,receipt FROM guard_dispatches")]
        usage = [json.loads(row[0]) for row in database.execute("SELECT usage FROM usage_revisions")]
        attempts = database.execute("SELECT attempt_id,submission_id,bound_decimal,cost_decimal,state "
                                    "FROM personal_campaign_attempts").fetchall()
        validations = database.execute("SELECT operation_id,state,submission_id FROM operator_provider_validations").fetchall()
        campaign = json.loads(database.execute("SELECT record FROM personal_campaigns").fetchone()[0])
    finally:
        database.close()
    arrivals, sends, guards = (rows(ROOT / name) for name in
                              ("receiver.jsonl", "send.jsonl", "guard.jsonl"))
    if (len(submissions) != 1 or len(intents) != 1 or len(dispatches) != 1 or
            len(usage) != 1 or len(attempts) != 1 or len(validations) != 1 or
            len(arrivals) != 1 or len(sends) != 1):
        raise AssertionError("browser generation was not exactly one attempt and arrival")
    submission, attempt = submissions[0], attempts[0]
    attempt_id = submission["attempt_id"]
    if (submission["submission_state"] != "completed" or
            submission["submission_id"] != attempt[1] or
            attempt[0] != attempt_id or attempt[4] != "settled" or
            attempt[3] != "0.000104500" or
            intents != [attempt_id] or [row[0] for row in dispatches] != [attempt_id] or
            dispatches[0][1]["body_sha256"] != arrivals[0]["body_sha256"] or
            dispatches[0][1]["body_bytes"] != arrivals[0]["body_bytes"] or
            arrivals[0]["attempt_id"] != attempt_id or not arrivals[0]["request_valid"] or
            sends[0]["attempt_id"] != attempt_id or
            sends[0]["first_bytes_accepted_by_local_socket"] is not True or
            sends[0]["first_acceptance_events"] != 1 or
            len([event for event in guards if event.get("stage") == "commit_acknowledged" and
                 event.get("attempt_id") == attempt_id]) != 1 or
            usage[0]["cost"] != {"status": "calculated", "currency": "USD",
                "amount_decimal": "0.000104500", "source_ref": "test.dev11.browser.cache.v1"} or
            (usage[0]["normalized_usage"]["input_total"]["count"],
             usage[0]["normalized_usage"]["input_uncached"]["count"],
             usage[0]["normalized_usage"]["input_cache_read"]["count"],
             usage[0]["normalized_usage"]["input_cache_write_30m"]["count"]) !=
            (120, 20, 70, 30) or
            validations[0][1:] != ("completed", submission["submission_id"])):
        raise AssertionError("browser attempt, guard, sender or accounting mismatch")
    available = str(Decimal(campaign["allowance_decimal"]) - Decimal(attempt[3]))
    print(json.dumps({"status": "PASS", "submission_id": submission["submission_id"],
        "attempt_id": attempt_id, "receiver_arrivals": 1, "guard_commits": 1,
        "first_byte_sends": 1, "validation_state": "completed",
        "output": submission["candidate"]["output_blocks"][0]["text"],
        "input_total": usage[0]["normalized_usage"]["input_total"]["count"],
        "ordinary_input": usage[0]["normalized_usage"]["input_uncached"]["count"],
        "cache_read": usage[0]["normalized_usage"]["input_cache_read"]["count"],
        "cache_write_30m": usage[0]["normalized_usage"]["input_cache_write_30m"]["count"],
        "output_tokens": usage[0]["normalized_usage"]["output_total"]["count"],
        "calculated_cost_decimal": attempt[3], "reserved_decimal": attempt[2],
        "request_count": 1, "outstanding_decimal": "0", "available_decimal": available,
        "campaign_state": campaign["state"], "receiver_path": arrivals[0]["path"],
        "receiver_body_sha256": arrivals[0]["body_sha256"]}, sort_keys=True))


def main():
    if sys.argv[1:] == ["--audit"]:
        audit()
        return
    if sys.argv[1:]:
        raise SystemExit("usage: dev10_browser_service.py [--audit]")
    ROOT.mkdir(mode=0o700)
    fixture_path, request_path = fixture_paths()
    fixture, request = json.loads(fixture_path.read_text()), json.loads(request_path.read_text())
    cert, key = certificate(ROOT)
    receiver = subprocess.Popen([sys.executable, "-B",
        str(Path(__file__).with_name("dev08_tls_receiver.py")), str(cert), str(key),
        str(ROOT / "receiver.jsonl"), "--dev11"], stdout=subprocess.DEVNULL,
        stderr=(ROOT / "receiver.stderr").open("w"))
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
    store, authority, registry, config = prepare_registry(ROOT, fixture,
        "https://localhost:8766", cert.read_text(), funding_kind="personal_testing",
        display_name="Synthetic personal TLS browser fixture")
    registry.mutate("owner.local", {"operation_id": "op.dev11.browser.cache.price",
        "action": "publish_price", "subject": config["configuration_ref"],
        "expected_revision": config["revision"], "data": {
            "price_version": "test.dev11.browser.cache.v1", "currency": "USD",
            "rates": {"input_uncached": "1", "input_cache_read": "0.1",
                      "input_cache_write_30m": "1.25", "output_text": "2"},
            "source": "operator-approved provider schedule",
            "usage_semantics_version": "openai.responses.text.cache.v2",
            "contract": {"version": "openai.responses.implicit-cache.v1",
                "requested_model": "test-response-model", "returned_models": ["test-response-model"],
                "cache_mode": "implicit_default_30m", "input_token_ceiling": 1000,
                "max_output_tokens": 32, "input_bound_basis": "provider_enforced_context_window",
                "temperature_zero_supported": True, "price_conditions": "single_tier_no_modifiers",
                "price_source_url": "https://example.test/fictional-cache-rates",
                "observed_on": "2026-10-25"}}})
    registry.mutate("owner.local", {"operation_id": "op.dev11.browser.owner.grant",
        "action": "set_grant", "subject": "owner.local", "expected_revision": 0,
        "data": {"configuration_ref": config["configuration_ref"], "status": "active",
                 "purposes": ["execution"], "task_classes": ["class.demo"]}})
    registry.controlled_provider_proof = False
    registry.personal_campaign = PersonalCampaign(store, registry)
    os.environ["EZLLMROUTER_DEV04_PROVIDER_KEY"] = "sk-" + "s" * 40
    os.environ["EZLLMROUTER_DEV04_GUARD_EVENTS"] = str(ROOT / "guard.jsonl")
    os.environ["EZLLMROUTER_DEV04_SEND_EVENTS"] = str(ROOT / "send.jsonl")
    adapter = ChoiceBSenderAdapter(authority, registry=registry, controlled_provider_proof=True)
    registry.runtime_ready = lambda: adapter.server_thread.is_alive() and not authority.is_revoked()
    coordinator = Coordinator(store, {TEST_TOKEN: fixture["trusted_context"]},
        public_destination(fixture), fixture["prompt_blocks"], fixture["allowed_lineages"],
        PlanAuthority(ed25519.Ed25519PrivateKey.generate(), proxy_policy(fixture), registry),
        adapter, fixture["retention"], fixture["classification"],
        GatewayProxyRecipe(controlled_provider_proof=True),
        trusted_source_labels=fixture["trusted_source_labels"], registry=registry)
    projection = OperatorProjection(store, fixture["trusted_context"]["principal_id"],
                                    ROOT / "send.jsonl")
    runner = DemoRunner(request, {}, "http://127.0.0.1:8773", TEST_TOKEN)
    validation = ProviderValidationRunner(request, "http://127.0.0.1:8773",
                                          TEST_TOKEN, "svc.demo")
    wire = serve_wire("127.0.0.1", 8773, coordinator)
    operator = serve_operator("0.0.0.0", 8780, projection=projection, runner=runner,
        password=PASSWORD, fixture=fixture,
        build=json.loads(Path("/app/local/build-identity.json").read_text()),
        web_root="/app/web", worker_probe=lambda: {"state": "live",
            "observed_attempts": len(probe(Path("/link/worker.sock"), deadline_seconds=1,
                                           require_empty=False)["relay_attempt_counts"])},
        sender_status=lambda: {"state": "live" if adapter.server_thread.is_alive() else "unavailable"},
        registry=registry, provider_validation=validation,
        allowed_hosts={"127.0.0.1:8790"})
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    for server in (wire, operator):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    print(json.dumps({"ready": True, "build_commit":
        json.loads(Path("/app/local/build-identity.json").read_text())["commit"],
        "at": datetime.now(timezone.utc).isoformat()}), flush=True)
    try:
        stop.wait()
    finally:
        for server in (operator, wire):
            server.shutdown()
            server.server_close()
        operator.operator_jobs.shutdown(wait=True)
        coordinator.pool.shutdown(wait=True)
        adapter.close()
        store.close()
        receiver.terminate()
        receiver.wait(timeout=5)


if __name__ == "__main__":
    main()
