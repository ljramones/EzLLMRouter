"""Persistent synthetic profile: trusted API, sender and operator surface."""
from __future__ import annotations

from pathlib import Path
import json
import os
import signal
import sys
import threading

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from duranki_server.observability import configure_logging
from duranki_server.core import Coordinator
from duranki_server.operator_demo import DemoRunner, ProviderValidationRunner
from duranki_server.operator_projection import OperatorProjection
from duranki_server.operator_web import serve as serve_operator
from duranki_server.plans import PlanAuthority
from duranki_server.registry import Registry
from duranki_server.provider_vault import ProviderVault
from duranki_server.personal_campaign import PersonalCampaign
from duranki_server.store import SQLiteStore
from duranki_server.web import serve as serve_wire
from duranki_server.gateway.choice_b_sender import ChoiceBSenderAdapter
from duranki_server.gateway.owned_sender_transport import LocalSendAuthority
from duranki_server.gateway.proxy_recipe import GatewayProxyRecipe, public_destination, proxy_policy
from duranki_server.gateway.worker_ready import probe
from socket_lease import remove_stale_socket


def main():
    configure_logging()
    if "litellm" in sys.modules:
        raise RuntimeError("LiteLLM imported into trusted sender")
    credentials = json.loads(Path("/run/duranki/credentials.json").read_text())
    token, provider_key = credentials["service_token"], credentials["synthetic_provider_key"]
    password = Path("/run/duranki/operator-password").read_text().strip()
    if (type(token) is not str or len(token) < 32 or type(provider_key) is not str or
            not provider_key.startswith("sk-") or len(provider_key) < 36 or len(password) < 32):
        raise RuntimeError("invalid local synthetic credential files")
    os.environ["DURANKI_DEV_TOKEN"] = token
    os.environ["DURANKI_DEV04_PROVIDER_KEY"] = provider_key
    os.environ["DURANKI_DEV04_GUARD_EVENTS"] = "/data/guard-events.jsonl"
    os.environ["DURANKI_DEV04_SEND_EVENTS"] = "/data/send-events.jsonl"
    fixture = json.loads(Path("/app/dev_slice/fixture.json").read_text())
    request = json.loads(Path("/app/local/request.json").read_text())
    scenarios = json.loads(Path("/app/local/scenarios.json").read_text())
    build = json.loads(Path("/app/local/build-identity.json").read_text())
    trusted = dict(fixture["trusted_context"])
    identity = {token: trusted}
    store = SQLiteStore(os.environ["DURANKI_DB_PATH"])
    has_connections = store.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='registry_connections'").fetchone()
    protected = (store.db.execute("SELECT json_extract(record,'$.connection_id'),"
        "json_extract(record,'$.credential_version') FROM registry_connections "
        "WHERE json_extract(record,'$.credential_state')='present'").fetchall()
        if has_connections else [])
    used_vault = (store.db.execute("SELECT 1 FROM registry_connections "
        "WHERE json_extract(record,'$.credential_version')>0 LIMIT 1").fetchone()
        if has_connections else None)
    vault = ProviderVault("/data/provider-vault", require_existing=bool(used_vault))
    for connection_id, version in protected:
        vault.resolve(connection_id, version)  # Fail startup if recovery material is missing or corrupt.
    remove_stale_socket(Path("/link/sender.sock"))
    remove_stale_socket(Path("/console/operator.sock"))
    authority = LocalSendAuthority()
    registry = Registry(store, authority, legacy_destination=public_destination(fixture),
                        legacy_token=token, legacy_trusted=trusted,
                        provider_vault=vault,
                        provider_execution_ready=True)
    registry.personal_campaign = PersonalCampaign(store, registry)
    adapter = ChoiceBSenderAdapter(authority, registry=registry)
    registry.runtime_ready = lambda: adapter.server_thread.is_alive() and not authority.is_revoked()
    coordinator = Coordinator(store, identity, public_destination(fixture),
        fixture["prompt_blocks"], fixture["allowed_lineages"],
        PlanAuthority(Ed25519PrivateKey.generate(), proxy_policy(fixture), registry=registry), adapter,
        fixture["retention"], fixture["classification"], GatewayProxyRecipe(),
        trusted_source_labels=fixture["trusted_source_labels"], registry=registry)
    projection = OperatorProjection(store, trusted["principal_id"], "/data/send-events.jsonl")
    runner = DemoRunner(request, scenarios, "http://127.0.0.1:8773", token)
    provider_validation = ProviderValidationRunner(request, "http://127.0.0.1:8773", token,
                                                   trusted["principal_id"])
    wire = serve_wire("127.0.0.1", 8773, coordinator)

    def worker_status():
        value = probe(Path("/link/worker.sock"), deadline_seconds=1,
                      require_empty=False)
        return {"state": "live", "transport": value["selected_transport"],
                "observed_attempts": len(value["relay_attempt_counts"])}

    def sender_status():
        return {"state": "live" if adapter.server_thread.is_alive() and not authority.is_revoked()
                else "unavailable", "exclusive_synthetic_provider": False,
                "selected_provider_ready": registry.personal_campaign.summary()["effective_state"] == "active"}

    operator = serve_operator("127.0.0.1", 8780, socket_path="/console/operator.sock",
        projection=projection, runner=runner,
        password=password, fixture=fixture, build=build, web_root="/app/web",
        worker_probe=worker_status, sender_status=sender_status, registry=registry,
        provider_validation=provider_validation)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    threads = [threading.Thread(target=server.serve_forever, daemon=True)
               for server in (wire, operator)]
    for thread in threads:
        thread.start()
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


if __name__ == "__main__":
    main()
