"""Private in-process ASGI bridge into the actual LiteLLM proxy route."""
from __future__ import annotations

import asyncio
from concurrent.futures import Future
import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path

import httpx

from duranki_server.canonical import ContractError
from guard import ACTIVE, GuardTransport, Invocation, PROVIDER_URL
from proxy_recipe import PROXY_MODEL, require_public_destination


PROXY_URL = "http://127.0.0.1:8767/v1/chat/completions"


class RestrictedProxy:
    """Expose only the selected route to this private ASGI caller."""

    def __init__(self, vendor_app):
        self.vendor_app = vendor_app

    async def __call__(self, scope, receive, send):
        if (scope["type"] != "http" or scope.get("path") != "/v1/chat/completions" or
            scope.get("method") != "POST" or ACTIVE.get() is None):
            await send({"type": "http.response.start", "status": 403, "headers": []})
            await send({"type": "http.response.body", "body": b""})
            return
        await self.vendor_app(scope, receive, send)


class LiteLLMAsgiAdapter:
    """The proxy executes on one event loop; ContextVar scopes each invocation."""

    def __init__(self):
        self.sdk_retry_log = Path("/data/sdk-retry-observations.jsonl")
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, name="dev04-proxy-asgi", daemon=True)
        self.thread.start()
        self._call(self._start()).result(timeout=45)

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _call(self, coroutine) -> Future:
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop)

    async def _start(self):
        # Set the selected SDK client before importing the proxy or caching SDK clients.
        import litellm
        self.pool_probe = os.environ.get("DURANKI_DEV04_POOL_PROBE") == "1"
        selected_timeout = 30.0 if self.pool_probe else 1.0
        lower = httpx.AsyncHTTPTransport(retries=0, trust_env=False,
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=1)
            if self.pool_probe else httpx.Limits())
        self.lower_transport = lower
        self.guarded_client = httpx.AsyncClient(
            transport=GuardTransport(lower), follow_redirects=False, trust_env=False,
            timeout=httpx.Timeout(selected_timeout))
        if litellm.aclient_session is not None or litellm.client_session is not None:
            raise RuntimeError("alternate or pre-cached LiteLLM HTTP session")
        litellm.aclient_session = self.guarded_client
        litellm.drop_params = False
        litellm.num_retries = 0
        litellm.network_mock = False
        self.proxy_mutation = os.environ.get("DURANKI_DEV04_PROXY_MUTATION", "")
        if self.proxy_mutation not in ("", "content", "tool"):
            raise RuntimeError("unsupported DEV-04 mutation")
        provider_base = os.environ.get("DURANKI_DEV04_PROVIDER_BASE_OVERRIDE",
                                       PROVIDER_URL.rsplit("/chat/completions", 1)[0])
        if provider_base not in (PROVIDER_URL.rsplit("/chat/completions", 1)[0],
                                 "http://127.0.0.1:8779/v1"):
            raise RuntimeError("unsupported DEV-04 provider destination")
        self.provider_base = provider_base
        from litellm.proxy import proxy_server
        await proxy_server.initialize(model=PROXY_MODEL,
                                      api_base=provider_base,
                                      request_timeout=selected_timeout, drop_params=False,
                                      add_function_to_prompt=False)
        if (litellm.aclient_session is not self.guarded_client or
            litellm.client_session is not None or litellm.drop_params is not False or
            litellm.num_retries != 0):
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
            "route": "/v1/chat/completions", "model": PROXY_MODEL,
        }
        if self.pool_probe:
            self.pool_monitor = asyncio.create_task(self._watch_pool())
        if os.environ.get("DURANKI_DEV04_BYPASS_PROBE") == "1":
            await self._bypass_probes()

    async def _bypass_probes(self):
        """Label selected-handler and deliberate raw-client probes in this process."""
        body = {"model": PROXY_MODEL, "messages": [{"role": "system", "content": "Synthetic."},
            {"role": "user", "content": "Synthetic bypass probe."}],
            "max_tokens": 32, "temperature": 0, "max_retries": 0}
        rows = []
        async with httpx.AsyncClient(trust_env=False, timeout=3) as observer:
            async def count():
                return len((await observer.get("http://127.0.0.1:8766/observations")).json()["arrivals"])

            before = await count()
            try:
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.proxy),
                        base_url="http://127.0.0.1:8767", trust_env=False, timeout=3) as client:
                    response = await asyncio.wait_for(client.post("/v1/chat/completions", json=body), 5)
                    outcome = {"status": response.status_code}
            except Exception as exc:
                outcome = {"error_type": type(exc).__name__}
            rows.append({"probe": "selected_restricted_handler_no_context", **outcome,
                         "receiver_delta": await count() - before})

            before = await count()
            try:
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.proxy.vendor_app),
                        base_url="http://127.0.0.1:8767", trust_env=False, timeout=3) as client:
                    response = await asyncio.wait_for(client.post("/v1/chat/completions", json=body), 5)
                    outcome = {"status": response.status_code}
            except Exception as exc:
                outcome = {"error_type": type(exc).__name__}
            rows.append({"probe": "direct_installed_vendor_handler_no_context", **outcome,
                         "receiver_delta": await count() - before})

            before = await count()
            try:
                response = await self.guarded_client.post(PROVIDER_URL, json={"model": "probe.invalid"})
                outcome = {"status": response.status_code}
            except Exception as exc:
                outcome = {"error_type": type(exc).__name__}
            rows.append({"probe": "selected_guarded_client_no_context", **outcome,
                         "receiver_delta": await count() - before})

            before = await count()
            raw = {"model": "probe.invalid", "messages": [{"role": "system", "content": "Synthetic."},
                {"role": "user", "content": "Deliberate raw-client probe."}]}
            async with httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(retries=0, trust_env=False),
                    trust_env=False, timeout=3) as client:
                response = await client.post(PROVIDER_URL, json=raw,
                    headers={"X-Duranki-Attempt": "probe.raw.dev04"})
            rows.append({"probe": "deliberate_arbitrary_raw_client", "status": response.status_code,
                         "receiver_delta": await count() - before,
                         "attempt_id": "probe.raw.dev04"})
        Path("/data/bypass-probes.json").write_text(json.dumps(rows, indent=2) + "\n")

    async def _watch_pool(self):
        """Observe the selected httpcore pool queue without changing its assignment."""
        seen = set()
        target = Path("/data/pool-observations.jsonl")
        while True:
            for item in tuple(self.lower_transport._pool._requests):
                if not item.is_queued():
                    continue
                attempt = next((value.decode("ascii") for key, value in item.request.headers
                    if key.lower() == b"x-duranki-attempt"), None)
                if attempt and attempt not in seen:
                    seen.add(attempt)
                    with target.open("a") as handle:
                        handle.write(json.dumps({"attempt_id": attempt,
                            "event": "queued_in_selected_httpcore_pool",
                            "monotonic_ns": time.monotonic_ns()}) + "\n")
                        handle.flush()
                        os.fsync(handle.fileno())
            await asyncio.sleep(0.005)

    async def _stop_pool_monitor(self):
        if getattr(self, "pool_monitor", None) is not None:
            self.pool_monitor.cancel()
            try:
                await self.pool_monitor
            except asyncio.CancelledError:
                pass

    def prepare(self, body: dict) -> bytes:
        return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def describe(self, prepared: bytes, timeout_ms: int, destination: dict) -> dict:
        require_public_destination(destination)
        return {"method": "POST", "url": PROXY_URL, "content_type": "application/json",
                "content_length": len(prepared),
                "body_sha256": hashlib.sha256(prepared).hexdigest(),
                "timeout_ms": timeout_ms, "processing_region": destination["processing_region"]}

    def send_with_context(self, prepared: bytes, timeout_ms: int, expected: dict,
                          guard_context: dict) -> dict:
        actual = self.describe(prepared, timeout_ms, guard_context["plan"]["destination"])
        if actual != expected:
            raise ContractError("FDC_REJECTED", 409)
        invocation = Invocation(**guard_context)
        return self._call(self._send(prepared, timeout_ms, invocation)).result(
            timeout=timeout_ms / 1000 + 5)

    async def _send(self, prepared: bytes, timeout_ms: int, invocation: Invocation) -> dict:
        token = ACTIVE.set(invocation)
        swap_token = None
        try:
            if os.environ.get("DURANKI_DEV04_CONTEXT_SWAP") == "1":
                user_text = json.loads(prepared)["messages"][1]["content"]
                if user_text == "Simulate hold":
                    self.swap_source = invocation
                elif user_text == "Simulate swapped context":
                    source = getattr(self, "swap_source", None)
                    if source is None or not source.attempted:
                        raise ContractError("FDC_REJECTED", 409)
                    swap_token = ACTIVE.set(source)
            if self.proxy_mutation:
                changed = json.loads(prepared)
                if self.proxy_mutation == "content":
                    changed["messages"][1]["content"] = "Changed after binding."
                elif self.proxy_mutation == "tool":
                    if changed.get("tool_choice") != "auto" or "tools" not in changed:
                        raise ContractError("FDC_REJECTED", 409)
                    changed["tool_choice"] = "none"
                prepared = self.prepare(changed)
            try:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=self.proxy),
                    base_url="http://127.0.0.1:8767", follow_redirects=False,
                    trust_env=False, timeout=httpx.Timeout(timeout_ms / 1000 + 2),
                ) as client:
                    response = await client.post("/v1/chat/completions", content=prepared,
                                                 headers={"Content-Type": "application/json"})
            except Exception as exc:
                if invocation.guard_error and not invocation.released:
                    code = ("INTENT_PERSIST_FAILED" if invocation.guard_error == "INTENT_PERSIST_FAILED"
                            else "FDC_REJECTED")
                    raise ContractError(code, 503 if code == "INTENT_PERSIST_FAILED" else 409) from exc
                if invocation.released:
                    raise OSError("lower provider outcome uncertain") from exc
                raise
            if invocation.guard_error and not invocation.released:
                code = ("INTENT_PERSIST_FAILED" if invocation.guard_error == "INTENT_PERSIST_FAILED"
                        else "FDC_REJECTED")
                raise ContractError(code, 503 if code == "INTENT_PERSIST_FAILED" else 409)
            if not invocation.released:
                raise ContractError("FDC_REJECTED", 409)
            if invocation.lower_error:
                raise OSError("lower provider outcome uncertain")
            if response.status_code != 200:
                return {"status": response.status_code, "body": None}
            return {"status": 200, "body": self._candidate(response.json())}
        finally:
            if getattr(self, "sdk_retry_log", None) is not None:
                self._record_sdk_retry(invocation)
            if swap_token is not None:
                ACTIVE.reset(swap_token)
            ACTIVE.reset(token)

    def _record_sdk_retry(self, invocation: Invocation) -> None:
        """Record only the effective retry scalar of the cached selected SDK client."""
        row = {"attempt_id": invocation.attempt_id}
        try:
            import litellm
            import openai
            cache = litellm.in_memory_llm_clients_cache
            clients = [value for value in cache.cache_dict.values()
                       if isinstance(value, openai.AsyncOpenAI) and
                       getattr(value, "_client", None) is self.guarded_client and
                       str(getattr(value, "base_url", "")).rstrip("/") == self.provider_base]
            values = [client.max_retries for client in clients]
            row["matched_sdk_clients"] = len(clients)
            row["effective_max_retries"] = (values[0] if values and
                all(type(value) is int and value == values[0] for value in values) else None)
            row["selected_pool_requests_at_send_end"] = len(self.lower_transport._pool._requests)
        except Exception as exc:
            row["inspection_error"] = type(exc).__name__
        try:
            with self.sdk_retry_log.open("a") as handle:
                handle.write(json.dumps(row, separators=(",", ":")) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            print("DEV-04 SDK retry observation write failed: " + type(exc).__name__, file=sys.stderr)

    @staticmethod
    def _candidate(provider: dict) -> dict:
        choice = provider["choices"][0]
        message = choice["message"]
        result = {"finish_reason": choice.get("finish_reason")}
        if isinstance(message.get("content"), str):
            result["text"] = message["content"]
        if isinstance(message.get("tool_calls"), list):
            result["tool_calls"] = [{"id": call["id"], "name": call["function"]["name"],
                                     "arguments_json": call["function"]["arguments"]}
                                    for call in message["tool_calls"]]
        usage = provider.get("usage")
        if isinstance(usage, dict):
            result["usage"] = {"input_tokens": usage.get("prompt_tokens"),
                               "output_tokens": usage.get("completion_tokens")}
        return result

    def close(self):
        self._call(self._stop_pool_monitor()).result(timeout=5)
        self._call(self.guarded_client.aclose()).result(timeout=5)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=5)
