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


@lru_cache(maxsize=1)
def _operator_routes() -> tuple[tuple[str, str, bool], ...]:
    # The copied worker logger must remain importable with only the stdlib.
    if not __package__:
        return ()
    from .operator_http.routing import ROUTES

    return tuple(
        sorted(((row.method, row.path, row.family) for row in ROUTES), key=lambda row: -len(row[1]))
    )


def _operator_tail(method: str, prefix: str, parts: list[str]) -> list[str]:
    first = {
        "/operator/v1/integration/": {"datasets", "accounts", "connections", "report", "export"},
        "/operator/v1/scripted-demo/": {"report", "workflow"},
        "/operator/v1/local-connectors/": {"check", "find"} if method == "POST" else set(),
        "/operator/v1/demos/": {"text", "tool", "no_store_text"},
    }.get(prefix, set())
    second = {
        "/operator/v1/users/": {"password"},
        "/operator/v1/local-connectors/": {"discover", "models"},
        "/operator/v1/connections/": {"inventory"},
    }.get(prefix, set())
    result = [":id"] * len(parts)
    if parts and parts[0] in first:
        result[0] = parts[0]
    if len(parts) > 1 and parts[1] in second:
        result[1] = parts[1]
    if prefix == "/operator/v1/integration/" and len(parts) > 2:
        actions = {
            "connections": {"save", "refresh", "replace", "disable", "retire"},
            "accounts": {"state", "permissions"},
        }.get(parts[0], set())
        if parts[2] in actions:
            result[2] = parts[2]
    return result


def _wire_label(parts: list[str]) -> list[str] | None:
    if (
        len(parts) >= 2
        and parts[0] == "v1"
        and parts[1] in {"capabilities", "submissions", "attribution-runs", "outcomes"}
    ):
        result = parts[:2] + [":id"] * (len(parts) - 2)
        if len(parts) > 3 and parts[1] == "submissions" and parts[2] == "by-work":
            result[2] = "by-work"
        return result
    if len(parts) < 3 or parts[0] != "integration" or parts[1] not in {"v1", "v2", "v3"}:
        return None
    result = parts[:2] + [":id"] * (len(parts) - 2)
    resource = parts[2]
    if resource in {"datasets", "accounts", "events", "snapshots", "reports", "credentials"}:
        result[2] = resource
    if len(parts) > 3 and (
        (resource == "reports" and parts[3] in {"usage", "dataset"})
        or (resource == "credentials" and parts[3] == "bindings")
    ):
        result[3] = parts[3]
    if len(parts) > 4:
        actions = {
            "accounts": {"state", "permissions", "eligibility"},
            "events": {"receipt"},
            "credentials": {"resolve"},
        }.get(resource, set())
        if parts[4] in actions:
            result[4] = parts[4]
    return result


def safe_route(method: str, path: str) -> str:
    try:
        selected = urlsplit(path).path
    except ValueError:
        return "/:id"
    for verb, prefix, family in _operator_routes():
        if verb != method:
            continue
        if not family and selected == prefix:
            return prefix
        if family and selected.startswith(prefix):
            tail = [part for part in selected[len(prefix) :].split("/") if part][:7]
            return prefix.rstrip("/") + (
                "/" + "/".join(_operator_tail(method, prefix, tail)) if tail else ""
            )
    parts = [part for part in selected.split("/") if part][:10]
    label = _wire_label(parts)
    if label is not None:
        return "/" + "/".join(label)
    if parts[:2] == ["operator", "v1"]:
        return "/operator/v1" + "/:id" * (len(parts) - 2)
    return "/" + "/".join(":id" for _part in parts)


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
    route = safe_route(method, path)
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
