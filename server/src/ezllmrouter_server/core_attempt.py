"""Coordinator attempt steps under the existing instance context."""

from __future__ import annotations

from typing import cast
from .core_types import RuntimeRegistry, DirectSenderAdapter

from concurrent.futures import Future
from typing import TYPE_CHECKING
from .records import Record
from .core_types import Reply

if TYPE_CHECKING:
    from .core import Coordinator

import json
import time
from concurrent.futures import TimeoutError
from copy import deepcopy
from datetime import datetime, timezone
from .canonical import (
    ContractError,
    digest,
    jcs,
    work_digest,
)
from .states import CandidateAccess, DeliveryState, DispatchState, SubmissionState
from . import core as _api


def _assert_current_dispatch(
    self: Coordinator,
    plan: Record,
    credential: str | None,
    admitted_scope: Record,
    admitted_projection: Record,
    decision: Record | None = None,
) -> None:
    """Check the same current authority at dispatch and at a DEV-04 lower guard."""
    self.authority.verify(plan, plan["work_digest"], self.authority.policy["policy_version"])
    if self.registry:
        bound = _registry_dispatch_record(self, plan, decision)
    current_config = (
        self.registry.check_current(
            admitted_scope["principal_id"],
            plan["configuration_ref"],
            plan["purpose"],
            plan["task_class"],
            cast(Record, decision),
        )
        if self.registry
        else self.config
    )
    current = self.authenticate(cast(str, credential))
    if self.registry and bound.get("attribution"):
        work = admitted_projection["work"]
        selected = {
            "task_id": work["task_id"],
            "task_class": work["task_class"],
            "requested_configuration_ref": plan["configuration_ref"],
            "purpose": work["purpose"],
            "requested_features": work["requested_features"],
        }
        if (
            self.registry.attribution.bind(current, selected, bound["attribution"]["run_id"])
            != bound["attribution"]
        ):
            raise ContractError("PLAN_INVALID_OR_STALE", 409)
    self._verify_sources(admitted_projection["work"]["messages"], current)
    admitted_classification = plan["classification_snapshot"]
    messages = admitted_projection["work"]["messages"]
    current_classification = self._current_classification(admitted_classification)
    self._effective_retention(current_classification)
    if (
        _api.semantic_scope(current) != admitted_scope
        or work_digest(admitted_projection) != plan["work_digest"]
        or admitted_projection["trusted"]
        != {
            k: admitted_scope[k]
            for k in ("principal_id", "charging_owner_id", "source_authority_id", "context_id")
        }
        or admitted_projection["work"]["task_id"] != admitted_scope["task_id"]
        or admitted_projection["work"]["resolved_prompt"]["prompt_id"]
        != admitted_scope["prompt_id"]
        or admitted_projection["work"]["resolved_prompt"]["prompt_version"]
        != admitted_scope["prompt_version"]
        or current["task_id"] != plan["work_key"]["task_id"]
        or plan["destination"] != current_config
        or not self._recipe_matches(plan, admitted_projection)
        or admitted_classification["content_digest"] != digest(jcs(messages))
        or plan["effective_retention"]
        != self._effective_retention(admitted_classification, current_config)
        or datetime.fromisoformat(plan["deadline"].replace("Z", "+00:00"))
        <= datetime.now(timezone.utc)
    ):
        raise ContractError("PLAN_INVALID_OR_STALE", 409)


def _dispatch(
    self: Coordinator,
    sid: str,
    aid: str,
    generation: int,
    prepared: bytes,
    plan: Record,
    expected_request: Record,
    credential: str | None,
    admitted_scope: Record,
    admitted_projection: Record,
    decision: Record | None = None,
) -> Record:
    try:
        self._assert_current_dispatch(
            plan, credential, admitted_scope, admitted_projection, decision
        )
    except Exception:
        _api.log_failure("core.dispatch.before_transmit_check_failed")
        self._failed(sid, aid, "FDC_REJECTED", "before_transmit")
        return {"kind": "failed", "code": "FDC_REJECTED", "stage": "before_transmit"}
    try:
        gateway_send = self.context_sender
        if gateway_send is None:
            response = cast(DirectSenderAdapter, self.adapter).send(
                prepared, plan["per_attempt_total_timeout_ms"], expected_request
            )
        else:
            guard_context = {
                "submission_id": sid,
                "attempt_id": aid,
                "plan": plan,
                "projection": admitted_projection,
                "fresh_check": lambda: self._assert_current_dispatch(
                    plan, credential, admitted_scope, admitted_projection, decision
                ),
                "commit": lambda receipt: self.store.guard_commit(sid, aid, receipt),
            }
            response = gateway_send(
                prepared, plan["per_attempt_total_timeout_ms"], expected_request, guard_context
            )
    except ContractError as exc:
        code = "INTENT_PERSIST_FAILED" if exc.code == "INTENT_PERSIST_FAILED" else "FDC_REJECTED"
        self._failed(sid, aid, code, "before_transmit")
        return {"kind": "failed", "code": code, "stage": "before_transmit"}
    except Exception:
        _api.log_failure("core.Coordinator._dispatch.failed")
        self.store.update(
            sid,
            {
                "submission_state": SubmissionState.OUTCOME_UNKNOWN.value,
                "dispatch_state": DispatchState.OUTCOME_UNKNOWN.value,
                "candidate_access": CandidateAccess.NOT_YET_AVAILABLE.value,
                "updated_at": _api.now(),
                "attempt_revision": 3,
            },
        )
        campaign = self.personal_campaign
        if campaign:
            campaign.settle(aid)
        return {"kind": "unknown"}
    try:
        return self._observe_response(
            sid, aid, generation, plan, admitted_projection, decision, response
        )
    except Exception:
        _api.log_failure("dispatch_response_failed")
        return self._outcome_unknown(sid, aid, plan, decision, response)


def _attempt_plan(
    self: Coordinator, admitted: _api.AdmittedWork
) -> tuple[Record | None, Reply | None]:
    try:
        plan = self.authority.issue(
            admitted.admitted_projection,
            admitted.wd,
            admitted.key,
            admitted.admitted_classification,
            admitted.admitted_retention,
            **{
                "decision_record_ref": "decision."
                + admitted.sid
                + ("." + admitted.attribution_digest if admitted.attribution_digest else "")
            }
            if self.registry
            else {},
        )
        if admitted.decision and plan["registry_version"] != "registry.local." + str(
            admitted.decision["authority_revision"]
        ):
            raise ContractError("PLAN_INVALID_OR_STALE", 409)
        self.authority.verify(plan, admitted.wd, self.authority.policy["policy_version"])
        if not self._recipe_matches(plan, admitted.projected):
            raise ContractError("PLAN_INVALID_OR_STALE", 409)
    except ContractError:
        self._failed(admitted.sid, admitted.aid, "FDC_REJECTED", "before_transmit")
        return (
            None,
            (
                409,
                self._failed_reply(
                    admitted.handle, admitted.aid, "FDC_REJECTED", "before_transmit"
                ),
            ),
        )
    except Exception:
        _api.log_failure("execution_plan_failed")
        self._failed(admitted.sid, admitted.aid, "INTERNAL_UNAVAILABLE", "before_transmit")
        return (
            None,
            (
                503,
                self._failed_reply(
                    admitted.handle, admitted.aid, "INTERNAL_UNAVAILABLE", "before_transmit"
                ),
            ),
        )
    return plan, None


def _prepare_attempt(
    self: Coordinator, admitted: _api.AdmittedWork, plan: Record
) -> tuple[bytes | None, Record | None, Reply | None]:
    timeout_ms = plan["per_attempt_total_timeout_ms"]
    try:
        expected, expected_request = self.recipe.expected(admitted.projected, timeout_ms)
        body = json.loads(expected)
        prepared = self.adapter.prepare(body)
    except Exception:
        _api.log_failure("core.Coordinator.request_prepare.failed")
        self._failed(admitted.sid, admitted.aid, "FDC_REJECTED", "before_transmit")
        return (
            None,
            None,
            (
                409,
                self._failed_reply(
                    admitted.handle, admitted.aid, "FDC_REJECTED", "before_transmit"
                ),
            ),
        )
    if self.faults.get("mutate_after_binding"):
        prepared = self.faults["mutate_after_binding"](prepared)
    try:
        observed_request = self.adapter.describe(prepared, timeout_ms, admitted.admitted_config)
        preparation_match = prepared == expected and observed_request == expected_request
    except Exception:
        _api.log_failure("core.Coordinator.request_describe.failed")
        preparation_match = False
    if not preparation_match:
        self._failed(admitted.sid, admitted.aid, "FDC_REJECTED", "before_transmit")
        return (
            None,
            None,
            (
                409,
                self._failed_reply(
                    admitted.handle, admitted.aid, "FDC_REJECTED", "before_transmit"
                ),
            ),
        )
    if self.faults.get("reject_before_intent"):
        self._failed(admitted.sid, admitted.aid, "FDC_REJECTED", "before_transmit")
        return (
            None,
            None,
            (
                409,
                self._failed_reply(
                    admitted.handle, admitted.aid, "FDC_REJECTED", "before_transmit"
                ),
            ),
        )
    return prepared, expected_request, None


def _record_attempt_intent(
    self: Coordinator, admitted: _api.AdmittedWork, plan: Record, expected_request: Record
) -> Reply | None:
    intent = {
        "attempt_id": admitted.aid,
        "plan_id": plan["plan_id"],
        "work_digest": admitted.wd,
        "prepared_request_digest": digest(jcs(expected_request)),
        "destination": deepcopy(plan["destination"]),
        **(
            {"attribution_digest": admitted.attribution_digest}
            if admitted.attribution_digest
            else {}
        ),
        **({"registry_decision": admitted.decision} if admitted.decision else {}),
        "committed_at": _api.now(),
    }
    try:
        self.store.intent(admitted.sid, admitted.aid, intent)
    except Exception as exc:
        _api.log_failure("core.Coordinator.intent_persist.failed")
        try:
            self._failed(admitted.sid, admitted.aid, "INTENT_PERSIST_FAILED", "before_transmit")
        except Exception:
            _api.log_failure("core.Coordinator.intent_failure_persist.failed")
            raise ContractError("INTERNAL_UNAVAILABLE", 503) from exc
        return 503, self._failed_reply(
            admitted.handle, admitted.aid, "INTENT_PERSIST_FAILED", "before_transmit"
        )
    return None


def _wait_for_attempt(
    self: Coordinator, admitted: _api.AdmittedWork, future: Future[Record], response_deadline: float
) -> Reply:
    with self._futures_lock:
        self._futures[admitted.sid] = future

    def release(done: Future[Record]) -> None:
        with self._futures_lock:
            if self._futures.get(admitted.sid) is done:
                self._futures.pop(admitted.sid, None)

    future.add_done_callback(release)
    try:
        outcome = future.result(timeout=max(0, response_deadline - time.monotonic()))
    except TimeoutError:
        pending = self._pending(cast(Record, self.store.get(admitted.sid)))
        if pending["pending_result_policy"] == "metadata_only_no_store":
            self.store.mark_wait_expired_no_store(admitted.sid, _api.now())
        return 202, pending
    except Exception as exc:
        _api.log_failure("core.Coordinator.attempt_wait.failed")
        # Intent remains recoverable by work key. An unavailable store cannot
        # honestly produce a durable post-transmit terminal result.
        raise ContractError("INTERNAL_UNAVAILABLE", 503) from exc
    if outcome["kind"] == "candidate":
        self.store.update(
            admitted.sid,
            {"delivery_state": DeliveryState.CANDIDATE_DELIVERED.value, "updated_at": _api.now()},
        )
        outcome["candidate"]["usage"] = _api.public_usage(outcome["candidate"]["usage"])
        return 200, {
            "contract_version": "0.2",
            "state": "delivered",
            "handle": admitted.handle,
            "candidate": outcome["candidate"],
        }
    if outcome["kind"] == "failed":
        stage = outcome.get("stage", "after_transmit")
        status = (
            503
            if outcome["code"] == "INTENT_PERSIST_FAILED"
            else 409
            if stage == "before_transmit"
            else 502
        )
        return status, self._failed_reply(admitted.handle, admitted.aid, outcome["code"], stage)
    return 202, self._pending(cast(Record, self.store.get(admitted.sid)))


def _registry_dispatch_record(self: Coordinator, plan: Record, decision: Record | None) -> Record:
    bound = self.store.by_work(plan["work_key"])
    if (
        not bound
        or bound.get("registry_decision") != decision
        or plan["decision_record_ref"]
        != "decision."
        + bound["submission_id"]
        + ("." + bound["attribution_digest"] if bound.get("attribution_digest") else "")
    ):
        raise ContractError("PLAN_INVALID_OR_STALE", 409)
    campaign = self.registry.personal_campaign if self.registry is not None else None
    if bound.get("campaign"):
        if not campaign:
            raise ContractError("FINANCIAL_AUTH_REQUIRED", 403)
        campaign.check(bound["attempt_id"], bound["campaign"]["campaign_revision"])
    elif (
        plan["destination"].get("service") == "openai.responses.v1"
        and not cast(RuntimeRegistry, self.registry).controlled_provider_proof
    ):
        raise ContractError("FINANCIAL_AUTH_REQUIRED", 403)
    return bound
