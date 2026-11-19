"""Offline v3 shape/semantic cases; no HTTP, credentials or provider call."""
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(root / "server/src"))
from duranki_server.integration_accounting import _checked, IntegrationError

here = Path(__file__).parent
schema = (here / "schema.json").read_bytes()
for path in (root / "server/src/duranki_server/integration_schema_v3.json",
             root / "clients/python/src/duranki_client/integration_schema_v3.json",
             root / "clients/js/integration_schema_v3.json"):
    assert path.read_bytes() == schema, path
example = json.loads((here / "examples.json").read_text())
for name, definition in (("account", "account"), ("start", "event"), ("decision", "event")):
    assert _checked(example[name], definition, "3") == example[name]


def rejects(body, definition):
    try:
        _checked(body, definition, "3")
    except IntegrationError:
        return
    raise AssertionError("v3 rejected-case accepted")


account = example["account"]
assert _checked({**account, "allowed_models": [], "allowed_operations": []}, "account", "3")
rejects({**account, "allowed_operations": ["generation"]}, "account")
rejects({**account, "allowed_operations": ["speech_input", "speech_input"]}, "account")
rejects({**example["decision"], "capability": "synthesis"}, "event")
rejects({**example["decision"], "selection_kind": "known_model"}, "event")
rejects({**example["start"], "model_identity_state": "known"}, "event")
assert _checked({**example["start"], "model_identity_state": "known",
                 "model_id": "model.synthetic"}, "event", "3")
assert _checked({"dataset_id": account["dataset_id"], "expected_revision": 1,
                 "allowed_models": [], "allowed_operations": []}, "account_permissions", "3")
print("v3 offline schema parity and focused shape/semantic cases PASS")
