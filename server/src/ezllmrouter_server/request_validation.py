"""Wire-0.2 request validation; the public canonical entry point delegates here."""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime, timezone
from .records import Record
from .canonical import (
    ContractError,
    restricted,
    exact_keys,
    ident,
    utc_second,
    _tool_schema_shape,
    SAFE,
    MAX_ATTEMPT_TIMEOUT_MS,
    MAX_OUTPUT_TOKENS,
    decimal_lexical,
    digest,
    jcs,
    _labels,
)


def validate_text_request(
    req: object,
    trusted: Record,
    config: Record,
    prompt_blocks: list[Record],
    allowed_lineages: Collection[str],
) -> tuple[list[Record], Record, str, str]:
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
    req = exact_keys(req, required, optional)
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
            (isinstance(k, str) and isinstance(v, str) for k, v in req["trace_context"].items())
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
        (k in req for k in ("parent_call", "subtask_id", "session_id", "construction_manifest_ref"))
    ):
        raise ContractError("CAPABILITY_UNSUPPORTED", 422)
    choice = req.get("tool_choice", "none")
    if choice == "required":
        raise ContractError("CAPABILITY_UNSUPPORTED", 422)
    features = req["requested_features"]
    if (
        not isinstance(features, list)
        or not all((isinstance(x, str) for x in features))
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
    settings = exact_keys(
        settings, ("max_output_tokens", "temperature_decimal", "total_timeout_ms")
    )
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
    prompt = exact_keys(
        prompt, ("prompt_id", "prompt_version", "block_ids", "source_artifact_digest")
    )
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
    resolved, ids, calls, results = ([], set(), {}, set())
    tool_content = False
    for index, message in enumerate(messages):
        exact_keys(message, ("role", "blocks"))
        role, blocks = (message["role"], message["blocks"])
        if (
            role not in ("system", "user", "assistant", "tool")
            or not isinstance(blocks, list)
            or (not blocks)
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
                        or (type(block["arguments"]["key"]) is not str)
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
    if tool_content and (not definitions):
        raise ContractError("SEMANTIC_INVALID", 422)
    derived_tools = bool(definitions or tool_content or choice != "none")
    if derived_tools != ("tools" in features):
        raise ContractError("SEMANTIC_INVALID", 422)
    if choice == "auto" and (not definitions):
        raise ContractError("SEMANTIC_INVALID", 422)
    return (resolved, settings, deadline, digest(jcs(prompt_blocks)))
