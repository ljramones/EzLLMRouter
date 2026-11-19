"""DEV-04-only Duranki service with a private LiteLLM ASGI proxy bridge."""
from pathlib import Path
import json
import os

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from duranki_server.core import Coordinator
from duranki_server.plans import PlanAuthority
from duranki_server.store import SQLiteStore
from duranki_server.web import serve
from duranki_server.gateway.adapter import LiteLLMAsgiAdapter
from duranki_server.gateway.proxy_recipe import GatewayProxyRecipe, public_destination, proxy_policy


def main():
    token = os.environ["DURANKI_DEV_TOKEN"]
    provider_key = os.environ["DURANKI_DEV04_PROVIDER_KEY"]
    if len(token) < 32 or not provider_key.startswith("sk-") or len(provider_key) < 36:
        raise ValueError("fresh synthetic credentials required")
    if os.environ.get("OPENAI_API_KEY") not in (None, provider_key):
        raise ValueError("unexpected provider credential")
    os.environ["OPENAI_API_KEY"] = provider_key
    os.environ["LITELLM_DONT_SHOW_FEEDBACK_BOX"] = "true"
    os.environ["LITELLM_LOG"] = "ERROR"
    os.environ["DURANKI_DEV04_GUARD_EVENTS"] = "/data/guard-events.jsonl"

    fixture = json.loads(Path("/app/dev_slice/fixture.json").read_text())
    config = public_destination(fixture)
    policy = proxy_policy(fixture)
    trusted = dict(fixture["trusted_context"])
    second_context = dict(trusted)
    second_context["context_id"] = trusted["context_id"] + ".alternate"


    class LiveIdentity(dict):
        """DEV-04 wait probe reads a local authority toggle at each real check."""

        def get(self, key, default=None):
            value = super().get(key, default)
            toggle = os.environ.get("DURANKI_DEV04_AUTHORITY_TOGGLE")
            if value and key == token and toggle and Path(toggle).is_file() and Path(toggle).read_text() == "revoked":
                return {**value, "context_id": value["context_id"] + ".revoked"}
            return value


    identity = LiveIdentity({token: trusted})
    if os.environ.get("DURANKI_DEV04_SECOND_CONTEXT") == "1":
        identity[token + ".alternate"] = second_context
    store = SQLiteStore(os.environ["DURANKI_DB_PATH"])
    if os.environ.get("DURANKI_DEV04_FAIL_GUARD_COMMIT") == "1":
        class FailGuardCommit:
            def __init__(self, inner):
                self.inner = inner

            def __getattr__(self, name):
                return getattr(self.inner, name)

            def guard_commit(self, *_args):
                raise OSError("injected final guard commit failure")

        store = FailGuardCommit(store)

    adapter = LiteLLMAsgiAdapter()
    Path("/data/module-identities.json").write_text(json.dumps(adapter.module_identities, indent=2) + "\n")
    coordinator = Coordinator(
        store, identity, config, fixture["prompt_blocks"], fixture["allowed_lineages"],
        PlanAuthority(Ed25519PrivateKey.generate(), policy), adapter, fixture["retention"],
        fixture["classification"], GatewayProxyRecipe(),
        trusted_source_labels=fixture["trusted_source_labels"],
    )
    server = serve("127.0.0.1", int(os.environ.get("PORT", "8765")), coordinator)
    try:
        server.serve_forever()
    finally:
        adapter.close()


if __name__ == "__main__":
    main()
