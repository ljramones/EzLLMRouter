"""Restricted ezllmrouter-work-v0.2 canonicalization for the development slice."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from .gateway.choice_b_wire import MAX_ATTEMPT_TIMEOUT_MS
from .identifiers import valid_identifier

PREFIX = b"ezllmrouter-work-v0.2\n"
SAFE = 9007199254740991
MAX_OUTPUT_TOKENS = 32768
_DECIMAL = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")


class ContractError(ValueError):
    def __init__(self, code: str, status: int = 422):
        super().__init__(code)
        self.code, self.status = code, status


def strict_loads(data: bytes):
    if len(data) > 65536:
        raise ContractError("LIMIT_EXCEEDED", 413)
    try:
        text = data.decode("utf-8", "strict")

        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError("duplicate key")
                result[key] = value
            return result

        def integer(value):
            if value == "-0" or abs(int(value)) > SAFE:
                raise ValueError("unsafe integer")
            return int(value)

        def reject(_value):
            raise ValueError("unsupported JSON number")

        obj = json.loads(
            text,
            object_pairs_hook=pairs,
            parse_int=integer,
            parse_float=reject,
            parse_constant=reject,
        )
        restricted(obj)
        return obj
    except (UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, ContractError):
            raise
        raise ContractError("MALFORMED_JSON", 400) from exc


def restricted(value, depth=0):
    if depth > 16:
        raise ContractError("LIMIT_EXCEEDED", 413)
    if isinstance(value, str):
        if any(0xD800 <= ord(c) <= 0xDFFF for c in value):
            raise ContractError("MALFORMED_JSON", 400)
    elif type(value) is int:
        if abs(value) > SAFE:
            raise ContractError("MALFORMED_JSON", 400)
    elif type(value) is bool:
        pass
    elif isinstance(value, list):
        for item in value:
            restricted(item, depth + 1)
    elif isinstance(value, dict):
        if len(value) > 1024:
            raise ContractError("LIMIT_EXCEEDED", 413)
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractError("MALFORMED_JSON", 400)
            restricted(key, depth + 1)
            restricted(item, depth + 1)
    else:
        raise ContractError("MALFORMED_JSON", 400)


def jcs(value) -> bytes:
    """The contract's UTF-16-sorted, safe-integer, no-null JCS profile."""
    restricted(value)

    def emit(obj):
        if isinstance(obj, str):
            return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        if type(obj) is bool:
            return "true" if obj else "false"
        if type(obj) is int:
            return str(obj)
        if isinstance(obj, list):
            return "[" + ",".join(emit(v) for v in obj) + "]"
        if isinstance(obj, dict):
            keys = sorted(obj, key=lambda k: k.encode("utf-16-be"))
            return "{" + ",".join(emit(k) + ":" + emit(obj[k]) for k in keys) + "}"
        raise ContractError("MALFORMED_JSON", 400)

    return emit(value).encode("utf-8")


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def decimal_lexical(value: str) -> str:
    if not isinstance(value, str) or not _DECIMAL.fullmatch(value):
        raise ContractError("SCHEMA_INVALID", 400)
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ContractError("SCHEMA_INVALID", 400) from exc
    if not number.is_finite() or number < 0:
        raise ContractError("SCHEMA_INVALID", 400)
    return value.rstrip("0").rstrip(".") if "." in value else value


def utc_second(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})", value
    ):
        raise ContractError("SCHEMA_INVALID", 400)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            raise ValueError("naive")
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ContractError("SCHEMA_INVALID", 400) from exc


def ident(value):
    if not valid_identifier(value):
        raise ContractError("SCHEMA_INVALID", 400)
    return value


def exact_keys(obj, required, optional=()):
    if (
        not isinstance(obj, dict)
        or not set(required) <= set(obj)
        or set(obj) - set(required) - set(optional)
    ):
        raise ContractError("SCHEMA_INVALID", 400)


def _labels(labels):
    exact_keys(labels, ("lineage_ids", "sensitivity", "restrictions"))
    if labels["sensitivity"] not in ("public", "internal", "confidential", "restricted"):
        raise ContractError("SCHEMA_INVALID", 400)
    result = dict(labels)
    for key in ("lineage_ids", "restrictions"):
        values = labels[key]
        if (
            not isinstance(values, list)
            or (key == "lineage_ids" and not values)
            or not all(isinstance(v, str) for v in values)
        ):
            raise ContractError("SCHEMA_INVALID", 400)
        if len(values) != len(set(values)):
            raise ContractError("SCHEMA_INVALID", 400)
        result[key] = sorted((ident(v) for v in values), key=lambda x: x.encode("utf-16-be"))
    return result


def _tool_schema_shape(value, depth=0):
    if depth > 16:
        raise ContractError("LIMIT_EXCEEDED", 413)
    exact_keys(
        value,
        ("type",),
        (
            "properties",
            "required",
            "items",
            "enum",
            "minLength",
            "maxLength",
            "pattern",
            "minimum",
            "maximum",
        ),
    )
    if value["type"] not in ("object", "array", "string", "integer", "boolean"):
        raise ContractError("SCHEMA_INVALID", 400)
    if "properties" in value:
        if not isinstance(value["properties"], dict):
            raise ContractError("SCHEMA_INVALID", 400)
        for key, child in value["properties"].items():
            if not isinstance(key, str):
                raise ContractError("SCHEMA_INVALID", 400)
            _tool_schema_shape(child, depth + 1)
    if "items" in value:
        _tool_schema_shape(value["items"], depth + 1)
    if "required" in value:
        names = value["required"]
        if (
            not isinstance(names, list)
            or not all(isinstance(x, str) for x in names)
            or len(names) != len(set(names))
        ):
            raise ContractError("SCHEMA_INVALID", 400)
    if "enum" in value and (not isinstance(value["enum"], list) or not value["enum"]):
        raise ContractError("SCHEMA_INVALID", 400)
    for key in ("minLength", "maxLength"):
        if key in value and (type(value[key]) is not int or not 0 <= value[key] <= SAFE):
            raise ContractError("SCHEMA_INVALID", 400)
    for key in ("minimum", "maximum"):
        if key in value and (type(value[key]) is not int or abs(value[key]) > SAFE):
            raise ContractError("SCHEMA_INVALID", 400)
    if "pattern" in value and not isinstance(value["pattern"], str):
        raise ContractError("SCHEMA_INVALID", 400)


def validate_text_request(req, trusted, config, prompt_blocks, allowed_lineages):
    """Resolve trusted prompt and the pinned, caller-owned lookup subset."""
    restricted(req)
    required = (
        "contract_version",
        "profile",
        "task_id",
        "task_class",
        "step_class",
        "step_id",
        "step_revision",
        "execution_generation",
        "purpose",
        "requested_configuration_ref",
        "requested_features",
        "resolved_prompt",
        "messages",
        "generation_settings",
        "deadline",
    )
    optional = (
        "claimed_principal_id",
        "claimed_charging_owner_id",
        "subtask_id",
        "session_id",
        "parent_call",
        "construction_manifest_ref",
        "tool_definitions",
        "tool_choice",
        "trace_context",
        "observed_at",
    )
    exact_keys(req, required, optional)
    if req["contract_version"] != "0.2" or req["profile"] != "initial_1a@1":
        raise ContractError("UNSUPPORTED_VERSION", 426)
    for key in (
        "task_id",
        "task_class",
        "step_id",
        "execution_generation",
        "requested_configuration_ref",
    ):
        ident(req[key])
    for key in (
        "claimed_principal_id",
        "claimed_charging_owner_id",
        "subtask_id",
        "session_id",
        "parent_call",
        "construction_manifest_ref",
    ):
        if key in req:
            ident(req[key])
    if "observed_at" in req:
        utc_second(req["observed_at"])
    if "trace_context" in req and (
        not isinstance(req["trace_context"], dict)
        or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in req["trace_context"].items()
        )
    ):
        raise ContractError("SCHEMA_INVALID", 400)
    if "tool_definitions" in req and (
        not isinstance(req["tool_definitions"], list) or len(req["tool_definitions"]) > 32
    ):
        raise ContractError("SCHEMA_INVALID", 400)
    for tool in req.get("tool_definitions", []):
        exact_keys(tool, ("name", "description", "input_schema"))
        ident(tool["name"])
        if not isinstance(tool["description"], str):
            raise ContractError("SCHEMA_INVALID", 400)
        _tool_schema_shape(tool["input_schema"])
    definitions = req.get("tool_definitions", [])
    lookup_schema = {
        "type": "object",
        "properties": {"key": {"type": "string"}},
        "required": ["key"],
    }
    if definitions and definitions != [
        {"name": "lookup", "description": "Synthetic lookup", "input_schema": lookup_schema}
    ]:
        raise ContractError("CAPABILITY_UNSUPPORTED", 422)
    if "tool_choice" in req and req["tool_choice"] not in ("none", "auto", "required"):
        raise ContractError("SCHEMA_INVALID", 400)
    if (
        type(req["step_revision"]) is not int
        or not 1 <= req["step_revision"] <= SAFE
        or req["step_class"] not in ("generic", "leaf", "spine")
    ):
        raise ContractError("SCHEMA_INVALID", 400)
    if req["step_class"] == "leaf" and "construction_manifest_ref" not in req:
        raise ContractError("SCHEMA_INVALID", 400)
    if (
        req["task_id"] != trusted["task_id"]
        or req["requested_configuration_ref"] != config["configuration_ref"]
    ):
        raise ContractError("POLICY_DENIED", 403)
    if (
        req.get("claimed_principal_id", trusted["principal_id"]) != trusted["principal_id"]
        or req.get("claimed_charging_owner_id", trusted["charging_owner_id"])
        != trusted["charging_owner_id"]
    ):
        raise ContractError("POLICY_DENIED", 403)
    if req["purpose"] not in (
        "execution",
        "feature_extraction",
        "verification",
        "judging",
        "evaluation",
        "replay",
    ):
        raise ContractError("SCHEMA_INVALID", 400)
    if req["purpose"] != "execution" or any(
        k in req for k in ("parent_call", "subtask_id", "session_id", "construction_manifest_ref")
    ):
        raise ContractError("CAPABILITY_UNSUPPORTED", 422)
    choice = req.get("tool_choice", "none")
    if choice == "required":
        raise ContractError("CAPABILITY_UNSUPPORTED", 422)
    features = req["requested_features"]
    if (
        not isinstance(features, list)
        or not all(isinstance(x, str) for x in features)
        or len(features) != len(set(features))
    ):
        raise ContractError("SCHEMA_INVALID", 400)
    recognized = {
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
    if not features or not set(features) <= recognized:
        raise ContractError("SCHEMA_INVALID", 400)
    if "text" not in features:
        raise ContractError("SEMANTIC_INVALID", 422)
    if not set(features) <= {"text", "tools"}:
        raise ContractError("CAPABILITY_UNSUPPORTED", 422)
    settings = req["generation_settings"]
    exact_keys(settings, ("max_output_tokens", "temperature_decimal", "total_timeout_ms"))
    if (
        type(settings["max_output_tokens"]) is not int
        or type(settings["total_timeout_ms"]) is not int
        or min(settings["max_output_tokens"], settings["total_timeout_ms"]) < 1
    ):
        raise ContractError("SCHEMA_INVALID", 400)
    if (
        settings["total_timeout_ms"] > MAX_ATTEMPT_TIMEOUT_MS
        or settings["max_output_tokens"] > MAX_OUTPUT_TOKENS
    ):
        raise ContractError("LIMIT_EXCEEDED", 422)
    settings = {**settings, "temperature_decimal": decimal_lexical(settings["temperature_decimal"])}
    if settings["temperature_decimal"] != "0":
        raise ContractError("CAPABILITY_UNSUPPORTED", 422)
    deadline = utc_second(req["deadline"])
    if datetime.fromisoformat(deadline.replace("Z", "+00:00")) <= datetime.now(timezone.utc):
        raise ContractError("SEMANTIC_INVALID", 422)
    prompt = req["resolved_prompt"]
    exact_keys(prompt, ("prompt_id", "prompt_version", "block_ids", "source_artifact_digest"))
    for k in ("prompt_id", "prompt_version"):
        ident(prompt[k])
    if (
        prompt["prompt_id"] != trusted["prompt_id"]
        or prompt["prompt_version"] != trusted["prompt_version"]
    ):
        raise ContractError("SOURCE_INVALID", 422)
    if prompt["block_ids"] != [b["block_id"] for b in prompt_blocks] or prompt[
        "source_artifact_digest"
    ] != digest(jcs(prompt_blocks)):
        raise ContractError("SOURCE_INVALID", 422)
    messages = req["messages"]
    if not isinstance(messages, list) or not 1 <= len(messages) <= 128:
        raise ContractError("SCHEMA_INVALID", 400)
    resolved, ids, calls, results = [], set(), {}, set()
    tool_content = False
    for index, message in enumerate(messages):
        exact_keys(message, ("role", "blocks"))
        role, blocks = message["role"], message["blocks"]
        if (
            role not in ("system", "user", "assistant", "tool")
            or not isinstance(blocks, list)
            or not blocks
        ):
            raise ContractError("CAPABILITY_UNSUPPORTED", 422)
        if index == 0 and role != "system":
            raise ContractError("SOURCE_INVALID", 422)
        out = []
        for block in blocks:
            if not isinstance(block, dict):
                raise ContractError("SCHEMA_INVALID", 400)
            kind = block.get("kind")
            if role in ("system", "user"):
                exact_keys(block, ("block_id", "kind", "text", "source_labels"))
                if kind != (
                    "system_text" if role == "system" else "content_text"
                ) or not isinstance(block["text"], str):
                    raise ContractError("CAPABILITY_UNSUPPORTED", 422)
            elif role == "assistant":
                if kind == "tool_call":
                    exact_keys(
                        block,
                        ("block_id", "kind", "call_id", "tool_name", "arguments", "source_labels"),
                    )
                    if (
                        block["tool_name"] != "lookup"
                        or type(block["arguments"]) is not dict
                        or set(block["arguments"]) != {"key"}
                        or type(block["arguments"]["key"]) is not str
                    ):
                        raise ContractError("SEMANTIC_INVALID", 422)
                    call_id = ident(block["call_id"])
                    if call_id in calls:
                        raise ContractError("SEMANTIC_INVALID", 422)
                    calls[call_id] = block
                    tool_content = True
                elif kind == "assistant_text":
                    exact_keys(block, ("block_id", "kind", "text", "source_labels"))
                    if not isinstance(block["text"], str):
                        raise ContractError("SCHEMA_INVALID", 400)
                else:
                    raise ContractError("CAPABILITY_UNSUPPORTED", 422)
            elif role == "tool":
                exact_keys(
                    block,
                    ("block_id", "kind", "call_id", "source_labels"),
                    ("result_text", "result_value"),
                )
                if kind != "tool_result" or ("result_text" in block) == ("result_value" in block):
                    raise ContractError("SCHEMA_INVALID", 400)
                call_id = ident(block["call_id"])
                if call_id not in calls or call_id in results:
                    raise ContractError("SEMANTIC_INVALID", 422)
                results.add(call_id)
                if "result_text" in block and type(block["result_text"]) is not str:
                    raise ContractError("SCHEMA_INVALID", 400)
                if "result_value" in block and type(block["result_value"]) is not dict:
                    raise ContractError("SCHEMA_INVALID", 400)
                tool_content = True
            bid = ident(block["block_id"])
            if bid in ids:
                raise ContractError("SEMANTIC_INVALID", 422)
            ids.add(bid)
            labels = _labels(block["source_labels"])
            if not set(labels["lineage_ids"]) <= set(allowed_lineages):
                raise ContractError("SOURCE_INVALID", 422)
            out.append({**block, "source_labels": labels})
        resolved.append({"role": role, "blocks": out})
    if [b for m in resolved if m["role"] == "system" for b in m["blocks"]] != prompt_blocks:
        raise ContractError("SOURCE_INVALID", 422)
    if len(ids) > 256:
        raise ContractError("LIMIT_EXCEEDED", 413)
    if set(calls) != results:
        raise ContractError("SEMANTIC_INVALID", 422)
    if tool_content and not definitions:
        raise ContractError("SEMANTIC_INVALID", 422)
    derived_tools = bool(definitions or tool_content or choice != "none")
    if derived_tools != ("tools" in features):
        raise ContractError("SEMANTIC_INVALID", 422)
    if choice == "auto" and not definitions:
        raise ContractError("SEMANTIC_INVALID", 422)
    return resolved, settings, deadline, digest(jcs(prompt_blocks))


def projection(req, trusted, config, messages, settings, deadline, prompt_digest):
    prompt = req["resolved_prompt"]
    work = {
        "task_id": req["task_id"],
        "task_class": req["task_class"],
        "step_class": req["step_class"],
        "step_id": req["step_id"],
        "step_revision": req["step_revision"],
        "execution_generation": req["execution_generation"],
        "purpose": req["purpose"],
        "destination_config_id": req["requested_configuration_ref"],
        "requested_features": sorted(
            req["requested_features"], key=lambda x: x.encode("utf-16-be")
        ),
        "resolved_prompt": {
            "prompt_id": prompt["prompt_id"],
            "prompt_version": prompt["prompt_version"],
            "block_ids": prompt["block_ids"],
            "resolved_digest": prompt_digest,
        },
        "messages": messages,
        "tool_definitions": req.get("tool_definitions", []),
        "tool_choice": req.get("tool_choice", "none"),
        "generation_settings": settings,
        "deadline": deadline,
    }
    return {
        "projection_version": "ezllmrouter-work-v0.2",
        "trusted": {
            k: trusted[k]
            for k in ("principal_id", "charging_owner_id", "source_authority_id", "context_id")
        },
        "work": work,
        "destination": config,
    }


def work_digest(value):
    return digest(PREFIX + jcs(value))
