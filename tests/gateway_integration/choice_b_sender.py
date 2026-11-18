"""DEV-04 Choice B trusted side: authority and provider socket stay outside LiteLLM."""
from __future__ import annotations

import asyncio
import base64
from concurrent.futures import Future
import hashlib
import json
import os
from pathlib import Path
import socket
import socketserver
import threading
import time

import httpx

from choice_b_wire import receive, send
from duranki_server.canonical import ContractError, SAFE
from guard import ACTIVE, GuardRejected, GuardTransport, Invocation, PROVIDER_URL
from owned_sender_transport import OwnedHTTPTransport
from owned_tls_sender_transport import OwnedTLSHTTPTransport
from proxy_recipe import require_public_destination


PROXY_URL = "http://127.0.0.1:8767/v1/chat/completions"
WORKER_KEY = "sk-dev04-worker-placeholder-not-provider-000000"
LINK = Path("/link")


class _ThreadingUnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = False


class ChoiceBSenderAdapter:
    """Single-use trusted attempt registry and pinned lower transport."""

    def __init__(self, authority, registry=None, *, controlled_provider_proof=False):
        self.authority = authority
        self.provider_registry = registry
        self.controlled_provider_proof = controlled_provider_proof
        self.provider_key = os.environ["DURANKI_DEV04_PROVIDER_KEY"]
        self.registry: dict[str, Invocation] = {}
        self.claimed: set[str] = set()
        self.lock = threading.Lock()
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True,
                                       name="dev04-trusted-sender")
        self.thread.start()
        self._call(self._start_lower()).result(timeout=5)
        path = LINK / "sender.sock"
        if path.exists() or path.is_symlink():
            raise RuntimeError("Choice B sender socket collision")
        adapter = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                try:
                    envelope = receive(self.request)
                    result = adapter.process_relay(envelope)
                except Exception as exc:
                    result = {"error_type": type(exc).__name__}
                send(self.request, result)

        self.server = _ThreadingUnixServer(str(path), Handler)
        os.chmod(path, 0o600)
        self.server_thread = threading.Thread(target=self.server.serve_forever,
                                              daemon=True, name="dev04-sender-uds")
        self.server_thread.start()

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _call(self, coro) -> Future:
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    async def _start_lower(self):
        self.lower = OwnedHTTPTransport(self.authority)
        adapter = self
        class SelectedLower(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request):
                invocation = ACTIVE.get()
                if invocation is None:
                    raise GuardRejected("NO_TRUSTED_CONTEXT")
                destination = invocation.plan["destination"]
                if destination.get("service") != "openai.responses.v1":
                    return await adapter.lower.handle_async_request(request)
                if adapter.provider_registry is None:
                    raise GuardRejected("PROVIDER_UNAVAILABLE")
                connection = adapter.provider_registry.connection(destination["connection_id"])
                if (not connection or connection["status"] != "active" or
                        connection["revision"] != destination["connection_revision"] or
                        connection["credential_version"] != destination["credential_version"] or
                        connection["settings"]["origin"] != destination["endpoint"]):
                    raise GuardRejected("PROVIDER_CONNECTION_STALE")
                lower = OwnedTLSHTTPTransport(adapter.authority, destination["adapter_id"],
                    connection["settings"], controlled=adapter.controlled_provider_proof)
                try:
                    response = await lower.handle_async_request(request)
                    body = await response.aread()
                    if len(body) > 65536:
                        raise ValueError("provider response size")
                    return httpx.Response(response.status_code, headers=response.headers,
                                          content=body, request=request)
                finally:
                    await lower.aclose()
            async def aclose(self):
                await adapter.lower.aclose()
        self.guard = GuardTransport(SelectedLower())
        self.pool_monitor = (asyncio.create_task(self._watch_pool())
                             if os.environ.get("DURANKI_DEV04_POOL_PROBE") == "1" else None)

    async def _watch_pool(self):
        """Observe the real selected queue; never use private state for enforcement."""
        seen = set()
        target = Path("/data/pool-observations.jsonl")
        while True:
            for item in tuple(self.lower.pool._requests):
                if not item.is_queued():
                    continue
                attempt = next((value.decode("ascii") for key, value in item.request.headers
                    if key.lower() == b"x-duranki-attempt"), None)
                if attempt and attempt not in seen:
                    seen.add(attempt)
                    with target.open("a") as handle:
                        handle.write(json.dumps({"attempt_id": attempt,
                            "event": "queued_in_owned_httpcore_pool",
                            "monotonic_ns": time.monotonic_ns()}) + "\n")
                        handle.flush()
                        os.fsync(handle.fileno())
            await asyncio.sleep(0.005)

    def _record_send(self, invocation):
        target = os.environ.get("DURANKI_DEV04_SEND_EVENTS")
        if not target:
            return
        row = {"attempt_id": invocation.attempt_id,
               "first_bytes_accepted_by_local_socket": invocation.first_bytes_accepted,
               "first_acceptance_events": (invocation.observations.count(
                   "FIRST_BYTES_ACCEPTED_BY_LOCAL_SOCKET") + invocation.observations.count(
                   "FIRST_TLS_REQUEST_BYTES_ACCEPTED_BY_LOCAL_SOCKET")),
               "lower_error": invocation.lower_error,
               "monotonic_ns": time.monotonic_ns()}
        try:
            with Path(target).open("a") as handle:
                handle.write(json.dumps(row) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:
            # This diagnostic is downstream of the in-memory first-byte fact.
            pass

    @staticmethod
    def prepare(body):
        return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    @staticmethod
    def describe(prepared, timeout_ms, destination):
        if destination.get("service") == "openai.responses.v1":
            if destination.get("adapter_id") != "openai.responses.v1":
                raise ValueError("unsupported provider adapter")
            url = "http://127.0.0.1:8767/v1/responses"
        else:
            require_public_destination(destination)
            url = PROXY_URL
        return {"method": "POST", "url": url, "content_type": "application/json",
                "content_length": len(prepared),
                "body_sha256": hashlib.sha256(prepared).hexdigest(),
                "timeout_ms": timeout_ms,
                "processing_region": destination["processing_region"]}

    @staticmethod
    def _worker_command(value, timeout):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
            stream.settimeout(timeout)
            stream.connect(str(LINK / "worker.sock"))
            send(stream, value)
            return receive(stream)

    def send_with_context(self, prepared, timeout_ms, expected, guard_context):
        actual = self.describe(prepared, timeout_ms, guard_context["plan"]["destination"])
        if actual != expected:
            raise ContractError("FDC_REJECTED", 409)
        invocation = Invocation(**guard_context)
        try:
            invocation.authority_epoch = self.authority.snapshot_epoch()
        except GuardRejected as exc:
            raise ContractError("FDC_REJECTED", 409) from exc
        with self.lock:
            if invocation.attempt_id in self.registry:
                raise ContractError("FDC_REJECTED", 409)
            self.registry[invocation.attempt_id] = invocation
        try:
            try:
                result = self._worker_command({"kind": "selected_request",
                    "route": "responses" if invocation.plan["destination"].get("service") == "openai.responses.v1" else "chat",
                    "attempt_id": invocation.attempt_id,
                    "prepared_b64": base64.b64encode(prepared).decode("ascii")},
                    timeout_ms / 1000 + 5)
            except Exception as exc:
                if invocation.released:
                    raise OSError("trusted sender outcome uncertain") from exc
                raise ContractError("FDC_REJECTED", 409) from exc
            if invocation.guard_error and not invocation.released:
                code = ("INTENT_PERSIST_FAILED" if invocation.guard_error == "INTENT_PERSIST_FAILED"
                        else "FDC_REJECTED")
                raise ContractError(code, 503 if code == "INTENT_PERSIST_FAILED" else 409)
            if not invocation.released:
                raise ContractError("FDC_REJECTED", 409)
            if invocation.lower_error and not invocation.first_bytes_accepted:
                raise ContractError("FDC_REJECTED", 409)
            if invocation.lower_error or "error_type" in result:
                raise OSError("trusted sender outcome uncertain")
            status = result.get("status")
            if type(status) is not int:
                raise OSError("worker response missing status")
            if status != 200:
                return {"status": status, "body": None}
            return {"status": 200, "body": self._candidate(result["body"],
                invocation.plan["destination"].get("service") == "openai.responses.v1")}
        finally:
            with self.lock:
                self.registry.pop(invocation.attempt_id, None)
                self.claimed.discard(invocation.attempt_id)

    def process_relay(self, envelope):
        if set(envelope) != {"kind", "attempt_id", "method", "url", "headers", "body_b64", "timeout"}:
            raise ValueError("relay envelope shape")
        if envelope["kind"] != "final_request" or envelope["method"] != "POST":
            raise ValueError("relay destination")
        attempt = envelope["attempt_id"]
        if type(attempt) is not str:
            raise ValueError("relay attempt")
        with self.lock:
            invocation = self.registry.get(attempt)
            if invocation is not None:
                if attempt in self.claimed:
                    raise ValueError("replayed attempt authority")
                self.claimed.add(attempt)
        if invocation is None:
            raise ValueError("unregistered attempt")
        destination = invocation.plan.get("destination", {})
        provider_route = destination.get("service") == "openai.responses.v1"
        expected_url = (destination["endpoint"].rstrip("/") + "/v1/responses"
                        if provider_route else PROVIDER_URL)
        if envelope["url"] != expected_url:
            raise ValueError("relay destination")
        work_key = invocation.plan.get("work_key")
        # WorkKey has four identifier strings and one positive safe integer.
        # Do not coerce the signed revision, or accept bool as an integer.
        if (type(work_key) is not dict or
            any(type(work_key.get(field)) is not str or not work_key[field]
                for field in ("principal_id", "task_id", "step_id",
                              "execution_generation")) or
            type(work_key.get("step_revision")) is not int or
            not 1 <= work_key["step_revision"] <= SAFE):
            raise ValueError("registered attempt missing required work identity")
        headers = envelope["headers"]
        if (type(headers) is not list or
            any(type(pair) is not list or len(pair) != 2 or
                any(type(item) is not str for item in pair) for pair in headers)):
            raise ValueError("relay headers")
        header_map = httpx.Headers(headers)
        if header_map.get("authorization") != "Bearer " + WORKER_KEY:
            raise ValueError("worker placeholder authorization")
        body = base64.b64decode(envelope["body_b64"], validate=True)
        if not body or len(body) > 65536:
            raise ValueError("relay body size")
        timeout = envelope["timeout"]
        if type(timeout) is not dict:
            raise ValueError("relay timeout")
        if provider_route:
            if self.provider_registry is None:
                raise ValueError("provider registry unavailable")
            connection = self.provider_registry.connection(destination["connection_id"])
            if (not connection or connection["status"] != "active" or
                    connection["revision"] != destination["connection_revision"] or
                    connection["credential_version"] != destination["credential_version"] or
                    connection["settings"]["origin"] != destination["endpoint"]):
                raise ValueError("provider binding stale")
            provider_key = self.provider_registry.provider_vault.resolve(
                destination["connection_id"], destination["credential_version"])
            invocation.provider_key = provider_key
        else:
            provider_key = self.provider_key
        header_map["authorization"] = "Bearer " + provider_key
        request = httpx.Request("POST", expected_url, headers=header_map,
                                content=body, extensions={"timeout": timeout})
        future = self._call(self._send(request, invocation))
        try:
            return future.result(timeout=invocation.plan["per_attempt_total_timeout_ms"] / 1000 + 3)
        except Exception:
            future.cancel()
            raise

    async def _send(self, request, invocation):
        token = ACTIVE.set(invocation)
        try:
            if (os.environ.get("DURANKI_DEV05_TEST_TOOL_MUTATION") == "1" and
                    invocation.plan["work_key"]["step_id"] == "step.dev03.mutation"):
                original = request.content
                changed = json.loads(request.content)
                description = changed["tools"][0]["function"]["description"]
                replacement = description[:-1] + (
                    "x" if description[-1] != "x" else "y")
                needle = json.dumps(description, ensure_ascii=False).encode()
                replacement_bytes = json.dumps(replacement, ensure_ascii=False).encode()
                if original.count(needle) != 1 or len(needle) != len(replacement_bytes):
                    raise ValueError("DEV-05 mutation field unavailable")
                request = httpx.Request(request.method, request.url, headers=request.headers,
                                        content=original.replace(needle, replacement_bytes, 1),
                                        extensions=request.extensions)
                with Path("/data/tool-mutation-events.jsonl").open("a") as handle:
                    handle.write(json.dumps({"attempt_id": invocation.attempt_id,
                        "field": "tools[0].function.description",
                        "bound_sha256": hashlib.sha256(original).hexdigest(),
                        "mutated_sha256": hashlib.sha256(request.content).hexdigest(),
                        "same_length": len(original) == len(request.content)}) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
            response = await self.guard.handle_async_request(request)
            raw = await response.aread()
            if len(raw) > 65536:
                raise ValueError("provider response size")
            return {"status": response.status_code,
                    "body_b64": base64.b64encode(raw).decode("ascii"),
                    "headers": [["content-type", response.headers.get("content-type", "application/json")]]}
        finally:
            self._record_send(invocation)
            ACTIVE.reset(token)

    @staticmethod
    def _candidate(provider, responses=False):
        if responses:
            if type(provider) is not dict or provider.get("object") != "response" or type(provider.get("output")) is not list:
                raise ValueError("invalid Responses candidate")
            text = "".join(part["text"] for item in provider["output"]
                if type(item) is dict and item.get("type") == "message" and
                type(item.get("content")) is list for part in item["content"]
                if type(part) is dict and part.get("type") == "output_text" and type(part.get("text")) is str)
            if not text:
                raise ValueError("Responses candidate lacks output text")
            usage = provider.get("usage")
            result = {"text": text}
            if (type(provider.get("model")) is str and 1 <= len(provider["model"]) <= 256 and
                    all(32 < ord(char) < 127 for char in provider["model"])):
                result["served_model"] = provider["model"]
            if type(usage) is dict:
                result["usage"] = {key: usage[key] for key in
                    ("input_tokens", "output_tokens", "total_tokens",
                     "input_tokens_details", "output_tokens_details")
                    if key in usage}
            return result
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
        self.server.shutdown()
        self.server.server_close()
        (LINK / "sender.sock").unlink()
        if self.pool_monitor is not None:
            async def stop_monitor():
                self.pool_monitor.cancel()
                try:
                    await self.pool_monitor
                except asyncio.CancelledError:
                    pass
            self._call(stop_monitor()).result(timeout=5)
        self._call(self.guard.aclose()).result(timeout=5)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=5)
