"""Provider response projection shared by both trusted adapters."""

from typing import Any


def candidate_from_provider(provider: dict[str, Any], responses: bool = False) -> dict[str, Any]:
    if responses:
        if (
            type(provider) is not dict
            or provider.get("object") != "response"
            or type(provider.get("output")) is not list
        ):
            raise ValueError("invalid Responses candidate")
        text = "".join(
            part["text"]
            for item in provider["output"]
            if type(item) is dict
            and item.get("type") == "message"
            and type(item.get("content")) is list
            for part in item["content"]
            if type(part) is dict
            and part.get("type") == "output_text"
            and type(part.get("text")) is str
        )
        if not text:
            raise ValueError("Responses candidate lacks output text")
        usage = provider.get("usage")
        result: dict[str, Any] = {"text": text}
        if (
            type(provider.get("model")) is str
            and 1 <= len(provider["model"]) <= 256
            and all(32 < ord(char) < 127 for char in provider["model"])
        ):
            result["served_model"] = provider["model"]
        if type(usage) is dict:
            result["usage"] = {
                key: usage[key]
                for key in (
                    "input_tokens",
                    "output_tokens",
                    "total_tokens",
                    "input_tokens_details",
                    "output_tokens_details",
                )
                if key in usage
            }
        return result
    choice = provider["choices"][0]
    message = choice["message"]
    result = {"finish_reason": choice.get("finish_reason")}
    if isinstance(message.get("content"), str):
        result["text"] = message["content"]
    if isinstance(message.get("tool_calls"), list):
        result["tool_calls"] = [
            {
                "id": call["id"],
                "name": call["function"]["name"],
                "arguments_json": call["function"]["arguments"],
            }
            for call in message["tool_calls"]
        ]
    usage = provider.get("usage")
    if isinstance(usage, dict):
        result["usage"] = {
            "input_tokens": usage.get("prompt_tokens"),
            "output_tokens": usage.get("completion_tokens"),
        }
    return result
