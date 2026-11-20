"""DEV-04 Choice B trusted side: authority and provider socket stay outside LiteLLM."""

from __future__ import annotations

import asyncio
import base64
from concurrent.futures import Future
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import socketserver
from contextlib import ExitStack
import threading
import time

import httpx

from ezllmrouter_server.runtime_resources import BoundedUnixServer, LoopThread
from .choice_b_wire import exchange, receive, remaining_seconds, send
from ezllmrouter_server.canonical import ContractError, SAFE
from .guard import (
    ACTIVE,
    GuardRejected,
    GuardTransport,
    Invocation,
    PROVIDER_URL,
    enqueue_event,
    flush_events,
)
from ezllmrouter_server.observability import log_failure
from .owned_sender_transport import OwnedHTTPTransport
from .owned_tls_sender_transport import OwnedTLSHTTPTransport
from .proxy_recipe import require_public_destination


PROXY_URL = "http://127.0.0.1:8767/v1/chat/completions"
WORKER_KEY = "sk-dev04-worker-placeholder-not-provider-000000"
LINK = Path("/link")
RESPONSE_LIMIT = 65536


async def read_response(response):
    """Stop at the response limit without buffering an unbounded provider body."""
    try:
        length = response.headers.get("content-length")
        if length is not None and (not length.isdigit() or int(length) > RESPONSE_LIMIT):
            raise ValueError("provider response size")
        chunks, size = [], 0
        async for chunk in response.aiter_bytes(chunk_size=8192):
            size += len(chunk)
            if size > RESPONSE_LIMIT:
                raise ValueError("provider response size")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        await response.aclose()


class ChoiceBSenderAdapter:
    """Single-use trusted attempt registry and pinned lower transport."""

    def __init__(self, authority, registry=None, *, provider_key, controlled_provider_proof=False):
        self.authority = authority
        self.provider_registry = registry
        self.controlled_provider_proof = controlled_provider_proof
        if (
            type(provider_key) is not str
            or not provider_key.startswith("sk-")
            or not 36 <= len(provider_key) <= 4096
            or any(not 33 <= ord(c) <= 126 for c in provider_key)
        ):
            raise ValueError("invalid trusted provider credential")
        self.provider_key = provider_key
        self.registry: dict[str, Invocation] = {}
        self.claimed: set[str] = set()
        self.lock = threading.Lock()
        self._close_lock = threading.Lock()
        self._closed = False
        self._socket_identity = None
        self.server = self.server_thread = None
        self._socket_path = LINK / "sender.sock"
        if self._socket_path.exists() or self._socket_path.is_symlink():
            raise RuntimeError("Choice B sender socket collision")
        self._runtime = LoopThread("ezllmrouter-trusted-sender")
        self.loop, self.thread = self._runtime.loop, self._runtime.thread
        try:
            self._runtime.call(self._start_lower(), timeout=5)
            adapter = self

            class Handler(socketserver.BaseRequestHandler):
                def handle(self):
                    adapter.handle_relay(self.request)

            self.server = BoundedUnixServer(
                str(self._socket_path), Handler, bind_and_activate=False
            )
            self.server.server_bind()
            status = self._socket_path.lstat()
            self._socket_identity = (status.st_dev, status.st_ino)
            os.chmod(self._socket_path, 0o600)
            self.server.server_activate()
            self.server_thread = threading.Thread(
                target=self.server.serve_forever, daemon=True, name="ezllmrouter-sender-ipc"
            )
            self.server_thread.start()
        except BaseException:
            try:
                self.close()
            except Exception:
                log_failure("gateway.sender.startup_cleanup_failed")
            raise

    def handle_relay(self, stream):
        try:
            result = self.process_relay(receive(stream, timeout=5))
        except Exception as exc:
            log_failure("gateway.relay.command_failed")
            result = {"error_type": type(exc).__name__}
        try:
            send(stream, result, timeout=5)
        except Exception:
            log_failure("gateway.relay.reply_failed")

    def _call(self, coro) -> Future:
        return self._runtime.submit(coro)

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
                if (
                    not connection
                    or connection["status"] != "active"
                    or connection["revision"] != destination["connection_revision"]
                    or connection["credential_version"] != destination["credential_version"]
                    or connection["settings"]["origin"] != destination["endpoint"]
                ):
                    raise GuardRejected("PROVIDER_CONNECTION_STALE")
                lower = OwnedTLSHTTPTransport(
                    adapter.authority,
                    destination["adapter_id"],
                    connection["settings"],
                    controlled=adapter.controlled_provider_proof,
                )
                try:
                    response = await lower.handle_async_request(request)
                    body = await read_response(response)
                    return httpx.Response(
                        response.status_code,
                        headers=response.headers,
                        content=body,
                        request=request,
                    )
                finally:
                    await lower.aclose()

            async def aclose(self):
                await adapter.lower.aclose()

        self.guard = GuardTransport(SelectedLower())

    def _record_send(self, invocation):
        target = os.environ.get("EZLLMROUTER_DEV04_SEND_EVENTS")
        if not target:
            return
        row = {
            "attempt_id": invocation.attempt_id,
            "first_bytes_accepted_by_local_socket": invocation.first_bytes_accepted,
            "first_acceptance_events": (
                invocation.observations.count("FIRST_BYTES_ACCEPTED_BY_LOCAL_SOCKET")
                + invocation.observations.count("FIRST_TLS_REQUEST_BYTES_ACCEPTED_BY_LOCAL_SOCKET")
            ),
            "lower_error": invocation.lower_error,
            "monotonic_ns": time.monotonic_ns(),
        }
        enqueue_event(target, row)

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
        return {
            "method": "POST",
            "url": url,
            "content_type": "application/json",
            "content_length": len(prepared),
            "body_sha256": hashlib.sha256(prepared).hexdigest(),
            "timeout_ms": timeout_ms,
            "processing_region": destination["processing_region"],
        }

    @staticmethod
    def _worker_command(value, timeout):
        return exchange(LINK / "worker.sock", value, timeout)

    def send_with_context(self, prepared, timeout_ms, expected, guard_context):
        actual = self.describe(prepared, timeout_ms, guard_context["plan"]["destination"])
        if actual != expected:
            raise ContractError("FDC_REJECTED", 409)
        invocation = Invocation(**guard_context)
        invocation.provider_key = self.provider_key
        budget = remaining_seconds(timeout_ms, invocation.deadline)
        invocation.execution_deadline = min(
            datetime.fromisoformat(invocation.deadline.replace("Z", "+00:00")),
            datetime.now(timezone.utc) + timedelta(seconds=budget),
        ).isoformat()
        invocation.authority_gate = self.authority.gate
        try:
            invocation.authority_epoch = self.authority.snapshot_epoch()
        except GuardRejected as exc:
            raise ContractError("FDC_REJECTED", 409) from exc
        with self.lock:
            if getattr(self, "_closed", False):
                raise ContractError("FDC_REJECTED", 409)
            if invocation.attempt_id in self.registry:
                raise ContractError("FDC_REJECTED", 409)
            self.registry[invocation.attempt_id] = invocation
        try:
            try:
                self._worker_command(
                    {
                        "kind": "selected_request",
                        "route": "responses"
                        if invocation.plan["destination"].get("service") == "openai.responses.v1"
                        else "chat",
                        "attempt_id": invocation.attempt_id,
                        "prepared_b64": base64.b64encode(prepared).decode("ascii"),
                        "timeout_ms": timeout_ms,
                        "deadline": invocation.deadline,
                    },
                    remaining_seconds(timeout_ms, invocation.deadline) + 5,
                )
            except Exception as exc:
                log_failure("gateway.worker.command_failed")
                # An untrusted worker failure does not settle a trusted relay.
                worker_failure = exc
            else:
                worker_failure = None
            with invocation.authority_gate:
                future = invocation.relay_future
            if future is None:
                self._reject_or_unknown(invocation, worker_failure)
            try:
                timeout = (
                    0 if future.done() else remaining_seconds(timeout_ms, invocation.deadline) + 1
                )
                result = future.result(timeout=timeout)
            except Exception as exc:
                self._reject_or_unknown(invocation, exc)
            status = result.get("status")
            if type(status) is not int:
                raise OSError("trusted relay response missing status")
            if status != 200:
                return {"status": status, "body": None}
            raw = base64.b64decode(result["body_b64"], validate=True)
            return {
                "status": 200,
                "body": self._candidate(
                    json.loads(raw),
                    invocation.plan["destination"].get("service") == "openai.responses.v1",
                ),
            }
        finally:
            with invocation.authority_gate:
                invocation.abandoned = True
                future = invocation.relay_future
            if future is not None and not future.done():
                future.cancel()
            with self.lock:
                self.registry.pop(invocation.attempt_id, None)
                self.claimed.discard(invocation.attempt_id)

    @staticmethod
    def _reject_or_unknown(invocation, cause):
        with invocation.authority_gate:
            invocation.abandoned = True
            possible_send = invocation.first_bytes_accepted
        if possible_send:
            raise OSError("trusted sender outcome uncertain") from cause
        code = (
            "INTENT_PERSIST_FAILED"
            if invocation.guard_error == "INTENT_PERSIST_FAILED"
            else "FDC_REJECTED"
        )
        raise ContractError(code, 503 if code == "INTENT_PERSIST_FAILED" else 409) from cause

    def process_relay(self, envelope):
        if set(envelope) != {
            "kind",
            "attempt_id",
            "method",
            "url",
            "headers",
            "body_b64",
            "timeout",
        }:
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
        expected_url = (
            destination["endpoint"].rstrip("/") + "/v1/responses"
            if provider_route
            else PROVIDER_URL
        )
        if envelope["url"] != expected_url:
            raise ValueError("relay destination")
        work_key = invocation.plan.get("work_key")
        # WorkKey has four identifier strings and one positive safe integer.
        # Do not coerce the signed revision, or accept bool as an integer.
        if (
            type(work_key) is not dict
            or any(
                type(work_key.get(field)) is not str or not work_key[field]
                for field in ("principal_id", "task_id", "step_id", "execution_generation")
            )
            or type(work_key.get("step_revision")) is not int
            or not 1 <= work_key["step_revision"] <= SAFE
        ):
            raise ValueError("registered attempt missing required work identity")
        headers = envelope["headers"]
        if type(headers) is not list or any(
            type(pair) is not list or len(pair) != 2 or any(type(item) is not str for item in pair)
            for pair in headers
        ):
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
            if (
                not connection
                or connection["status"] != "active"
                or connection["revision"] != destination["connection_revision"]
                or connection["credential_version"] != destination["credential_version"]
                or connection["settings"]["origin"] != destination["endpoint"]
            ):
                raise ValueError("provider binding stale")
            provider_key = self.provider_registry.provider_vault.resolve(
                destination["connection_id"], destination["credential_version"]
            )
            invocation.provider_key = provider_key
        else:
            provider_key = self.provider_key
            invocation.provider_key = provider_key
        header_map["authorization"] = "Bearer " + provider_key
        request = httpx.Request(
            "POST", expected_url, headers=header_map, content=body, extensions={"timeout": timeout}
        )
        with invocation.authority_gate:
            if invocation.abandoned:
                raise GuardRejected("ATTEMPT_ABANDONED")
            future = self._call(self._send(request, invocation))
            invocation.relay_future = future
        try:
            timeout = (
                0
                if future.done()
                else remaining_seconds(
                    invocation.plan["per_attempt_total_timeout_ms"], invocation.deadline
                )
                + 1
            )
            return future.result(timeout=timeout)
        except Exception:
            future.cancel()
            raise

    async def _send(self, request, invocation):
        token = ACTIVE.set(invocation)
        try:
            async with asyncio.timeout(
                remaining_seconds(
                    invocation.plan["per_attempt_total_timeout_ms"], invocation.deadline
                )
            ):
                response = await self.guard.handle_async_request(request)
                raw = await read_response(response)
            return {
                "status": response.status_code,
                "body_b64": base64.b64encode(raw).decode("ascii"),
                "headers": [
                    ["content-type", response.headers.get("content-type", "application/json")]
                ],
            }
        except Exception as exc:
            if not isinstance(exc, (ContractError, GuardRejected)):
                log_failure("gateway.sender.request_failed")
            raise
        finally:
            self._record_send(invocation)
            ACTIVE.reset(token)

    @staticmethod
    def _candidate(provider, responses=False):
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
            result = {"text": text}
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

    def _remove_socket(self):
        try:
            status = self._socket_path.lstat()
        except FileNotFoundError:
            return
        if (status.st_dev, status.st_ino) == self._socket_identity:
            self._socket_path.unlink()

    async def _cleanup(self):
        transport = getattr(self, "guard", None) or getattr(self, "lower", None)
        if transport is not None:
            await transport.aclose()

    def close(self):
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            with self.lock:
                invocations = tuple(self.registry.values())
            for invocation in invocations:
                with invocation.authority_gate:
                    invocation.abandoned = True
                    if invocation.relay_future is not None:
                        invocation.relay_future.cancel()
            # Every callback runs even if another cleanup step fails.
            with ExitStack() as cleanup:
                cleanup.callback(flush_events)
                cleanup.callback(self._runtime.close, self._cleanup())
                cleanup.callback(self._remove_socket)
                if self.server is not None:
                    cleanup.callback(self.server.server_close)
                if self.server_thread is not None and self.server_thread.is_alive():
                    self.server.shutdown()
                    self.server_thread.join(timeout=5)
