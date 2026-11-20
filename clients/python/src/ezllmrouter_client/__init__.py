"""CognitiveDynamics EzLLMRouter synchronous wire-0.2 client for text and caller-owned tools.

Ordinary construction uses HTTPX 0.28.1. ``transport`` may be an object with
``request(method, url, **kwargs)`` and ``close()`` for isolated tests.
"""

from __future__ import annotations

from copy import deepcopy
import json
from urllib.parse import quote
from typing import Any

from ._errors import ClientError
from ._session import ClientSession
from .integration import IntegrationClient
from ._errors import (
    IntegrationClientError as IntegrationClientError,
    IntegrationInputError as IntegrationInputError,
)

from . import _validation as v
from . import _successor_validation as v03
from ._http import WIRE_RESPONSE_LIMIT, SUCCESSOR_RESPONSE_LIMIT

from ._metadata import release_version

__version__ = release_version("cognitivedynamics-ezllmrouter-client", __file__)


class EzLLMRouterError(ClientError):
    """Typed protocol or transport error with query-first recovery context."""

    def __init__(
        self,
        code: str,
        http_status: int | None = None,
        retry_guidance: str = "never",
        correlation_id: str | None = None,
        *,
        selector: dict[str, Any] | None = None,
        handle: dict[str, Any] | None = None,
        attempt_id: str | None = None,
        failure_stage: str | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code, http_status, retry_guidance, correlation_id, selector=selector)
        self.handle = handle
        self.attempt_id = attempt_id
        self.failure_stage = failure_stage
        self.work_key = (
            handle["work_key"]
            if handle is not None and (v.handle(handle) or v03.named_shape(handle, "Handle"))
            else None
        )
        self.error = error


def _matching_handle(
    value: Any, selected: dict[str, Any] | None, *, successor: bool = False
) -> dict[str, Any] | None:
    if type(value) is not dict or selected is None:
        return None
    handle = value.get("handle")
    if type(handle) is not dict:
        return None
    if successor:
        matches = v03.matches_selector(handle, selected)
    elif not v.handle(handle):
        matches = False
    elif "submission_id" in selected:
        matches = handle["submission_id"] == selected["submission_id"]
    else:
        matches = all(handle["work_key"][key] == selected[key] for key in v.SELECTOR)
    return deepcopy(handle) if matches else None


def _wire_data(value: Any, seen: set[int] | None = None, depth: int = 0) -> None:
    if depth > 32:
        raise ValueError("request nesting limit")
    if value is None or type(value) is float:
        raise ValueError("unsupported request value")
    if type(value) is int:
        if abs(value) > 9007199254740991:
            raise ValueError("unsafe integer")
        return
    if type(value) is str:
        if "\0" in value:
            raise ValueError("invalid request text")
        value.encode("utf-8", "strict")
        return
    if type(value) is bool:
        return
    if seen is None:
        seen = set()
    if type(value) not in (dict, list) or id(value) in seen:
        raise ValueError("invalid request container")
    seen.add(id(value))
    try:
        if type(value) is dict:
            for key, item in value.items():
                if type(key) is not str:
                    raise ValueError("non-string key")
                _wire_data(key, seen, depth + 1)
                _wire_data(item, seen, depth + 1)
        else:
            for item in value:
                _wire_data(item, seen, depth + 1)
    finally:
        seen.remove(id(value))


class EzLLMRouterClient(ClientSession):
    """Synchronous client; call ``close`` or use ``with``.

    ``base_url`` is the EzLLMRouter service URL, ``token`` its bearer credential.
    Default connect/read/write/pool timeouts are 10/35/30/10 seconds, allowing
    a 30-second server response wait. The total HTTP budget defaults to 60
    seconds; ``total_timeout=`` overrides it independently of phase timeouts. Redirects,
    environment proxy inheritance and automatic request retries are disabled.
    """

    def _perform(
        self,
        method: str,
        path: str,
        selected: dict[str, Any] | None,
        kind: str,
        *,
        body: bytes | None = None,
        wait_ms: int | None = None,
        attribution_run_id: str | None = None,
    ) -> dict[str, Any]:
        original = dict(selected) if selected is not None else None
        headers = {}
        if wait_ms is not None:
            headers["EzLLMRouter-Wait-Ms"] = str(wait_ms)
        if attribution_run_id is not None:
            headers["EzLLMRouter-Attribution-Version"] = "1"
            headers["EzLLMRouter-Attribution-Run"] = attribution_run_id
        response, value = self._exchange(
            method,
            path,
            version_header="EzLLMRouter-Contract-Version",
            version_field="contract_version",
            version=v.VERSION,
            limit=WIRE_RESPONSE_LIMIT,
            error_type=EzLLMRouterError,
            body=body,
            headers=headers,
            selector=original,
        )
        status = response.status_code
        usable_handle = _matching_handle(value, original)
        try:
            envelope_error = "error" in value and "state" not in value
            valid = (
                (
                    v.shape(value, ("contract_version", "error"))
                    and v.error(value["error"])
                    and status >= 400
                )
                if envelope_error
                else (
                    v.reply(value, status)
                    if kind == "submit"
                    else v.status_snapshot(value, status)
                    if kind == "status"
                    else v.capabilities(value, status)
                )
            )
            corresponds = v.correspondence(value, original, kind)
        except (KeyError, TypeError, ValueError, OverflowError):
            valid = corresponds = False
        if not valid or not corresponds:
            raise EzLLMRouterError(
                "PROTOCOL_INVALID",
                status,
                "query_first",
                selector=original,
                handle=usable_handle,
            )
        if envelope_error or value.get("state") in ("failed", "rejected"):
            err = value["error"]
            raise EzLLMRouterError(
                err["code"],
                status,
                err["retry_guidance"],
                err["correlation_id"],
                selector=original,
                handle=usable_handle,
                attempt_id=value.get("attempt_id"),
                failure_stage=value.get("failure_stage"),
                error=err,
            )
        if not 200 <= status < 300:
            raise EzLLMRouterError(
                "PROTOCOL_INVALID",
                status,
                "query_first",
                selector=original,
                handle=usable_handle,
            )
        return value

    def _submit(
        self, request: dict[str, Any], options: dict[str, Any] | None, run_id: str | None
    ) -> dict[str, Any]:
        if type(request) is not dict:
            raise EzLLMRouterError("SCHEMA_INVALID")
        try:
            copied = deepcopy(request)
            selected = {k: copied[k] for k in v.SELECTOR}
            if not v.selector(selected):
                raise ValueError("invalid work selector")
            _wire_data(copied)
            body = json.dumps(
                copied, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
        except (
            KeyError,
            TypeError,
            ValueError,
            UnicodeError,
            OverflowError,
            RecursionError,
        ) as cause:
            raise EzLLMRouterError("SCHEMA_INVALID") from cause
        if options is not None and (type(options) is not dict or options.keys() - {"wait_ms"}):
            raise EzLLMRouterError("SCHEMA_INVALID")
        wait = None
        if options is not None and "wait_ms" in options:
            wait = options["wait_ms"]
            if type(wait) is not int or not 0 <= wait <= 30000:
                raise EzLLMRouterError("SCHEMA_INVALID")
        return self._perform(
            "POST",
            "/v1/submissions",
            selected,
            "submit",
            body=body,
            wait_ms=wait,
            attribution_run_id=run_id,
        )

    def submit(
        self, request: dict[str, Any], options: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return self._submit(request, options, None)

    def submit_in_run(
        self, request: dict[str, Any], run_id: str, options: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Bind an unchanged strict wire-0.2 request to a preauthorized v1 run."""
        if not v.identifier(run_id):
            raise EzLLMRouterError("SCHEMA_INVALID")
        return self._submit(request, options, run_id)

    def _attribution_operation(
        self, method: str, path: str, payload: dict[str, Any] | None, kind: str
    ) -> dict[str, Any]:
        try:
            if payload is not None:
                _wire_data(payload)
                body = json.dumps(
                    payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False
                ).encode()
            else:
                body = None
        except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
            raise EzLLMRouterError("SCHEMA_INVALID") from exc
        response, value = self._exchange(
            method,
            path,
            version_header="EzLLMRouter-Contract-Version",
            version_field="contract_version",
            version=v.VERSION,
            limit=WIRE_RESPONSE_LIMIT,
            error_type=EzLLMRouterError,
            body=body,
        )
        if (
            response.status_code >= 400
            and set(value) == {"contract_version", "error"}
            and v.error(value["error"])
        ):
            err = value["error"]
            raise EzLLMRouterError(
                err["code"], response.status_code, err["retry_guidance"], err["correlation_id"]
            )
        version = "outcome_version" if kind == "receipt" else "attribution_version"
        result = "receipt" if kind == "receipt" else "run"
        if (
            set(value) != {"contract_version", version, result}
            or value[version] != "1"
            or response.status_code not in ((200, 201) if kind == "receipt" else (200,))
            or type(value[result]) is not dict
        ):
            raise EzLLMRouterError("PROTOCOL_INVALID", response.status_code, "query_first")
        item: dict[str, Any] = value[result]
        if kind == "receipt":
            valid = (
                set(item)
                == {
                    "version",
                    "event_id",
                    "run_id",
                    "kind",
                    "subject_revision",
                    "recorded_at",
                    "event_digest",
                }
                and item["version"] == "1"
                and all(v.identifier(item[key]) for key in ("event_id", "run_id", "event_digest"))
                and v.positive(item["subject_revision"])
                and v.utc(item["recorded_at"])
                and item["kind"] in ("task_outcome", "step_evaluation")
            )
        else:
            required = {
                "run_id",
                "principal_id",
                "charging_owner_id",
                "initiating_user_id",
                "agent_id",
                "agent_version",
                "parent_run_id",
                "root_run_id",
                "task_id",
                "task_class",
                "evaluation_ref",
                "mode",
                "created_at",
                "status",
                "request_digest",
            }
            valid = (
                (set(item) == required or set(item) == required | {"terminal_at"})
                and all(
                    v.identifier(item[key])
                    for key in (
                        "run_id",
                        "principal_id",
                        "charging_owner_id",
                        "root_run_id",
                        "task_id",
                        "task_class",
                        "evaluation_ref",
                        "request_digest",
                    )
                )
                and all(
                    item[key] is None or v.identifier(item[key])
                    for key in ("initiating_user_id", "agent_id", "agent_version", "parent_run_id")
                )
                and item["mode"]
                in ("direct_human", "autonomous_agent", "user_delegated_agent", "nested_agent")
                and item["status"] in ("running", "accepted", "rejected", "abandoned")
                and v.utc(item["created_at"])
                and ("terminal_at" not in item or v.utc(item["terminal_at"]))
            )
        if not valid:
            raise EzLLMRouterError("PROTOCOL_INVALID", response.status_code, "query_first")
        return item

    def start_run(self, run: dict[str, Any]) -> dict[str, Any]:
        required = {"version", "run_id", "task_id", "task_class", "evaluation_ref", "mode"}
        if (
            type(run) is not dict
            or not required <= run.keys()
            or set(run)
            - (required | {"agent_id", "agent_version", "initiating_user_id", "parent_run_id"})
            or run.get("version") != "1"
            or not all(
                v.identifier(run.get(key))
                for key in ("run_id", "task_id", "task_class", "evaluation_ref")
            )
            or not all(
                v.identifier(run[key])
                for key in ("agent_id", "agent_version", "initiating_user_id", "parent_run_id")
                if key in run
            )
            or run["mode"]
            not in ("direct_human", "autonomous_agent", "user_delegated_agent", "nested_agent")
        ):
            raise EzLLMRouterError("SCHEMA_INVALID")
        extras = set(run) - required
        expected = {
            "direct_human": set(),
            "autonomous_agent": {"agent_id", "agent_version"},
            "user_delegated_agent": {"agent_id", "agent_version", "initiating_user_id"},
            "nested_agent": {"agent_id", "agent_version", "parent_run_id"},
        }[run["mode"]]
        if extras != expected:
            raise EzLLMRouterError("SCHEMA_INVALID")
        return self._attribution_operation("POST", "/v1/attribution-runs", deepcopy(run), "run")

    def get_run(self, run_id: str) -> dict[str, Any]:
        if not v.identifier(run_id):
            raise EzLLMRouterError("SCHEMA_INVALID")
        return self._attribution_operation(
            "GET", "/v1/attribution-runs/" + quote(run_id, safe=""), None, "run"
        )

    def report_outcome(self, event: dict[str, Any]) -> dict[str, Any]:
        required = {
            "version",
            "event_id",
            "run_id",
            "kind",
            "subject_revision",
            "verdict",
            "evaluator_version",
            "evidence_ref",
        }
        if (
            type(event) is not dict
            or not required <= event.keys()
            or set(event) - (required | {"step_id", "step_revision", "execution_generation"})
            or event.get("version") != "1"
            or not all(
                v.identifier(event.get(key))
                for key in ("event_id", "run_id", "evaluator_version", "evidence_ref")
            )
            or not v.positive(event["subject_revision"])
            or (
                (
                    event["kind"] == "task_outcome"
                    and (
                        set(event) != required
                        or event["verdict"] not in ("accepted", "rejected", "abandoned")
                    )
                )
                or (
                    event["kind"] == "step_evaluation"
                    and (
                        set(event)
                        != required | {"step_id", "step_revision", "execution_generation"}
                        or not v.identifier(event["step_id"])
                        or not v.positive(event["step_revision"])
                        or not v.identifier(event["execution_generation"])
                        or event["verdict"] not in ("correct", "incorrect", "undetermined")
                    )
                )
                or event["kind"] not in ("task_outcome", "step_evaluation")
            )
        ):
            raise EzLLMRouterError("SCHEMA_INVALID")
        return self._attribution_operation("POST", "/v1/outcomes", deepcopy(event), "receipt")

    def get_outcome_receipt(self, event_id: str) -> dict[str, Any]:
        if not v.identifier(event_id):
            raise EzLLMRouterError("SCHEMA_INVALID")
        return self._attribution_operation(
            "GET", "/v1/outcomes/" + quote(event_id, safe=""), None, "receipt"
        )

    def get_status(
        self, selector: dict[str, Any], *, contract_version: str = "0.2"
    ) -> dict[str, Any]:
        if contract_version == "0.3":
            return self.get_successor_status(selector)
        if contract_version != "0.2":
            raise EzLLMRouterError("UNSUPPORTED_VERSION")
        try:
            selected = deepcopy(selector)
            if v.shape(selected, ("submission_id",)) and v.identifier(selected["submission_id"]):
                path = "/v1/submissions/" + quote(selected["submission_id"], safe="")
            elif v.selector(selected):
                path = "/v1/submissions/by-work/" + "/".join(
                    quote(str(selected[k]), safe="") for k in v.SELECTOR
                )
            else:
                raise ValueError("invalid selector")
        except (TypeError, ValueError, RecursionError) as cause:
            raise EzLLMRouterError("SCHEMA_INVALID") from cause
        return self._perform("GET", path, selected, "status")

    def _successor_request(
        self,
        method: str,
        path: str,
        selector: dict[str, Any],
        *,
        body: bytes | None = None,
        wait_ms: int | None = None,
        kind: str = "submit",
        request: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {}
        if wait_ms is not None:
            headers["EzLLMRouter-Wait-Ms"] = str(wait_ms)
        response, value = self._exchange(
            method,
            path,
            version_header="EzLLMRouter-Contract-Version",
            version_field="contract_version",
            version="0.3",
            limit=SUCCESSOR_RESPONSE_LIMIT,
            error_type=EzLLMRouterError,
            body=body,
            headers=headers,
            selector=selector,
        )
        if "code" in value:
            if not v03.error_valid(value, response.status_code, kind):
                raise EzLLMRouterError(
                    "PROTOCOL_INVALID", response.status_code, "query_first", selector=selector
                )
            raise EzLLMRouterError(
                value["code"],
                response.status_code,
                value["retry_guidance"],
                value["correlation_id"],
                selector=selector,
            )
        name = "SubmitReply" if kind == "submit" else "StatusSnapshot"
        usable_handle = _matching_handle(value, selector, successor=True)
        if not v03.response_valid(value, name, response.status_code, selector, request):
            raise EzLLMRouterError(
                "PROTOCOL_INVALID",
                response.status_code,
                "query_first",
                selector=selector,
                handle=usable_handle,
            )
        if kind == "submit" and value["state"] == "failed":
            error = value["error"]
            raise EzLLMRouterError(
                error["code"],
                response.status_code,
                error["retry_guidance"],
                error["correlation_id"],
                selector=selector,
                handle=value["handle"],
                attempt_id=value["attempt_id"],
                failure_stage=value["failure_stage"],
                error=error,
            )
        if response.status_code not in (200, 202):
            raise EzLLMRouterError(
                "PROTOCOL_INVALID", response.status_code, "query_first", selector=selector
            )
        return value

    def _submit_successor(
        self, request: dict[str, Any], expected_operation: str, options: dict[str, Any] | None
    ) -> dict[str, Any]:
        if (
            type(request) is not dict
            or request.get("operation") != {"type": expected_operation, "version": 1}
            or request.get("contract_version") != "0.3"
            or not v03.named_shape(request, "SubmitRequest")
        ):
            raise EzLLMRouterError("SCHEMA_INVALID")
        if options is not None and (type(options) is not dict or set(options) - {"wait_ms"}):
            raise EzLLMRouterError("SCHEMA_INVALID")
        wait_ms = options.get("wait_ms") if options else None
        if wait_ms is not None and (type(wait_ms) is not int or not 0 <= wait_ms <= 30000):
            raise EzLLMRouterError("SCHEMA_INVALID")
        selector = deepcopy(request["work_selector"])
        body = json.dumps(
            request, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        if len(body) > 262144:
            raise EzLLMRouterError("LIMIT_EXCEEDED")
        return self._successor_request(
            "POST",
            "/v1/submissions",
            selector,
            body=body,
            wait_ms=wait_ms,
            kind="submit",
            request=deepcopy(request),
        )

    def submit_embedding(
        self, request: dict[str, Any], options: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return self._submit_successor(request, "embedding.create", options)

    def submit_rerank(
        self, request: dict[str, Any], options: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return self._submit_successor(request, "rerank", options)

    def get_successor_status(self, selector: dict[str, Any]) -> dict[str, Any]:
        selected = deepcopy(selector)
        if type(selected) is not dict or not v03.named_shape(selected, "StatusQuery"):
            raise EzLLMRouterError("SCHEMA_INVALID")
        if "submission_id" in selected:
            path = "/v1/submissions/" + quote(selected["submission_id"], safe="")
        else:
            work_selector = selected["work_selector"]
            path = "/v1/submissions/by-work/" + "/".join(
                quote(str(work_selector[key]), safe="")
                for key in ("task_id", "step_id", "step_revision", "execution_generation")
            )
        return self._successor_request(
            "GET", path, selected.get("work_selector", selected), kind="status"
        )

    def get_capabilities(self) -> dict[str, Any]:
        return self._perform("GET", "/v1/capabilities", None, "capabilities")

    def getStatus(
        self, selector: dict[str, Any], *, contract_version: str = "0.2"
    ) -> dict[str, Any]:
        """Compatibility spelling; prefer get_status."""
        return self.get_status(selector, contract_version=contract_version)

    def getCapabilities(self) -> dict[str, Any]:
        """Compatibility spelling; prefer get_capabilities."""
        return self.get_capabilities()


__all__ = [
    "ClientError",
    "IntegrationInputError",
    "EzLLMRouterClient",
    "EzLLMRouterError",
    "IntegrationClient",
    "IntegrationClientError",
    "__version__",
]
