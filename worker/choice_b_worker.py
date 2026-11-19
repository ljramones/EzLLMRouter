"""DEV-04 Choice B LiteLLM worker: no authority, provider key or network route."""

from __future__ import annotations

import asyncio
import base64
from collections import OrderedDict
from contextvars import ContextVar
import hashlib
import json
import os
from pathlib import Path
import socket
import socketserver
import threading

import httpx

from choice_b_wire import receive, remaining_seconds, send
from worker_logging import configure_logging, log_failure


PROVIDER_URL = "http://127.0.0.1:8766/v1/chat/completions"
PROXY_MODEL = "openai/model.demo"
WORKER_KEY = "sk-dev04-worker-placeholder-not-provider-000000"
LINK = Path("/link")
ACTIVE: ContextVar[str | None] = ContextVar("dev04_worker_attempt", default=None)
ACTIVE_BUDGET: ContextVar[tuple[int, str] | None] = ContextVar(
    "ezllmrouter_worker_budget", default=None
)
RECENT_ATTEMPTS = 512


class RelayTransport(httpx.AsyncBaseTransport):
    def __init__(self):
        self.seen = set()
        self.attempt_counts = OrderedDict()

    def claim(self, attempt):
        if (
            type(attempt) is not str
            or not attempt.startswith("attempt.")
            or len(attempt) > 160
            or any(
                char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-"
                for char in attempt
            )
        ):
            raise httpx.TransportError("worker request has no valid attempt reference")
        self.attempt_counts[attempt] = min(self.attempt_counts.get(attempt, 0) + 1, 2)
        self.attempt_counts.move_to_end(attempt)
        if len(self.attempt_counts) > RECENT_ATTEMPTS:
            expired, _ = self.attempt_counts.popitem(last=False)
            self.seen.discard(expired)
        if attempt in self.seen:
            raise httpx.TransportError("worker request has no unused trusted attempt reference")
        self.seen.add(attempt)

    async def handle_async_request(self, request):
        attempt = ACTIVE.get()
        self.claim(attempt)
        budget = ACTIVE_BUDGET.get()
        if budget is None:
            raise httpx.TransportError("worker request has no deadline")
        raw = await request.aread()
        if len(raw) > 65536:
            raise httpx.TransportError("worker request exceeds proof limit")
        envelope = {
            "kind": "final_request",
            "attempt_id": attempt,
            "method": request.method,
            "url": str(request.url),
            "headers": [[key, value] for key, value in request.headers.items()],
            "body_b64": base64.b64encode(raw).decode("ascii"),
            "timeout": request.extensions.get("timeout"),
        }

        def exchange():
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
                stream.settimeout(remaining_seconds(*budget) + 2)
                stream.connect(str(LINK / "sender.sock"))
                send(stream, envelope)
                return receive(stream)

        try:
            result = await asyncio.to_thread(exchange)
        except Exception as exc:
            log_failure("gateway.worker.relay_failed")
            raise httpx.TransportError("trusted sender unavailable") from exc
        if "error_type" in result:
            raise httpx.TransportError("trusted sender rejected final request")
        body = base64.b64decode(result["body_b64"], validate=True)
        return httpx.Response(
            result["status"], headers=result["headers"], content=body, request=request
        )


class RestrictedProxy:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send_response):
        if (
            scope["type"] != "http"
            or scope.get("path") != "/v1/chat/completions"
            or scope.get("method") != "POST"
            or ACTIVE.get() is None
        ):
            await send_response({"type": "http.response.start", "status": 403, "headers": []})
            await send_response({"type": "http.response.body", "body": b""})
            return
        await self.app(scope, receive, send_response)


class Worker:
    def __init__(self):
        if "EZLLMROUTER_DEV_TOKEN" in os.environ or "EZLLMROUTER_DEV04_PROVIDER_KEY" in os.environ:
            raise RuntimeError("trusted credential present in LiteLLM worker")
        os.environ["OPENAI_API_KEY"] = WORKER_KEY
        os.environ["LITELLM_DONT_SHOW_FEEDBACK_BOX"] = "true"
        os.environ["LITELLM_LOG"] = "ERROR"
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(
            target=self._run_loop, daemon=True, name="dev04-litellm-worker"
        )
        self.thread.start()
        asyncio.run_coroutine_threadsafe(self._start(), self.loop).result(timeout=45)

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    async def _start(self):
        import litellm

        if litellm.aclient_session is not None or litellm.client_session is not None:
            raise RuntimeError("alternate LiteLLM HTTP session")
        self.client = httpx.AsyncClient(
            transport=RelayTransport(),
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(1.0),
        )
        # The pinned LiteLLM Responses handler does not use aclient_session.
        # Its supported client= parameter requires AsyncHTTPHandler; bind that
        # handler to the same network-disabled relay transport as Chat.
        from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler

        self.responses_handler = AsyncHTTPHandler(
            transport=self.client._transport, follow_redirects=False
        )
        if self.responses_handler.client._transport is not self.client._transport:
            raise RuntimeError("Responses handler escaped the worker relay")
        litellm.aclient_session = self.client
        litellm.drop_params = False
        litellm.num_retries = 0
        from litellm.proxy import proxy_server

        # Preserve the approved model from the prepared body. A fixed
        # initialize(model=...) overwrites it before LiteLLM's OpenAI call.
        await proxy_server.initialize(
            model=None,
            api_base=PROVIDER_URL.rsplit("/chat/completions", 1)[0],
            request_timeout=1,
            drop_params=False,
            add_function_to_prompt=False,
        )
        if litellm.aclient_session is not self.client or litellm.client_session is not None:
            raise RuntimeError("selected LiteLLM client replaced")
        self.proxy = RestrictedProxy(proxy_server.app)
        import openai

        def module_file(module):
            path = Path(module.__file__)
            return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

        self.module_identities = {
            "boundary": "network-disabled LiteLLM ASGI worker",
            "litellm": module_file(litellm),
            "proxy": module_file(proxy_server),
            "openai_sdk": module_file(openai),
            "httpx": module_file(httpx),
            "selected_transport": type(self.client._transport).__name__,
        }

    async def _selected(self, envelope):
        if set(envelope) != {
            "kind",
            "attempt_id",
            "prepared_b64",
            "route",
            "timeout_ms",
            "deadline",
        } or envelope["route"] not in ("chat", "responses"):
            raise ValueError("worker command shape")
        remaining_seconds(envelope["timeout_ms"], envelope["deadline"])
        attempt = envelope["attempt_id"]
        if type(attempt) is not str or not attempt.startswith("attempt."):
            raise ValueError("worker attempt reference")
        prepared = base64.b64decode(envelope["prepared_b64"], validate=True)
        if not prepared or len(prepared) > 65536:
            raise ValueError("worker prepared size")
        token = ACTIVE.set(attempt)
        budget_token = ACTIVE_BUDGET.set((envelope["timeout_ms"], envelope["deadline"]))
        try:
            if envelope["route"] == "responses":
                import litellm

                body = json.loads(prepared)
                if (
                    type(body) is not dict
                    or body.get("stream") is not False
                    or body.get("store") is not False
                    or body.get("max_retries") != 0
                    or not str(body.get("model", "")).startswith("openai/")
                    or type(body.get("api_base")) is not str
                ):
                    raise ValueError("invalid selected Responses recipe")
                if self.responses_handler.client._transport is not self.client._transport:
                    raise RuntimeError("Responses handler relay changed")
                response = await litellm.aresponses(
                    **body,
                    api_key=WORKER_KEY,
                    client=self.responses_handler,
                    extra_headers={"X-EzLLMRouter-Attempt": attempt},
                )
                if (
                    litellm.aclient_session is not self.client
                    or self.responses_handler.client._transport is not self.client._transport
                ):
                    raise RuntimeError("selected LiteLLM session changed")
                # Preserve provider omission versus explicit null/zero in
                # nested usage details. Pydantic's default dump fills absent
                # optional counters with None, which would erase evidence.
                return {"status": 200, "body": response.model_dump(mode="json", exclude_unset=True)}
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.proxy),
                base_url="http://127.0.0.1:8767",
                follow_redirects=False,
                trust_env=False,
                timeout=httpx.Timeout(
                    remaining_seconds(envelope["timeout_ms"], envelope["deadline"])
                ),
            ) as client:
                response = await client.post(
                    "/v1/chat/completions",
                    content=prepared,
                    headers={"Content-Type": "application/json"},
                )
            return {
                "status": response.status_code,
                "body": response.json() if response.status_code == 200 else None,
            }
        finally:
            ACTIVE_BUDGET.reset(budget_token)
            ACTIVE.reset(token)

    def dispatch(self, envelope):
        kind = envelope.get("kind")
        if kind == "module_identity" and set(envelope) == {"kind"}:
            return {
                **self.module_identities,
                "relay_attempt_counts": dict(self.client._transport.attempt_counts),
            }
        if kind == "selected_request":
            timeout = remaining_seconds(envelope["timeout_ms"], envelope["deadline"]) + 2
            coro = self._selected(envelope)
        else:
            raise ValueError("unknown worker command")
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        try:
            return future.result(timeout=timeout)
        except BaseException:
            future.cancel()
            raise


class _ThreadingUnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = False


def handle_command(worker, stream):
    try:
        result = worker.dispatch(receive(stream))
    except Exception as exc:
        log_failure("gateway.worker.command_failed")
        result = {"error_type": type(exc).__name__}
    try:
        send(stream, result)
    except Exception:
        log_failure("gateway.worker.reply_failed")


def _serve():
    worker = Worker()
    path = LINK / "worker.sock"
    if path.exists() or path.is_symlink():
        raise RuntimeError("Choice B worker socket collision")

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            handle_command(worker, self.request)

    server = _ThreadingUnixServer(str(path), Handler)
    os.chmod(path, 0o600)
    server.serve_forever()


def main():
    configure_logging()
    try:
        _serve()
    except Exception:
        log_failure("gateway.worker.start_or_serve_failed")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
