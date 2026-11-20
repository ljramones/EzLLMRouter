"""Common client errors, including legacy TypeError-compatible input errors."""

from typing import Any


class ClientError(Exception):
    """Base for protocol, transport and input errors from either client."""

    def __init__(
        self,
        code: str,
        http_status: int | None = None,
        retry_guidance: str = "never",
        correlation_id: str | None = None,
        *,
        selector: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.http_status = http_status
        self.retry_guidance = retry_guidance
        self.correlation_id = correlation_id
        self.selector = selector


class IntegrationClientError(ClientError):
    """External accounting protocol or delivery failure."""


class IntegrationInputError(IntegrationClientError, TypeError):
    """Invalid accounting input; remains catchable as TypeError."""


def retry_guidance(value: Any, status: int) -> str:
    return (
        value
        if value in ("never", "query_first", "orchestrator_decision")
        else "query_first"
        if status >= 500
        else "never"
    )
