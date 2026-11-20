"""DEV-04 Choice B trusted service: public contract, authority and sender only."""

from pathlib import Path
import json
import os
from contextlib import ExitStack
import socketserver
import sys
import threading
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ezllmrouter_server.core import Coordinator
from ezllmrouter_server.plans import PlanAuthority
from ezllmrouter_server.store import SQLiteStore
from ezllmrouter_server.web import serve
from ezllmrouter_server.gateway.choice_b_sender import ChoiceBSenderAdapter
from ezllmrouter_server.gateway.owned_sender_transport import LocalSendAuthority
from ezllmrouter_server.gateway.proxy_recipe import (
    GatewayProxyRecipe,
    public_destination,
    proxy_policy,
)


def main(*, adapter_factory=ChoiceBSenderAdapter):
    token = os.environ["EZLLMROUTER_DEV_TOKEN"]
    provider_key = os.environ["EZLLMROUTER_DEV04_PROVIDER_KEY"]
    if len(token) < 32 or not provider_key.startswith("sk-") or len(provider_key) < 36:
        raise ValueError("fresh synthetic credentials required")
    if "litellm" in sys.modules:
        raise RuntimeError("LiteLLM imported into trusted sender")
    os.environ["EZLLMROUTER_DEV04_GUARD_EVENTS"] = "/data/guard-events.jsonl"
    fixture = json.loads(Path("/app/dev_slice/fixture.json").read_text())
    trusted = dict(fixture["trusted_context"])

    authority = LocalSendAuthority()

    class LiveIdentity(dict):
        def get(self, key, default=None):
            value = super().get(key, default)
            if value and key == token and authority.is_revoked():
                return {**value, "context_id": value["context_id"] + ".revoked"}
            return value

    identity = LiveIdentity({token: trusted})
    adapter = adapter_factory(authority)

    class AuthorityControl(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        daemon_threads = True

    control_path = Path("/data/authority.sock")
    if control_path.exists() or control_path.is_symlink():
        raise RuntimeError("Choice B authority control socket collision")

    class AuthorityHandler(socketserver.BaseRequestHandler):
        def handle(self):
            command = self.request.makefile("rb").readline(64)
            if command not in (b"revoke\n", b"restore\n"):
                self.request.sendall(b'{"error":"unknown control"}\n')
                return
            if command == b"revoke\n":
                epoch, state = authority.revoke(), "revoked"
            else:
                epoch, state = authority.restore(), "active"
            self.request.sendall(
                json.dumps(
                    {"authority_state": state, "epoch": epoch, "monotonic_ns": time.monotonic_ns()}
                ).encode()
                + b"\n"
            )

    control = AuthorityControl(str(control_path), AuthorityHandler)
    os.chmod(control_path, 0o600)
    control_thread = threading.Thread(
        target=control.serve_forever, daemon=True, name="dev04-choice-b-authority"
    )
    control_thread.start()
    Path("/data/module-identities.json").write_text(
        json.dumps(
            {
                "boundary": "separate trusted Choice B sender",
                "litellm_imported": "litellm" in sys.modules,
                "provider_key_in_trusted_process": True,
                "worker_socket": "/link/worker.sock",
                "sender_socket": "/link/sender.sock",
            },
            indent=2,
        )
        + "\n"
    )
    coordinator = Coordinator(
        SQLiteStore(os.environ["EZLLMROUTER_DB_PATH"]),
        identity,
        public_destination(fixture),
        fixture["prompt_blocks"],
        fixture["allowed_lineages"],
        PlanAuthority(Ed25519PrivateKey.generate(), proxy_policy(fixture)),
        adapter,
        fixture["retention"],
        fixture["classification"],
        GatewayProxyRecipe(),
        trusted_source_labels=fixture["trusted_source_labels"],
    )
    server = serve("127.0.0.1", int(os.environ.get("PORT", "8773")), coordinator)
    try:
        server.serve_forever()
    finally:
        control.shutdown()
        control.server_close()
        control_path.unlink()
        with ExitStack() as cleanup:
            cleanup.callback(coordinator.store.close)
            cleanup.callback(adapter.close)
            cleanup.callback(coordinator.close)
            cleanup.callback(server.server_close)


if __name__ == "__main__":
    main()
