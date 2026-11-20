"""Explicit gateway fixtures, staged only for the disposable gateway harness."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

import httpx

from ezllmrouter_server.canonical import ContractError
from ezllmrouter_server.gateway import adapter as runtime_adapter
from ezllmrouter_server.gateway.adapter import LiteLLMAsgiAdapter
from ezllmrouter_server.gateway.choice_b_sender import ChoiceBSenderAdapter
from ezllmrouter_server.gateway.guard import ACTIVE, Invocation, PROVIDER_URL
from ezllmrouter_server.gateway.proxy_recipe import PROXY_MODEL


class TraceTransport(httpx.AsyncBaseTransport):
    def __init__(self, lower, target, authority_file):
        self.lower, self.target, self.authority_file = lower, target, authority_file

    async def handle_async_request(self, request):
        invocation = ACTIVE.get()

        async def trace(name, _info):
            if name.endswith(
                (
                    "connect_tcp.started",
                    "connect_tcp.complete",
                    "send_request_headers.started",
                    "send_request_headers.complete",
                    "send_request_body.complete",
                )
            ):
                row = {
                    "attempt_id": invocation.attempt_id,
                    "event": name,
                    "monotonic_ns": time.monotonic_ns(),
                }
                if self.authority_file and Path(self.authority_file).is_file():
                    row["authority_state"] = Path(self.authority_file).read_text()
                with Path(self.target).open("a") as handle:
                    handle.write(json.dumps(row) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())

        request.extensions["trace"] = trace
        return await self.lower.handle_async_request(request)

    async def aclose(self):
        await self.lower.aclose()


class SwappingProxy:
    def __init__(self, app, swaps):
        self.app, self.swaps = app, swaps

    @property
    def vendor_app(self):
        return self.app.vendor_app

    async def __call__(self, scope, receive, send):
        current = ACTIVE.get()
        source = self.swaps.get(current.attempt_id) if current is not None else None
        token = ACTIVE.set(source) if source is not None else None
        try:
            await self.app(scope, receive, send)
        finally:
            if token is not None:
                ACTIVE.reset(token)


class FixtureAsgiAdapter(LiteLLMAsgiAdapter):
    def __init__(self, *, provider_key):
        self.pool_probe = os.environ.get("EZLLMROUTER_DEV04_POOL_PROBE") == "1"
        self.proxy_mutation = os.environ.get("EZLLMROUTER_DEV04_PROXY_MUTATION", "")
        if self.proxy_mutation not in ("", "content", "tool"):
            raise ValueError("unknown fixture mutation")
        self.fixture_provider = os.environ.get(
            "EZLLMROUTER_DEV04_PROVIDER_BASE_OVERRIDE",
            PROVIDER_URL.rsplit("/chat/completions", 1)[0],
        )
        if self.fixture_provider not in (
            PROVIDER_URL.rsplit("/chat/completions", 1)[0],
            "http://127.0.0.1:8779/v1",
        ):
            raise ValueError("unsupported fixture destination")
        self.swaps = {}
        self.sdk_retry_log = Path("/data/sdk-retry-observations.jsonl")
        self.fixture_lower = httpx.AsyncHTTPTransport(
            retries=0,
            trust_env=False,
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=1)
            if self.pool_probe
            else httpx.Limits(),
        )
        lower = self.fixture_lower
        trace = os.environ.get("EZLLMROUTER_DEV04_LOWER_TRACE")
        if trace:
            lower = TraceTransport(
                lower, trace, os.environ.get("EZLLMROUTER_DEV04_AUTHORITY_TOGGLE")
            )
        super().__init__(
            provider_key=provider_key, lower=lower, request_timeout=30.0 if self.pool_probe else 1.0
        )

    async def _start(self):
        # Only the fixture adapter changes the proxy destination. The actual
        # guard retains its fixed destination, so the mismatch must be rejected.
        url = self.fixture_provider + "/chat/completions"
        with patch.object(runtime_adapter, "PROVIDER_URL", url):
            await super()._start()
        self.proxy = SwappingProxy(self.proxy, self.swaps)
        self.pool_monitor = asyncio.create_task(self._watch_pool()) if self.pool_probe else None
        if os.environ.get("EZLLMROUTER_DEV04_BYPASS_PROBE") == "1":
            await self._bypass_probes()

    async def _send(self, prepared, timeout_ms, invocation):
        try:
            if os.environ.get("EZLLMROUTER_DEV04_CONTEXT_SWAP") == "1":
                text = json.loads(prepared)["messages"][1]["content"]
                if text == "Simulate hold":
                    self.swap_source = invocation
                elif text == "Simulate swapped context":
                    source = getattr(self, "swap_source", None)
                    if source is None or not source.attempted:
                        raise ContractError("FDC_REJECTED", 409)
                    self.swaps[invocation.attempt_id] = source
            if self.proxy_mutation:
                changed = json.loads(prepared)
                if self.proxy_mutation == "content":
                    changed["messages"][1]["content"] = "Changed after binding."
                else:
                    if changed.get("tool_choice") != "auto" or "tools" not in changed:
                        raise ContractError("FDC_REJECTED", 409)
                    changed["tool_choice"] = "none"
                prepared = self.prepare(changed)
            return await super()._send(prepared, timeout_ms, invocation)
        finally:
            self.swaps.pop(invocation.attempt_id, None)
            self._record_sdk_retry(invocation)

    def close(self):
        self._call(self._stop_pool_monitor()).result(timeout=5)
        super().close()

    async def _bypass_probes(self):
        """Label selected-handler and deliberate raw-client probes in this process."""
        body = {
            "model": PROXY_MODEL,
            "messages": [
                {"role": "system", "content": "Synthetic."},
                {"role": "user", "content": "Synthetic bypass probe."},
            ],
            "max_tokens": 32,
            "temperature": 0,
            "max_retries": 0,
        }
        rows = []
        async with httpx.AsyncClient(trust_env=False, timeout=3) as observer:

            async def count():
                return len(
                    (await observer.get("http://127.0.0.1:8766/observations")).json()["arrivals"]
                )

            before = await count()
            try:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=self.proxy),
                    base_url="http://127.0.0.1:8767",
                    trust_env=False,
                    timeout=3,
                ) as client:
                    response = await asyncio.wait_for(
                        client.post("/v1/chat/completions", json=body), 5
                    )
                    outcome = {"status": response.status_code}
            except Exception as exc:
                outcome = {"error_type": type(exc).__name__}
            rows.append(
                {
                    "probe": "selected_restricted_handler_no_context",
                    **outcome,
                    "receiver_delta": await count() - before,
                }
            )

            before = await count()
            try:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=self.proxy.vendor_app),
                    base_url="http://127.0.0.1:8767",
                    trust_env=False,
                    timeout=3,
                ) as client:
                    response = await asyncio.wait_for(
                        client.post("/v1/chat/completions", json=body), 5
                    )
                    outcome = {"status": response.status_code}
            except Exception as exc:
                outcome = {"error_type": type(exc).__name__}
            rows.append(
                {
                    "probe": "direct_installed_vendor_handler_no_context",
                    **outcome,
                    "receiver_delta": await count() - before,
                }
            )

            before = await count()
            try:
                response = await self.guarded_client.post(
                    PROVIDER_URL, json={"model": "probe.invalid"}
                )
                outcome = {"status": response.status_code}
            except Exception as exc:
                outcome = {"error_type": type(exc).__name__}
            rows.append(
                {
                    "probe": "selected_guarded_client_no_context",
                    **outcome,
                    "receiver_delta": await count() - before,
                }
            )

            before = await count()
            raw = {
                "model": "probe.invalid",
                "messages": [
                    {"role": "system", "content": "Synthetic."},
                    {"role": "user", "content": "Deliberate raw-client probe."},
                ],
            }
            async with httpx.AsyncClient(
                transport=httpx.AsyncHTTPTransport(retries=0, trust_env=False),
                trust_env=False,
                timeout=3,
            ) as client:
                response = await client.post(
                    PROVIDER_URL, json=raw, headers={"X-EzLLMRouter-Attempt": "probe.raw.dev04"}
                )
            rows.append(
                {
                    "probe": "deliberate_arbitrary_raw_client",
                    "status": response.status_code,
                    "receiver_delta": await count() - before,
                    "attempt_id": "probe.raw.dev04",
                }
            )
        Path("/data/bypass-probes.json").write_text(json.dumps(rows, indent=2) + "\n")

    async def _watch_pool(self):
        """Observe the selected httpcore pool queue without changing its assignment."""
        seen = set()
        target = Path("/data/pool-observations.jsonl")
        while True:
            for item in tuple(self.fixture_lower._pool._requests):
                if not item.is_queued():
                    continue
                attempt = next(
                    (
                        value.decode("ascii")
                        for key, value in item.request.headers
                        if key.lower() == b"x-ezllmrouter-attempt"
                    ),
                    None,
                )
                if attempt and attempt not in seen:
                    seen.add(attempt)
                    with target.open("a") as handle:
                        handle.write(
                            json.dumps(
                                {
                                    "attempt_id": attempt,
                                    "event": "queued_in_selected_httpcore_pool",
                                    "monotonic_ns": time.monotonic_ns(),
                                }
                            )
                            + "\n"
                        )
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

    def _record_sdk_retry(self, invocation: Invocation) -> None:
        """Record only the effective retry scalar of the cached selected SDK client."""
        row = {"attempt_id": invocation.attempt_id}
        try:
            import litellm
            import openai

            cache = litellm.in_memory_llm_clients_cache
            clients = [
                value
                for value in cache.cache_dict.values()
                if isinstance(value, openai.AsyncOpenAI)
                and getattr(value, "_client", None) is self.guarded_client
                and str(getattr(value, "base_url", "")).rstrip("/") == self.provider_base
            ]
            values = [client.max_retries for client in clients]
            row["matched_sdk_clients"] = len(clients)
            row["effective_max_retries"] = (
                values[0]
                if values and all(type(value) is int and value == values[0] for value in values)
                else None
            )
            row["selected_pool_requests_at_send_end"] = len(self.fixture_lower._pool._requests)
        except Exception as exc:
            row["inspection_error"] = type(exc).__name__
        try:
            with self.sdk_retry_log.open("a") as handle:
                handle.write(json.dumps(row, separators=(",", ":")) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            print(
                "DEV-04 SDK retry observation write failed: " + type(exc).__name__, file=sys.stderr
            )


class ToolMutationTransport(httpx.AsyncBaseTransport):
    def __init__(self, lower, target):
        self.lower, self.target = lower, Path(target)

    async def handle_async_request(self, request):
        invocation = ACTIVE.get()
        if invocation.plan["work_key"]["step_id"] == "step.dev03.mutation":
            original = request.content
            changed = json.loads(original)
            description = changed["tools"][0]["function"]["description"]
            replacement = description[:-1] + ("x" if description[-1] != "x" else "y")
            needle = json.dumps(description, ensure_ascii=False).encode()
            replacement_bytes = json.dumps(replacement, ensure_ascii=False).encode()
            if original.count(needle) != 1 or len(needle) != len(replacement_bytes):
                raise ValueError("fixture mutation field unavailable")
            request = httpx.Request(
                request.method,
                request.url,
                headers=request.headers,
                content=original.replace(needle, replacement_bytes, 1),
                extensions=request.extensions,
            )
            with self.target.open("a") as handle:
                handle.write(
                    json.dumps(
                        {
                            "attempt_id": invocation.attempt_id,
                            "field": "tools[0].function.description",
                            "bound_sha256": hashlib.sha256(original).hexdigest(),
                            "mutated_sha256": hashlib.sha256(request.content).hexdigest(),
                            "same_length": len(original) == len(request.content),
                        }
                    )
                    + "\n"
                )
                handle.flush()
                os.fsync(handle.fileno())
        return await self.lower.handle_async_request(request)

    async def aclose(self):
        await self.lower.aclose()


class FixtureSenderAdapter(ChoiceBSenderAdapter):
    async def _start_lower(self):
        await super()._start_lower()
        if os.environ.get("EZLLMROUTER_DEV05_TEST_TOOL_MUTATION") == "1":
            self.guard = ToolMutationTransport(self.guard, "/data/tool-mutation-events.jsonl")
        self.pool_monitor = (
            asyncio.create_task(self._watch_pool())
            if os.environ.get("EZLLMROUTER_DEV04_POOL_PROBE") == "1"
            else None
        )

    def close(self):
        async def stop():
            if self.pool_monitor is not None:
                self.pool_monitor.cancel()
                try:
                    await self.pool_monitor
                except asyncio.CancelledError:
                    pass

        self._call(stop()).result(timeout=5)
        super().close()

    async def _watch_pool(self):
        """Observe the real selected queue; never use private state for enforcement."""
        seen = set()
        target = Path("/data/pool-observations.jsonl")
        while True:
            for item in tuple(self.lower.pool._requests):
                if not item.is_queued():
                    continue
                attempt = next(
                    (
                        value.decode("ascii")
                        for key, value in item.request.headers
                        if key.lower() == b"x-ezllmrouter-attempt"
                    ),
                    None,
                )
                if attempt and attempt not in seen:
                    seen.add(attempt)
                    with target.open("a") as handle:
                        handle.write(
                            json.dumps(
                                {
                                    "attempt_id": attempt,
                                    "event": "queued_in_owned_httpcore_pool",
                                    "monotonic_ns": time.monotonic_ns(),
                                }
                            )
                            + "\n"
                        )
                        handle.flush()
                        os.fsync(handle.fileno())
            await asyncio.sleep(0.005)
