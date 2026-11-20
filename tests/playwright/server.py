"""Disposable real console for browser tests; controls use stdin, never HTTP routes."""

from __future__ import annotations

import argparse
from contextlib import suppress
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/src"))
from ezllmrouter_server.operator_projection import OperatorProjection
from ezllmrouter_server.integration_credentials import DatabaseCredentialStore
from ezllmrouter_server.operator_web import serve
from ezllmrouter_server.registry import Registry
from ezllmrouter_server.provider_vault import ProviderVault
from ezllmrouter_server.store import SQLiteStore, encode
from ezllmrouter_server.user_management import UserManager

BOOTSTRAP = "Browser bootstrap passphrase!2026"
ADMIN = "Browser administrator passphrase!2026"
USER = "Browser user passphrase!2026"
TOKEN = "browser-fixture-private-operator-token-0000000000"
DESTINATION = {
    "configuration_ref": "cfg.demo",
    "service": "litellm.dev04",
    "endpoint": "127.0.0.1",
    "model": "model.demo",
    "model_version": "v1",
    "processing_region": "local",
}


class Authority:
    def __init__(self):
        self.gate = threading.RLock()
        self.epoch = 0


class NoExecution:
    def __init__(self):
        self.calls = 0

    def run(self, *_args, **_kwargs):
        self.calls += 1
        raise AssertionError("Browser journeys must not execute a model")


class Inventory(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self):
        self.server.inference_requests += 1
        self.send_error(405)

    def do_GET(self):
        self.server.requests.append(self.path)
        mode = self.server.mode
        if mode == "auth":
            status, value = (
                401,
                {"error": "Synthetic private provider detail must not be displayed"},
            )
        elif mode == "unavailable":
            status, value = 503, {"error": "synthetic offline"}
        elif mode == "invalid":
            status, value = 200, {"invalid": True}
        elif self.path == "/api/version":
            status, value = 200, {"version": "0.9.0"}
        elif self.path == "/api/ps":
            status, value = (
                200,
                {
                    "models": [
                        {"name": "browser.text.v1", "model": "browser.text.v1", "size_vram": 1024}
                    ]
                },
            )
        elif self.path == "/api/tags":
            models = (
                []
                if mode == "empty"
                else [
                    {
                        "name": "browser.text.v1",
                        "model": "browser.text.v1",
                        "size": 2048,
                        "details": {
                            "family": "browser-fixture",
                            "format": "gguf",
                            "parameter_size": "1B",
                        },
                    }
                ]
            )
            status, value = 200, {"models": models}
        elif self.path == "/v1/models":
            status, value = (
                200,
                {
                    "data": []
                    if mode == "empty"
                    else [
                        {"id": "browser.text.v1", "object": "model", "owned_by": "browser-fixture"}
                    ]
                },
            )
        else:
            status, value = 404, {"error": "Fixed inventory paths only"}
        raw = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def seed(store, registry, users, options):
    if not options.get("bootstrap", False):
        users.change_password("owner.local", {"current_password": BOOTSTRAP, "new_password": ADMIN})
    identities = {}
    for name, role in (("reader", "read_only_operator"), ("member", "ordinary")):
        account = users.create(
            "owner.local",
            {
                "username": name,
                "display_name": name.title() + " Browser",
                "role": role,
                "status": "active",
                "password": BOOTSTRAP,
            },
        )
        users.change_password(
            account["principal_id"], {"current_password": BOOTSTRAP, "new_password": USER}
        )
        identities[name] = account["principal_id"]
    if not options.get("seed", True):
        return identities
    catalogue = json.loads((ROOT / "deploy/local/inputs/catalogue.json").read_text())
    sources = {item["id"]: item for item in catalogue["sources"]}
    for index, entry in enumerate(catalogue["models"]):
        registry.mutate(
            "owner.local",
            {
                "operation_id": "op.browser.catalogue." + str(index),
                "action": "import_catalogue",
                "subject": "catalogue." + entry["catalogue_key"],
                "expected_revision": 0,
                "data": {"entry": entry, "sources": [sources[key] for key in entry["source_refs"]]},
            },
        )
    for index, principal in enumerate((identities["member"], "svc.demo", identities["reader"]), 1):
        identifier = "submission.browser." + str(index)
        store.create(
            {
                "submission_id": identifier,
                "attempt_id": "attempt.browser." + str(index),
                "principal_id": principal,
                "task_id": "task.browser." + str(index),
                "task_class": "class.demo",
                "purpose": "execution",
                "created_at": "2026-11-01T00:00:00Z",
                "updated_at": "2026-11-01T00:00:01Z",
                "work_digest": "sha256:" + str(index) * 64,
                "status_revision": 1,
                "work_key": {
                    "principal_id": principal,
                    "task_id": "task.browser." + str(index),
                    "step_id": "step.browser." + str(index),
                    "step_revision": 1,
                    "execution_generation": "gen.1",
                },
                "submission_state": "completed" if index != 2 else "failed_before_transmit",
                "dispatch_state": "response_observed" if index != 2 else "failed_before_dispatch",
            }
        )
        if index != 2:
            store.db.execute(
                "INSERT INTO intents VALUES (?,?,?)",
                ("attempt.browser." + str(index), identifier, encode({"destination": DESTINATION})),
            )
    # Append actual versioned ledger events, including an unknown cost replaced
    # by a known cost. These observations never dispatch a request.
    registry.mutate(
        "owner.local",
        {
            "operation_id": "op.browser.ingest",
            "action": "create_principal",
            "subject": "svc.browser",
            "expected_revision": 0,
            "data": {
                "display_name": "Browser accounting service",
                "kind": "service",
                "owner": "owner.local",
            },
        },
    )
    registry.provision_credential("owner.local", "svc.browser", 1, "op.browser.ingest.credential")
    registry.mutate(
        "owner.local",
        {
            "operation_id": "op.browser.ingest.activate",
            "action": "principal_state",
            "subject": "svc.browser",
            "expected_revision": 2,
            "data": {"status": "active", "reason": "Synthetic browser fixture"},
        },
    )
    examples = json.loads(
        (ROOT / "tests/fixtures/contracts/integration-readiness-v2/examples.json").read_text()
    )
    dataset = {**examples["dataset"], "ingest_principal_id": "svc.browser"}
    ledger = registry.integration
    ledger.create_dataset(registry.principal("owner.local"), dataset, "2")
    ledger.create_account(registry.principal("owner.local"), examples["account"], "2")
    for event in examples["events"][:3]:
        ledger.append_event(registry.principal("svc.browser"), event, "2")
    unknown = {
        **examples["events"][0],
        "event_id": "event.browser.unknown",
        "attempt_id": "attempt.browser.unknown",
        "step_id": "step.unknown",
        "logical_operation_id": "logical.browser.unknown",
    }
    ledger.append_event(registry.principal("svc.browser"), unknown, "2")
    return identities


class Instance:
    def __init__(self, root, options):
        self.root, self.options = root, options
        self.runner = NoExecution()
        self.port = 0
        self.server = self.thread = self.store = None
        self.identities = {}
        self.metadata_probes = 0
        self.connections = set()
        self.connection_lock = threading.Lock()

    def credential_inventory(self, _adapter, _settings, key, _operation, **_kwargs):
        """Replace the external provider boundary, retaining real credential storage."""
        self.metadata_probes += 1
        if key.startswith("bad-"):
            return {
                "state": "failed",
                "reason": "credential_rejected",
                "models": [],
                "has_more": False,
            }
        return {
            "state": "observed",
            "reason": "browser_fixture_inventory",
            "models": ["browser.text.v1"],
            "details": [{"id": "browser.text.v1", "name": "Browser text model"}],
            "has_more": False,
        }

    def open_store(self, initial=False):
        self.store = SQLiteStore(self.root / "browser.sqlite")
        self.registry = Registry(
            self.store,
            Authority(),
            legacy_destination=DESTINATION,
            legacy_token=TOKEN,
            legacy_trusted={"principal_id": "svc.demo", "charging_owner_id": "team.browser"},
            provider_vault=ProviderVault(self.root / "vault"),
        )
        self.users = UserManager(
            self.registry, bootstrap_password_file=self.root / "admin.password"
        )
        self.registry.integration_credentials = DatabaseCredentialStore(
            self.registry,
            self.root / "integration.keys.json",
            discover=self.credential_inventory,
            controlled=True,
        )
        if initial:
            self.identities = seed(self.store, self.registry, self.users, self.options)

    def start(self, initial=False):
        self.open_store(initial)
        fixture = json.loads((ROOT / "tests/gateway_integration/dev05_fixture.json").read_text())
        self.server = serve(
            "127.0.0.1",
            self.port,
            projection=OperatorProjection(self.store, "svc.demo"),
            runner=self.runner,
            password=TOKEN,
            fixture=fixture,
            build={
                "commit": "browser-fixture",
                "fingerprint": "browser-fixture",
                "dirty": False,
                "profile": "browser-test",
            },
            web_root=ROOT / "web",
            worker_probe=lambda: {"state": "disabled"},
            sender_status=lambda: {"state": "disabled"},
            registry=self.registry,
            integration_only=self.options.get("integrationOnly", False),
            successor_store=self.store,
        )
        self.port = self.server.server_port
        self.server.application.allowed_hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        self.server.application.allowed_origins = {
            "http://" + host for host in self.server.application.allowed_hosts
        }
        # Restart must retire established HTTP connections before closing SQLite.
        # Otherwise a browser can send its next request to an old handler thread.
        self.server.daemon_threads = False
        self.server.block_on_close = True
        accept_request = self.server.get_request
        release_request = self.server.shutdown_request

        def accept():
            connection, address = accept_request()
            with self.connection_lock:
                self.connections.add(connection)
            return connection, address

        def release(connection):
            try:
                release_request(connection)
            finally:
                with self.connection_lock:
                    self.connections.discard(connection)

        self.server.get_request = accept
        self.server.shutdown_request = release
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        if self.server:
            self.server.shutdown()
            with self.connection_lock:
                connections = tuple(self.connections)
            for connection in connections:
                with suppress(OSError):
                    connection.shutdown(socket.SHUT_RDWR)
                connection.close()
            self.thread.join(timeout=5)
            self.server.server_close()
            with self.connection_lock:
                self.connections.clear()
            self.server = None
        if self.store:
            self.store.close()
            self.store = None

    def state(self):
        return {
            "submissions": self.store.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0],
            "datasets": self.store.db.execute(
                "SELECT COUNT(*) FROM integration_datasets"
            ).fetchone()[0],
            "credential_metadata_probes": self.metadata_probes,
            "execution_calls": self.runner.calls,
        }

    def correct_usage(self):
        examples = json.loads(
            (ROOT / "tests/fixtures/contracts/integration-readiness-v2/examples.json").read_text()
        )
        event = deepcopy(examples["events"][2])
        event.update(
            event_id="event.browser.usage.3",
            usage_revision=3,
            occurred_at="2026-10-27T00:00:40Z",
            amount_decimal="0.030000000",
        )
        return self.registry.integration.append_event(
            self.registry.principal("svc.browser"), event, "2"
        )[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--options", default="{}")
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    options = json.loads(args.options)
    os.environ["EZLLMROUTER_ADMIN_USERNAME"] = "admin"
    os.environ["EZLLMROUTER_ADMIN_PASSWORD"] = BOOTSTRAP
    with tempfile.TemporaryDirectory(prefix="ezllmrouter-browser-") as directory:
        instance = Instance(Path(directory), options)
        if args.validate:
            try:
                instance.open_store(initial=True)
                print(json.dumps({"valid": True, **instance.state(), "users": instance.identities}))
            finally:
                instance.close()
            return
        inventory = ThreadingHTTPServer(("127.0.0.1", 0), Inventory)
        inventory.mode, inventory.requests, inventory.inference_requests = "ready", [], 0
        inventory_thread = threading.Thread(target=inventory.serve_forever, daemon=True)
        inventory_thread.start()
        # Fail closed on any outbound connection outside the test machine.
        original_connect = socket.socket.connect

        def local_connect(connection, address):
            if (
                connection.family in (socket.AF_INET, socket.AF_INET6)
                and not ipaddress.ip_address(address[0]).is_loopback
            ):
                raise AssertionError("Browser fixture attempted an external connection")
            return original_connect(connection, address)

        socket.socket.connect = local_connect
        original_resolve = socket.getaddrinfo

        def local_resolve(host, *values, **settings):
            name = host.decode() if isinstance(host, bytes) else host
            if name != "localhost" and not ipaddress.ip_address(name).is_loopback:
                raise AssertionError("Browser fixture attempted external DNS resolution")
            return original_resolve(host, *values, **settings)

        socket.getaddrinfo = local_resolve
        try:
            instance.start(initial=True)
            print(
                json.dumps(
                    {
                        "ready": True,
                        "origin": f"http://127.0.0.1:{instance.port}",
                        "inventoryOrigin": f"http://127.0.0.1:{inventory.server_port}",
                        "users": instance.identities,
                        "adminPassword": ADMIN,
                        "bootstrapPassword": BOOTSTRAP,
                        "userPassword": USER,
                    }
                ),
                flush=True,
            )
            for raw in sys.stdin:
                request = json.loads(raw)
                try:
                    command = request["command"]
                    if command == "expire_sessions":
                        with instance.server.application.session_lock:
                            for session in instance.server.application.sessions.values():
                                session["expires"] = 0
                        value = {"expired": True}
                    elif command == "inventory_mode":
                        inventory.mode = request["mode"]
                        value = {"mode": inventory.mode}
                    elif command == "restart":
                        instance.close()
                        instance.start()
                        value = {"restarted": True}
                    elif command == "correct_usage":
                        value = instance.correct_usage()
                    elif command == "state":
                        value = {
                            **instance.state(),
                            "metadata_requests": inventory.requests,
                            "inference_requests": inventory.inference_requests,
                        }
                    elif command == "stop":
                        value = {"stopped": True}
                    else:
                        raise ValueError("Unknown fixture command")
                    print(json.dumps({"id": request["id"], "value": value}), flush=True)
                    if command == "stop":
                        break
                except Exception as error:
                    print(
                        json.dumps(
                            {
                                "id": request.get("id"),
                                "error": type(error).__name__ + ": " + str(error),
                            }
                        ),
                        flush=True,
                    )
        finally:
            instance.close()
            inventory.shutdown()
            inventory_thread.join(timeout=5)
            inventory.server_close()


if __name__ == "__main__":
    main()
