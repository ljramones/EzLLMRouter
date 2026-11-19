"""One-use, network-isolated cache-accounting proof through the installed route."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
from ezllmrouter_client import EzLLMRouterClient
from ezllmrouter_server.core import Coordinator
from ezllmrouter_server.personal_campaign import PersonalCampaign
from ezllmrouter_server.plans import PlanAuthority
from ezllmrouter_server.registry import Registry
from ezllmrouter_server.web import serve
from choice_b_sender import ChoiceBSenderAdapter
from dev08_integrated import (TEST_KEY, TEST_TOKEN, certificate, fixture_paths, prepare_registry, rows)
from dev10_target import request_for
from proxy_recipe import GatewayProxyRecipe, proxy_policy, public_destination
from worker_ready import probe


def check(value, label):
    if not value:
        raise AssertionError(label)


def main():
    case = sys.argv[1] if len(sys.argv) == 2 else "mixed"
    if case not in ("mixed", "read", "zero", "missing", "null") or len(sys.argv) > 2:
        raise SystemExit("usage: dev11_cache_target.py [mixed|read|zero|missing|null]")
    fixture_path, request_path = fixture_paths()
    fixture, base = json.loads(fixture_path.read_text()), json.loads(request_path.read_text())
    probe(Path("/link/worker.sock"), deadline_seconds=50, require_empty=True)
    with tempfile.TemporaryDirectory(prefix="dev11-cache-target-") as scratch:
        root = Path(scratch)
        cert, key = certificate(root)
        receiver_log = root / "receiver.jsonl"
        os.environ["EZLLMROUTER_DEV04_PROVIDER_KEY"] = "sk-" + "s" * 40
        os.environ["EZLLMROUTER_DEV04_GUARD_EVENTS"] = str(root / "guard.jsonl")
        os.environ["EZLLMROUTER_DEV04_SEND_EVENTS"] = str(root / "send.jsonl")
        with (root / "receiver.stderr").open("w") as err:
            receiver = subprocess.Popen([sys.executable, "-B",
                str(Path(__file__).with_name("dev08_tls_receiver.py")), str(cert), str(key),
                str(receiver_log), "--dev11"], stdout=subprocess.DEVNULL, stderr=err)
        store = adapter = coordinator = wire = None
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
            (root / "scenario").mkdir()
            store, authority, registry, config = prepare_registry(root / "scenario", fixture,
                "https://localhost:8766", cert.read_text(), funding_kind="personal_testing")
            # Preserve v1 in the disposable price history, then publish an
            # exact fictional v2 contract; no commercial model is selected.
            contract = {"version": "openai.responses.implicit-cache.v1",
                "requested_model": "test-response-model", "returned_models": ["test-response-model"],
                "cache_mode": "implicit_default_30m", "input_token_ceiling": 1000,
                "max_output_tokens": 32, "input_bound_basis": "provider_enforced_context_window",
                "temperature_zero_supported": True, "price_conditions": "single_tier_no_modifiers",
                "price_source_url": "https://example.test/fictional-cache-rates",
                "observed_on": "2026-10-25"}
            registry.mutate("owner.local", {"operation_id": "op.dev11.cache.price",
                "action": "publish_price", "subject": config["configuration_ref"],
                "expected_revision": config["revision"], "data": {
                    "price_version": "test.dev11.cache.v1", "currency": "USD",
                    "rates": {"input_uncached": "1", "input_cache_read": "0.1",
                              "input_cache_write_30m": "1.25", "output_text": "2"},
                    "source": "operator-approved provider schedule",
                    "usage_semantics_version": "openai.responses.text.cache.v2",
                    "contract": contract}})
            registry.mutate("owner.local", {"operation_id": "op.dev11.cache.grant",
                "action": "set_grant", "subject": "owner.local", "expected_revision": 0,
                "data": {"configuration_ref": config["configuration_ref"], "status": "active",
                         "purposes": ["execution"], "task_classes": ["class.demo"]}})
            registry.controlled_provider_proof = False
            campaign = PersonalCampaign(store, registry)
            registry.personal_campaign = campaign
            campaign.configure("owner.local", {"connection_id": "conn.dev08-controlled",
                "configuration_ref": config["configuration_ref"], "principal_id": "owner.local",
                "currency": "USD", "allowance_decimal": "0.02", "per_request_decimal": "0.01",
                "max_requests": 1, "max_input_bytes": 4096, "max_output_tokens": 32,
                "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")})
            campaign.transition("owner.local", "active")
            adapter = ChoiceBSenderAdapter(authority, registry=registry, controlled_provider_proof=True)
            coordinator = Coordinator(store, {TEST_TOKEN: fixture["trusted_context"]},
                public_destination(fixture), fixture["prompt_blocks"],
                fixture["allowed_lineages"],
                PlanAuthority(ed25519.Ed25519PrivateKey.generate(), proxy_policy(fixture), registry),
                adapter, fixture["retention"], fixture["classification"],
                GatewayProxyRecipe(controlled_provider_proof=True),
                trusted_source_labels=fixture["trusted_source_labels"], registry=registry)
            wire = serve("127.0.0.1", 8773, coordinator)
            threading.Thread(target=wire.serve_forever, daemon=True).start()
            token = registry.issue_local_operator_token("owner.local")
            request = request_for(base, config, "cache-" + case)
            if case != "mixed":
                request["messages"][1]["blocks"][0]["text"] += " DEV11_CACHE_" + case.upper()
            with EzLLMRouterClient("http://127.0.0.1:8773", token) as client:
                reply = client.submit(request, {"wait_ms": 10000})
                check(reply["state"] == "delivered", "one controlled call did not deliver")
                duplicate = client.submit(request, {"wait_ms": 10000})
                check(duplicate["handle"] == reply["handle"], "duplicate changed handle")
                status = client.getStatus({"submission_id": reply["handle"]["submission_id"]})
                check(status["submission_state"] == "completed", "read-only status failed")
            candidate = reply["candidate"]
            aid, sid = candidate["attempt_id"], reply["handle"]["submission_id"]
            check(set(candidate["usage"]["revision"]["normalized_usage"]) ==
                  {"input_uncached", "input_cache_read", "input_cache_write",
                   "output_text", "output_reasoning", "other_billable"},
                  "installed client wire 0.2 shape changed")
            revision = store.get(sid)["usage"]["revision"]
            counts = revision["normalized_usage"]
            expected = {"mixed": (70, 30, 20, "known", "0.000104500"),
                        "read": (70, 0, 50, "known", "0.000097000"),
                        "zero": (0, 0, 120, "known", "0.000160000"),
                        "missing": (0, None, None, "absent", None),
                        "null": (0, None, None, "null", None)}[case]
            read, write, ordinary, state, amount = expected
            check((counts["input_total"]["count"], counts["input_cache_read"]["count"],
                   counts["input_cache_write_30m"].get("count"),
                   counts["input_uncached"].get("count"),
                   counts["output_total"]["count"], counts["output_reasoning"]["count"]) ==
                  (120, read, write, ordinary, 20, 2),
                  "cache usage lost in worker/guard/sender")
            check(revision["reported_usage"]["input_cache_write"]["state"] == state,
                  "write counter presence changed through worker")
            check(revision["cost"].get("amount_decimal") == amount and
                  revision["cost"]["status"] == ("calculated" if amount else "unknown"),
                  "calculated/unknown cost mismatch")
            summary = campaign.summary()
            check(summary["attempts"][0]["bound_decimal"] == "0.001314000" and
                  summary["attempts"][0]["state"] == ("settled" if amount else "unknown") and
                  summary["state"] == ("active" if amount else "paused") and
                  summary["incurred_decimal"] == (amount if amount else "0") and
                  summary["outstanding_decimal"] == ("0" if amount else "0.001314000"),
                  "allowance settlement or unknown exposure mismatch")
            arrivals, sends, guards = rows(receiver_log), rows(root / "send.jsonl"), rows(root / "guard.jsonl")
            check(len(arrivals) == 1 and arrivals[0]["attempt_id"] == aid and
                  arrivals[0]["request_valid"] and store.intent_count(sid) == 1 and
                  store.guard_record(aid)["attempt_id"] == aid and
                  len([x for x in sends if x["attempt_id"] == aid and
                       x["first_bytes_accepted_by_local_socket"]]) == 1 and
                  len([x for x in guards if x["attempt_id"] == aid and
                       x["stage"] == "commit_acknowledged"]) == 1,
                  "receiver/guard/send correspondence mismatch")
            print(json.dumps({"status": "PASS", "case": case, "controlled_arrivals": 1,
                "real_provider_calls": 0, "write_counter_state": state,
                "usage": {key: counts[key].get("count") for key in ("input_total", "input_cache_read",
                    "input_cache_write_30m", "input_uncached", "output_total", "output_reasoning")},
                "cost_status": revision["cost"]["status"], "calculated_usd": amount,
                "reserved_usd": summary["attempts"][0]["bound_decimal"],
                "outstanding_usd": summary["outstanding_decimal"],
                "campaign_state": summary["state"],
                "attempt_correlated": True, "duplicate_send_count": 0, "read_only_send_count": 0},
                sort_keys=True))
        finally:
            if wire:
                wire.shutdown()
                wire.server_close()
            if coordinator:
                coordinator.pool.shutdown(wait=True)
            if adapter:
                adapter.close()
            if store:
                store.close()
            receiver.terminate()
            receiver.wait(timeout=5)


if __name__ == "__main__":
    main()
