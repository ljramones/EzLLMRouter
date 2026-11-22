"""DEV-04 final HTTPX guard for the selected LiteLLM/OpenAI SDK path."""

from __future__ import annotations

from pathlib import Path
from typing import cast
from ..records import Record

import asyncio
import atexit
import hashlib
import json
import math
import os
import queue
import threading
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Protocol, TypeVar
from concurrent.futures import Future
from contextlib import AbstractContextManager
from ..execution_policy import PROVIDER_URL as PROVIDER_URL, valid_provider_key

import httpx

from ezllmrouter_server.canonical import ContractError
from ezllmrouter_server.errors import ServerError
from ezllmrouter_server.observability import log_failure

from ezllmrouter_server.runtime_resources import BoundedExecutor
from ezllmrouter_server.diagnostic_journal import append_event

from .proxy_recipe import require_public_destination

RECIPE_VERSION = "recipe.dev04.openai-sdk.v2"


R = TypeVar("R")


class CheckExecutor(Protocol):
    def submit(self, action: Callable[[], R]) -> Future[R]: ...


class GuardRejected(ServerError, RuntimeError):
    def __init__(self, code: str = "FDC_REJECTED") -> None:
        super().__init__(code)
        self.code = code


@dataclass
class Invocation:
    submission_id: str
    attempt_id: str
    plan: Record
    projection: Record
    fresh_check: Callable[[], None]
    commit: Callable[[Record], None]
    attempted: bool = False
    committed: bool = False
    released: bool = False
    first_bytes_accepted: bool = False
    authority_epoch: int | None = None
    response_received: bool = False
    guard_error: str | None = None
    lower_error: str | None = None
    provider_key: str | None = field(default=None, repr=False)
    abandoned: bool = False
    execution_deadline: str | None = None
    authority_gate: AbstractContextManager[object] = field(
        default_factory=threading.RLock, repr=False
    )
    check_executor: CheckExecutor | None = field(default=None, repr=False)
    relay_future: Future[Record] | None = field(default=None, repr=False)
    observations: list[str] = field(default_factory=list)

    @property
    def deadline(self) -> str:
        return cast(
            str, self.execution_deadline or self.plan.get("deadline", self.plan.get("expires_at"))
        )


async def run_check(invocation: Invocation, action: Callable[[], R]) -> R:
    """Keep blocking registry/SQLite checks off the provider response loop."""
    executor = invocation.check_executor
    if executor is None:
        return await asyncio.to_thread(action)
    return await asyncio.wrap_future(executor.submit(action))


SDK_HEADERS = frozenset(
    {
        "x-stainless-lang",
        "x-stainless-package-version",
        "x-stainless-os",
        "x-stainless-arch",
        "x-stainless-runtime",
        "x-stainless-runtime-version",
        "x-stainless-retry-count",
        "x-stainless-read-timeout",
        "x-stainless-async",
        "x-stainless-raw-response",
    }
)

ACTIVE: ContextVar[Invocation | None] = ContextVar("ezllmrouter_gateway_invocation", default=None)
_EVENT_QUEUE: queue.Queue[tuple[str | Path, Record] | tuple[None, threading.Event]] = queue.Queue(
    maxsize=1024
)
_EVENT_START = threading.Lock()
_EVENT_WRITER: threading.Thread | None = None
_EVENT_COUNTS = {"written": 0, "dropped": 0, "write_errors": 0}
_EVENT_COUNT_LOCK = threading.Lock()


def _write_events() -> None:
    while True:
        target, row = _EVENT_QUEUE.get()
        try:
            if target is None:
                cast(threading.Event, row).set()
                continue
            append_event(target, cast(Record, row))
            with _EVENT_COUNT_LOCK:
                _EVENT_COUNTS["written"] += 1
        except (OSError, ValueError, TypeError):
            with _EVENT_COUNT_LOCK:
                _EVENT_COUNTS["write_errors"] += 1
            log_failure("gateway.diagnostic_write_failed")
        finally:
            _EVENT_QUEUE.task_done()


def enqueue_event(target: str | Path | None, row: Record) -> None:
    global _EVENT_WRITER
    if not target:
        return
    try:
        with _EVENT_START:
            if _EVENT_WRITER is None:
                writer = threading.Thread(
                    target=_write_events, daemon=True, name="ezllmrouter-gateway-diagnostics"
                )
                writer.start()
                _EVENT_WRITER = writer
        _EVENT_QUEUE.put_nowait((target, row))
    except (queue.Full, RuntimeError):
        # Diagnostics neither authorize nor settle work.
        with _EVENT_COUNT_LOCK:
            _EVENT_COUNTS["dropped"] += 1
        return


def diagnostic_status() -> dict[str, int]:
    with _EVENT_COUNT_LOCK:
        return {**_EVENT_COUNTS, "queued": _EVENT_QUEUE.qsize(), "capacity": _EVENT_QUEUE.maxsize}


def flush_events(timeout: float = 1) -> bool:
    if _EVENT_WRITER is None:
        return True
    done = threading.Event()
    try:
        _EVENT_QUEUE.put_nowait((None, done))
    except queue.Full:
        return False
    return done.wait(timeout)


atexit.register(flush_events)


def _event(invocation: Invocation | None, stage: str, code: str | None = None) -> None:
    target = os.environ.get("EZLLMROUTER_GATEWAY_GUARD_EVENTS")
    if not target:
        return
    row = {
        "attempt_id": invocation.attempt_id if invocation else None,
        "stage": stage,
        "code": code,
        "at": datetime.now(timezone.utc).isoformat(),
        "monotonic_ns": time.monotonic_ns(),
    }
    enqueue_event(target, row)


def _text(blocks: list[Record]) -> str:
    return "\n".join(block["text"] for block in blocks)


def provider_expectation(projected: Record) -> Record:
    """Independent versioned map from admitted work to provider semantics."""
    work, destination = projected["work"], projected["destination"]
    try:
        require_public_destination(destination)
    except (AttributeError, ValueError) as exc:
        raise GuardRejected() from exc
    messages = []
    for message in work["messages"]:
        role, blocks = message["role"], message["blocks"]
        if role in ("system", "user"):
            messages.append({"role": role, "content": _text(blocks)})
        elif role == "assistant":
            calls = [
                {
                    "id": block["call_id"],
                    "type": "function",
                    "function": {
                        "name": block["tool_name"],
                        "arguments": json.dumps(
                            block["arguments"],
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    },
                }
                for block in blocks
                if block["kind"] == "tool_call"
            ]
            item: Record = {
                "role": "assistant",
                "content": _text([block for block in blocks if block["kind"] == "assistant_text"]),
            }
            if calls:
                item["tool_calls"] = calls
            messages.append(item)
        elif role == "tool":
            for block in blocks:
                content = (
                    block["result_text"]
                    if "result_text" in block
                    else json.dumps(
                        block["result_value"],
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
                messages.append(
                    {"role": "tool", "tool_call_id": block["call_id"], "content": content}
                )
        else:
            raise GuardRejected()
    expected = {
        "model": destination["model"],
        "messages": messages,
        "max_tokens": work["generation_settings"]["max_output_tokens"],
        "temperature": 0,
    }
    if "tools" in work["requested_features"]:
        expected["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["input_schema"],
                },
            }
            for tool in work["tool_definitions"]
        ]
        expected["tool_choice"] = work["tool_choice"]
    return expected


def responses_expectation(projected: Record) -> Record:
    """Independent selected Responses map; reject every unsupported message/feature."""
    destination, work = projected["destination"], projected["work"]
    if (
        destination.get("service") != "openai.responses.v1"
        or destination.get("adapter_id") != "openai.responses.v1"
        or set(work["requested_features"]) != {"text"}
        or work["generation_settings"]["temperature_decimal"] != "0"
    ):
        raise GuardRejected()
    messages = []
    for item in work["messages"]:
        role = item["role"]
        if role not in ("system", "user") or any(
            block.get("kind") != ("system_text" if role == "system" else "content_text")
            for block in item["blocks"]
        ):
            raise GuardRejected()
        messages.append(
            {
                "role": role,
                "content": [
                    {
                        "type": "input_text",
                        "text": "\n".join(block["text"] for block in item["blocks"]),
                    }
                ],
            }
        )
    return {
        "model": destination["model"],
        "input": messages,
        "max_output_tokens": work["generation_settings"]["max_output_tokens"],
        "temperature": 0,
        "store": False,
    }


def check_request(request: httpx.Request, invocation: Invocation, body: bytes) -> Record:
    plan = invocation.plan
    if plan.get("plan_version") == "dev12-plan@1":
        from .retrieval_guard import check_synthetic_request

        return check_synthetic_request(request, invocation, body)
    provider_route = plan.get("destination", {}).get("service") == "openai.responses.v1"
    expected = (
        responses_expectation(invocation.projection)
        if provider_route
        else provider_expectation(invocation.projection)
    )
    expected_url = (
        plan["destination"]["endpoint"].rstrip("/") + "/v1/responses"
        if provider_route
        else PROVIDER_URL
    )
    if request.method != "POST" or str(request.url) != expected_url:
        raise GuardRejected()
    headers = _validate_request_headers(body, invocation, provider_route, request)
    try:
        actual = json.loads(body)
    except (UnicodeError, ValueError) as exc:
        raise GuardRejected() from exc
    if type(actual) is not dict:
        raise GuardRejected()
    # The pinned SDK may omit explicit false streaming and the no-tools choice.
    # Those two omitted fields have the same selected non-streaming semantics.
    actual = dict(actual)
    if actual.pop("stream", False) is not False:
        raise GuardRejected()
    if (
        not provider_route
        and "tools" not in expected
        and actual.pop("tool_choice", "none") != "none"
    ):
        raise GuardRejected()
    if actual != expected:
        raise GuardRejected()
    timeout = request.extensions.get("timeout")
    limit = plan["per_attempt_total_timeout_ms"] / 1000
    read_timeout_header = headers.get("x-stainless-read-timeout")
    try:
        read_timeout_ok = read_timeout_header is None or 0 < float(read_timeout_header) <= limit
    except ValueError:
        read_timeout_ok = False
    if (
        type(timeout) is not dict
        or set(timeout) != {"connect", "read", "write", "pool"}
        or not read_timeout_ok
        or any(
            type(value) not in (int, float)
            or not math.isfinite(value)
            or value <= 0
            or value > limit
            for value in timeout.values()
        )
    ):
        raise GuardRejected()
    return {
        "attempt_id": invocation.attempt_id,
        "plan_id": plan["plan_id"],
        "work_digest": plan["work_digest"],
        "recipe_version": "recipe.dev08.openai.responses.text.v1"
        if provider_route
        else RECIPE_VERSION,
        "method": request.method,
        "url": str(request.url),
        "body_sha256": hashlib.sha256(body).hexdigest(),
        "body_bytes": len(body),
        "timeout_seconds": timeout,
        "committed_at": datetime.now(timezone.utc).isoformat(),
    }


class GuardTransport(httpx.AsyncBaseTransport):
    """One lower HTTPX invocation per authenticated in-process work context."""

    def __init__(self, lower: httpx.AsyncBaseTransport) -> None:
        self.lower = lower
        self.checks = BoundedExecutor(
            max_workers=2, max_pending=32, thread_name_prefix="ezllmrouter-send-check"
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        invocation = ACTIVE.get()
        if invocation is None:
            _event(None, "blocked", "NO_TRUSTED_CONTEXT")
            raise GuardRejected("NO_TRUSTED_CONTEXT")
        if invocation.attempted:
            # A rejected retry must not erase the cause of the first blocked send.
            if invocation.guard_error is None:
                invocation.guard_error = "SECOND_SEND_REJECTED"
            invocation.observations.append("second_transport_invocation_blocked")
            _event(invocation, "blocked", "SECOND_SEND_REJECTED")
            raise GuardRejected("SECOND_SEND_REJECTED")
        invocation.attempted = True
        _event(invocation, "entered")
        try:
            body = await request.aread()
            # A named DEV-04 transport control, added before the complete check.
            request.headers["x-ezllmrouter-attempt"] = invocation.attempt_id
            receipt = check_request(request, invocation, body)
            invocation.check_executor = self.checks

            def authorize() -> None:
                with invocation.authority_gate:
                    if invocation.abandoned:
                        raise GuardRejected("ATTEMPT_ABANDONED")
                    invocation.fresh_check()
                    try:
                        invocation.commit(receipt)
                    except Exception as exc:
                        log_failure("gateway.guard.intent_commit_failed")
                        raise GuardRejected("INTENT_PERSIST_FAILED") from exc
                    invocation.committed = True
                    invocation.observations.append("guard_commit_acknowledged")
                    _event(invocation, "commit_acknowledged")
                    invocation.released = True
                    _event(invocation, "released_to_lower_transport")

            await run_check(invocation, authorize)
            response = await self.lower.handle_async_request(request)
            invocation.response_received = True
            return response
        except BaseException as exc:
            if not isinstance(exc, (GuardRejected, ContractError, asyncio.CancelledError)):
                log_failure(
                    "gateway.guard.lower_failed"
                    if invocation.released
                    else "gateway.guard.check_failed"
                )
            if invocation.released:
                invocation.lower_error = type(exc).__name__
                _event(invocation, "lower_error", invocation.lower_error)
            else:
                invocation.guard_error = (
                    exc.code if isinstance(exc, GuardRejected) else "FDC_REJECTED"
                )
                _event(invocation, "blocked", invocation.guard_error)
            raise

    async def aclose(self) -> None:
        try:
            await self.lower.aclose()
        finally:
            await asyncio.to_thread(self.checks.shutdown, wait=True, cancel_futures=True)


def _validate_request_headers(
    body: bytes, invocation: Invocation, provider_route: bool, request: httpx.Request
) -> httpx.Headers:
    headers = request.headers
    provider_key = invocation.provider_key
    if not valid_provider_key(provider_key, responses=provider_route):
        raise GuardRejected()
    if (
        headers.get("host") != request.url.netloc.decode()
        or headers.get("content-type", "").split(";", 1)[0] != "application/json"
        or headers.get("authorization") != "Bearer " + provider_key
        or headers.get("x-ezllmrouter-attempt") != invocation.attempt_id
        or headers.get("x-stainless-retry-count", "0") != "0"
    ):
        raise GuardRejected()
    if any(
        name in headers
        for name in (
            "proxy-authorization",
            "cookie",
            "idempotency-key",
            "openai-organization",
            "openai-project",
        )
    ):
        raise GuardRejected()
    allowed_headers = {
        "host",
        "content-type",
        "authorization",
        "content-length",
        "accept",
        "accept-encoding",
        "user-agent",
        "connection",
        "x-ezllmrouter-attempt",
    }
    if any(name not in allowed_headers | SDK_HEADERS for name in headers) or any(
        len(value) > 256 for name, value in headers.items() if name in SDK_HEADERS
    ):
        raise GuardRejected()
    if headers.get("content-length") and headers["content-length"] != str(len(body)):
        raise GuardRejected()
    return headers
