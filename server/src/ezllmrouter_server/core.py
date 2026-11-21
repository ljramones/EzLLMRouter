"""Admission, binding, dispatch coordination and public accounting for DEV-01."""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
import uuid
from contextvars import copy_context
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_HALF_EVEN, Decimal

from .cache_accounting import SEMANTICS as CACHE_SEMANTICS
from .cache_accounting import cache_usage_revision
from .canonical import (
    ContractError,
    ident,
    projection,
    work_digest,
)
from .formatting import money, utc_timestamp
from .json_validation import MAX_SAFE_INTEGER, JSONValue
from .observability import log_failure as log_failure
from .runtime_resources import AdmissionGate, BoundedExecutor, ServiceClosing
from .store import Store


def now():
    return utc_timestamp(datetime.now(timezone.utc))


def public_error(code: str, guidance: str = "never") -> dict[str, str]:
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
    return {
        "configuration_ref": destination["configuration_ref"],
        "service": destination["service"],
        "endpoint": destination["deployment_id"],
        "model": destination["model"],
        "model_version": destination["model_version"],
        "processing_region": region,
    }


SCOPE_FIELDS = (
    "context_id",
    "issuer_id",
    "principal_id",
    "charging_owner_id",
    "source_authority_id",
    "task_id",
    "prompt_id",
    "prompt_version",
)


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
    keys = (
        "attempt_id",
        "revision",
        "usage_observation",
        "usage_semantics_version",
        "price_version",
        "cost",
        "recorded_at",
        "previous_revision",
    )
    categories = (
        "input_uncached",
        "input_cache_read",
        "input_cache_write",
        "output_text",
        "output_reasoning",
        "other_billable",
    )

    def wire_knowledge(item):
        # v0.2 clients know only known/unknown/not_applicable. The persisted
        # operator record retains the more precise absent/null/invalid state.
        return (
            item
            if item.get("state") in ("known", "unknown", "not_applicable")
            else {"state": "unknown"}
        )

    return {
        "state": "available",
        "revision": {
            **{key: revision[key] for key in keys if key in revision},
            "normalized_usage": {
                key: (
                    revision["normalized_usage"][key]
                    if key == "other_billable"
                    else wire_knowledge(revision["normalized_usage"][key])
                )
                for key in categories
            },
        },
    }


def _text_cost(schedule, input_count, output_count, *, compact):
    """Preserve unknown exposure when a positive charge rounds below the quantum."""
    raw_amount = (
        Decimal(input_count) * Decimal(schedule["rates"]["input_uncached"])
        + Decimal(output_count) * Decimal(schedule["rates"]["output_text"])
    ) / Decimal(schedule["unit_denominator"])
    amount = raw_amount.quantize(Decimal("0.000000001"), rounding=ROUND_HALF_EVEN)
    if amount == 0 and raw_amount != 0:
        return None
    cost = {
        "status": "calculated",
        "currency": schedule["currency"],
        "amount_decimal": money(amount, compact=compact),
        "source_ref": schedule["price_version"],
    }
    if amount == 0:
        cost["zero_basis"] = (
            "provider_reported_free" if input_count == output_count == 0 else "contract_free"
        )
    return cost


def usage_revision(attempt_id, report, tool=False, decision=None, reported_model=None):
    """Unknown remains unknown; cost is independent and never inferred."""
    categories = {"input_uncached": "input_tokens", "output_text": "output_tokens"}
    normalized = {}
    for name in (
        "input_uncached",
        "input_cache_read",
        "input_cache_write",
        "output_text",
        "output_reasoning",
    ):
        key = categories.get(name)
        value = report.get(key) if isinstance(report, dict) and key else None
        if type(value) is int and 0 <= value <= MAX_SAFE_INTEGER:
            normalized[name] = {"state": "known", "count": value}
        else:
            normalized[name] = {"state": "unknown"}
    normalized["other_billable"] = [
        {"component": "unclassified", "unit": "units", "knowledge": {"state": "unknown"}}
    ]
    schedule = decision.get("price_schedule") if decision else None
    cost = {"status": "unknown", "currency": "USD"}
    if schedule and schedule["usage_semantics_version"] == CACHE_SEMANTICS:
        return cache_usage_revision(
            attempt_id, report, schedule, decision.get("provider_model"), reported_model
        )
    if schedule and schedule["usage_semantics_version"] == "openai.responses.text.v1":
        details = report.get("input_tokens_details")
        output_details = report.get("output_tokens_details")
        cached = details.get("cached_tokens") if type(details) is dict else None
        cache_write = details.get("cache_write_tokens", 0) if type(details) is dict else None
        reasoning = output_details.get("reasoning_tokens") if type(output_details) is dict else None
        if type(cached) is int and 0 <= cached <= MAX_SAFE_INTEGER:
            normalized["input_cache_read"] = {"state": "known", "count": cached}
        if type(reasoning) is int and 0 <= reasoning <= MAX_SAFE_INTEGER:
            normalized["output_reasoning"] = {"state": "known", "count": reasoning}
        if type(cache_write) is int and cache_write == 0:
            normalized["input_cache_write"] = {"state": "not_applicable"}
        input_count = normalized["input_uncached"].get("count")
        output_count = normalized["output_text"].get("count")
        # Responses totals include their detail counts. The adopted usage
        # categories are disjoint, so subtract the details before reporting.
        normalized["input_uncached"] = (
            {"state": "known", "count": input_count - cached}
            if input_count is not None and type(cached) is int and 0 <= cached <= input_count
            else {"state": "unknown"}
        )
        normalized["output_text"] = (
            {"state": "known", "count": output_count - reasoning}
            if output_count is not None
            and type(reasoning) is int
            and 0 <= reasoning <= output_count
            else {"state": "unknown"}
        )
        expected_model = decision.get("provider_model") if decision else None
        model_matches = type(reported_model) is str and reported_model == expected_model
        if (
            input_count is not None
            and output_count is not None
            and cached == 0
            and model_matches
            and cache_write == 0
            and type(reasoning) is int
            and 0 <= reasoning <= output_count
        ):
            normalized["other_billable"] = []
            cost = _text_cost(schedule, input_count, output_count, compact=False) or cost
    elif schedule:
        # Only this fixed synthetic route defines the remaining dimensions as
        # absent. Missing input/output quantities remain unknown, never zero.
        for category in ("input_cache_read", "input_cache_write", "output_reasoning"):
            normalized[category] = {"state": "not_applicable"}
        normalized["other_billable"] = []
        input_count = normalized["input_uncached"].get("count")
        output_count = normalized["output_text"].get("count")
        if input_count is not None and output_count is not None:
            cost = _text_cost(schedule, input_count, output_count, compact=True) or cost
    return {
        "attempt_id": attempt_id,
        "usage_observation": (
            "reported"
            if schedule and cost["status"] == "calculated"
            else "partial"
            if any(x.get("state") == "known" for x in normalized.values() if isinstance(x, dict))
            else "unknown"
        ),
        "normalized_usage": normalized,
        "usage_semantics_version": (
            decision["usage_semantics_version"]
            if schedule
            else "synthetic.tool.v1"
            if tool
            else "synthetic.text.v1"
        ),
        "price_version": decision["price_version"] if decision else "synthetic.unpriced.v1",
        "cost": cost,
        "recorded_at": now(),
    }


@dataclass(frozen=True)
class AdmittedWork:
    """The admitted snapshot passed to preparation and dispatch, never current registry state."""

    admitted_classification: dict[str, JSONValue]
    admitted_config: dict[str, JSONValue]
    admitted_projection: dict[str, JSONValue]
    admitted_retention: dict[str, JSONValue]
    admitted_scope: dict[str, JSONValue]
    aid: str
    attribution_digest: str | None
    deadline: str
    decision: dict[str, JSONValue] | None
    handle: dict[str, JSONValue]
    key: dict[str, JSONValue]
    projected: dict[str, JSONValue]
    sid: str
    wd: str


from . import core_policy
from . import core_admission
from . import core_attempt
from . import core_outcomes
from . import core_status


class Coordinator:
    def __init__(
        self,
        store: Store,
        *,
        identity,
        config,
        prompt_blocks,
        allowed_lineages,
        authority,
        adapter,
        retention,
        classification,
        recipe,
        faults=None,
        trusted_source_labels=None,
        registry=None,
        authentication_context=None,
        successor=None,
        context_sender=None,
    ):
        self.store, self.identity = store, identity
        self.config, self.prompt_blocks = config, prompt_blocks
        self.allowed_lineages = allowed_lineages
        self.authority, self.adapter, self.recipe = authority, adapter, recipe
        self.retention, self.classification = retention, classification
        self.trusted_source_labels = trusted_source_labels or {}
        self.registry = registry
        self.successor = successor
        self.context_sender = (
            context_sender
            if context_sender is not None
            else getattr(adapter, "send_with_context", None)
        )
        self.authentication_context = deepcopy(authentication_context)
        self.faults = faults or {}
        self.pool = BoundedExecutor(max_workers=4, thread_name_prefix="ezllmrouter-execution")
        self._admission = AdmissionGate()
        self._futures = {}
        self._futures_lock = threading.Lock()
        # A process-local key authenticates complete live no-store blocks without
        # persisting their content or accepting a caller-supplied receipt.
        self._live_source_key = secrets.token_bytes(32)

    @property
    def personal_campaign(self):
        return self.registry.personal_campaign if self.registry is not None else None

    def close(self):
        self._admission.close()
        try:
            successor = self.successor
            if successor is not None:
                successor.close()
        finally:
            self.pool.shutdown(wait=True)

    _live_source_tag = core_policy._live_source_tag

    authenticate = core_policy.authenticate

    capabilities = core_policy.capabilities

    _prepared = core_policy._prepared

    _recipe_matches = core_policy._recipe_matches

    _classification_for = core_policy._classification_for

    _current_classification = core_policy._current_classification

    _effective_retention = core_policy._effective_retention

    _verify_sources = core_policy._verify_sources

    def submit(self, req, trusted, wait_ms=1000, credential=None, run_id=None):
        try:
            with self._admission.enter():
                return self._submit(req, trusted, wait_ms, credential=credential, run_id=run_id)
        except ServiceClosing as exc:
            raise ContractError("INTERNAL_UNAVAILABLE", 503) from exc

    def _submit(self, req, trusted, wait_ms=1000, credential=None, run_id=None):
        admitted_config, decision, messages, settings, deadline, prompt_digest = (
            self._validate_admission(req, trusted, wait_ms)
        )
        admitted_trusted = deepcopy(trusted)
        attribution = (
            self.registry.attribution.bind(admitted_trusted, req, run_id) if run_id else None
        )
        attribution_digest = (
            hashlib.sha256(
                json.dumps(attribution, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            if attribution
            else None
        )
        admitted_scope = semantic_scope(admitted_trusted)
        admitted_classification = self._classification_for(messages)
        admitted_retention = self._effective_retention(admitted_classification, admitted_config)
        projected = projection(
            req, admitted_trusted, admitted_config, messages, settings, deadline, prompt_digest
        )
        self._check_admission_exposure(decision, settings, projected)
        admitted_projection = deepcopy(projected)
        wd = work_digest(projected)
        key = work_key(req, admitted_trusted)
        owner = self.store.work_owner(key)
        if owner and owner["contract_version"] != "0.2":
            raise ContractError("WORK_VERSION_CONFLICT", 409)
        existing = self.store.by_work(key)
        if existing:
            if (
                existing["work_digest"] != wd
                or existing.get("attribution_digest") != attribution_digest
            ):
                raise ContractError("WORK_CONFLICT", 409)
            return 202, self._pending(existing)
        sid, aid = "submission." + uuid.uuid4().hex, "attempt." + uuid.uuid4().hex
        handle = {"submission_id": sid, "work_key": key}
        admitted = AdmittedWork(
            admitted_classification=admitted_classification,
            admitted_config=admitted_config,
            admitted_projection=admitted_projection,
            admitted_retention=admitted_retention,
            admitted_scope=admitted_scope,
            aid=aid,
            attribution_digest=attribution_digest,
            deadline=deadline,
            decision=decision,
            handle=handle,
            key=key,
            projected=projected,
            sid=sid,
            wd=wd,
        )
        record = self._admission_record(admitted, req, admitted_trusted, attribution)
        replay = self._persist_admission(admitted, record, req, settings)
        if replay is not None:
            return replay
        return self._start_attempt(admitted, req, trusted, wait_ms, credential)

    def _start_attempt(self, admitted: AdmittedWork, req, trusted, wait_ms, credential):
        admission_clock = time.monotonic()
        deadline_seconds = (
            datetime.fromisoformat(admitted.deadline.replace("Z", "+00:00"))
            - datetime.now(timezone.utc)
        ).total_seconds()
        response_deadline = admission_clock + max(0, min(wait_ms / 1000, deadline_seconds))
        # The signed plan is generated from trusted facts only, after durable admission.
        plan, failure = self._attempt_plan(admitted)
        if failure is not None:
            return failure
        if credential is None:
            matches = (
                []
                if self.registry
                else [token for token, scope in self.identity.items() if scope is trusted]
            )
            credential = matches[0] if len(matches) == 1 else None
        if credential is None:
            self._failed(admitted.sid, admitted.aid, "FDC_REJECTED", "before_transmit")
            return 409, self._failed_reply(
                admitted.handle, admitted.aid, "FDC_REJECTED", "before_transmit"
            )
        prepared, expected_request, failure = self._prepare_attempt(admitted, plan)
        if failure is not None:
            return failure
        failure = self._record_attempt_intent(admitted, plan, expected_request)
        if failure is not None:
            return failure
        try:
            future = self.pool.submit(
                copy_context().run,
                self._dispatch,
                admitted.sid,
                admitted.aid,
                req["execution_generation"],
                prepared,
                plan,
                expected_request,
                credential,
                admitted.admitted_scope,
                admitted.admitted_projection,
                admitted.decision,
            )
        except Exception:
            log_failure("execution_schedule_failed")
            self._failed(admitted.sid, admitted.aid, "INTERNAL_UNAVAILABLE", "before_transmit")
            return 503, self._failed_reply(
                admitted.handle, admitted.aid, "INTERNAL_UNAVAILABLE", "before_transmit"
            )
        return self._wait_for_attempt(admitted, future, response_deadline)

    _failed = core_outcomes._failed

    _failed_reply = core_outcomes._failed_reply

    _assert_current_dispatch = core_attempt._assert_current_dispatch

    _dispatch = core_attempt._dispatch

    _outcome_unknown = core_outcomes._outcome_unknown

    _observe_response = core_outcomes._observe_response

    _pending = core_status._pending

    status = core_status.status

    status_by_work = core_status.status_by_work

    _attempt_plan = core_attempt._attempt_plan

    _prepare_attempt = core_attempt._prepare_attempt

    _record_attempt_intent = core_attempt._record_attempt_intent

    _wait_for_attempt = core_attempt._wait_for_attempt

    _validate_admission = core_admission._validate_admission

    _check_admission_exposure = core_admission._check_admission_exposure

    _admission_record = core_admission._admission_record

    _persist_admission = core_admission._persist_admission

    _observe_usage = core_outcomes._observe_usage

    _output_blocks = core_outcomes._output_blocks

    _complete_observed_candidate = core_outcomes._complete_observed_candidate
