"""Frozen worker check: reject an alternate handler before a vendor request."""

import json
import litellm
from tools.gateway.asgi_adapter import LiteLLMAsgiAdapter

original = litellm.client_session
try:
    litellm.client_session = object()
    try:
        instance = LiteLLMAsgiAdapter(
            provider_key="sk-" + "synthetic-alt-handler-credential-000000"
        )
    except RuntimeError as error:
        if str(error) != "alternate or pre-cached LiteLLM HTTP session":
            raise AssertionError("fixture invariant failed") from error
        print(
            json.dumps(
                {"alternate_handler_startup": "rejected", "error_type": type(error).__name__}
            )
        )
    else:
        instance.close()
        raise AssertionError("alternate handler accepted")
finally:
    litellm.client_session = original
