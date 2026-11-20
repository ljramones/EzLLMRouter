"""Structured operational events that never serialize requests or exception values."""

from __future__ import annotations

from datetime import datetime, timezone
from contextvars import ContextVar
from functools import lru_cache
import json
import logging
from pathlib import PurePath
import sys
import traceback
from typing import TextIO
from urllib.parse import urlsplit

LOGGER = logging.getLogger("ezllmrouter")
LOGGER.addHandler(logging.NullHandler())
REQUEST_CORRELATION: ContextVar[str | None] = ContextVar("request_correlation", default=None)
_BASE_ROUTE_WORDS = frozenset(
    (
        "operator v1 v2 v3 integration capabilities session login logout account password users principals models "
        "connections local-connectors registry providers activity usage usage-costs overview config build access explain "
        "datasets events receipts report export credential resolve credentials connect replace refresh retire save disable "
        "check availability nearby find discover provision demos launch snapshots eligibility accounts "
        "app.js app.css index.html integration_console.css users_view.js local_connectors_view.js "
        "catalogue_view.js activity_usage_view.js crud_view.js providers_view.js source_pages.js usage_costs_view.js "
        "demo_workspace_view.js demo_workspace_team_view.js scripted_demo_view.js integration_view.js integration_console.js "
        "integration_accounting.js"
    ).split()
)


@lru_cache(maxsize=1)
def route_words() -> frozenset[str]:
    # This module is also copied as a standalone worker logger. Only HTTP
    # processes need the operator router; keep the worker copy stdlib-only.
    if not __package__:
        return _BASE_ROUTE_WORDS
    from .operator_http.routing import ROUTES

    return _BASE_ROUTE_WORDS | frozenset(
        segment for route in ROUTES for segment in route.path.split("/") if segment
    )


class EventFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event = {
            "at": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "event": getattr(record, "event", "operational_event"),
        }
        for key in (
            "exception_type",
            "code",
            "stack",
            "correlation_id",
            "status",
            "method",
            "route",
            "elapsed_ms",
        ):
            if hasattr(record, key):
                event[key] = getattr(record, key)
        return json.dumps(event, ensure_ascii=True, separators=(",", ":"))


def configure_logging(stream: TextIO | None = None) -> None:
    handler = logging.StreamHandler(stream)
    handler.setFormatter(EventFormatter())
    LOGGER.handlers[:] = [handler]
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False


def log_failure(
    event: str,
    error: BaseException | None = None,
    *,
    correlation_id: str | None = None,
    status: int | None = None,
) -> None:
    """Record stack locations and exception type, excluding messages and locals.

    Exception strings, source lines, URLs and HTTP logging arguments can contain
    credentials or customer content. They are deliberately never passed to logging.
    """
    error = error if error is not None else sys.exception()
    if error is None:
        return
    frames = traceback.extract_tb(error.__traceback__)
    fields: dict[str, object] = {
        "event": event,
        "exception_type": type(error).__name__,
        "stack": [
            {"file": PurePath(frame.filename).name, "function": frame.name, "line": frame.lineno}
            for frame in frames
        ],
    }
    correlation_id = correlation_id or REQUEST_CORRELATION.get()
    if correlation_id is not None:
        fields["correlation_id"] = correlation_id
    if status is not None:
        fields["status"] = status
    LOGGER.error(event, extra=fields)


def log_rejection(event: str, *, code: str, status: int) -> None:
    """Expected domain errors carry a public code, never a stack or message."""
    fields: dict[str, object] = {"event": event, "code": code, "status": status}
    correlation = REQUEST_CORRELATION.get()
    if correlation is not None:
        fields["correlation_id"] = correlation
    LOGGER.info(event, extra=fields)


def log_http_request(
    method: str, path: str, status: int, elapsed_ms: int, correlation_id: str
) -> None:
    try:
        segments = urlsplit(path).path.split("/")
    except ValueError:
        segments = ["invalid"]
    route = "/" + "/".join(
        segment if segment in route_words() else ":id" for segment in segments[:10] if segment
    )
    LOGGER.info(
        "http_request",
        extra={
            "event": "http_request",
            "method": method
            if method in {"GET", "HEAD", "POST", "DELETE", "PUT", "OPTIONS"}
            else "OTHER",
            "route": route,
            "status": status,
            "elapsed_ms": elapsed_ms,
            "correlation_id": correlation_id,
        },
    )
