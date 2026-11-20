"""Disposable installed-client → isolated worker → trusted TLS sender proof."""

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

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa
from cryptography.x509.oid import NameOID

from ezllmrouter_server.core import Coordinator
from ezllmrouter_server.plans import PlanAuthority
from ezllmrouter_server.provider_vault import ProviderVault
from ezllmrouter_server.registry import Registry
from ezllmrouter_server.store import SQLiteStore
from ezllmrouter_server.web import serve
from choice_b_sender import ChoiceBSenderAdapter
from owned_sender_transport import LocalSendAuthority
from proxy_recipe import GatewayProxyRecipe, proxy_policy, public_destination


TEST_TOKEN = "dev08-controlled-client-token-000000000000000000"
TEST_KEY = "test-provider-key-123456"


def fixture_paths():
    local = Path(__file__).resolve().parents[1] / "dev_slice"
    if not local.is_dir():
        local = Path(__file__).resolve().parents[2] / "tests/development_slice"
        fixture = Path(__file__).with_name("dev05_fixture.json")
    else:
        fixture = local / "fixture.json"
    return fixture, local / "request.json"


def certificate(root):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = root / "cert.pem", root / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)
    return cert_path, key_path


def prepare_registry(
    root, fixture, origin, ca_pem, *, funding_kind=None, display_name="Controlled TLS fixture"
):
    store = SQLiteStore(root / "store.sqlite")
    authority = LocalSendAuthority()
    registry = Registry(
        store,
        authority,
        legacy_destination=public_destination(fixture),
        legacy_token=TEST_TOKEN,
        legacy_trusted=fixture["trusted_context"],
        provider_vault=ProviderVault(root / "vault"),
        provider_execution_ready=True,
        controlled_provider_proof=True,
    )
    count = 0

    def change(action, subject, expected, data):
        nonlocal count
        count += 1
        return registry.mutate(
            "owner.local",
            {
                "operation_id": f"op.dev08.integrated.{count}",
                "action": action,
                "subject": subject,
                "expected_revision": expected,
                "data": data,
            },
        )["record"]

    model = change(
        "register_catalogue",
        "catalogue.operator.dev08-controlled",
        0,
        {
            "display_name": "Controlled synthetic Responses model",
            "vendor": "Test fixture",
            "family": "Responses",
            "api_model_id": "test-response-model",
            "model_version": "test-v1",
            "owner": "owner.local",
            "capabilities": ["text"],
            "context_window": None,
            "max_output": None,
            "notes": "Synthetic, never a real provider entry",
            "price": {
                "snapshot_id": "test.dev08.reference.v1",
                "source_title": "Test fixture",
                "source_url": "https://example.org/test",
                "bands": [
                    {
                        "label": "Test",
                        "conditions": {},
                        "rates_usd_per_1000000_tokens": {
                            "input_uncached": "1",
                            "output": "2",
                            "input_cached": None,
                        },
                    }
                ],
            },
        },
    )
    connection = change(
        "create_connection",
        "conn.dev08-controlled",
        0,
        {
            "display_name": display_name,
            "adapter_id": "openai.responses.v1",
            "settings": {
                "origin": origin,
                "location": "commercial",
                "site": "Controlled local",
                "ca_pem": ca_pem,
            },
            "owner": "owner.local",
            **({"funding_kind": funding_kind} if funding_kind else {}),
        },
    )
    connection = registry.set_provider_credential(
        "owner.local",
        connection["connection_id"],
        1,
        "op.dev08.integrated.credential",
        "replace",
        TEST_KEY,
    )["record"]
    connection = change(
        "connection_state",
        connection["connection_id"],
        2,
        {"status": "active", "reason": "Isolated controlled proof"},
    )
    connection = change(
        "associate_deployment",
        connection["connection_id"],
        3,
        {
            "deployment_id": "deployment.dev08-controlled",
            "model_ref": model["configuration_ref"],
            "serving_id": "test-response-model",
            "site": "Controlled local",
            "status": "catalogued",
        },
    )
    change(
        "set_source_permissions",
        connection["connection_id"],
        0,
        {"allowed": True, "items": [{"serving_id": "test-response-model", "expected_revision": 0}]},
    )
    config = change(
        "create_provider_configuration",
        "cfg.provider.dev08-controlled",
        0,
        {
            "display_name": "Controlled Responses text",
            "deployment_id": "deployment.dev08-controlled",
            "owner": "owner.local",
            "purposes": ["execution"],
            "task_classes": ["class.demo"],
        },
    )
    config = change(
        "publish_price",
        config["configuration_ref"],
        1,
        {
            "price_version": "test.dev08.price.v1",
            "currency": "USD",
            "rates": {"input_uncached": "1", "output_text": "2"},
            "source": "operator-approved provider schedule",
            "usage_semantics_version": "openai.responses.text.v1",
        },
    )
    config = change(
        "model_state",
        config["configuration_ref"],
        2,
        {"status": "enabled", "reason": "Controlled execution only"},
    )
    change(
        "set_grant",
        "svc.demo",
        0,
        {
            "configuration_ref": config["configuration_ref"],
            "status": "active",
            "purposes": ["execution"],
            "task_classes": ["class.demo"],
        },
    )
    return store, authority, registry, config


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def run(preflight=False):
    fixture_path, request_path = fixture_paths()
    fixture = json.loads(fixture_path.read_text())
    request = json.loads(request_path.read_text())
    with tempfile.TemporaryDirectory(prefix="dev08-integrated-") as scratch:
        root = Path(scratch)
        cert_path, key_path = certificate(root)
        origin = "https://localhost:8766"
        store, authority, registry, config = prepare_registry(
            root, fixture, origin, cert_path.read_text()
        )
        try:
            destination, decision = registry.admit(
                "svc.demo", config["configuration_ref"], "execution", "class.demo", ("text",)
            )
            if (
                destination["endpoint"] != origin
                or decision["price_version"] != "test.dev08.price.v1"
            ):
                raise AssertionError("controlled provider binding mismatch")
            request["requested_configuration_ref"] = config["configuration_ref"]
            request["step_id"] = "step.dev08.integrated"
            request["execution_generation"] = "gen.dev08.integrated"
            request["generation_settings"]["total_timeout_ms"] = 10000
            prepared, _ = GatewayProxyRecipe(controlled_provider_proof=True).expected(
                {"destination": destination, "work": request}, 10000
            )
            if json.loads(prepared)["model"] != "openai/test-response-model":
                raise AssertionError("selected private recipe mismatch")
            if preflight:
                print(
                    json.dumps(
                        {
                            "kind": "DEV-08 controlled integrated preflight",
                            "status": "PASS",
                            "provider_execution_only_in_disposable_fixture": True,
                            "network_or_model_requests": 0,
                        },
                        sort_keys=True,
                    )
                )
                return
            from ezllmrouter_client import EzLLMRouterClient
            from worker_ready import probe

            probe(Path("/link/worker.sock"), deadline_seconds=50, require_empty=True)
            os.environ["EZLLMROUTER_DEV04_PROVIDER_KEY"] = "sk-" + "s" * 40
            os.environ["EZLLMROUTER_DEV04_GUARD_EVENTS"] = str(root / "guard.jsonl")
            os.environ["EZLLMROUTER_DEV04_SEND_EVENTS"] = str(root / "send.jsonl")
            receiver_log = root / "receiver.jsonl"
            receiver_error = root / "receiver.stderr"
            with receiver_error.open("w") as err:
                receiver = subprocess.Popen(
                    [
                        sys.executable,
                        "-B",
                        str(Path(__file__).with_name("dev08_tls_receiver.py")),
                        str(cert_path),
                        str(key_path),
                        str(receiver_log),
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=err,
                )
            adapter = None
            wire = None
            coordinator = None
            stage = "receiver_ready"
            try:
                for _ in range(50):
                    if receiver.poll() is not None:
                        raise RuntimeError("controlled receiver exited before readiness")
                    try:
                        with socket.create_connection(("127.0.0.1", 8766), timeout=0.1):
                            break
                    except OSError:
                        time.sleep(0.1)
                else:
                    raise RuntimeError("controlled receiver readiness deadline")
                stage = "sender_and_coordinator"
                adapter = ChoiceBSenderAdapter(
                    authority, registry=registry, controlled_provider_proof=True
                )
                coordinator = Coordinator(
                    store,
                    {TEST_TOKEN: fixture["trusted_context"]},
                    public_destination(fixture),
                    fixture["prompt_blocks"],
                    fixture["allowed_lineages"],
                    PlanAuthority(
                        ed25519.Ed25519PrivateKey.generate(), proxy_policy(fixture), registry
                    ),
                    adapter,
                    fixture["retention"],
                    fixture["classification"],
                    GatewayProxyRecipe(controlled_provider_proof=True),
                    trusted_source_labels=fixture["trusted_source_labels"],
                    registry=registry,
                )
                wire = serve("127.0.0.1", 8773, coordinator)
                thread = threading.Thread(target=wire.serve_forever, daemon=True)
                thread.start()
                stage = "installed_client_submit"
                with EzLLMRouterClient("http://127.0.0.1:8773", TEST_TOKEN) as client:
                    reply = client.submit(request, {"wait_ms": 10000})
                    if reply["state"] != "delivered":
                        raise AssertionError(
                            "controlled installed-client result not delivered: " + reply["state"]
                        )
                    candidate = reply["candidate"]
                    submission_id = reply["handle"]["submission_id"]
                    stage = "installed_client_status"
                    status = client.getStatus({"submission_id": submission_id})
                stage = "correlation"
                if (
                    candidate["output_blocks"][0]["text"] != "Hello."
                    or status["submission_state"] != "completed"
                ):
                    raise AssertionError("controlled Responses candidate mismatch")
                if candidate["output_blocks"][0]["source_labels"]["lineage_ids"] != [
                    "src.candidate.provider"
                ]:
                    raise AssertionError("provider candidate provenance mismatch")
                arrivals, sends, guards = (
                    rows(receiver_log),
                    rows(root / "send.jsonl"),
                    rows(root / "guard.jsonl"),
                )
                attempt = candidate["attempt_id"]
                if (
                    len(arrivals) != 1
                    or arrivals[0]["attempt_id"] != attempt
                    or not arrivals[0]["request_valid"]
                    or len(sends) != 1
                    or sends[0]["attempt_id"] != attempt
                    or sends[0]["first_bytes_accepted_by_local_socket"] is not True
                    or sends[0]["first_acceptance_events"] != 1
                    or len(
                        [
                            g
                            for g in guards
                            if g["stage"] == "commit_acknowledged" and g["attempt_id"] == attempt
                        ]
                    )
                    != 1
                ):
                    raise AssertionError("controlled receiver/guard/first-write correlation failed")
                record = store.get(submission_id)
                if (
                    record["attempt_id"] != attempt
                    or store.intent_count(submission_id) != 1
                    or store.guard_record(attempt)["attempt_id"] != attempt
                ):
                    raise AssertionError("attempt-linked durable accounting mismatch")
                registry.mutate(
                    "owner.local",
                    {
                        "operation_id": "op.dev08.integrated.disable",
                        "action": "connection_state",
                        "subject": "conn.dev08-controlled",
                        "expected_revision": 4,
                        "data": {"status": "disabled", "reason": "Controlled negative"},
                    },
                )
                if (
                    registry.explain(
                        "svc.demo", config["configuration_ref"], "execution", "class.demo"
                    )["reason"]
                    != "TRANSPORT_UNAVAILABLE"
                ):
                    raise AssertionError("disabled connection still eligible")
                if len(rows(receiver_log)) != 1:
                    raise AssertionError("read-only eligibility check added request")
                print(
                    json.dumps(
                        {
                            "kind": "DEV-08 installed-client controlled HTTPS proof",
                            "status": "PASS",
                            "submissions": 1,
                            "receiver_arrivals": 1,
                            "attempt_correlated": True,
                            "first_socket_acceptance_events": 1,
                            "post_disable_eligibility": "TRANSPORT_UNAVAILABLE",
                            "real_provider_calls": 0,
                            "controlled_receiver_only": True,
                        },
                        sort_keys=True,
                    )
                )
            except Exception as exc:
                diagnostic = {
                    "kind": "DEV-08 controlled integration failure checkpoint",
                    "stage": stage,
                    "exception_type": type(exc).__name__,
                    "receiver_arrivals": len(rows(receiver_log)),
                    "send_events": len(rows(root / "send.jsonl")),
                    "guard_stages": [row.get("stage") for row in rows(root / "guard.jsonl")][:20],
                }
                if type(exc).__name__ == "EzLLMRouterError":
                    diagnostic["sdk_code"] = exc.code
                    diagnostic["http_status"] = exc.http_status
                    diagnostic["failure_stage"] = exc.failure_stage
                print(json.dumps(diagnostic, sort_keys=True), file=sys.stderr)
                raise
            finally:
                if wire is not None:
                    wire.shutdown()
                    wire.server_close()
                if coordinator is not None:
                    coordinator.pool.shutdown(wait=True)
                if adapter is not None:
                    adapter.close()
                receiver.terminate()
                try:
                    receiver.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    receiver.kill()
                    receiver.wait(timeout=5)
        finally:
            store.close()


if __name__ == "__main__":
    try:
        run(preflight=sys.argv[1:] == ["--preflight"])
    except Exception as exc:
        print("DEV-08 controlled integration failed: " + type(exc).__name__, file=sys.stderr)
        raise SystemExit(1) from exc
