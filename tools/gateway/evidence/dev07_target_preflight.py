"""Frozen service-image Coordinator → real signed plan component discriminator.

Runs in the offline service image before touching a live profile. The lower
adapter is controlled; the installed-client/owned-sender path is a later target
step and is never inferred from this component pass.
"""

from __future__ import annotations

if not __package__:
    import sys
    from pathlib import Path

    for _parent in Path(__file__).resolve().parents:
        if (_parent / "tools/gateway/__init__.py").is_file():
            sys.path.insert(0, str(_parent))
            break
        if (_parent / "server/tools/gateway/__init__.py").is_file():
            sys.path.insert(0, str(_parent / "server"))
            break


from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import threading

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ezllmrouter_server.canonical import ContractError
from ezllmrouter_server.core import Coordinator
from ezllmrouter_server.plans import PlanAuthority
from ezllmrouter_server.registry import Registry
from ezllmrouter_server.store import SQLiteStore
from ezllmrouter_server.gateway.proxy_recipe import (
    GatewayProxyRecipe,
    proxy_policy,
    public_destination,
)


class Authority:
    def __init__(self):
        self.gate = threading.RLock()
        self.epoch = 0


class Adapter:
    def __init__(self, recipe):
        self.recipe = recipe
        self.sent = []

    def prepare(self, body):
        return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()

    def describe(self, prepared, timeout_ms, destination):
        return {
            "method": "POST",
            "url": "http://127.0.0.1:8767/v1/chat/completions",
            "content_type": "application/json",
            "content_length": len(prepared),
            "body_sha256": hashlib.sha256(prepared).hexdigest(),
            "timeout_ms": timeout_ms,
            "processing_region": destination["processing_region"],
        }

    def send(self, prepared, _timeout_ms, _expected):
        self.sent.append(json.loads(prepared))
        return {
            "status": 200,
            "body": {"text": "Hello.", "usage": {"input_tokens": 5, "output_tokens": 2}},
        }


def change(registry, index, action, subject, revision, data):
    return registry.mutate(
        "owner.local",
        {
            "operation_id": "op.preflight." + str(index),
            "action": action,
            "subject": subject,
            "expected_revision": revision,
            "data": data,
        },
    )["record"]


def main():
    fixture = json.loads(Path("/app/dev_slice/fixture.json").read_text())
    request = json.loads(Path("/app/local/request.json").read_text())
    token = "synthetic-dev07-preflight-credential-0000000000000"
    with tempfile.TemporaryDirectory() as scratch:
        store = SQLiteStore(Path(scratch) / "store.sqlite")
        try:
            trusted = fixture["trusted_context"]
            registry = Registry(
                store,
                Authority(),
                legacy_destination=public_destination(fixture),
                legacy_token=token,
                legacy_trusted=trusted,
            )
            model = change(
                registry,
                1,
                "create_model",
                "cfg.preflight.alt",
                0,
                {
                    "display_name": "Preflight alternate",
                    "model": "model.demo.alt",
                    "model_version": "v1",
                    "owner": "owner.local",
                    "capabilities": ["text"],
                    "purposes": ["execution"],
                    "task_classes": ["class.demo"],
                },
            )
            model = change(
                registry,
                2,
                "publish_price",
                "cfg.preflight.alt",
                model["revision"],
                {
                    "price_version": "preflight.alt.v1",
                    "currency": "USD",
                    "rates": {"input_uncached": "2", "output_text": "8"},
                    "source": "synthetic fixture",
                    "usage_semantics_version": "synthetic.text.v1",
                },
            )
            change(
                registry,
                3,
                "model_state",
                "cfg.preflight.alt",
                model["revision"],
                {"status": "enabled", "reason": "Offline signed-plan preflight"},
            )
            principal = change(
                registry,
                4,
                "create_principal",
                "svc.preflight",
                0,
                {"display_name": "Preflight caller", "kind": "service", "owner": "owner.preflight"},
            )
            principal, secret = registry.provision_credential(
                "owner.local", "svc.preflight", principal["revision"], "op.preflight.provision"
            )
            change(
                registry,
                5,
                "principal_state",
                "svc.preflight",
                principal["revision"],
                {"status": "active", "reason": "Offline signed-plan preflight"},
            )
            recipe = GatewayProxyRecipe()
            adapter = Adapter(recipe)
            plan = PlanAuthority(Ed25519PrivateKey.generate(), proxy_policy(fixture), registry)
            coordinator = Coordinator(
                store,
                {token: trusted},
                public_destination(fixture),
                fixture["prompt_blocks"],
                fixture["allowed_lineages"],
                plan,
                adapter,
                fixture["retention"],
                fixture["classification"],
                recipe,
                trusted_source_labels=fixture["trusted_source_labels"],
                registry=registry,
            )
            try:
                work = deepcopy(request)
                work["requested_configuration_ref"] = "cfg.preflight.alt"
                work["step_id"] = "step.preflight.alt"
                caller = coordinator.authenticate(secret)
                try:
                    coordinator.submit(work, caller, credential=secret, wait_ms=3000)
                except ContractError as exc:
                    assert exc.code == "POLICY_DENIED"
                else:
                    raise AssertionError("ungranted work accepted")
                assert adapter.sent == []
                change(
                    registry,
                    6,
                    "set_grant",
                    "svc.preflight",
                    0,
                    {
                        "configuration_ref": "cfg.preflight.alt",
                        "status": "active",
                        "purposes": ["execution"],
                        "task_classes": ["class.demo"],
                    },
                )
                status, reply = coordinator.submit(work, caller, credential=secret, wait_ms=3000)
                assert status == 200 and reply["state"] == "delivered"
                assert (
                    len(adapter.sent) == 1 and adapter.sent[0]["model"] == "openai/model.demo.alt"
                )
                assert (
                    reply["candidate"]["usage"]["revision"]["cost"]["amount_decimal"] == "0.000026"
                )
                sid = reply["handle"]["submission_id"]
                assert store.get(sid)["registry_decision"]["price_version"] == "preflight.alt.v1"
                print(
                    json.dumps(
                        {
                            "kind": "DEV-07 frozen signed-plan component",
                            "status": "PASS",
                            "unsigned_request_fields_added": False,
                            "accepted": 1,
                            "denied": 1,
                            "private_proxy_model": adapter.sent[0]["model"],
                            "price_version": "preflight.alt.v1",
                        }
                    )
                )
            finally:
                coordinator.pool.shutdown(wait=True)
        finally:
            store.close()


if __name__ == "__main__":
    main()
