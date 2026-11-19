"""DEV-01 fixture injection only. This is not a production entrypoint."""
from pathlib import Path
import json
import os

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ezllmrouter_server.core import Coordinator
from ezllmrouter_server.plans import PlanAuthority
from ezllmrouter_server.store import SQLiteStore
from ezllmrouter_server.web import serve
from native_adapter import NativeSyntheticAdapter
from recipe import SyntheticDevelopmentRecipe
from synthetic_routes import fixture_destination

fixture = json.loads(Path(__file__).with_name("fixture.json").read_text())
token = os.environ["EZLLMROUTER_DEV_TOKEN"].strip()
if not token or len(token) < 32:
    raise ValueError("missing per-run development token")
url = os.environ["EZLLMROUTER_SYNTHETIC_URL"]
config = fixture_destination(fixture["destination"], url)
adapter = NativeSyntheticAdapter(url, config["endpoint"], os.environ.get("EZLLMROUTER_TRANSPORT_FAULT"))
trusted = dict(fixture["trusted_context"])
trusted["expires_at"] = fixture["trusted_context"]["expires_at"]
identities = {token: trusted}
secondary_token = os.environ.get("EZLLMROUTER_DEV_TOKEN_SECONDARY")
if secondary_token:
    if len(secondary_token) < 32 or secondary_token == token:
        raise ValueError("invalid secondary development token")
    secondary = dict(trusted)
    secondary["principal_id"] = "svc.dev02.secondary"
    secondary["context_id"] = "ctx.dev02.secondary"
    identities[secondary_token] = secondary
retention = dict(fixture["retention"])
if os.environ.get("EZLLMROUTER_DEV_NO_STORE") == "1":
    retention = {"retention_class": "no_store", "policy_version": retention["policy_version"],
                 "content_store_allowed": False}
store = SQLiteStore(os.environ["EZLLMROUTER_DB_PATH"])
if os.environ.get("EZLLMROUTER_FAIL_INTENT") == "1":
    class FailIntentStore:
        def __init__(self, inner):
            self.inner = inner
        def __getattr__(self, name):
            return getattr(self.inner, name)
        def intent(self, *_args):
            raise OSError("injected intent commit failure")
    store = FailIntentStore(store)
authority = PlanAuthority(Ed25519PrivateKey.generate(), fixture["policy"])
mutator = (lambda b: b.replace(b'"model":"model.demo"', b'"model":"model.other"')) if os.environ.get("EZLLMROUTER_MUTATE_AFTER_BINDING") == "1" else None
no_store_user_label = {"lineage_ids": ["src.user.no_store"], "sensitivity": "confidential",
                       "restrictions": ["no.content.store"]}
trusted_source_labels = dict(fixture["trusted_source_labels"])
trusted_source_labels["src.user.no_store"] = no_store_user_label
coordinator = Coordinator(store, identities, config, fixture["prompt_blocks"],
                          [*fixture["allowed_lineages"], "src.user.no_store"], authority, adapter,
                          retention, fixture["classification"], SyntheticDevelopmentRecipe(config["endpoint"]),
                          {"mutate_after_binding": mutator} if mutator else {},
                          trusted_source_labels)
server = serve("0.0.0.0", int(os.environ.get("PORT", "8765")), coordinator)
server.serve_forever()
