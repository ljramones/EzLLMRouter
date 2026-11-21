"""Coordinator policy steps under the existing instance context."""

from __future__ import annotations

import hashlib
import hmac
from copy import deepcopy
from datetime import datetime, timezone
from .canonical import (
    ContractError,
    digest,
    jcs,
)
from .plans import PROVIDER_ADAPTER_VERSION, PROVIDER_RECIPE_REF


def _live_source_tag(self, block):
    return hmac.new(self._live_source_key, jcs(block), hashlib.sha256).hexdigest()


def authenticate(self, token):
    if type(token) is not str:
        raise ContractError("AUTHENTICATION_FAILED", 401)
    trusted = self.identity.get(token)
    if self.registry:
        template = trusted if trusted is not None else self.authentication_context
        if template is None:
            # Inherit a context only when every configured identity has the
            # same non-identity scope. Conflicting scopes need an explicit one.
            scopes = [
                {
                    key: value
                    for key, value in context.items()
                    if key not in {"principal_id", "charging_owner_id"}
                }
                for context in self.identity.values()
            ]
            if scopes and all(scope == scopes[0] for scope in scopes):
                template = scopes[0]
        if not isinstance(template, dict):
            raise ContractError("AUTHENTICATION_FAILED", 401)
        trusted = self.registry.authenticate(token, template)
    try:
        expiry = (
            datetime.fromisoformat(trusted["expires_at"].replace("Z", "+00:00"))
            if trusted
            else None
        )
        if expiry is None or expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
            raise ValueError("expired authentication context")
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ContractError("AUTHENTICATION_FAILED", 401) from exc
    return trusted


def capabilities(self, trusted):
    return {
        "contract_version": "0.2",
        "profile": "initial_1a@1",
        "supported_features": ["text", "tools"],
        "disabled_features": [
            "document_text",
            "background",
            "nested",
            "streaming",
            "realtime_voice",
            "binary_multimodal",
            "responses_web_search",
            "provider_managed_state",
        ],
    }


def _prepared(self, projected):
    return self.recipe.expected(
        projected, projected["work"]["generation_settings"]["total_timeout_ms"]
    )[0]


def _recipe_matches(self, plan, projected):
    policy = self.authority.policy
    if "tool_adapter_recipe_ref" not in policy:
        return True  # Older isolated test authorities do not model recipe selection.
    if projected["destination"].get("service") == "openai.responses.v1":
        return "tools" not in projected["work"]["requested_features"] and (
            plan["adapter_recipe_ref"],
            plan["adapter_version"],
        ) == (PROVIDER_RECIPE_REF, PROVIDER_ADAPTER_VERSION)
    tool = "tools" in projected["work"]["requested_features"]
    ref = policy["tool_adapter_recipe_ref"] if tool else policy["adapter_recipe_ref"]
    version = policy["tool_adapter_version"] if tool else policy["adapter_version"]
    return (plan["adapter_recipe_ref"], plan["adapter_version"]) == (ref, version)


def _classification_for(self, messages):
    labels = [b["source_labels"] for m in messages for b in m["blocks"]]
    rank = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
    return {
        "sensitivity": max(
            [self.classification["sensitivity"]] + [x["sensitivity"] for x in labels],
            key=rank.get,
        ),
        "combined_restrictions": sorted(
            set(self.classification["combined_restrictions"])
            | {r for x in labels for r in x["restrictions"]}
        ),
        "content_digest": digest(jcs(messages)),
        "rules_engine_version": self.classification["rules_engine_version"],
    }


def _current_classification(self, snapshot):
    """Apply a stricter current classifier to admitted source handling."""
    rank = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
    return {
        **snapshot,
        "sensitivity": max(
            (snapshot["sensitivity"], self.classification["sensitivity"]), key=rank.get
        ),
        "combined_restrictions": sorted(
            set(snapshot["combined_restrictions"])
            | set(self.classification["combined_restrictions"])
        ),
        "rules_engine_version": self.classification["rules_engine_version"],
    }


def _effective_retention(self, classification, config=None):
    """The local synthetic destination supports only these handling rules."""
    restrictions = set(classification["combined_restrictions"])
    if (
        restrictions - {"no.content.store"}
        or classification["sensitivity"] == "restricted"
        or (classification["sensitivity"] == "confidential" or restrictions)
        and (config or self.config)["processing_region"] != "local"
    ):
        raise ContractError("POLICY_DENIED", 403)
    retention = deepcopy(self.retention)
    if "no.content.store" in restrictions:
        retention["retention_class"] = "no_store"
        retention["content_store_allowed"] = False
        retention.pop("content_expires_at", None)
    return retention


def _verify_sources(self, messages, trusted):
    roles = {
        "src.prompt.1": ("system", "system_text"),
        "src.user.1": ("user", "content_text"),
        "src.user.no_store": ("user", "content_text"),
        "src.candidate.tool": ("assistant", "tool_call"),
        "src.tool.1": ("tool", "tool_result"),
    }
    for message in messages:
        for block in message["blocks"]:
            labels = block["source_labels"]
            for lineage in labels["lineage_ids"]:
                if (
                    lineage != "src.candidate.tool"
                    and lineage in self.trusted_source_labels
                    and labels != self.trusted_source_labels[lineage]
                ):
                    raise ContractError("SOURCE_INVALID", 422)
                if lineage in roles and (message["role"], block["kind"]) != roles[lineage]:
                    raise ContractError("SOURCE_INVALID", 422)
            if message["role"] == "assistant" and block["kind"] == "tool_call":
                if not self.store.has_authorized_tool_call(
                    trusted["principal_id"],
                    trusted["task_id"],
                    trusted["source_authority_id"],
                    trusted["context_id"],
                    block,
                    self._live_source_tag(block),
                ):
                    raise ContractError("SOURCE_INVALID", 422)
            if message["role"] == "tool" and block[
                "source_labels"
            ] != self.trusted_source_labels.get("src.tool.1"):
                raise ContractError("SOURCE_INVALID", 422)
