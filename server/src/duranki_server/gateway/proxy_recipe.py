"""DEV-04 v4 private proxy mapping with bound SDK timeout and no-retry controls."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from .synthetic_recipe import SyntheticDevelopmentRecipe


PUBLIC_MODEL = "model.demo"
PUBLIC_MODELS = frozenset({"model.demo", "model.demo.alt"})
PROXY_MODEL = "openai/model.demo"
PUBLIC_SERVICE = "litellm.dev04"
PUBLIC_ENDPOINT = "127.0.0.1"


def public_destination(fixture: dict) -> dict:
    return {**fixture["destination"], "service": PUBLIC_SERVICE,
            "endpoint": PUBLIC_ENDPOINT, "model": PUBLIC_MODEL}


def proxy_policy(fixture: dict) -> dict:
    return {**fixture["policy"],
            "adapter_recipe_ref": "recipe.dev04.proxy.text.v4",
            "tool_adapter_recipe_ref": "recipe.dev04.proxy.tool.v4"}


def require_public_destination(destination: dict) -> None:
    if (destination.get("service") != PUBLIC_SERVICE or
        destination.get("endpoint") != PUBLIC_ENDPOINT or
        destination.get("model") not in PUBLIC_MODELS):
        raise ValueError("unregistered DEV-04 public destination")


def provider_text_input(projected):
    work = projected["work"]
    if (projected["destination"].get("service") != "openai.responses.v1" or
            set(work["requested_features"]) != {"text"} or
            work["generation_settings"]["temperature_decimal"] != "0"):
        raise ValueError("selected Responses text semantics unsupported")
    messages = []
    for item in work["messages"]:
        if item["role"] not in ("system", "user") or any(
                block.get("kind") != ("system_text" if item["role"] == "system" else "content_text")
                for block in item["blocks"]):
            raise ValueError("selected Responses text message unsupported")
        messages.append({"role": item["role"], "content": [
            {"type": "input_text", "text": "\n".join(block["text"] for block in item["blocks"])}]})
    return messages


class GatewayProxyRecipe:
    """Prepare the private proxy body from a copy of approved signed work."""

    def __init__(self, *, controlled_provider_proof=False):
        self.inner = SyntheticDevelopmentRecipe(PUBLIC_ENDPOINT, 8767)
        self.controlled_provider_proof = controlled_provider_proof

    def expected(self, projected: dict, timeout_ms: int):
        if projected["destination"].get("service") == "openai.responses.v1":
            destination = projected["destination"]
            from duranki_server.provider_adapters import validate_settings
            validate_settings("openai.responses.v1", {"origin": destination["endpoint"],
                "location": "commercial", "site": destination["processing_region"]},
                controlled=self.controlled_provider_proof)
            if type(timeout_ms) is not int or timeout_ms <= 0:
                raise ValueError("invalid signed provider timeout")
            body = {"model": "openai/" + destination["model"],
                "input": provider_text_input(projected),
                "max_output_tokens": projected["work"]["generation_settings"]["max_output_tokens"],
                "temperature": 0, "store": False, "stream": False,
                "api_base": destination["endpoint"].rstrip("/") + "/v1",
                "max_retries": 0, "timeout": timeout_ms / 1000}
            raw = json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
            return raw, {"method": "POST", "url": "http://127.0.0.1:8767/v1/responses",
                "content_type": "application/json", "content_length": len(raw),
                "body_sha256": hashlib.sha256(raw).hexdigest(), "timeout_ms": timeout_ms,
                "processing_region": destination["processing_region"]}
        require_public_destination(projected["destination"])
        private_projection = deepcopy(projected)
        private_projection["destination"]["model"] = "openai/" + projected["destination"]["model"]
        raw, controls = self.inner.expected(private_projection, timeout_ms)
        body = json.loads(raw)
        # Private SDK control; neither signed work nor the provider body includes it.
        body["max_retries"] = 0
        # Bind the selected SDK request to this signed attempt's budget.
        if type(timeout_ms) is not int or timeout_ms <= 0:
            raise ValueError("invalid signed DEV-04 timeout")
        body["timeout"] = timeout_ms / 1000
        raw = json.dumps(body, ensure_ascii=False, separators=(",", ":"),
                         allow_nan=False).encode("utf-8")
        return raw, {**controls, "content_length": len(raw),
                     "body_sha256": hashlib.sha256(raw).hexdigest()}
