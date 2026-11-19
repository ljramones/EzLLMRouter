"""Pinned synthetic text recipe, independent of the HTTP adapter under test."""
import hashlib
import json


class SyntheticTextRecipe:
    def __init__(self, endpoint="receiver", port=8766):
        self.endpoint, self.port = endpoint, port

    def expected(self, projected, timeout_ms):
        destination = projected["destination"]
        if destination["endpoint"] != self.endpoint:
            raise ValueError("recipe destination changed")
        work = projected["work"]
        body = {
            "model": destination["model"],
            "messages": [{"role": message["role"],
                          "content": "\n".join(block["text"] for block in message["blocks"])}
                         for message in work["messages"]],
            "max_tokens": work["generation_settings"]["max_output_tokens"],
            "temperature": 0, "tool_choice": "none", "stream": False,
        }
        raw = json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        return raw, {"method": "POST", "url": f"http://{self.endpoint}:{self.port}/v1/chat/completions",
                     "content_type": "application/json", "content_length": len(raw),
                     "body_sha256": hashlib.sha256(raw).hexdigest(), "timeout_ms": timeout_ms,
                     "processing_region": destination["processing_region"]}


class SyntheticDevelopmentRecipe:
    """Versioned tool transport beside the unchanged synthetic text recipe."""

    tool_version = "recipe.dev03.tool.v1"

    def __init__(self, endpoint="receiver", port=8766):
        self.endpoint, self.port = endpoint, port
        self.text = SyntheticTextRecipe(endpoint, port)

    def expected(self, projected, timeout_ms):
        work = projected["work"]
        if "tools" not in work["requested_features"]:
            return self.text.expected(projected, timeout_ms)
        destination = projected["destination"]
        if destination["endpoint"] != self.endpoint:
            raise ValueError("recipe destination changed")
        messages = []
        for message in work["messages"]:
            role = message["role"]
            blocks = message["blocks"]
            if role in ("system", "user"):
                messages.append({"role": role, "content": "\n".join(b["text"] for b in blocks)})
            elif role == "assistant":
                calls = [{"id": b["call_id"], "type": "function", "function": {
                    "name": b["tool_name"], "arguments": json.dumps(b["arguments"], ensure_ascii=False,
                        sort_keys=True, separators=(",", ":"))}} for b in blocks if b["kind"] == "tool_call"]
                item = {"role": "assistant", "content": "\n".join(
                    b["text"] for b in blocks if b["kind"] == "assistant_text")}
                if calls:
                    item["tool_calls"] = calls
                messages.append(item)
            else:
                for block in blocks:
                    content = block["result_text"] if "result_text" in block else json.dumps(
                        block["result_value"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    messages.append({"role": "tool", "tool_call_id": block["call_id"], "content": content})
        tools = [{"type": "function", "function": {"name": t["name"],
                  "description": t["description"], "parameters": t["input_schema"]}}
                 for t in work["tool_definitions"]]
        body = {"model": destination["model"], "messages": messages,
                "max_tokens": work["generation_settings"]["max_output_tokens"],
                "temperature": 0, "tool_choice": work["tool_choice"], "stream": False,
                "tools": tools}
        raw = json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        return raw, {"method": "POST", "url": f"http://{self.endpoint}:{self.port}/v1/chat/completions",
                     "content_type": "application/json", "content_length": len(raw),
                     "body_sha256": hashlib.sha256(raw).hexdigest(), "timeout_ms": timeout_ms,
                     "processing_region": destination["processing_region"]}
