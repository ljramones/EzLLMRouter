"""Disposable wire-0.3 normal-HTTP → installed-client → guarded TLS campaign."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_EVEN
import hashlib
import json
import os
from pathlib import Path
from contextlib import nullcontext
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import csv
import io
import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "tests/development_slice"))

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa
from cryptography.x509.oid import NameOID

from ezllmrouter_server.core import Coordinator
from ezllmrouter_server.operator_projection import OperatorProjection
from ezllmrouter_server.operator_web import serve as serve_operator
from ezllmrouter_server.store import SQLiteStore
from ezllmrouter_server.successor_contract import content_digest
from ezllmrouter_server.successor_authority import SyntheticSuccessorAuthority
from ezllmrouter_server.successor_campaign import FiniteSuccessorCampaign
from ezllmrouter_server.successor_service import SuccessorService
from ezllmrouter_server.web import serve
from dev12_executor import Dev12SyntheticExecutor
from dev12_tls_receiver import TEST_KEY


def certificate(root, *, stem=None, valid_hours=2):
    if stem is not None and (
        not stem.startswith("receiver.continue") or not stem.replace(".", "").isalnum()
    ):
        raise ValueError("bounded continuation certificate stem required")
    if type(valid_hours) is not int or not 1 <= valid_hours <= 24:
        raise ValueError("bounded synthetic certificate validity required")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "synthetic.invalid")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=valid_hours))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("synthetic.invalid")]), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = (
        (root / "cert.pem", root / "key.pem")
        if stem is None
        else (root / (stem + ".cert.pem"), root / (stem + ".key.pem"))
    )
    if stem is not None and (cert_path.exists() or key_path.exists()):
        raise FileExistsError("continuation TLS identity already exists")
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


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def observations(path):
    return [json.loads(row) for row in path.read_text().splitlines()] if path.exists() else []


def runtime_source_identity():
    """Hash mounted runtime inputs independently of Git availability in the image."""
    roots = (
        ROOT / "server/src",
        ROOT / "clients/python/src",
        ROOT / "clients/js",
        ROOT / "tools/gateway",
        ROOT / "worker",
        ROOT / "tests/gateway_integration",
        ROOT / "tests/fixtures/contracts/dev12-successor-01",
    )
    files = sorted(
        path
        for directory in roots
        for path in directory.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix in (".py", ".cjs", ".json", ".md")
    )
    value = hashlib.sha256()
    for path in files:
        name = str(path.relative_to(ROOT)).encode()
        contents = path.read_bytes()
        value.update(len(name).to_bytes(4, "big") + name)
        value.update(len(contents).to_bytes(8, "big") + contents)
    return {"sha256": value.hexdigest(), "file_count": len(files)}


def independent_amount(name, request):
    count = len(request["input"].get("items", request["input"].get("candidates", [])))
    if name.startswith("tariff_a"):
        raw = max(Decimal("0.005"), Decimal("0.003") * ((count + 9) // 10))
    elif name.startswith("tariff_b") or name == "DELEGATED_RERANK":
        raw = Decimal(count) * Decimal("0.0003000005" if count <= 10 else "0.0004000005")
    else:
        raw = Decimal(count) * Decimal("0.000200000")
    return str(raw.quantize(Decimal("0.000000001"), rounding=ROUND_HALF_EVEN))


def fixture(case):
    vectors = json.loads(
        (ROOT / "tests/fixtures/contracts/dev12-successor-01/vectors.json").read_text()
    )
    entry = next(row for row in vectors["examples"] if row["id"] == case)
    request, context = deepcopy(entry["request"]), deepcopy(entry["trusted_context"])
    now = datetime.now(timezone.utc).replace(microsecond=0)
    fmt = lambda moment: moment.strftime("%Y-%m-%dT%H:%M:%SZ")
    request["deadline"] = fmt(now + timedelta(minutes=30))
    context["authenticated_at"] = fmt(now - timedelta(minutes=1))
    context["expires_at"] = fmt(now + timedelta(hours=1))
    return request, context


def selected_cases(full):
    base = [fixture(name) for name in ("DIRECT_DOCUMENT", "DELEGATED_RERANK", "AUTONOMOUS_QUERY")]
    if not full:
        return [
            (name, request, context)
            for name, (request, context) in zip(
                ("DIRECT_DOCUMENT", "DELEGATED_RERANK", "AUTONOMOUS_QUERY"), base
            )
        ]
    selected = []
    for family, original in (("document", base[0]), ("tariff_a", base[1]), ("tariff_b", base[1])):
        for count in range(1, 26):
            request, context = deepcopy(original)
            request["work_selector"]["step_id"] = f"step.domain.{family}.{count}"
            if family == "document":
                request["input"]["items"] = [
                    {"item_id": f"doc.{index}", "text": ("Sky", "Earth 🌍", "River")[index % 3]}
                    for index in range(1, count + 1)
                ]
            else:
                if family == "tariff_a":
                    request["requested_configuration_ref"] = "cfg.rerank.synthetic.a"
                sample = request["input"]["candidates"][0]
                request["input"]["candidates"] = []
                for index in range(1, count + 1):
                    candidate = deepcopy(sample)
                    candidate["candidate_id"] = f"doc.{index}"
                    candidate["text"] = ("Sky", "Earth 🌍", "River")[index % 3]
                    candidate["content_digest"] = content_digest(candidate)
                    request["input"]["candidates"].append(candidate)
                request["input"]["top_k"] = min(2, count)
            selected.append((f"{family}.{count}", request, context))
    selected.append(("query.1", *deepcopy(base[2])))
    return selected


def run():
    wheel = Path(os.environ["DEV12_CLIENT_WHEEL"])
    js_package = Path(os.environ["DEV12_JS_PACKAGE"])
    if not wheel.is_file():
        raise RuntimeError("installed-client wheel absent")
    if not js_package.is_file():
        raise RuntimeError("installed-client CommonJS package absent")
    source_commit = os.environ["DEV12_SOURCE_COMMIT"]
    source_tree = os.environ["DEV12_SOURCE_TREE"]
    service_image = os.environ["DEV12_SERVICE_IMAGE_ID"]
    node_image = os.environ["DEV12_NODE_IMAGE_ID"]
    if (
        len(source_commit) != 40
        or len(source_tree) != 40
        or not service_image.startswith("sha256:")
        or not node_image.startswith("sha256:")
    ):
        raise RuntimeError("exact source/image identity preflight failed")
    subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-deps",
            "--target",
            "/tmp/dev12-installed-client",
            str(wheel),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    sys.path.insert(0, "/tmp/dev12-installed-client")
    from ezllmrouter_client import EzLLMRouterClient

    worker = Path("/link/dev12-worker.sock")
    if not worker.exists():
        raise RuntimeError("networkless worker not ready")
    persistent = os.environ.get("DEV12_TARGET_DIR")
    campaign_id = os.environ.get("DEV12_CAMPAIGN_ID")
    budget_account = os.environ.get("DEV12_BUDGET_ACCOUNT_ID")
    financial_owner = os.environ.get("DEV12_FINANCIAL_OWNER_ID")
    if (
        not persistent
        or not campaign_id
        or not budget_account
        or not financial_owner
        or budget_account == "budget.synthetic.dev12"
        or financial_owner == "team.demo"
    ):
        raise RuntimeError("durable distinct supplemental campaign/scope preflight required")
    destination = Path(persistent)
    if (
        not destination.is_dir()
        or not os.access(destination, os.W_OK)
        or any(destination.iterdir())
    ):
        raise RuntimeError("empty writable durable evidence destination required")
    manager = nullcontext(persistent)
    with manager as directory:
        root = Path(directory)
        cert, key = certificate(root)
        receiver_port, service_port, operator_port = free_port(), free_port(), free_port()
        receiver_log = root / "receiver.jsonl"
        cases = selected_cases(os.environ.get("DEV12_FULL_DOMAIN") == "1")
        inventory = {
            "campaign_id": campaign_id,
            "budget_account_id": budget_account,
            "financial_owner_id": financial_owner,
            "currency": "USD",
            "predecessor_partial_campaign": "campaign.dev12.863890ce5d9c",
            "cases": [name for name, _, _ in cases]
            + ["installed_js.embedding", "installed_js.rerank"],
            "worker": "separate Docker --network none",
            "worker_socket": "/link/dev12-worker.sock",
            "receiver": f"127.0.0.1:{receiver_port}",
            "service": f"127.0.0.1:{service_port}",
            "operator": f"127.0.0.1:{operator_port}",
            "real_provider_calls": 0,
            "max_attempts": 256,
            "max_possible_sends": 256,
            "max_concurrent": 2,
            "ceiling_decimal": "3.000000000",
            "release_window_hours": 24,
            "initial_attempt_count": 0,
            "initial_possible_send_count": 0,
            "durable_evidence_directory": str(root),
            "source_commit": source_commit,
            "source_tree": source_tree,
            "mounted_source_identity": runtime_source_identity(),
            "service_image_id": service_image,
            "node_image_id": node_image,
            "python_wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
            "js_package_sha256": hashlib.sha256(js_package.read_bytes()).hexdigest(),
        }
        (root / "inventory.json").write_text(json.dumps(inventory, indent=2) + "\n")
        receiver = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-B",
                str(Path(__file__).with_name("dev12_tls_receiver.py")),
                str(cert),
                str(key),
                str(receiver_log),
                str(receiver_port),
            ],
            stdout=subprocess.DEVNULL,
            stderr=(root / "receiver.stderr").open("w"),
        )
        wire = None
        operator = None
        store = None
        coordinator = None
        try:
            for _ in range(100):
                if receiver.poll() is not None:
                    raise RuntimeError("controlled receiver failed startup")
                try:
                    with socket.create_connection(("127.0.0.1", receiver_port), timeout=0.1):
                        break
                except OSError:
                    time.sleep(0.05)
            else:
                raise RuntimeError("controlled receiver readiness deadline")
            for _, _request, context in cases:
                context["identity"]["charging_owner_id"] = financial_owner
            requests = [(request, context) for _, request, context in cases]
            js_enabled = Path("/dev12-node").is_file()
            tokens = [
                f"dev12.synthetic.token.{index}." + "x" * 32 for index in range(len(requests))
            ]
            legacy = {
                token: {
                    **context["identity"],
                    "task_id": request["work_selector"]["task_id"],
                    "expires_at": context["expires_at"],
                }
                for token, (request, context) in zip(tokens, requests)
            }
            contexts = {token: context for token, (_, context) in zip(tokens, requests)}
            store = SQLiteStore(root / "campaign.sqlite")
            signing_key = ed25519.Ed25519PrivateKey.generate()
            signing_path = root / "signing-key.pem"
            signing_path.write_bytes(
                signing_key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
            )
            signing_path.chmod(0o600)
            authority = SyntheticSuccessorAuthority(store, signing_key, "key.synthetic.dev12", "v1")
            for identity in {
                tuple(sorted(context["identity"].items())): context["identity"]
                for context in contexts.values()
            }.values():
                authority.set_historical_access(
                    identity,
                    read=True,
                    write=True,
                    resume=True,
                    observed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                )
            allowance = FiniteSuccessorCampaign(
                store, campaign_id, budget_account, financial_owner_id=financial_owner
            )
            if not js_enabled:
                raise RuntimeError("installed CommonJS runtime absent")
            started = allowance.start(
                {"receiver": inventory["receiver"], "service": inventory["service"]},
                ["campaign.sqlite", "receiver.jsonl", "/link/dev12-worker.sock"],
                max_attempts=256,
                max_concurrent=2,
                ceiling_decimal="3.000000000",
            )
            inventory["start_at"], inventory["expires_at"] = (
                started["start_at"],
                started["expires_at"],
            )
            (root / "inventory.json").write_text(json.dumps(inventory, indent=2) + "\n")
            executor = Dev12SyntheticExecutor(worker, receiver_port, cert.read_text(), TEST_KEY)
            os.environ["EZLLMROUTER_DEV04_GUARD_EVENTS"] = str(root / "guard.jsonl")
            executed = executor.execute

            def diagnosed_execute(*args, **kwargs):
                try:
                    return executed(*args, **kwargs)
                except Exception as exc:
                    print(
                        json.dumps(
                            {
                                "stage": "executor",
                                "error_type": type(exc).__name__,
                                "error": str(exc)[:160],
                                "guard_events": observations(root / "guard.jsonl"),
                                "arrivals": observations(receiver_log),
                            }
                        ),
                        file=sys.stderr,
                        flush=True,
                    )
                    raise

            executor.execute = diagnosed_execute
            permitted = lambda trusted, record: (
                trusted["principal_id"] == record["work_key"]["principal_id"]
                and trusted["source_authority_id"]
                == record["trusted_identity"]["source_authority_id"]
                and trusted["identity_binding_id"]
                == record["trusted_identity"]["identity_binding_id"]
            )
            coordinator = Coordinator(store, legacy, {}, {}, {}, None, None, {}, {}, None)
            from ezllmrouter_server.successor_assembly import attach_standalone_synthetic

            successor = attach_standalone_synthetic(
                coordinator,
                store=store,
                contexts_by_credential=contexts,
                authority=authority,
                executor=executor,
                allowance=allowance,
                read_allowed=permitted,
                usage_write_allowed=permitted,
            )
            successor.recover_incomplete()
            submitted = successor.submit

            def diagnosed_submit(*args, **kwargs):
                try:
                    return submitted(*args, **kwargs)
                except Exception as exc:
                    print(
                        json.dumps(
                            {
                                "stage": "service_submit",
                                "error_type": type(exc).__name__,
                                "error": str(exc)[:160],
                            }
                        ),
                        file=sys.stderr,
                        flush=True,
                    )
                    raise

            successor.submit = diagnosed_submit
            wire = serve("127.0.0.1", service_port, coordinator)
            threading.Thread(target=wire.serve_forever, daemon=True).start()
            operator = serve_operator(
                "127.0.0.1",
                operator_port,
                projection=OperatorProjection(store, "user.demo", str(root / "send-events.jsonl")),
                runner=None,
                password="dev12.synthetic.operator." + "x" * 32,
                fixture={"destination": {}, "policy": {}},
                build={
                    "commit": "disposable.dev12",
                    "dirty": True,
                    "fingerprint": "controlled.synthetic",
                },
                web_root=ROOT / "web",
                worker_probe=lambda: {"state": "networkless"},
                sender_status=lambda: {"state": "controlled"},
                successor_store=store,
            )
            threading.Thread(target=operator.serve_forever, daemon=True).start()
            results = []
            for index, ((request, _context), token) in enumerate(zip(requests, tokens)):
                with EzLLMRouterClient(f"http://127.0.0.1:{service_port}", token) as client:
                    reply = (
                        client.submit_embedding(request, {"wait_ms": 5000})
                        if request["operation"]["type"] == "embedding.create"
                        else client.submit_rerank(request, {"wait_ms": 5000})
                    )
                    if reply["state"] == "pending":
                        for _ in range(50):
                            status = client.get_successor_status(
                                {"submission_id": reply["handle"]["submission_id"]}
                            )
                            if status["submission_state"] != "pending":
                                break
                            time.sleep(0.05)
                    else:
                        status = client.get_successor_status(
                            {"submission_id": reply["handle"]["submission_id"]}
                        )
                    if status["submission_state"] == "completed":
                        actual = status["attempts"][0]["usage_revision"]["amount_decimal"]
                        expected = independent_amount(cases[index][0], request)
                        if actual != expected:
                            raise AssertionError(
                                f"independent native tariff mismatch: {cases[index][0]} {actual} {expected}"
                            )
                    results.append({"case": cases[index][0], "reply": reply, "status": status})
            if js_enabled:
                rerank_index = next(
                    i
                    for i, (request, _) in enumerate(requests)
                    if request["operation"]["type"] == "rerank"
                )
                for index, name in (
                    (0, "installed_js.embedding"),
                    (rerank_index, "installed_js.rerank"),
                ):
                    request = deepcopy(requests[index][0])
                    request["work_selector"]["step_id"] = "step.js." + (
                        "embedding" if index == 0 else "rerank"
                    )
                    input_file = root / ("js-input-" + str(index) + ".json")
                    input_file.write_text(
                        json.dumps(
                            {
                                "base_url": f"http://127.0.0.1:{service_port}",
                                "token": tokens[index],
                                "request": request,
                            }
                        )
                    )
                    process = subprocess.run(
                        [
                            "/dev12-node",
                            str(Path(__file__).with_name("dev12_js_actor.cjs")),
                            str(input_file),
                        ],
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    data = json.loads(process.stdout)
                    if data["status"]["attempts"][0]["usage_revision"][
                        "amount_decimal"
                    ] != independent_amount(cases[index][0], request):
                        raise AssertionError("installed JS tariff mismatch")
                    results.append({"case": name, **data})
            with EzLLMRouterClient(f"http://127.0.0.1:{service_port}", tokens[0]) as client:
                first = requests[0][0]
                duplicate = (
                    client.submit_embedding(first, {"wait_ms": 0})
                    if first["operation"]["type"] == "embedding.create"
                    else client.submit_rerank(first, {"wait_ms": 0})
                )
                if (
                    duplicate["handle"]["submission_id"]
                    != results[0]["reply"]["handle"]["submission_id"]
                ):
                    raise AssertionError("duplicate full WorkKey created a new submission")
                client.get_successor_status({"work_selector": first["work_selector"]})
            arrivals = observations(receiver_log)
            census = allowance.inspect()
            operator_origin = f"http://127.0.0.1:{operator_port}"
            with httpx.Client(
                base_url=operator_origin, trust_env=False, headers={"Origin": operator_origin}
            ) as browser:
                login = browser.post(
                    "/operator/v1/login", json={"password": "dev12.synthetic.operator." + "x" * 32}
                )
                login.raise_for_status()
                report_response = browser.get("/operator/v1/dev12-usage")
                report_response.raise_for_status()
                report = report_response.json()
                csv_response = browser.get("/operator/v1/dev12-usage?export=csv")
                csv_response.raise_for_status()
                exported = list(csv.DictReader(io.StringIO(csv_response.text)))
                if (
                    report["total"]["attempts"] != len(results)
                    or len(exported) != len(results)
                    or {row["attempt_id"] for row in exported}
                    != {row["attempt_id"] for row in report["attempts"]}
                ):
                    raise AssertionError("authenticated operator CSV/JSON unique-attempt mismatch")
            if len(observations(receiver_log)) != len(arrivals):
                raise AssertionError("read-only operator reporting caused a synthetic send")
            with store._lock:
                guard_receipts = [
                    json.loads(row[0])
                    for row in store.db.execute(
                        "SELECT guard_receipt FROM dev12_send_ownership ORDER BY rowid"
                    )
                ]
                events = [
                    {"submission_id": sid, "kind": kind, "at": at, "evidence": json.loads(raw)}
                    for sid, kind, at, raw in store.db.execute(
                        "SELECT submission_id,event_kind,observed_at,evidence FROM dev12_evidence_events ORDER BY event_id"
                    )
                ]
            evidence = {
                "inventory": inventory,
                "allowance": census,
                "arrivals": arrivals,
                "results": results,
                "guard_receipts": guard_receipts,
                "guard_events": observations(root / "guard.jsonl"),
                "store_events": events,
                "operator_report": report,
                "operator_csv_attempts": len(exported),
                "totals": {
                    item["identity"]["principal_id"]: store.successor_totals(
                        item["identity"]["principal_id"]
                    )
                    for item in contexts.values()
                },
            }
            if len(guard_receipts) != len(arrivals) or {
                row["attempt_id"]: row["body_sha256"] for row in guard_receipts
            } != {row["attempt_id"]: row["body_sha256"] for row in arrivals}:
                raise AssertionError("receiver and durable final-body correlation differs")
            (root / "target-result.json").write_text(
                json.dumps(evidence, sort_keys=True, indent=2) + "\n"
            )
            expected_count = len(requests) + (2 if js_enabled else 0)
            print(
                json.dumps(
                    {
                        "status": "PASS"
                        if len(arrivals) == expected_count
                        and all(r["status"]["submission_state"] == "completed" for r in results)
                        else "FAIL",
                        "campaign_id": campaign_id,
                        "arrivals": len(arrivals),
                        "states": [r["status"]["submission_state"] for r in results],
                        "attempt_count": census["attempt_count"],
                        "possible_send_count": census["possible_send_count"],
                    },
                    sort_keys=True,
                )
            )
            if len(arrivals) != expected_count or any(
                r["status"]["submission_state"] != "completed" for r in results
            ):
                raise AssertionError("controlled target did not complete all selected cases")
        finally:
            if operator is not None:
                operator.shutdown()
                operator.server_close()
                operator.operator_jobs.shutdown(wait=True)
            if wire is not None:
                wire.shutdown()
                wire.server_close()
            if coordinator is not None:
                coordinator.pool.shutdown(wait=True)
                coordinator.successor.pool.shutdown(wait=True)
            receiver.terminate()
            receiver.wait(timeout=5)
            if store is not None:
                store.close()


if __name__ == "__main__":
    try:
        run()
    except BaseException as exc:
        destination = os.environ.get("DEV12_TARGET_DIR")
        if destination and Path(destination).is_dir():
            (Path(destination) / "failure.json").write_text(
                json.dumps(
                    {
                        "type": type(exc).__name__,
                        "message": str(exc),
                        "traceback": traceback.format_exc(),
                        "source_commit": os.environ.get("DEV12_SOURCE_COMMIT"),
                        "mounted_source_identity": runtime_source_identity(),
                    },
                    indent=2,
                )
                + "\n"
            )
        raise
