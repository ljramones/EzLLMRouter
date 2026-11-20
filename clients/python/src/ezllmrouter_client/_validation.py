"""Enabled wire-0.2 response checks, independent of the server package."""

from __future__ import annotations

from datetime import datetime
import re

VERSION = "0.2"
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}\Z")
UTC = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")
FEATURES = {
    "text",
    "tools",
    "document_text",
    "background",
    "nested",
    "streaming",
    "realtime_voice",
    "binary_multimodal",
    "responses_web_search",
    "provider_managed_state",
}
ERROR_CODES = {
    "UNSUPPORTED_VERSION",
    "AUTHENTICATION_FAILED",
    "MALFORMED_JSON",
    "SCHEMA_INVALID",
    "LIMIT_EXCEEDED",
    "SEMANTIC_INVALID",
    "SOURCE_INVALID",
    "POLICY_DENIED",
    "FINANCIAL_AUTH_REQUIRED",
    "CAPABILITY_UNSUPPORTED",
    "NOT_FOUND_OR_FORBIDDEN",
    "WORK_CONFLICT",
    "EVENT_CONFLICT",
    "STALE_REVISION",
    "PLAN_INVALID_OR_STALE",
    "FDC_REJECTED",
    "INTENT_PERSIST_FAILED",
    "INTERNAL_UNAVAILABLE",
    "REMOTE_EXECUTION_FAILED",
    "CANDIDATE_UNUSABLE",
}
SELECTOR = ("task_id", "step_id", "step_revision", "execution_generation")
WORK_KEY = ("principal_id",) + SELECTOR


def shape(value, required, optional=()):
    return (
        type(value) is dict
        and set(required) <= value.keys()
        and value.keys() <= set(required) | set(optional)
    )


def identifier(value):
    return type(value) is str and ID.fullmatch(value) is not None


def positive(value):
    return type(value) is int and 0 < value <= 9007199254740991


def nonnegative(value):
    return type(value) is int and 0 <= value <= 9007199254740991


def utc(value):
    if type(value) is not str or UTC.fullmatch(value) is None:
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
        return True
    except ValueError:
        return False


def selector(value):
    return (
        shape(value, SELECTOR)
        and identifier(value["task_id"])
        and identifier(value["step_id"])
        and positive(value["step_revision"])
        and identifier(value["execution_generation"])
    )


def handle(value):
    return (
        shape(value, ("submission_id", "work_key"))
        and identifier(value["submission_id"])
        and shape(value["work_key"], WORK_KEY)
        and identifier(value["work_key"]["principal_id"])
        and selector({k: value["work_key"][k] for k in SELECTOR})
    )


def error(value):
    return (
        shape(value, ("code", "correlation_id", "retry_guidance"), ("safe_message",))
        and value["code"] in ERROR_CODES
        and identifier(value["correlation_id"])
        and value["retry_guidance"] in ("never", "query_first", "orchestrator_decision")
        and ("safe_message" not in value or type(value["safe_message"]) is str)
    )


def knowledge(value):
    if type(value) is not dict:
        return False
    if value.get("state") == "known":
        return shape(value, ("state", "count")) and nonnegative(value["count"])
    return value.get("state") in ("unknown", "not_applicable") and shape(value, ("state",))


def labels(value):
    return (
        shape(value, ("lineage_ids", "sensitivity", "restrictions"))
        and type(value["lineage_ids"]) is list
        and bool(value["lineage_ids"])
        and all(map(identifier, value["lineage_ids"]))
        and len(set(value["lineage_ids"])) == len(value["lineage_ids"])
        and value["sensitivity"] in ("public", "internal", "confidential", "restricted")
        and type(value["restrictions"]) is list
        and all(map(identifier, value["restrictions"]))
        and len(set(value["restrictions"])) == len(value["restrictions"])
    )


def output_block(value):
    if (
        type(value) is not dict
        or not identifier(value.get("block_id"))
        or not labels(value.get("source_labels"))
    ):
        return False
    if value.get("kind") == "assistant_text":
        return (
            shape(value, ("block_id", "kind", "text", "source_labels"))
            and type(value["text"]) is str
        )
    if value.get("kind") == "tool_call":
        return (
            shape(value, ("block_id", "kind", "call_id", "tool_name", "arguments", "source_labels"))
            and identifier(value["call_id"])
            and value["tool_name"] == "lookup"
            and type(value["arguments"]) is dict
            and set(value["arguments"]) == {"key"}
            and type(value["arguments"]["key"]) is str
        )
    return False


def destination(value):
    required = (
        "configuration_ref",
        "service",
        "endpoint",
        "model",
        "model_version",
        "processing_region",
    )
    return shape(value, required, ("pool", "quantization")) and all(map(identifier, value.values()))


def cost(value):
    if (
        type(value) is not dict
        or type(value.get("currency")) is not str
        or re.fullmatch(r"[A-Z]{3}", value["currency"]) is None
    ):
        return False
    money = (
        lambda x: type(x) is str and re.fullmatch(r"(0|[1-9][0-9]*)(\.[0-9]{1,9})?", x) is not None
    )
    state = value.get("status")
    if state == "unknown":
        return shape(value, ("status", "currency"))
    if state in ("reported", "calculated", "reconciled"):
        return (
            shape(value, ("status", "currency", "amount_decimal", "source_ref"), ("zero_basis",))
            and money(value["amount_decimal"])
            and identifier(value["source_ref"])
            and (
                value["amount_decimal"] != "0"
                or value.get("zero_basis")
                in ("provider_reported_free", "contract_free", "cache_hit", "invoice_reconciled")
            )
        )
    if state == "estimated":
        return (
            shape(
                value,
                (
                    "status",
                    "currency",
                    "amount_decimal",
                    "method_ref",
                    "lower_bound_decimal",
                    "upper_bound_decimal",
                ),
            )
            and all(
                money(value[k])
                for k in ("amount_decimal", "lower_bound_decimal", "upper_bound_decimal")
            )
            and identifier(value["method_ref"])
        )
    return False


def usage(value):
    if type(value) is not dict:
        return False
    if value.get("state") == "not_recorded":
        return shape(value, ("state",))
    if not shape(value, ("state", "revision")) or value["state"] != "available":
        return False
    r = value["revision"]
    if not shape(
        r,
        (
            "attempt_id",
            "revision",
            "usage_observation",
            "normalized_usage",
            "usage_semantics_version",
            "price_version",
            "cost",
            "recorded_at",
        ),
        ("previous_revision", "usage_estimate_method_ref", "processing_region"),
    ):
        return False
    if (
        not identifier(r["attempt_id"])
        or not positive(r["revision"])
        or r["usage_observation"]
        not in ("unknown", "partial", "reported", "estimated", "reconciled")
        or not identifier(r["usage_semantics_version"])
        or not identifier(r["price_version"])
        or not utc(r["recorded_at"])
    ):
        return False
    if "previous_revision" in r and (
        not positive(r["previous_revision"]) or r["previous_revision"] >= r["revision"]
    ):
        return False
    if any(
        k in r and not identifier(r[k]) for k in ("usage_estimate_method_ref", "processing_region")
    ):
        return False
    n = r["normalized_usage"]
    categories = (
        "input_uncached",
        "input_cache_read",
        "input_cache_write",
        "output_text",
        "output_reasoning",
    )
    return (
        shape(n, categories + ("other_billable",))
        and all(knowledge(n[k]) for k in categories)
        and type(n["other_billable"]) is list
        and all(
            shape(x, ("component", "unit", "knowledge"))
            and identifier(x["component"])
            and identifier(x["unit"])
            and knowledge(x["knowledge"])
            for x in n["other_billable"]
        )
        and cost(r["cost"])
    )


def candidate(value):
    required = (
        "candidate_id",
        "attempt_id",
        "execution_generation",
        "served_destination",
        "output_blocks",
        "finish_reason",
        "structural_status",
        "observed_at",
        "usage",
    )
    if not shape(value, required, ("provider_request_id", "structural_code")):
        return False
    return (
        all(identifier(value[k]) for k in ("candidate_id", "attempt_id", "execution_generation"))
        and destination(value["served_destination"])
        and type(value["output_blocks"]) is list
        and bool(value["output_blocks"])
        and all(output_block(x) for x in value["output_blocks"])
        and len({x["block_id"] for x in value["output_blocks"]}) == len(value["output_blocks"])
        and len({x["call_id"] for x in value["output_blocks"] if x["kind"] == "tool_call"})
        == sum(x["kind"] == "tool_call" for x in value["output_blocks"])
        and (
            value["finish_reason"] != "tool_calls"
            or any(x["kind"] == "tool_call" for x in value["output_blocks"])
        )
        and value["finish_reason"] in ("stop", "tool_calls", "length", "provider_other")
        and value["structural_status"] in ("pass", "fail", "not_checked")
        and utc(value["observed_at"])
        and usage(value["usage"])
    )


def attempt(value):
    required = (
        "attempt_id",
        "execution_generation",
        "attempt_revision",
        "dispatch_state",
        "delivery_state",
        "cancel_state",
        "settlement_state",
        "generation_state",
        "usage",
    )
    return (
        shape(value, required, ("provider_request_id", "cancel_evidence_ref"))
        and identifier(value["attempt_id"])
        and identifier(value["execution_generation"])
        and positive(value["attempt_revision"])
        and value["dispatch_state"]
        in (
            "prepared",
            "intent_persisted",
            "transmitted",
            "response_observed",
            "outcome_unknown",
            "rejected",
            "failed_before_dispatch",
        )
        and value["delivery_state"] in ("none", "candidate_delivered")
        and value["cancel_state"] in ("none", "requested", "confirmed", "unresolved")
        and value["settlement_state"] in ("unsettled", "provisional", "final")
        and value["generation_state"] in ("current", "superseded")
        and usage(value["usage"])
        and (value["cancel_state"] != "confirmed" or identifier(value.get("cancel_evidence_ref")))
    )


def usage_matches(a, b):
    return a["state"] == b["state"] and (
        a["state"] != "available"
        or (
            a["revision"]["attempt_id"] == b["revision"]["attempt_id"]
            and a["revision"]["revision"] == b["revision"]["revision"]
        )
    )


def reply(value, status):
    if type(value) is not dict or value.get("contract_version") != VERSION:
        return False
    state = value.get("state")
    if state == "delivered":
        return (
            status == 200
            and shape(value, ("contract_version", "state", "handle", "candidate"))
            and handle(value["handle"])
            and candidate(value["candidate"])
            and value["candidate"]["execution_generation"]
            == value["handle"]["work_key"]["execution_generation"]
            and (
                value["candidate"]["usage"]["state"] != "available"
                or value["candidate"]["usage"]["revision"]["attempt_id"]
                == value["candidate"]["attempt_id"]
            )
        )
    if state == "pending":
        return (
            status == 202
            and shape(value, ("contract_version", "state", "handle", "pending_result_policy"))
            and handle(value["handle"])
            and value["pending_result_policy"] in ("pollable_if_retained", "metadata_only_no_store")
        )
    if state == "failed":
        return (
            status >= 400
            and shape(
                value,
                ("contract_version", "state", "handle", "error", "attempt_id", "failure_stage"),
            )
            and handle(value["handle"])
            and error(value["error"])
            and identifier(value["attempt_id"])
            and value["failure_stage"] in ("before_transmit", "after_transmit")
        )
    if state == "rejected":
        return (
            status >= 400
            and shape(value, ("contract_version", "state", "selector", "error"))
            and selector(value["selector"])
            and error(value["error"])
        )
    return False


def status_snapshot(value, status):
    required = (
        "contract_version",
        "handle",
        "status_revision",
        "submission_state",
        "attempts",
        "candidate_access",
        "updated_at",
    )
    if (
        status != 200
        or not shape(
            value,
            required,
            ("candidate", "terminal_failure", "terminal_attempt_id", "result_unavailable_reason"),
        )
        or value["contract_version"] != VERSION
        or not handle(value["handle"])
        or not positive(value["status_revision"])
        or value["submission_state"]
        not in (
            "received",
            "admitted",
            "no_route",
            "completed",
            "outcome_unknown",
            "failed_before_transmit",
            "failed_after_transmit",
        )
        or type(value["attempts"]) is not list
        or not all(attempt(a) for a in value["attempts"])
        or value["candidate_access"]
        not in (
            "present",
            "not_retained",
            "expired",
            "not_yet_available",
            "unavailable_due_failure",
        )
        or not utc(value["updated_at"])
    ):
        return False
    attempts = value["attempts"]
    if len({a["attempt_id"] for a in attempts}) != len(attempts) or any(
        a["execution_generation"] != value["handle"]["work_key"]["execution_generation"]
        or (
            a["usage"]["state"] == "available"
            and a["usage"]["revision"]["attempt_id"] != a["attempt_id"]
        )
        for a in attempts
    ):
        return False
    if value["candidate_access"] == "present":
        if (
            not candidate(value.get("candidate"))
            or value["candidate"]["execution_generation"]
            != value["handle"]["work_key"]["execution_generation"]
            or not any(
                a["attempt_id"] == value["candidate"]["attempt_id"]
                and usage_matches(a["usage"], value["candidate"]["usage"])
                for a in attempts
            )
        ):
            return False
    elif "candidate" in value:
        return False
    if "result_unavailable_reason" in value and not (
        value["result_unavailable_reason"] == "wait_expired_no_store"
        and value["submission_state"] == "completed"
        and value["candidate_access"] == "not_retained"
    ):
        return False
    if value["submission_state"] in ("failed_before_transmit", "failed_after_transmit"):
        return (
            error(value.get("terminal_failure"))
            and identifier(value.get("terminal_attempt_id"))
            and any(a["attempt_id"] == value["terminal_attempt_id"] for a in attempts)
        )
    return "terminal_failure" not in value and "terminal_attempt_id" not in value


def capabilities(value, status):
    if (
        status != 200
        or not shape(
            value, ("contract_version", "profile", "supported_features", "disabled_features")
        )
        or value["contract_version"] != VERSION
        or value["profile"] != "initial_1a@1"
    ):
        return False
    supported, disabled = value["supported_features"], value["disabled_features"]
    return all(
        type(x) is list
        and all(type(f) is str and f in FEATURES for f in x)
        and len(set(x)) == len(x)
        for x in (supported, disabled)
    ) and not set(supported) & set(disabled)


def correspondence(value, selected, kind):
    if kind == "capabilities" or "error" in value and "state" not in value:
        return True
    if kind == "submit" and value.get("state") == "rejected":
        return selector(value.get("selector")) and all(
            value["selector"][k] == selected[k] for k in SELECTOR
        )
    if "handle" not in value:
        return True
    h = value["handle"]
    if not handle(h):
        return False
    if "submission_id" in selected:
        return h["submission_id"] == selected["submission_id"]
    return all(h["work_key"][k] == selected[k] for k in SELECTOR)
