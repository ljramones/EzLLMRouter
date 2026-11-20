"""Persistent synthetic profile: trusted API, sender and operator surface."""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
from contextlib import ExitStack
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ezllmrouter_server.core import Coordinator
from ezllmrouter_server.gateway.choice_b_sender import ChoiceBSenderAdapter
from ezllmrouter_server.gateway.owned_sender_transport import LocalSendAuthority
from ezllmrouter_server.gateway.proxy_recipe import (
    GatewayProxyRecipe,
    proxy_policy,
    public_destination,
)
from ezllmrouter_server.gateway.worker_ready import probe
from ezllmrouter_server.observability import configure_logging
from ezllmrouter_server.operator_demo import DemoRunner, ProviderValidationRunner
from ezllmrouter_server.operator_projection import OperatorProjection
from ezllmrouter_server.operator_web import serve as serve_operator
from ezllmrouter_server.personal_campaign import PersonalCampaign
from ezllmrouter_server.plans import PlanAuthority
from ezllmrouter_server.provider_vault import ProviderVault
from ezllmrouter_server.registry import Registry
from ezllmrouter_server.repositories import startup as startup_queries
from ezllmrouter_server.store import SQLiteStore
from ezllmrouter_server.web import serve as serve_wire
from socket_lease import remove_stale_socket


def main():
    configure_logging()
    if "litellm" in sys.modules:
        raise RuntimeError("LiteLLM imported into trusted sender")
    credentials = json.loads(Path("/run/ezllmrouter/credentials.json").read_text())
    token, provider_key = credentials["service_token"], credentials["synthetic_provider_key"]
    password = Path("/run/ezllmrouter/operator-password").read_text().strip()
    if (
        type(token) is not str
        or len(token) < 32
        or type(provider_key) is not str
        or not provider_key.startswith("sk-")
        or len(provider_key) < 36
        or len(password) < 32
    ):
        raise RuntimeError("invalid local synthetic credential files")
    os.environ["EZLLMROUTER_DEV_TOKEN"] = token
    os.environ["EZLLMROUTER_DEV04_PROVIDER_KEY"] = provider_key
    os.environ["EZLLMROUTER_DEV04_GUARD_EVENTS"] = "/data/guard-events.jsonl"
    os.environ["EZLLMROUTER_DEV04_SEND_EVENTS"] = "/data/send-events.jsonl"
    fixture = json.loads(Path("/app/dev_slice/fixture.json").read_text())
    request = json.loads(Path("/app/local/request.json").read_text())
    scenarios = json.loads(Path("/app/local/scenarios.json").read_text())
    build = json.loads(Path("/app/local/build-identity.json").read_text())
    trusted = dict(fixture["trusted_context"])
    identity = {token: trusted}
    with ExitStack() as cleanup:
        store = SQLiteStore(os.environ["EZLLMROUTER_DB_PATH"])
        cleanup.callback(store.close)
        protected = store.database.execute(
            startup_queries.PROTECTED_PROVIDER_CREDENTIALS
        ).fetchall()
        used_vault = store.database.execute(startup_queries.USED_PROVIDER_VAULT).fetchone()
        vault = ProviderVault("/data/provider-vault", require_existing=bool(used_vault))
        for connection_id, version in protected:
            vault.resolve(
                connection_id, version
            )  # Fail startup if recovery material is missing or corrupt.
        remove_stale_socket(Path("/link/sender.sock"))
        remove_stale_socket(Path("/console/operator.sock"))
        authority = LocalSendAuthority()
        registry = Registry(
            store,
            authority,
            legacy_destination=public_destination(fixture),
            legacy_token=token,
            legacy_trusted=trusted,
            provider_vault=vault,
            provider_execution_ready=True,
        )
        registry.personal_campaign = PersonalCampaign(store, registry)
        adapter = ChoiceBSenderAdapter(authority, registry=registry)
        cleanup.callback(adapter.close)
        registry.runtime_ready = (
            lambda: adapter.server_thread.is_alive() and not authority.is_revoked()
        )
        coordinator = Coordinator(
            store,
            identity,
            public_destination(fixture),
            fixture["prompt_blocks"],
            fixture["allowed_lineages"],
            PlanAuthority(Ed25519PrivateKey.generate(), proxy_policy(fixture), registry=registry),
            adapter,
            fixture["retention"],
            fixture["classification"],
            GatewayProxyRecipe(),
            trusted_source_labels=fixture["trusted_source_labels"],
            registry=registry,
            authentication_context=trusted,
            context_sender=lambda *args: adapter.send_with_context(*args),
        )
        cleanup.callback(coordinator.close)
        projection = OperatorProjection(store, trusted["principal_id"], "/data/send-events.jsonl")
        runner = DemoRunner(request, scenarios, "http://127.0.0.1:8773", token)
        provider_validation = ProviderValidationRunner(
            request, "http://127.0.0.1:8773", token, trusted["principal_id"]
        )
        server_threads = {}

        def close_server(server):
            try:
                thread = server_threads.get(server)
                if thread is not None and thread.is_alive():
                    server.shutdown()
                    thread.join()
            finally:
                server.server_close()

        wire = serve_wire("127.0.0.1", 8773, coordinator)
        cleanup.callback(close_server, wire)

        def worker_status():
            value = probe(Path("/link/worker.sock"), deadline_seconds=1, require_empty=False)
            return {
                "state": "live",
                "transport": value["selected_transport"],
                "observed_attempts": len(value["relay_attempt_counts"]),
            }

        def sender_status():
            return {
                "state": "live"
                if adapter.server_thread.is_alive() and not authority.is_revoked()
                else "unavailable",
                "exclusive_synthetic_provider": False,
                "selected_provider_ready": registry.personal_campaign.summary()["effective_state"]
                == "active",
            }

        operator = serve_operator(
            "127.0.0.1",
            8780,
            socket_path="/console/operator.sock",
            projection=projection,
            runner=runner,
            password=password,
            fixture=fixture,
            build=build,
            web_root="/app/web",
            worker_probe=worker_status,
            sender_status=sender_status,
            registry=registry,
            provider_validation=provider_validation,
        )
        cleanup.callback(close_server, operator)
        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        threads = [
            threading.Thread(target=server.serve_forever, daemon=True)
            for server in (wire, operator)
        ]

        for server, thread in zip((wire, operator), threads, strict=True):
            server_threads[server] = thread
            thread.start()
        stop.wait()


if __name__ == "__main__":
    main()
