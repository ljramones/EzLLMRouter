"""DEV-01 signed internal plan; never accepts caller-provided plans."""

from __future__ import annotations

from typing import TYPE_CHECKING
from .records import Record

if TYPE_CHECKING:
    from .registry import Registry

import base64
from copy import deepcopy
from datetime import datetime, timezone
import uuid

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.exceptions import InvalidSignature

from .canonical import ContractError, digest, jcs

PROVIDER_RECIPE_REF = "recipe.dev08.openai.responses.text.v1"
PROVIDER_ADAPTER_VERSION = "adapter.dev08.openai.responses.v1"


def signing_message(scheme: str, key_id: str, key_version: str, signed_plan_digest: str) -> bytes:
    """The adopted, domain-separated v0.2 plan signature frame."""
    return (
        "ezllmrouter-plan-v0.2\n"
        + scheme
        + "\n"
        + key_id
        + "\n"
        + key_version
        + "\n"
        + signed_plan_digest
    ).encode("utf-8")


class PlanAuthority:
    def __init__(
        self, private_key: Ed25519PrivateKey, policy: Record, registry: Registry | None = None
    ) -> None:
        self._private_key = private_key
        self.public_key = private_key.public_key()
        self.policy = policy
        self.registry = registry

    def issue(
        self,
        projection: Record,
        work_digest: str,
        work_key: Record,
        classification: Record,
        retention: Record,
        decision_record_ref: str | None = None,
    ) -> Record:
        work = projection["work"]
        trusted = projection["trusted"]
        tool_work = "tools" in work["requested_features"]
        provider_work = projection["destination"].get("service") == "openai.responses.v1"
        if provider_work and tool_work:
            raise ContractError("PLAN_INVALID_OR_STALE", 409)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        unsigned = {
            "plan_id": "plan." + uuid.uuid4().hex,
            "profile": "initial_1a@1",
            "expires_at": work["deadline"],
            "work_digest": work_digest,
            "work_key": work_key,
            "purpose": work["purpose"],
            "task_class": work["task_class"],
            "step_class": work["step_class"],
            "configuration_ref": projection["destination"]["configuration_ref"],
            "destination": projection["destination"],
            "quality_approval_ref": self.policy["quality_approval_ref"],
            "adapter_recipe_ref": PROVIDER_RECIPE_REF
            if provider_work
            else self.policy["tool_adapter_recipe_ref"]
            if tool_work
            else self.policy["adapter_recipe_ref"],
            "adapter_version": PROVIDER_ADAPTER_VERSION
            if provider_work
            else self.policy["tool_adapter_version"]
            if tool_work
            else self.policy["adapter_version"],
            "policy_version": self.policy["policy_version"],
            "recovery_policy_version": self.policy["recovery_policy_version"],
            "registry_version": (
                "registry.local." + str(self.registry.version())
                if self.registry
                else self.policy["registry_version"]
            ),
            "capability_profile_version": "initial_1a@1",
            "classification_snapshot": classification,
            "effective_retention": retention,
            "financial_scope": {
                "profile": "spend_limit_1a",
                "principal_id": trusted["principal_id"],
                "charging_owner_id": trusted["charging_owner_id"],
                "limit_ref": self.policy["limit_ref"],
                "limit_version": self.policy["limit_version"],
                "max_attempt_charge_decimal": self.policy["max_attempt_charge_decimal"],
                "currency": self.policy["currency"],
                "checked_at": now,
                "alert_policy_ref": self.policy["alert_policy_ref"],
            },
            "decision_record_ref": decision_record_ref or self.policy["decision_record_ref"],
            "propensity_decimal": "1",
            "failure_action_map": {
                "transport_failure": "return_to_orchestrator",
                "semantic_rejection": "return_to_orchestrator",
            },
            "retry_allowance": 0,
            "escalation_allowance": 0,
            "per_attempt_total_timeout_ms": work["generation_settings"]["total_timeout_ms"],
            "deadline": work["deadline"],
            "permitted_fallbacks": [],
            "pinned_model": True,
            "streaming": False,
            "cancellation_token": "cancel." + uuid.uuid4().hex,
            "capacity_lease_state": "not_applicable",
        }
        unsigned = deepcopy(unsigned)
        body = jcs(unsigned)
        body_digest = digest(body)
        signature = self._private_key.sign(
            signing_message(
                "Ed25519", self.policy["key_id"], self.policy["key_version"], body_digest
            )
        )
        return {
            **unsigned,
            "signature_envelope": {
                "scheme": "Ed25519",
                "key_id": self.policy["key_id"],
                "key_version": self.policy["key_version"],
                "signed_plan_digest": body_digest,
                "signature": base64.urlsafe_b64encode(signature).decode().rstrip("="),
            },
        }

    def verify(self, plan: Record, expected_digest: str, current_policy_version: str) -> None:
        try:
            envelope = plan["signature_envelope"]
            unsigned = {k: v for k, v in plan.items() if k != "signature_envelope"}
            body = jcs(unsigned)
            raw = base64.urlsafe_b64decode(
                envelope["signature"] + "=" * (-len(envelope["signature"]) % 4)
            )
            current = {
                "quality_approval_ref": self.policy["quality_approval_ref"],
                "policy_version": self.policy["policy_version"],
                "recovery_policy_version": self.policy["recovery_policy_version"],
                "registry_version": (
                    "registry.local." + str(self.registry.version())
                    if self.registry
                    else self.policy["registry_version"]
                ),
                "decision_record_ref": (
                    plan["decision_record_ref"]
                    if self.registry
                    else self.policy["decision_record_ref"]
                ),
            }
            financial = {
                "limit_ref": self.policy["limit_ref"],
                "limit_version": self.policy["limit_version"],
                "max_attempt_charge_decimal": self.policy["max_attempt_charge_decimal"],
                "currency": self.policy["currency"],
                "alert_policy_ref": self.policy["alert_policy_ref"],
            }
            if (
                envelope["scheme"] != "Ed25519"
                or envelope["key_id"] != self.policy["key_id"]
                or envelope["key_version"] != self.policy["key_version"]
                or envelope["signed_plan_digest"] != digest(body)
                or plan["work_digest"] != expected_digest
                or plan["policy_version"] != current_policy_version
                or any(plan[k] != v for k, v in current.items())
                or (
                    self.registry is not None
                    and not plan["decision_record_ref"].startswith("decision.submission.")
                )
                or (plan["adapter_recipe_ref"], plan["adapter_version"])
                not in {
                    (self.policy["adapter_recipe_ref"], self.policy["adapter_version"]),
                    (self.policy["tool_adapter_recipe_ref"], self.policy["tool_adapter_version"]),
                    (PROVIDER_RECIPE_REF, PROVIDER_ADAPTER_VERSION),
                }
                or (plan["destination"].get("service") == "openai.responses.v1")
                != (plan["adapter_recipe_ref"] == PROVIDER_RECIPE_REF)
                or any(plan["financial_scope"][k] != v for k, v in financial.items())
                or plan["permitted_fallbacks"] != []
                or plan["retry_allowance"] != 0
                or plan["streaming"] is not False
                or datetime.fromisoformat(plan["expires_at"].replace("Z", "+00:00"))
                <= datetime.now(timezone.utc)
            ):
                raise ValueError("stale or incompatible plan")
            self.public_key.verify(
                raw,
                signing_message(
                    envelope["scheme"],
                    envelope["key_id"],
                    envelope["key_version"],
                    envelope["signed_plan_digest"],
                ),
            )
        except (KeyError, TypeError, ValueError, InvalidSignature) as exc:
            raise ContractError("PLAN_INVALID_OR_STALE", 409) from exc
