"""Coordinator outcomes steps under the existing instance context."""

from __future__ import annotations

from typing import cast

from typing import TYPE_CHECKING
from .records import Record

if TYPE_CHECKING:
    from .core import Coordinator

import json
import uuid
from .canonical import (
    ContractError,
    digest,
    ident,
    strict_loads,
)
from .states import CandidateAccess, DispatchState, SubmissionState


def _failed(self: Coordinator, sid: str, aid: str, code: str, stage: str) -> Record:
    from . import core as _api

    result = self.store.update(
        sid,
        {
            "submission_state": "failed_before_transmit"
            if stage == "before_transmit"
            else "failed_after_transmit",
            "dispatch_state": "failed_before_dispatch"
            if stage == "before_transmit"
            else "response_observed",
            "candidate_access": CandidateAccess.UNAVAILABLE_DUE_FAILURE.value,
            "terminal_failure": _api.public_error(code, "query_first"),
            "updated_at": _api.now(),
            "attempt_revision": 3,
        },
    )
    campaign = self.personal_campaign
    if campaign and result.get("campaign"):
        observed = cast(Record, self.store.get(sid))
        campaign.settle(
            aid,
            observed.get("usage", {}).get("revision"),
            before_transmit=stage == "before_transmit",
        )
    return result


def _failed_reply(self: Coordinator, handle: Record, aid: str, code: str, stage: str) -> Record:
    from . import core as _api

    record = self.store.get(handle["submission_id"])
    return {
        "contract_version": "0.2",
        "state": "failed",
        "handle": handle,
        "attempt_id": aid,
        "failure_stage": stage,
        "error": record["terminal_failure"] if record else _api.public_error(code, "query_first"),
    }


def _outcome_unknown(
    self: Coordinator,
    sid: str,
    aid: str,
    plan: Record | None = None,
    decision: Record | None = None,
    response: Record | None = None,
) -> Record:
    from . import core as _api

    record = cast(Record, self.store.get(sid))
    usage = record.get("usage", {}).get("revision")
    if usage is None and type(response) is dict and type(response.get("body")) is dict:
        body = response["body"]
        raw_usage = body.get("usage")
        if type(raw_usage) is dict:
            try:
                provider = cast(Record, plan)["destination"].get("service") == "openai.responses.v1"
                pricing = (
                    {**decision, "provider_model": cast(Record, plan)["destination"]["model"]}
                    if provider and decision
                    else decision
                )
                usage = _api.usage_revision(
                    aid,
                    raw_usage,
                    decision=pricing,
                    reported_model=body.get("served_model") if provider else None,
                )
            except Exception:
                _api.log_failure("response_usage_unusable")
                usage = None
    if record["submission_state"] != "completed":
        self.store.update(
            sid,
            {
                "submission_state": SubmissionState.OUTCOME_UNKNOWN.value,
                "dispatch_state": DispatchState.OUTCOME_UNKNOWN.value,
                "candidate_access": CandidateAccess.NOT_YET_AVAILABLE.value,
                "updated_at": _api.now(),
                "attempt_revision": 3,
            },
            usage=usage if record.get("usage", {}).get("state") != "available" else None,
        )
        record = cast(Record, self.store.get(sid))
    campaign = self.personal_campaign
    if campaign and record.get("campaign"):
        campaign.settle(aid, record.get("usage", {}).get("revision"))
    return {"kind": "unknown"}


def _observe_response(
    self: Coordinator,
    sid: str,
    aid: str,
    generation: int,
    plan: Record,
    admitted_projection: Record,
    decision: Record | None,
    response: Record,
) -> Record:
    if response["status"] != 200:
        self._failed(sid, aid, "REMOTE_EXECUTION_FAILED", "after_transmit")
        return {"kind": "failed", "code": "REMOTE_EXECUTION_FAILED"}
    body = response["body"]
    tool_request = "tools" in admitted_projection["work"]["requested_features"]
    provider = plan["destination"].get("service") == "openai.responses.v1"
    provider_model = body.get("served_model") if provider and isinstance(body, dict) else None
    pricing = (
        {**decision, "provider_model": plan["destination"]["model"]}
        if provider and decision
        else decision
    )
    raw_usage_bytes, failure = self._observe_usage(
        sid, aid, body, tool_request, pricing, provider_model
    )
    if failure is not None:
        return failure
    if not isinstance(body, dict) or (
        not isinstance(body.get("text"), str)
        and not (tool_request and isinstance(body.get("tool_calls"), list))
    ):
        self._failed(sid, aid, "CANDIDATE_UNUSABLE", "after_transmit")
        return {"kind": "failed", "code": "CANDIDATE_UNUSABLE"}
    blocks, failure = self._output_blocks(sid, aid, body, tool_request, plan, admitted_projection)
    if failure is not None:
        return failure
    return self._complete_observed_candidate(
        sid,
        aid,
        generation,
        plan,
        body=body,
        blocks=cast(list[Record], blocks),
        raw_usage_bytes=raw_usage_bytes,
        provider_model=provider_model,
    )


def _observe_usage(
    self: Coordinator,
    sid: str,
    aid: str,
    body: object,
    tool_request: bool,
    pricing: Record | None,
    provider_model: object,
) -> tuple[bytes | None, Record | None]:
    from . import core as _api

    try:
        raw_usage = body.get("usage") if isinstance(body, dict) else None
        if isinstance(body, dict) and "usage" in body and (not isinstance(raw_usage, dict)):
            raise ValueError("invalid reported usage")
        raw_usage_bytes = (
            json.dumps(
                raw_usage,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            if raw_usage is not None
            else None
        )
        if raw_usage_bytes is not None and len(raw_usage_bytes) > 65536:
            raise ValueError("oversize usage")
        if isinstance(raw_usage, dict):
            observed_usage = _api.usage_revision(
                aid, raw_usage, tool_request, pricing, provider_model
            )
            self.store.update(
                sid,
                {
                    "raw_usage_digest": digest(cast(bytes, raw_usage_bytes)),
                    "updated_at": _api.now(),
                },
                usage=observed_usage,
            )
    except (TypeError, ValueError, UnicodeError, ContractError):
        self._failed(sid, aid, "CANDIDATE_UNUSABLE", "after_transmit")
        return (None, {"kind": "failed", "code": "CANDIDATE_UNUSABLE"})
    return raw_usage_bytes, None


def _output_blocks(
    self: Coordinator,
    sid: str,
    aid: str,
    body: Record,
    tool_request: bool,
    plan: Record,
    admitted_projection: Record,
) -> tuple[list[Record] | None, Record | None]:
    try:
        blocks = []
        output_classification = self._current_classification(plan["classification_snapshot"])

        def output_labels(lineage: str) -> Record:
            return {
                "lineage_ids": [lineage],
                "sensitivity": output_classification["sensitivity"],
                "restrictions": list(output_classification["combined_restrictions"]),
            }

        if isinstance(body.get("text"), str):
            blocks.append(_text_output_block(body, plan, output_classification))
        if "tool_calls" in body:
            if (
                not tool_request
                or admitted_projection["work"]["tool_choice"] == "none"
                or (not body["tool_calls"])
                or (len(body["tool_calls"]) > 2)
            ):
                raise ValueError("unusable tool calls")
            seen_calls = set()
            for index, call in enumerate(body["tool_calls"]):
                if (
                    not isinstance(call, dict)
                    or set(call) != {"id", "name", "arguments_json"}
                    or (not isinstance(call["id"], str))
                    or (not isinstance(call["arguments_json"], str))
                    or (call["name"] != "lookup")
                    or (call["id"] in seen_calls)
                ):
                    raise ValueError("unusable tool call")
                ident(call["id"])
                seen_calls.add(call["id"])
                arguments = strict_loads(call["arguments_json"].encode("utf-8"))
                if (
                    type(arguments) is not dict
                    or set(arguments) != {"key"}
                    or type(arguments["key"]) is not str
                ):
                    raise ValueError("unusable arguments")
                blocks.append(
                    {
                        "block_id": f"block.call.{index + 1}",
                        "kind": "tool_call",
                        "call_id": call["id"],
                        "tool_name": "lookup",
                        "arguments": arguments,
                        "source_labels": output_labels("src.candidate.tool"),
                    }
                )
        if not blocks or ("tool_calls" in body) != (body.get("finish_reason") == "tool_calls"):
            if "tool_calls" in body or "finish_reason" in body:
                raise ValueError("invalid finish reason")
    except (TypeError, ValueError, UnicodeError, ContractError):
        self._failed(sid, aid, "CANDIDATE_UNUSABLE", "after_transmit")
        return (None, {"kind": "failed", "code": "CANDIDATE_UNUSABLE"})
    return blocks, None


def _complete_observed_candidate(
    self: Coordinator,
    sid: str,
    aid: str,
    generation: int,
    plan: Record,
    *,
    body: Record,
    blocks: list[Record],
    raw_usage_bytes: bytes | None,
    provider_model: object,
) -> Record:
    from . import core as _api

    candidate = {
        "candidate_id": "candidate." + uuid.uuid4().hex,
        "attempt_id": aid,
        "execution_generation": generation,
        "served_destination": _api.public_served_destination(plan["destination"]),
        "output_blocks": blocks,
        "finish_reason": "tool_calls" if "tool_calls" in body else "stop",
        "structural_status": "pass",
        "observed_at": _api.now(),
        "usage": {"state": "not_recorded"},
    }
    try:
        current_retention = self._effective_retention(
            self._current_classification(plan["classification_snapshot"])
        )
        current_delivery_allowed = True
    except ContractError:
        current_retention = {"content_store_allowed": False}
        current_delivery_allowed = False
    if raw_usage_bytes is not None:
        raw_usage_digest = digest(raw_usage_bytes)
    else:
        raw_usage_digest = None
    if plan["destination"].get("service") == "openai.responses.v1":
        self.store.update(
            sid, {"provider_model_reported": provider_model, "updated_at": _api.now()}
        )
    final = self.store.complete_candidate(
        sid,
        candidate,
        None,
        raw_usage_digest,
        current_retention["content_store_allowed"],
        current_retention.get("content_expires_at"),
        _api.now(),
        [self._live_source_tag(block) for block in blocks if block["kind"] == "tool_call"]
        if current_delivery_allowed
        else [],
    )
    candidate["usage"] = final["usage"]
    campaign = self.personal_campaign
    if campaign and final.get("campaign"):
        campaign.settle(aid, final["usage"].get("revision"))
    if (
        not current_delivery_allowed
        or final["wait_expired_no_store"]
        or final["candidate_access"] == "expired"
    ):
        return {"kind": "completed_no_store"}
    return {"kind": "candidate", "candidate": candidate}


def _text_output_block(body: Record, plan: Record, output_classification: Record) -> Record:
    output = body["text"]
    output_bytes = output.encode("utf-8", "strict")
    if (
        not output_bytes
        or len(output_bytes) > 65536
        or any((55296 <= ord(c) <= 57343 for c in output))
    ):
        raise ValueError("unusable output text")
    lineage = (
        "src.candidate.provider"
        if plan["destination"].get("service") == "openai.responses.v1"
        else "src.candidate.synthetic"
    )
    return {
        "block_id": "block.output.1",
        "kind": "assistant_text",
        "text": output,
        "source_labels": _labels(output_classification, lineage),
    }


def _labels(output_classification: Record, lineage: str) -> Record:
    return {
        "lineage_ids": [lineage],
        "sensitivity": output_classification["sensitivity"],
        "restrictions": list(output_classification["combined_restrictions"]),
    }
