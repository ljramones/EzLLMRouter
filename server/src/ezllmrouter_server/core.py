"""Admission, binding, dispatch coordination and public accounting for DEV-01."""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from copy import deepcopy
from contextvars import copy_context
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN
import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
import uuid

from .canonical import (ContractError, digest, ident, jcs, projection, utc_second,
                        validate_text_request, work_digest, strict_loads)
from .plans import PROVIDER_RECIPE_REF, PROVIDER_ADAPTER_VERSION
from .observability import log_failure
from .cache_accounting import SEMANTICS as CACHE_SEMANTICS, cache_usage_revision, exposure_bound


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def public_error(code, guidance="never"):
    return {"code": code, "correlation_id": "corr." + uuid.uuid4().hex, "retry_guidance": guidance}


def selector(req):
    return {k: req[k] for k in ("task_id", "step_id", "step_revision", "execution_generation")}


def work_key(req, trusted):
    return {"principal_id": trusted["principal_id"], **selector(req)}


def public_served_destination(destination):
    """Project the signed private route to the strict wire-0.2 Destination."""
    if destination.get("service") != "openai.responses.v1":
        return deepcopy(destination)
    site = destination["processing_region"]
    try:
        region = ident(site)
    except ContractError:
        region = "site." + hashlib.sha256(site.encode("utf-8")).hexdigest()[:16]
    return {"configuration_ref": destination["configuration_ref"],
            "service": destination["service"],
            "endpoint": destination["deployment_id"],
            "model": destination["model"],
            "model_version": destination["model_version"],
            "processing_region": region}


SCOPE_FIELDS = ("context_id", "issuer_id", "principal_id", "charging_owner_id",
                "source_authority_id", "task_id", "prompt_id", "prompt_version")


def semantic_scope(trusted):
    """Authorization identity excluding renewable credential expiry."""
    return {name: trusted[name] for name in SCOPE_FIELDS}


def public_usage(value):
    """Keep wire 0.2 stable while the ledger retains additive DEV-11 evidence."""
    if value.get("state") != "available":
        return value
    revision = value["revision"]
    if revision.get("usage_semantics_version") != CACHE_SEMANTICS:
        return value
    keys = ("attempt_id", "revision", "usage_observation", "usage_semantics_version",
            "price_version", "cost", "recorded_at", "previous_revision")
    categories = ("input_uncached", "input_cache_read", "input_cache_write",
                  "output_text", "output_reasoning", "other_billable")
    def wire_knowledge(item):
        # v0.2 clients know only known/unknown/not_applicable. The persisted
        # operator record retains the more precise absent/null/invalid state.
        return item if item.get("state") in ("known", "unknown", "not_applicable") else {"state": "unknown"}
    return {"state": "available", "revision": {
        **{key: revision[key] for key in keys if key in revision},
        "normalized_usage": {key: (revision["normalized_usage"][key] if key == "other_billable" else
                                    wire_knowledge(revision["normalized_usage"][key]))
                             for key in categories}}}


def usage_revision(attempt_id, report, tool=False, decision=None, reported_model=None):
    """Unknown remains unknown; cost is independent and never inferred."""
    categories = {"input_uncached": "input_tokens", "output_text": "output_tokens"}
    normalized = {}
    for name in ("input_uncached", "input_cache_read", "input_cache_write", "output_text", "output_reasoning"):
        key = categories.get(name)
        value = report.get(key) if isinstance(report, dict) and key else None
        if type(value) is int and 0 <= value <= 9007199254740991:
            normalized[name] = {"state": "known", "count": value}
        else:
            normalized[name] = {"state": "unknown"}
    normalized["other_billable"] = [{"component": "unclassified", "unit": "units",
                                      "knowledge": {"state": "unknown"}}]
    schedule = decision.get("price_schedule") if decision else None
    cost = {"status": "unknown", "currency": "USD"}
    if schedule and schedule["usage_semantics_version"] == CACHE_SEMANTICS:
        return cache_usage_revision(attempt_id, report, schedule,
                                    decision.get("provider_model"), reported_model)
    if schedule and schedule["usage_semantics_version"] == "openai.responses.text.v1":
        details = report.get("input_tokens_details")
        output_details = report.get("output_tokens_details")
        cached = details.get("cached_tokens") if type(details) is dict else None
        cache_write = details.get("cache_write_tokens", 0) if type(details) is dict else None
        reasoning = output_details.get("reasoning_tokens") if type(output_details) is dict else None
        if type(cached) is int and 0 <= cached <= 9007199254740991:
            normalized["input_cache_read"] = {"state": "known", "count": cached}
        if type(reasoning) is int and 0 <= reasoning <= 9007199254740991:
            normalized["output_reasoning"] = {"state": "known", "count": reasoning}
        if type(cache_write) is int and cache_write == 0:
            normalized["input_cache_write"] = {"state": "not_applicable"}
        input_count = normalized["input_uncached"].get("count")
        output_count = normalized["output_text"].get("count")
        # Responses totals include their detail counts. The adopted usage
        # categories are disjoint, so subtract the details before reporting.
        normalized["input_uncached"] = ({"state": "known", "count": input_count - cached}
            if input_count is not None and type(cached) is int and 0 <= cached <= input_count
            else {"state": "unknown"})
        normalized["output_text"] = ({"state": "known", "count": output_count - reasoning}
            if output_count is not None and type(reasoning) is int and 0 <= reasoning <= output_count
            else {"state": "unknown"})
        expected_model = decision.get("provider_model") if decision else None
        model_matches = type(reported_model) is str and reported_model == expected_model
        if (input_count is not None and output_count is not None and cached == 0 and model_matches and
                cache_write == 0 and type(reasoning) is int and 0 <= reasoning <= output_count):
            normalized["other_billable"] = []
            raw_amount = ((Decimal(input_count) * Decimal(schedule["rates"]["input_uncached"]) +
                          Decimal(output_count) * Decimal(schedule["rates"]["output_text"])) /
                         Decimal(schedule["unit_denominator"]))
            amount = raw_amount.quantize(Decimal("0.000000001"), rounding=ROUND_HALF_EVEN)
            if amount != 0 or raw_amount == 0:
                cost = {"status": "calculated", "currency": schedule["currency"],
                        "amount_decimal": format(amount, "f"), "source_ref": schedule["price_version"]}
                if amount == 0:
                    cost["zero_basis"] = "provider_reported_free" if input_count == output_count == 0 else "contract_free"
    elif schedule:
        # Only this fixed synthetic route defines the remaining dimensions as
        # absent. Missing input/output quantities remain unknown, never zero.
        for category in ("input_cache_read", "input_cache_write", "output_reasoning"):
            normalized[category] = {"state": "not_applicable"}
        normalized["other_billable"] = []
        input_count = normalized["input_uncached"].get("count")
        output_count = normalized["output_text"].get("count")
        if input_count is not None and output_count is not None:
            raw_amount = ((Decimal(input_count) * Decimal(schedule["rates"]["input_uncached"]) +
                          Decimal(output_count) * Decimal(schedule["rates"]["output_text"])) /
                         Decimal(schedule["unit_denominator"]))
            amount = raw_amount.quantize(Decimal("0.000000001"), rounding=ROUND_HALF_EVEN)
            if amount != 0 or raw_amount == 0:
                cost = {"status": "calculated", "currency": schedule["currency"],
                        "amount_decimal": format(amount, "f").rstrip("0").rstrip(".") or "0",
                        "source_ref": schedule["price_version"]}
                if amount == 0:
                    cost["zero_basis"] = "provider_reported_free" if input_count == output_count == 0 else "contract_free"
    return {"attempt_id": attempt_id,
            "usage_observation": ("reported" if schedule and cost["status"] == "calculated" else
                                  "partial" if any(x.get("state") == "known" for x in normalized.values()
                                                   if isinstance(x, dict)) else "unknown"),
            "normalized_usage": normalized,
            "usage_semantics_version": (decision["usage_semantics_version"] if schedule else
                                        "synthetic.tool.v1" if tool else "synthetic.text.v1"),
            "price_version": decision["price_version"] if decision else "synthetic.unpriced.v1",
            "cost": cost,
            "recorded_at": now()}


class Coordinator:
    def __init__(self, store, identity, config, prompt_blocks, allowed_lineages,
                 authority, adapter, retention, classification, recipe, faults=None,
                 trusted_source_labels=None, registry=None):
        self.store, self.identity = store, identity
        self.config, self.prompt_blocks = config, prompt_blocks
        self.allowed_lineages = allowed_lineages
        self.authority, self.adapter, self.recipe = authority, adapter, recipe
        self.retention, self.classification = retention, classification
        self.trusted_source_labels = trusted_source_labels or {}
        self.registry = registry
        self.faults = faults or {}
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ezllmrouter-dev01")
        self._futures = {}
        self._futures_lock = threading.Lock()
        # A process-local key authenticates complete live no-store blocks without
        # persisting their content or accepting a caller-supplied receipt.
        self._live_source_key = secrets.token_bytes(32)

    def _live_source_tag(self, block):
        return hmac.new(self._live_source_key, jcs(block), hashlib.sha256).hexdigest()

    def authenticate(self, token):
        trusted = (self.registry.authenticate(token, next(iter(self.identity.values())))
                   if self.registry else self.identity.get(token))
        if not trusted or datetime.fromisoformat(trusted["expires_at"].replace("Z", "+00:00")) <= datetime.now(timezone.utc):
            raise ContractError("AUTHENTICATION_FAILED", 401)
        return trusted

    def capabilities(self, trusted):
        return {"contract_version": "0.2", "profile": "initial_1a@1",
                "supported_features": ["text", "tools"],
                "disabled_features": ["document_text", "background", "nested", "streaming",
                                      "realtime_voice", "binary_multimodal", "responses_web_search",
                                      "provider_managed_state"]}

    def _prepared(self, projected):
        return self.recipe.expected(projected, projected["work"]["generation_settings"]["total_timeout_ms"])[0]

    def _recipe_matches(self, plan, projected):
        policy = self.authority.policy
        if "tool_adapter_recipe_ref" not in policy:
            return True  # Older isolated test authorities do not model recipe selection.
        if projected["destination"].get("service") == "openai.responses.v1":
            return ("tools" not in projected["work"]["requested_features"] and
                (plan["adapter_recipe_ref"], plan["adapter_version"]) ==
                (PROVIDER_RECIPE_REF, PROVIDER_ADAPTER_VERSION))
        tool = "tools" in projected["work"]["requested_features"]
        ref = policy["tool_adapter_recipe_ref"] if tool else policy["adapter_recipe_ref"]
        version = policy["tool_adapter_version"] if tool else policy["adapter_version"]
        return (plan["adapter_recipe_ref"], plan["adapter_version"]) == (ref, version)

    def _classification_for(self, messages):
        labels = [b["source_labels"] for m in messages for b in m["blocks"]]
        rank = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
        return {"sensitivity": max([self.classification["sensitivity"]] +
                                   [x["sensitivity"] for x in labels], key=rank.get),
                "combined_restrictions": sorted(set(self.classification["combined_restrictions"]) |
                                                {r for x in labels for r in x["restrictions"]}),
                "content_digest": digest(jcs(messages)),
                "rules_engine_version": self.classification["rules_engine_version"]}

    def _current_classification(self, snapshot):
        """Apply a stricter current classifier to admitted source handling."""
        rank = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
        return {**snapshot,
                "sensitivity": max((snapshot["sensitivity"], self.classification["sensitivity"]),
                                   key=rank.get),
                "combined_restrictions": sorted(set(snapshot["combined_restrictions"]) |
                                                set(self.classification["combined_restrictions"])),
                "rules_engine_version": self.classification["rules_engine_version"]}

    def _effective_retention(self, classification, config=None):
        """The local synthetic destination supports only these handling rules."""
        restrictions = set(classification["combined_restrictions"])
        if (restrictions - {"no.content.store"} or classification["sensitivity"] == "restricted" or
                (classification["sensitivity"] == "confidential" or restrictions) and
                (config or self.config)["processing_region"] != "local"):
            raise ContractError("POLICY_DENIED", 403)
        retention = deepcopy(self.retention)
        if "no.content.store" in restrictions:
            retention["retention_class"] = "no_store"
            retention["content_store_allowed"] = False
            retention.pop("content_expires_at", None)
        return retention

    def _verify_sources(self, messages, trusted):
        roles = {"src.prompt.1": ("system", "system_text"),
                 "src.user.1": ("user", "content_text"),
                 "src.user.no_store": ("user", "content_text"),
                 "src.candidate.tool": ("assistant", "tool_call"),
                 "src.tool.1": ("tool", "tool_result")}
        for message in messages:
            for block in message["blocks"]:
                labels = block["source_labels"]
                for lineage in labels["lineage_ids"]:
                    if (lineage != "src.candidate.tool" and lineage in self.trusted_source_labels and
                            labels != self.trusted_source_labels[lineage]):
                        raise ContractError("SOURCE_INVALID", 422)
                    if lineage in roles and (message["role"], block["kind"]) != roles[lineage]:
                        raise ContractError("SOURCE_INVALID", 422)
                if message["role"] == "assistant" and block["kind"] == "tool_call":
                    if not self.store.has_authorized_tool_call(
                            trusted["principal_id"], trusted["task_id"],
                            trusted["source_authority_id"], trusted["context_id"], block,
                            self._live_source_tag(block)):
                        raise ContractError("SOURCE_INVALID", 422)
                if message["role"] == "tool" and block["source_labels"] != \
                        self.trusted_source_labels.get("src.tool.1"):
                    raise ContractError("SOURCE_INVALID", 422)

    def submit(self, req, trusted, wait_ms=1000, credential=None, run_id=None):
        if type(wait_ms) is not int or not 0 <= wait_ms <= 30000:
            raise ContractError("SCHEMA_INVALID", 400)
        decision = None
        if self.registry:
            # The request supplies only the exact reference. Identity and owner
            # came from the authenticated service credential, never the body.
            if type(req) is not dict or any(type(req.get(field)) is not str for field in
                                            ("requested_configuration_ref", "purpose", "task_class")):
                raise ContractError("SCHEMA_INVALID", 400)
            # The existing strict wire/source validator runs before policy
            # lookup; it uses only the reference field of this placeholder.
            messages, settings, deadline, prompt_digest = validate_text_request(
                req, trusted, {"configuration_ref": req["requested_configuration_ref"]},
                self.prompt_blocks, self.allowed_lineages)
            self._verify_sources(messages, trusted)
            admitted_config, decision = self.registry.admit(
                trusted["principal_id"], req["requested_configuration_ref"],
                req["purpose"], req["task_class"], req["requested_features"])
        else:
            admitted_config = deepcopy(self.config)
            messages, settings, deadline, prompt_digest = validate_text_request(
                req, trusted, admitted_config, self.prompt_blocks, self.allowed_lineages)
            self._verify_sources(messages, trusted)
        admitted_trusted = deepcopy(trusted)
        attribution = self.registry.attribution.bind(admitted_trusted, req, run_id) if run_id else None
        attribution_digest = (hashlib.sha256(json.dumps(attribution, sort_keys=True,
            separators=(",", ":")).encode()).hexdigest() if attribution else None)
        admitted_scope = semantic_scope(admitted_trusted)
        admitted_classification = self._classification_for(messages)
        admitted_retention = self._effective_retention(admitted_classification, admitted_config)
        projected = projection(req, admitted_trusted, admitted_config, messages, settings, deadline, prompt_digest)
        if decision and decision["price_schedule"]:
            schedule = decision["price_schedule"]
            policy = self.authority.policy
            if schedule["currency"] != policy["currency"]:
                raise ContractError("FINANCIAL_AUTH_REQUIRED", 403)
            if schedule["usage_semantics_version"] == CACHE_SEMANTICS:
                try:
                    upper = exposure_bound(schedule, settings["max_output_tokens"])
                except (KeyError, ValueError):
                    raise ContractError("FINANCIAL_AUTH_REQUIRED", 403) from None
                if upper > Decimal(policy["max_attempt_charge_decimal"]):
                    raise ContractError("FINANCIAL_AUTH_REQUIRED", 403)
            else:
                # Historical synthetic and DEV-10 prices keep their original
                # behavior. They are not eligible for a new live campaign.
                input_bound = len(jcs(projected["work"]["messages"])) + 1024
                upper = ((Decimal(input_bound) * Decimal(schedule["rates"]["input_uncached"]) +
                          Decimal(settings["max_output_tokens"]) * Decimal(schedule["rates"]["output_text"])) /
                         Decimal(schedule["unit_denominator"]))
                if upper > Decimal(policy["max_attempt_charge_decimal"]):
                    raise ContractError("FINANCIAL_AUTH_REQUIRED", 403)
        admitted_projection = deepcopy(projected)
        wd = work_digest(projected)
        key = work_key(req, admitted_trusted)
        owner = self.store.work_owner(key)
        if owner and owner["contract_version"] != "0.2":
            raise ContractError("WORK_VERSION_CONFLICT", 409)
        existing = self.store.by_work(key)
        if existing:
            if existing["work_digest"] != wd or existing.get("attribution_digest") != attribution_digest:
                raise ContractError("WORK_CONFLICT", 409)
            return 202, self._pending(existing)
        sid, aid = "submission." + uuid.uuid4().hex, "attempt." + uuid.uuid4().hex
        handle = {"submission_id": sid, "work_key": key}
        principal = self.registry.principal(admitted_trusted["principal_id"]) if self.registry else None
        record = {"submission_id": sid, "attempt_id": aid, "principal_id": admitted_trusted["principal_id"],
                  "principal_kind": principal["kind"] if principal else None,
                  "charging_owner_id": admitted_trusted["charging_owner_id"],
                  "task_id": req["task_id"], "work_key": key, "work_digest": wd,
                  "created_at": now(),
                  "task_class": req["task_class"], "purpose": req["purpose"],
                  "provenance": "synthetic_local" if admitted_config.get("service") == "litellm.dev04" else
                      "live_personal_test" if getattr(self.registry, "personal_campaign", None) else
                      "controlled_provider_test" if getattr(self.registry, "controlled_provider_proof", False)
                      else "selected_provider_attempt",
                  "selected_destination": deepcopy(admitted_config),
                  **({"attribution": attribution, "attribution_digest": attribution_digest} if attribution else {}),
                  "source_authority_id": admitted_trusted["source_authority_id"],
                  "context_id": admitted_trusted["context_id"],
                  "classification_snapshot": admitted_classification,
                  **({"registry_decision": decision} if decision else {}),
                  "submission_state": "admitted", "dispatch_state": "prepared", "delivery_state": "none",
                  "cancel_state": "none", "settlement_state": "unsettled", "generation_state": "current",
                  "status_revision": 1, "attempt_revision": 1, "updated_at": now(),
                  "candidate_access": "not_yet_available", "content_store_allowed": admitted_retention["content_store_allowed"],
                  "content_expires_at": admitted_retention.get("content_expires_at"),
                  "wait_expired_no_store": False}
        campaign = getattr(self.registry, "personal_campaign", None) if self.registry else None
        provider_work = admitted_config.get("service") == "openai.responses.v1"
        if provider_work and not getattr(self.registry, "controlled_provider_proof", False) and campaign is None:
            raise ContractError("FINANCIAL_AUTH_REQUIRED", 403)
        if provider_work and ("tools" in req["requested_features"] or projected["work"].get("tools") or
                              projected["work"].get("tool_choice") != "none"):
            raise ContractError("FINANCIAL_AUTH_REQUIRED", 403)
        try:
            if provider_work and campaign is not None:
                message_bytes = len(jcs(projected["work"]["messages"]))
                self.store.create(record, reserve=lambda db, item: campaign.reserve(
                    db, item, message_bytes, settings["max_output_tokens"]))
            else:
                self.store.create(record)
        except ContractError:
            raise
        except sqlite3.IntegrityError:
            owner = self.store.work_owner(key)
            if owner and owner["contract_version"] != "0.2":
                raise ContractError("WORK_VERSION_CONFLICT", 409) from None
            duplicate = self.store.by_work(key)
            if duplicate and duplicate["work_digest"] == wd and duplicate.get("attribution_digest") == attribution_digest:
                return 202, self._pending(duplicate)
            raise ContractError("WORK_CONFLICT", 409)
        except Exception as exc:
            log_failure('core.Coordinator.submit.failed')
            raise ContractError("INTERNAL_UNAVAILABLE", 503) from exc
        admission_clock = time.monotonic()
        deadline_seconds = (datetime.fromisoformat(deadline.replace("Z", "+00:00")) -
                            datetime.now(timezone.utc)).total_seconds()
        response_deadline = admission_clock + max(0, min(wait_ms / 1000, deadline_seconds))
        # The signed plan is generated from trusted facts only, after durable admission.
        try:
            plan = self.authority.issue(admitted_projection, wd, key, admitted_classification, admitted_retention,
                **({"decision_record_ref": "decision." + sid +
                    ("." + attribution_digest if attribution_digest else "")} if self.registry else {}))
            if decision and plan["registry_version"] != "registry.local." + str(decision["authority_revision"]):
                raise ContractError("PLAN_INVALID_OR_STALE", 409)
            self.authority.verify(plan, wd, self.authority.policy["policy_version"])
            if not self._recipe_matches(plan, projected):
                raise ContractError("PLAN_INVALID_OR_STALE", 409)
        except ContractError:
            self._failed(sid, aid, "FDC_REJECTED", "before_transmit")
            return 409, self._failed_reply(handle, aid, "FDC_REJECTED", "before_transmit")
        except Exception:
            log_failure("execution_plan_failed")
            self._failed(sid, aid, "INTERNAL_UNAVAILABLE", "before_transmit")
            return 503, self._failed_reply(handle, aid, "INTERNAL_UNAVAILABLE", "before_transmit")
        if credential is None:
            credential = (None if self.registry else
                          next((token for token, scope in self.identity.items() if scope is trusted), None))
        if credential is None:
            self._failed(sid, aid, "FDC_REJECTED", "before_transmit")
            return 409, self._failed_reply(handle, aid, "FDC_REJECTED", "before_transmit")
        timeout_ms = plan["per_attempt_total_timeout_ms"]
        try:
            expected, expected_request = self.recipe.expected(projected, timeout_ms)
            body = json.loads(expected)
            prepared = self.adapter.prepare(body)
        except Exception:
            log_failure('core.Coordinator.submit.failed')
            self._failed(sid, aid, "FDC_REJECTED", "before_transmit")
            return 409, self._failed_reply(handle, aid, "FDC_REJECTED", "before_transmit")
        if self.faults.get("mutate_after_binding"):
            prepared = self.faults["mutate_after_binding"](prepared)
        try:
            observed_request = self.adapter.describe(prepared, timeout_ms, admitted_config)
            preparation_match = prepared == expected and observed_request == expected_request
        except Exception:
            log_failure('core.Coordinator.submit.failed')
            preparation_match = False
        if not preparation_match:
            self._failed(sid, aid, "FDC_REJECTED", "before_transmit")
            return 409, self._failed_reply(handle, aid, "FDC_REJECTED", "before_transmit")
        if self.faults.get("reject_before_intent"):
            self._failed(sid, aid, "FDC_REJECTED", "before_transmit")
            return 409, self._failed_reply(handle, aid, "FDC_REJECTED", "before_transmit")
        intent = {"attempt_id": aid, "plan_id": plan["plan_id"], "work_digest": wd,
                  "prepared_request_digest": digest(jcs(expected_request)), "destination": deepcopy(plan["destination"]),
                  **({"attribution_digest": attribution_digest} if attribution_digest else {}),
                  **({"registry_decision": decision} if decision else {}),
                  "committed_at": now()}
        try:
            self.store.intent(sid, aid, intent)
        except Exception as exc:
            log_failure('core.Coordinator.submit.failed')
            try:
                self._failed(sid, aid, "INTENT_PERSIST_FAILED", "before_transmit")
            except Exception:
                log_failure('core.Coordinator.submit.failed')
                raise ContractError("INTERNAL_UNAVAILABLE", 503) from exc
            return 503, self._failed_reply(handle, aid, "INTENT_PERSIST_FAILED", "before_transmit")
        try:
            future = self.pool.submit(copy_context().run, self._dispatch, sid, aid, req["execution_generation"],
                                      prepared, plan, expected_request, credential, admitted_scope,
                                      admitted_projection, decision)
        except Exception:
            log_failure("execution_schedule_failed")
            self._failed(sid, aid, "INTERNAL_UNAVAILABLE", "before_transmit")
            return 503, self._failed_reply(handle, aid, "INTERNAL_UNAVAILABLE", "before_transmit")
        with self._futures_lock:
            self._futures[sid] = future
        def release(done):
            with self._futures_lock:
                if self._futures.get(sid) is done:
                    self._futures.pop(sid, None)
        future.add_done_callback(release)
        try:
            outcome = future.result(timeout=max(0, response_deadline - time.monotonic()))
        except TimeoutError:
            pending = self._pending(self.store.get(sid))
            if pending["pending_result_policy"] == "metadata_only_no_store":
                self.store.mark_wait_expired_no_store(sid, now())
            return 202, pending
        except Exception as exc:
            log_failure('core.Coordinator.submit.failed')
            # Intent remains recoverable by work key. An unavailable store cannot
            # honestly produce a durable post-transmit terminal result.
            raise ContractError("INTERNAL_UNAVAILABLE", 503) from exc
        if outcome["kind"] == "candidate":
            self.store.update(sid, {"delivery_state": "candidate_delivered", "updated_at": now()})
            outcome["candidate"]["usage"] = public_usage(outcome["candidate"]["usage"])
            return 200, {"contract_version": "0.2", "state": "delivered", "handle": handle,
                         "candidate": outcome["candidate"]}
        if outcome["kind"] == "failed":
            stage = outcome.get("stage", "after_transmit")
            status = (503 if outcome["code"] == "INTENT_PERSIST_FAILED" else
                      409 if stage == "before_transmit" else 502)
            return status, self._failed_reply(handle, aid, outcome["code"], stage)
        return 202, self._pending(self.store.get(sid))

    def _failed(self, sid, aid, code, stage):
        result = self.store.update(sid, {"submission_state": "failed_before_transmit" if stage == "before_transmit" else "failed_after_transmit",
                                       "dispatch_state": "failed_before_dispatch" if stage == "before_transmit" else "response_observed",
                                       "candidate_access": "unavailable_due_failure", "terminal_failure": public_error(code, "query_first"),
                                       "updated_at": now(), "attempt_revision": 3})
        campaign = getattr(self.registry, "personal_campaign", None) if self.registry else None
        if campaign and result.get("campaign"):
            observed = self.store.get(sid)
            campaign.settle(aid, observed.get("usage", {}).get("revision"), before_transmit=stage == "before_transmit")
        return result

    def _failed_reply(self, handle, aid, code, stage):
        record = self.store.get(handle["submission_id"])
        return {"contract_version": "0.2", "state": "failed", "handle": handle,
                "attempt_id": aid, "failure_stage": stage,
                "error": record["terminal_failure"] if record else public_error(code, "query_first")}

    def _assert_current_dispatch(self, plan, credential, admitted_scope, admitted_projection,
                                 decision=None):
        """Check the same current authority at dispatch and at a DEV-04 lower guard."""
        self.authority.verify(plan, plan["work_digest"], self.authority.policy["policy_version"])
        if self.registry:
            bound = self.store.by_work(plan["work_key"])
            if (not bound or bound.get("registry_decision") != decision or
                    plan["decision_record_ref"] != "decision." + bound["submission_id"] +
                    ("." + bound["attribution_digest"] if bound.get("attribution_digest") else "")):
                raise ContractError("PLAN_INVALID_OR_STALE", 409)
            campaign = getattr(self.registry, "personal_campaign", None)
            if bound.get("campaign"):
                if not campaign:
                    raise ContractError("FINANCIAL_AUTH_REQUIRED", 403)
                campaign.check(bound["attempt_id"], bound["campaign"]["campaign_revision"])
            elif plan["destination"].get("service") == "openai.responses.v1" and not self.registry.controlled_provider_proof:
                raise ContractError("FINANCIAL_AUTH_REQUIRED", 403)
        current_config = (self.registry.check_current(
            admitted_scope["principal_id"], plan["configuration_ref"], plan["purpose"],
            plan["task_class"], decision) if self.registry else self.config)
        current = self.authenticate(credential)
        if self.registry and bound.get("attribution"):
            work = admitted_projection["work"]
            selected = {"task_id": work["task_id"], "task_class": work["task_class"],
                "requested_configuration_ref": plan["configuration_ref"], "purpose": work["purpose"],
                "requested_features": work["requested_features"]}
            if self.registry.attribution.bind(current, selected, bound["attribution"]["run_id"]) != bound["attribution"]:
                raise ContractError("PLAN_INVALID_OR_STALE", 409)
        self._verify_sources(admitted_projection["work"]["messages"], current)
        admitted_classification = plan["classification_snapshot"]
        messages = admitted_projection["work"]["messages"]
        current_classification = self._current_classification(admitted_classification)
        self._effective_retention(current_classification)
        if (semantic_scope(current) != admitted_scope or
            work_digest(admitted_projection) != plan["work_digest"] or
            admitted_projection["trusted"] != {k: admitted_scope[k] for k in
                ("principal_id", "charging_owner_id", "source_authority_id", "context_id")} or
            admitted_projection["work"]["task_id"] != admitted_scope["task_id"] or
            admitted_projection["work"]["resolved_prompt"]["prompt_id"] != admitted_scope["prompt_id"] or
            admitted_projection["work"]["resolved_prompt"]["prompt_version"] != admitted_scope["prompt_version"] or
            current["task_id"] != plan["work_key"]["task_id"] or
            plan["destination"] != current_config or
            not self._recipe_matches(plan, admitted_projection) or
            admitted_classification["content_digest"] != digest(jcs(messages)) or
            plan["effective_retention"] != self._effective_retention(
                admitted_classification, current_config) or
            datetime.fromisoformat(plan["deadline"].replace("Z", "+00:00")) <= datetime.now(timezone.utc)):
            raise ContractError("PLAN_INVALID_OR_STALE", 409)

    def _dispatch(self, sid, aid, generation, prepared, plan, expected_request, credential,
                  admitted_scope, admitted_projection, decision=None):
        try:
            self._assert_current_dispatch(plan, credential, admitted_scope, admitted_projection, decision)
        except (ContractError, KeyError, ValueError):
            self._failed(sid, aid, "FDC_REJECTED", "before_transmit")
            return {"kind": "failed", "code": "FDC_REJECTED", "stage": "before_transmit"}
        try:
            gateway_send = getattr(self.adapter, "send_with_context", None)
            if gateway_send is None:
                response = self.adapter.send(prepared, plan["per_attempt_total_timeout_ms"], expected_request)
            else:
                guard_context = {
                    "submission_id": sid, "attempt_id": aid, "plan": plan,
                    "projection": admitted_projection,
                    "fresh_check": lambda: self._assert_current_dispatch(
                        plan, credential, admitted_scope, admitted_projection, decision),
                    "commit": lambda receipt: self.store.guard_commit(sid, aid, receipt),
                }
                response = gateway_send(prepared, plan["per_attempt_total_timeout_ms"],
                                        expected_request, guard_context)
        except ContractError as exc:
            code = "INTENT_PERSIST_FAILED" if exc.code == "INTENT_PERSIST_FAILED" else "FDC_REJECTED"
            self._failed(sid, aid, code, "before_transmit")
            return {"kind": "failed", "code": code, "stage": "before_transmit"}
        except Exception:
            log_failure('core.Coordinator._dispatch.failed')
            self.store.update(sid, {"submission_state": "outcome_unknown", "dispatch_state": "outcome_unknown",
                                    "candidate_access": "not_yet_available", "updated_at": now(), "attempt_revision": 3})
            campaign = getattr(self.registry, "personal_campaign", None) if self.registry else None
            if campaign:
                campaign.settle(aid)
            return {"kind": "unknown"}
        try:
            return self._observe_response(sid, aid, generation, plan, admitted_projection, decision, response)
        except Exception:
            log_failure("dispatch_response_failed")
            return self._outcome_unknown(sid, aid, plan, decision, response)

    def _outcome_unknown(self, sid, aid, plan=None, decision=None, response=None):
        record = self.store.get(sid)
        usage = record.get("usage", {}).get("revision")
        if usage is None and type(response) is dict and type(response.get("body")) is dict:
            body = response["body"]
            raw_usage = body.get("usage")
            if type(raw_usage) is dict:
                try:
                    provider = plan["destination"].get("service") == "openai.responses.v1"
                    pricing = {**decision, "provider_model": plan["destination"]["model"]} if provider and decision else decision
                    usage = usage_revision(aid, raw_usage, decision=pricing,
                                           reported_model=body.get("served_model") if provider else None)
                except Exception:
                    log_failure("response_usage_unusable")
                    usage = None
        if record["submission_state"] != "completed":
            self.store.update(sid, {"submission_state": "outcome_unknown", "dispatch_state": "outcome_unknown",
                                   "candidate_access": "not_yet_available", "updated_at": now(), "attempt_revision": 3},
                              usage=usage if record.get("usage", {}).get("state") != "available" else None)
            record = self.store.get(sid)
        campaign = getattr(self.registry, "personal_campaign", None) if self.registry else None
        if campaign and record.get("campaign"):
            campaign.settle(aid, record.get("usage", {}).get("revision"))
        return {"kind": "unknown"}

    def _observe_response(self, sid, aid, generation, plan, admitted_projection, decision, response):
        if response["status"] != 200:
            self._failed(sid, aid, "REMOTE_EXECUTION_FAILED", "after_transmit")
            return {"kind": "failed", "code": "REMOTE_EXECUTION_FAILED"}
        body = response["body"]
        tool_request = "tools" in admitted_projection["work"]["requested_features"]
        provider = plan["destination"].get("service") == "openai.responses.v1"
        provider_model = body.get("served_model") if provider and isinstance(body, dict) else None
        pricing = {**decision, "provider_model": plan["destination"]["model"]} if provider and decision else decision
        try:
            raw_usage = body.get("usage") if isinstance(body, dict) else None
            if isinstance(body, dict) and "usage" in body and not isinstance(raw_usage, dict):
                raise ValueError("invalid reported usage")
            raw_usage_bytes = (json.dumps(raw_usage, ensure_ascii=False, sort_keys=True,
                                          separators=(",", ":"), allow_nan=False).encode("utf-8")
                               if raw_usage is not None else None)
            if raw_usage_bytes is not None and len(raw_usage_bytes) > 65536:
                raise ValueError("oversize usage")
            if isinstance(raw_usage, dict):
                observed_usage = usage_revision(aid, raw_usage, tool_request, pricing, provider_model)
                self.store.update(sid, {"raw_usage_digest": digest(raw_usage_bytes), "updated_at": now()},
                                  usage=observed_usage)
        except (TypeError, ValueError, UnicodeError, ContractError):
            self._failed(sid, aid, "CANDIDATE_UNUSABLE", "after_transmit")
            return {"kind": "failed", "code": "CANDIDATE_UNUSABLE"}
        if not isinstance(body, dict) or (not isinstance(body.get("text"), str) and
                                          not (tool_request and isinstance(body.get("tool_calls"), list))):
            self._failed(sid, aid, "CANDIDATE_UNUSABLE", "after_transmit")
            return {"kind": "failed", "code": "CANDIDATE_UNUSABLE"}
        try:
            blocks = []
            output_classification = self._current_classification(plan["classification_snapshot"])
            def output_labels(lineage):
                return {"lineage_ids": [lineage],
                        "sensitivity": output_classification["sensitivity"],
                        "restrictions": list(output_classification["combined_restrictions"])}
            if isinstance(body.get("text"), str):
                output = body["text"]
                output_bytes = output.encode("utf-8", "strict")
                if not output_bytes or len(output_bytes) > 65536 or any(0xD800 <= ord(c) <= 0xDFFF for c in output):
                    raise ValueError("unusable output text")
                lineage = ("src.candidate.provider" if plan["destination"].get("service") == "openai.responses.v1"
                           else "src.candidate.synthetic")
                blocks.append({"block_id": "block.output.1", "kind": "assistant_text", "text": output,
                               "source_labels": output_labels(lineage)})
            if "tool_calls" in body:
                if not tool_request or admitted_projection["work"]["tool_choice"] == "none" or \
                        not body["tool_calls"] or len(body["tool_calls"]) > 2:
                    raise ValueError("unusable tool calls")
                seen_calls = set()
                for index, call in enumerate(body["tool_calls"]):
                    if not isinstance(call, dict) or set(call) != {"id", "name", "arguments_json"} or \
                            not isinstance(call["id"], str) or not isinstance(call["arguments_json"], str) or \
                            call["name"] != "lookup" or call["id"] in seen_calls:
                        raise ValueError("unusable tool call")
                    from .canonical import ident
                    ident(call["id"])
                    seen_calls.add(call["id"])
                    arguments = strict_loads(call["arguments_json"].encode("utf-8"))
                    if type(arguments) is not dict or set(arguments) != {"key"} or type(arguments["key"]) is not str:
                        raise ValueError("unusable arguments")
                    blocks.append({"block_id": f"block.call.{index + 1}", "kind": "tool_call",
                                   "call_id": call["id"], "tool_name": "lookup", "arguments": arguments,
                                   "source_labels": output_labels("src.candidate.tool")})
            if not blocks or ("tool_calls" in body) != (body.get("finish_reason") == "tool_calls"):
                if "tool_calls" in body or "finish_reason" in body:
                    raise ValueError("invalid finish reason")
        except (TypeError, ValueError, UnicodeError, ContractError):
            self._failed(sid, aid, "CANDIDATE_UNUSABLE", "after_transmit")
            return {"kind": "failed", "code": "CANDIDATE_UNUSABLE"}
        candidate = {"candidate_id": "candidate." + uuid.uuid4().hex, "attempt_id": aid,
                     "execution_generation": generation,
                     "served_destination": public_served_destination(plan["destination"]),
                     "output_blocks": blocks,
                     "finish_reason": "tool_calls" if "tool_calls" in body else "stop",
                     "structural_status": "pass", "observed_at": now(),
                     "usage": {"state": "not_recorded"}}
        try:
            current_retention = self._effective_retention(
                self._current_classification(plan["classification_snapshot"]))
            current_delivery_allowed = True
        except ContractError:
            current_retention = {"content_store_allowed": False}
            current_delivery_allowed = False
        if raw_usage_bytes is not None:
            raw_usage_digest = digest(raw_usage_bytes)
        else:
            raw_usage_digest = None
        if plan["destination"].get("service") == "openai.responses.v1":
            self.store.update(sid, {"provider_model_reported": provider_model,
                                    "updated_at": now()})
        final = self.store.complete_candidate(sid, candidate, None, raw_usage_digest,
            current_retention["content_store_allowed"], current_retention.get("content_expires_at"), now(),
            [self._live_source_tag(block) for block in blocks
             if block["kind"] == "tool_call"] if current_delivery_allowed else [])
        candidate["usage"] = final["usage"]
        campaign = getattr(self.registry, "personal_campaign", None) if self.registry else None
        if campaign and final.get("campaign"):
            campaign.settle(aid, final["usage"].get("revision"))
        if not current_delivery_allowed or final["wait_expired_no_store"] or final["candidate_access"] == "expired":
            return {"kind": "completed_no_store"}
        return {"kind": "candidate", "candidate": candidate}

    def _pending(self, record):
        try:
            current_retention = self._effective_retention(
                self._current_classification(record["classification_snapshot"]))
        except (ContractError, KeyError):
            current_retention = {"content_store_allowed": False}
        return {"contract_version": "0.2", "state": "pending",
                "handle": {"submission_id": record["submission_id"], "work_key": record["work_key"]},
                "pending_result_policy": "pollable_if_retained" if not record["wait_expired_no_store"] and
                 record["content_store_allowed"] and
                 current_retention["content_store_allowed"] else "metadata_only_no_store"}

    def status(self, sid, trusted):
        record = self.store.get(sid)
        if not record or record["principal_id"] != trusted["principal_id"] or record["task_id"] != trusted["task_id"]:
            raise ContractError("NOT_FOUND_OR_FORBIDDEN", 404)
        if record["candidate_access"] == "present":
            try:
                current_retention = self._effective_retention(
                    self._current_classification(record["classification_snapshot"]))
            except (ContractError, KeyError):
                current_retention = {"content_store_allowed": False}
            current_expiry = current_retention.get("content_expires_at")
            expired = (current_expiry is not None and
                       datetime.fromisoformat(current_expiry.replace("Z", "+00:00")) <= datetime.now(timezone.utc))
            if (record["wait_expired_no_store"] or not record["content_store_allowed"] or
                    not current_retention["content_store_allowed"] or expired):
                self.store.update(sid, {"candidate": None,
                                        "candidate_access": "expired" if expired else "not_retained",
                                        "updated_at": now()})
                record = self.store.get(sid)
        attempt = {"attempt_id": record["attempt_id"], "execution_generation": record["work_key"]["execution_generation"],
                   "attempt_revision": record["attempt_revision"], "dispatch_state": record["dispatch_state"],
                   "delivery_state": record["delivery_state"], "cancel_state": record["cancel_state"],
                   "settlement_state": record["settlement_state"], "generation_state": record["generation_state"],
                   "usage": public_usage(record["usage"])}
        result = {"contract_version": "0.2", "handle": {"submission_id": sid, "work_key": record["work_key"]},
                  "status_revision": record["status_revision"], "submission_state": record["submission_state"],
                  "attempts": [attempt], "candidate_access": record["candidate_access"],
                  "updated_at": record["updated_at"]}
        if record["candidate_access"] == "present" and record.get("candidate"):
            result["candidate"] = {**record["candidate"], "usage": public_usage(record["usage"])}
        if record.get("terminal_failure"):
            result["terminal_failure"] = record["terminal_failure"]
            result["terminal_attempt_id"] = record["attempt_id"]
        if record.get("result_unavailable_reason"):
            result["result_unavailable_reason"] = record["result_unavailable_reason"]
        return result

    def status_by_work(self, key, trusted):
        if key["principal_id"] != trusted["principal_id"]:
            raise ContractError("NOT_FOUND_OR_FORBIDDEN", 404)
        record = self.store.by_work(key)
        if not record:
            raise ContractError("NOT_FOUND_OR_FORBIDDEN", 404)
        return self.status(record["submission_id"], trusted)
