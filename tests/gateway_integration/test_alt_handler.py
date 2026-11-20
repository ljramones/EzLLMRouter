"""Check the selected gateway refuses a preinstalled alternate LiteLLM handler."""

import asyncio
import json

import litellm
from ezllmrouter_server.gateway.adapter import LiteLLMAsgiAdapter


original = litellm.client_session
instance = object.__new__(LiteLLMAsgiAdapter)
try:
    litellm.client_session = object()
    try:
        instance.__init__()
    except RuntimeError as error:
        if not (str(error) == "alternate or pre-cached LiteLLM HTTP session"):
            raise AssertionError("fixture invariant failed") from error
        print(
            json.dumps(
                {"alternate_handler_startup": "rejected", "error_type": type(error).__name__}
            )
        )
    else:
        raise AssertionError("alternate handler accepted")
finally:
    litellm.client_session = original
    if getattr(instance, "guarded_client", None) is not None:
        asyncio.run_coroutine_threadsafe(instance.guarded_client.aclose(), instance.loop).result(
            timeout=5
        )
    if getattr(instance, "loop", None) is not None:
        instance.loop.call_soon_threadsafe(instance.loop.stop)
        instance.thread.join(timeout=5)
