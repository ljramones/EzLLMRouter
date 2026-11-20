"""Private in-process ASGI bridge into the actual LiteLLM proxy route."""

from __future__ import annotations

from concurrent.futures import Future
import hashlib
import json
from pathlib import Path

import httpx

from ezllmrouter_server.runtime_resources import LoopThread
from ezllmrouter_server.canonical import ContractError
from .provider_reply import candidate_from_provider
from .guard import ACTIVE, GuardRejected, GuardTransport, Invocation, PROVIDER_URL
from ezllmrouter_server.observability import log_failure
from .proxy_recipe import PROXY_MODEL, require_public_destination


PROXY_URL = "http://127.0.0.1:8767/v1/chat/completions"


class RestrictedProxy:
    """Expose only the selected route to this private ASGI caller."""

    def __init__(self, vendor_app):
        self.vendor_app = vendor_app

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope.get("path") != "/v1/chat/completions"
            or scope.get("method") != "POST"
            or ACTIVE.get() is None
        ):
            await send({"type": "http.response.start", "status": 403, "headers": []})
            await send({"type": "http.response.body", "body": b""})
            return
        await self.vendor_app(scope, receive, send)


class LiteLLMAsgiAdapter:
    """The proxy executes on one event loop; ContextVar scopes each invocation."""

    def __init__(self, *, provider_key, lower=None, request_timeout=1.0):
        if (
            type(provider_key) is not str
            or not provider_key.startswith("sk-")
            or not 36 <= len(provider_key) <= 4096
        ):
            raise ValueError("invalid trusted provider credential")
        self.provider_key = provider_key
        self.lower_transport = lower
        self.request_timeout = request_timeout
        self._runtime = LoopThread("ezllmrouter-proxy-asgi")
        self.loop, self.thread = self._runtime.loop, self._runtime.thread
        try:
            self._runtime.call(self._start(), timeout=45)
        except BaseException:
            try:
                self.close()
            except Exception:
                log_failure("gateway.proxy.startup_cleanup_failed")
            raise

    def _call(self, coroutine) -> Future:
        return self._runtime.submit(coroutine)

    async def _start(self):
        # Set the selected SDK client before importing the proxy or caching SDK clients.
        import litellm

        self._litellm = litellm

        selected_timeout = self.request_timeout
        lower = self.lower_transport
        if lower is None:
            lower = httpx.AsyncHTTPTransport(retries=0, trust_env=False)
        self.lower_transport = lower
        self.guarded_client = httpx.AsyncClient(
            transport=GuardTransport(lower),
            follow_redirects=False,
            trust_env=False,
            timeout=httpx.Timeout(selected_timeout),
        )
        if litellm.aclient_session is not None or litellm.client_session is not None:
            raise RuntimeError("alternate or pre-cached LiteLLM HTTP session")
        litellm.aclient_session = self.guarded_client
        litellm.drop_params = False
        litellm.num_retries = 0
        litellm.network_mock = False
        provider_base = PROVIDER_URL.rsplit("/chat/completions", 1)[0]
        self.provider_base = provider_base
        from litellm.proxy import proxy_server

        await proxy_server.initialize(
            model=PROXY_MODEL,
            api_base=provider_base,
            api_key=self.provider_key,
            request_timeout=selected_timeout,
            drop_params=False,
            add_function_to_prompt=False,
        )
        if (
            litellm.aclient_session is not self.guarded_client
            or litellm.client_session is not None
            or litellm.drop_params is not False
            or litellm.num_retries != 0
        ):
            raise RuntimeError("alternate LiteLLM handler or retry configuration")
        self.proxy = RestrictedProxy(proxy_server.app)
        import openai as openai_sdk
        from litellm.llms.openai import common_utils as openai_utils
        from litellm.llms.openai import openai as openai_adapter

        def module_file(module):
            path = Path(module.__file__)
            return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

        self.module_identities = {
            "boundary": "in-process ASGI LiteLLM proxy route",
            "proxy_module": module_file(proxy_server),
            "litellm_module": module_file(litellm),
            "openai_adapter_module": module_file(openai_adapter),
            "openai_utils_module": module_file(openai_utils),
            "openai_sdk_module": module_file(openai_sdk),
            "httpx_module": module_file(httpx),
            "transport": type(self.guarded_client._transport).__name__,
            "route": "/v1/chat/completions",
            "model": PROXY_MODEL,
        }

    def prepare(self, body: dict) -> bytes:
        return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def describe(self, prepared: bytes, timeout_ms: int, destination: dict) -> dict:
        require_public_destination(destination)
        return {
            "method": "POST",
            "url": PROXY_URL,
            "content_type": "application/json",
            "content_length": len(prepared),
            "body_sha256": hashlib.sha256(prepared).hexdigest(),
            "timeout_ms": timeout_ms,
            "processing_region": destination["processing_region"],
        }

    def send_with_context(
        self, prepared: bytes, timeout_ms: int, expected: dict, guard_context: dict
    ) -> dict:
        actual = self.describe(prepared, timeout_ms, guard_context["plan"]["destination"])
        if actual != expected:
            raise ContractError("FDC_REJECTED", 409)
        invocation = Invocation(**guard_context)
        invocation.provider_key = self.provider_key
        future = self._call(self._send(prepared, timeout_ms, invocation))
        try:
            return future.result(timeout=timeout_ms / 1000 + 5)
        except BaseException:
            future.cancel()
            raise

    async def _send(self, prepared: bytes, timeout_ms: int, invocation: Invocation) -> dict:
        token = ACTIVE.set(invocation)
        try:
            try:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=self.proxy),
                    base_url="http://127.0.0.1:8767",
                    follow_redirects=False,
                    trust_env=False,
                    timeout=httpx.Timeout(timeout_ms / 1000 + 2),
                ) as client:
                    response = await client.post(
                        "/v1/chat/completions",
                        content=prepared,
                        headers={"Content-Type": "application/json"},
                    )
            except Exception as exc:
                if invocation.guard_error and not invocation.released:
                    code = (
                        "INTENT_PERSIST_FAILED"
                        if invocation.guard_error == "INTENT_PERSIST_FAILED"
                        else "FDC_REJECTED"
                    )
                    raise ContractError(
                        code, 503 if code == "INTENT_PERSIST_FAILED" else 409
                    ) from exc
                if invocation.released:
                    raise OSError("lower provider outcome uncertain") from exc
                raise
            if invocation.guard_error and not invocation.released:
                code = (
                    "INTENT_PERSIST_FAILED"
                    if invocation.guard_error == "INTENT_PERSIST_FAILED"
                    else "FDC_REJECTED"
                )
                raise ContractError(code, 503 if code == "INTENT_PERSIST_FAILED" else 409)
            if not invocation.released:
                raise ContractError("FDC_REJECTED", 409)
            if invocation.lower_error:
                raise OSError("lower provider outcome uncertain")
            if response.status_code != 200:
                return {"status": response.status_code, "body": None}
            return {"status": 200, "body": candidate_from_provider(response.json())}
        except Exception as exc:
            if not isinstance(exc, (ContractError, GuardRejected)):
                log_failure("gateway.asgi.request_failed")
            raise
        finally:
            ACTIVE.reset(token)

    async def _cleanup(self):
        client = getattr(self, "guarded_client", None)
        try:
            if client is not None:
                await client.aclose()
            elif self.lower_transport is not None:
                await self.lower_transport.aclose()
        finally:
            module = getattr(self, "_litellm", None)
            if module is not None and module.aclient_session is client:
                module.aclient_session = None

    def close(self):
        self._runtime.close(self._cleanup())
