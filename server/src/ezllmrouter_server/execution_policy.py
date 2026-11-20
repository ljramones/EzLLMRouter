"""Dependency-free execution limits and the private worker/proxy boundary."""

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, TypeAlias, TypeGuard

MAX_ATTEMPT_TIMEOUT_MS = 300_000
WORKER_KEY = "sk-dev04-worker-placeholder-not-provider-000000"
PROVIDER_URL = "http://127.0.0.1:8766/v1/chat/completions"
PROXY_URL = "http://127.0.0.1:8767/v1/chat/completions"
PROXY_MODEL = "openai/model.demo"
TRUSTED_CREDENTIAL_ENV = (
    "EZLLMROUTER_SERVICE_TOKEN",
    "EZLLMROUTER_PROVIDER_KEY",
    "OPENAI_API_KEY",
    "EZLLMROUTER_DEV_TOKEN",
    "EZLLMROUTER_DEV04_PROVIDER_KEY",
)

ASGIMessage: TypeAlias = dict[str, Any]
Receive: TypeAlias = Callable[[], Awaitable[ASGIMessage]]
Send: TypeAlias = Callable[[ASGIMessage], Awaitable[None]]
Application: TypeAlias = Callable[[ASGIMessage, Receive, Send], Awaitable[None]]


def valid_provider_key(value: object, *, responses: bool = False) -> TypeGuard[str]:
    return (
        type(value) is str
        and (responses or value.startswith("sk-"))
        and (16 if responses else 36) <= len(value) <= 4096
        and all(33 <= ord(char) <= 126 for char in value)
    )


class RestrictedProxy:
    """Expose one POST route only while the owner supplies an active invocation."""

    def __init__(self, vendor_app: Application, active: Callable[[], bool]) -> None:
        self.vendor_app, self.active = vendor_app, active

    async def __call__(self, scope: ASGIMessage, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("path") != "/v1/chat/completions"
            or scope.get("method") != "POST"
            or not self.active()
        ):
            await send({"type": "http.response.start", "status": 403, "headers": []})
            await send({"type": "http.response.body", "body": b""})
            return
        await self.vendor_app(scope, receive, send)


def trusted_credentials_present(environment: Mapping[str, str]) -> bool:
    return any(
        name in environment for name in TRUSTED_CREDENTIAL_ENV if name != "OPENAI_API_KEY"
    ) or environment.get("OPENAI_API_KEY") not in (None, WORKER_KEY)
