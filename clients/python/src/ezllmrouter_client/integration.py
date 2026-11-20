"""Synchronous external-observation HTTP client, without automatic delivery retry."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
import re
from urllib.parse import quote
from typing import Any

from ._http import DEFAULT_TIMEOUT, INTEGRATION_RESPONSE_LIMIT
from ._deadline import DEFAULT_TOTAL_TIMEOUT
from ._errors import IntegrationClientError, IntegrationInputError
from ._schema_validation import validate
from ._session import ClientSession
from ._json import strict_reply

SCHEMAS = {
    version: json.loads((Path(__file__).parent / filename).read_text())["$defs"]
    for version, filename in (
        ("1", "integration_schema.json"),
        ("2", "integration_schema_v2.json"),
        ("3", "integration_schema_v3.json"),
    )
}
SCHEMA = SCHEMAS["1"]


def _valid(value: Any, shape: dict[str, Any], definitions: dict[str, Any] = SCHEMA) -> bool:
    return validate(value, shape, definitions)


def _event_valid(event: dict[str, Any]) -> bool:
    definitions = SCHEMAS.get(event.get("integration_version", "")) if type(event) is dict else None
    if definitions is None or not _valid(event, definitions["event"], definitions):
        return False
    if event["kind"] in ("activity", "attempt_started") and (
        (event["root_run_id"] == event["run_id"]) == ("parent_run_id" in event)
        or event.get("parent_run_id") == event["run_id"]
    ):
        return False
    if event["integration_version"] in ("2", "3"):
        if (
            event["kind"] == "activity"
            and event["activity_kind"] == "outcome"
            and "outcome" not in event
        ):
            return False
        if event["kind"] == "attempt_started" and (
            (event["model_identity_state"] == "known") != ("model_id" in event)
            or (event["attempt_role"] in ("retry", "fallback"))
            != ("predecessor_attempt_id" in event)
        ):
            return False
        if event["kind"] == "decision" and (
            (event["eligibility_evidence"]["status"] in ("verified", "stale", "denied"))
            != ("eligibility_id" in event["eligibility_evidence"])
        ):
            return False
        if (
            event["integration_version"] == "3"
            and event["kind"] == "decision"
            and (
                (event["selection_kind"] == "known_model") != ("selected_model_id" in event)
                or event["capability"]
                != (
                    "transcription"
                    if event["operation_family"] == "speech_input"
                    else "synthesis"
                    if event["operation_family"] == "speech_output"
                    else event["operation_family"]
                )
            )
        ):
            return False
        if event["kind"] == "usage":
            known_units, known_cost = (
                event["usage_state"] == "known",
                event["cost_state"] == "known",
            )
            units = event.get("native_units", ())
            fields = ("currency", "amount_decimal", "cost_basis", "price_ref", "price_version")
            if (
                len({x["unit"] for x in units}) != len(units)
                or known_units != ("native_units" in event and "usage_provenance" in event)
                or not known_units
                and ("native_units" in event or "usage_provenance" in event)
                or known_cost != all(key in event for key in fields)
                or not known_cost
                and any(key in event for key in fields + ("zero_basis",))
                or known_cost
                and ((event["amount_decimal"].strip("0.") == "") != ("zero_basis" in event))
            ):
                return False
    elif (
        event["kind"] == "usage"
        and event["usage_state"] == "known"
        and (
            len({x["unit"] for x in event["native_units"]}) != len(event["native_units"])
            or (event["amount_decimal"].strip("0.") == "") != ("zero_basis" in event)
        )
    ):
        return False
    return True


def _snapshot_valid(snapshot: dict[str, Any]) -> bool:
    schema = (
        SCHEMAS.get(snapshot.get("integration_version", "")) if type(snapshot) is dict else None
    )
    if schema is None or snapshot["integration_version"] not in ("2", "3"):
        return False
    if not _valid(snapshot, schema["snapshot"], schema):
        return False
    content_key = "features" if snapshot["snapshot_kind"] == "feature" else "selected_action"
    if (
        (snapshot["status"] == "captured") != (content_key in snapshot)
        or ({"features", "selected_action"} - {content_key}) & set(snapshot)
        or snapshot["source_at"] > snapshot["available_at"]
        or snapshot["available_at"] > snapshot["retention_until"]
        or snapshot.get("source_expires_at", snapshot["retention_until"])
        < snapshot["retention_until"]
    ):
        return False
    if "selected_action" in snapshot:
        evidence = snapshot["selected_action"]["eligibility_evidence"]
        if (evidence["status"] in ("verified", "stale", "denied")) != (
            "eligibility_id" in evidence
        ):
            return False
        action = snapshot["selected_action"]
        if snapshot["integration_version"] == "3" and (
            (action["selection_kind"] == "known_model") != ("selected_model_id" in action)
            or action["capability"]
            != (
                "transcription"
                if action["operation_family"] == "speech_input"
                else "synthesis"
                if action["operation_family"] == "speech_output"
                else action["operation_family"]
            )
        ):
            return False
    return True


def _decode(raw: bytes) -> Any:
    if len(raw) > INTEGRATION_RESPONSE_LIMIT:
        raise ValueError("response limit")
    return strict_reply(raw)


def _receipt_valid(
    value: Any, dataset_id: str, event_id: str, kind: str | None = None, digest: str | None = None
) -> bool:
    return (
        type(value) is dict
        and value.get("dataset_id") == dataset_id
        and value.get("event_id") == event_id
        and value.get("kind")
        in (
            "activity",
            "attempt_started",
            "decision",
            "result",
            "usage",
            "lineage",
            "account_resolution",
        )
        and (kind is None or value["kind"] == kind)
        and (digest is None or value.get("event_digest") == digest)
        and type(value.get("event_digest")) is str
        and re.fullmatch(r"sha256:[0-9a-f]{64}", value["event_digest"]) is not None
        and value.get("membership_at_receipt")
        in ("included", "excluded_before_activation", "pending_start")
    )


class IntegrationClient(ClientSession):
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        transport: Any = None,
        timeout: Any = DEFAULT_TIMEOUT,
        version: str = "1",
        total_timeout: float | None = DEFAULT_TOTAL_TIMEOUT,
    ) -> None:
        if version not in SCHEMAS:
            raise TypeError("unsupported integration version")
        super().__init__(
            base_url, token, transport=transport, timeout=timeout, total_timeout=total_timeout
        )
        self.version, self.schema, self.base_path = (
            version,
            SCHEMAS[version],
            "/integration/v" + version,
        )

    @property
    def transport(self) -> Any:
        """Injected/owned transport, retained for existing diagnostic callers."""
        return self._transport

    @property
    def closed(self) -> bool:
        return self._closed

    def _request(
        self, method: str, path: str, body: dict[str, Any] | None, expected: tuple[int, ...]
    ) -> dict[str, Any]:
        data = (
            json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
                "utf-8"
            )
            if body is not None
            else None
        )
        response, value = self._exchange(
            method,
            path,
            version_header="EzLLMRouter-Integration-Version",
            version_field="integration_version",
            version=self.version,
            limit=INTEGRATION_RESPONSE_LIMIT,
            error_type=IntegrationClientError,
            body=data,
        )
        if response.status_code >= 400:
            error = value.get("error")
            if type(error) is not dict or type(error.get("code")) is not str:
                raise IntegrationClientError(
                    "TRANSPORT_OUTCOME_UNKNOWN", response.status_code, "query_first"
                )
            raise IntegrationClientError(
                error["code"], response.status_code, error.get("retry_guidance", "never")
            )
        if response.status_code not in expected:
            raise IntegrationClientError("PROTOCOL_INVALID", response.status_code, "query_first")
        return value

    def create_dataset(self, body: dict[str, Any] | None) -> dict[str, Any]:
        if not _valid(body, self.schema["dataset"], self.schema):
            raise IntegrationInputError("SCHEMA_INVALID") from ValueError("invalid dataset")
        return self._request("POST", self.base_path + "/datasets", body, (200, 201))

    def register_account(self, body: dict[str, Any] | None) -> dict[str, Any]:
        if not _valid(body, self.schema["account"], self.schema):
            raise IntegrationInputError("SCHEMA_INVALID") from ValueError("invalid account")
        return self._request("POST", self.base_path + "/accounts", body, (200, 201))

    def set_account_state(self, account_id: str, body: dict[str, Any] | None) -> dict[str, Any]:
        if not _valid(account_id, self.schema["id"], self.schema) or not _valid(
            body, self.schema["account_state"], self.schema
        ):
            raise IntegrationInputError("SCHEMA_INVALID") from ValueError("invalid account state")
        return self._request(
            "POST",
            self.base_path + "/accounts/" + quote(account_id, safe="") + "/state",
            body,
            (200,),
        )

    def set_account_permissions(
        self, account_id: str, body: dict[str, Any] | None
    ) -> dict[str, Any]:
        if (
            self.version != "3"
            or not _valid(account_id, self.schema["id"], self.schema)
            or not _valid(body, self.schema["account_permissions"], self.schema)
        ):
            raise IntegrationInputError("SCHEMA_INVALID") from ValueError(
                "invalid account permissions"
            )
        return self._request(
            "POST",
            self.base_path + "/accounts/" + quote(account_id, safe="") + "/permissions",
            body,
            (200,),
        )

    def submit_observation(self, event: dict[str, Any]) -> dict[str, Any]:
        if (
            type(event) is not dict
            or event.get("integration_version") != self.version
            or not _event_valid(event)
        ):
            raise IntegrationInputError("SCHEMA_INVALID") from ValueError("invalid observation")
        snapshot = json.loads(json.dumps(event, ensure_ascii=False))
        digest = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(
                    snapshot, ensure_ascii=False, separators=(",", ":"), sort_keys=True
                ).encode("utf-8")
            ).hexdigest()
        )
        reply = self._request("POST", self.base_path + "/events", snapshot, (200, 201))
        if not _receipt_valid(
            reply, snapshot["dataset_id"], snapshot["event_id"], snapshot["kind"], digest
        ):
            raise IntegrationClientError("PROTOCOL_INVALID", retry_guidance="query_first")
        return reply

    def recover_receipt(self, dataset_id: str, event_id: str) -> dict[str, Any]:
        if not _valid(dataset_id, self.schema["id"], self.schema) or not _valid(
            event_id, self.schema["id"], self.schema
        ):
            raise IntegrationInputError("SCHEMA_INVALID") from ValueError(
                "invalid receipt selector"
            )
        reply = self._request(
            "GET",
            self.base_path
            + "/events/"
            + quote(event_id, safe="")
            + "/receipt?dataset_id="
            + quote(dataset_id, safe=""),
            None,
            (200,),
        )
        if not _receipt_valid(reply, dataset_id, event_id):
            raise IntegrationClientError("PROTOCOL_INVALID", retry_guidance="query_first")
        return reply

    def eligibility(self, dataset_id: str, account_id: str, model_id: str) -> dict[str, Any]:
        if self.version == "3":
            return self.operation_eligibility(
                dataset_id,
                account_id,
                {
                    "operation_family": "generation",
                    "capability": "generation",
                    "selection_kind": "known_model",
                    "model_id": model_id,
                },
            )
        if not all(
            _valid(item, self.schema["id"], self.schema)
            for item in (dataset_id, account_id, model_id)
        ):
            raise IntegrationInputError("SCHEMA_INVALID") from ValueError(
                "invalid eligibility selector"
            )
        reply = self._request(
            "GET",
            self.base_path
            + "/accounts/"
            + quote(account_id, safe="")
            + "/eligibility?dataset_id="
            + quote(dataset_id, safe="")
            + "&model_id="
            + quote(model_id, safe=""),
            None,
            (200,),
        )
        if (
            reply.get("dataset_id") != dataset_id
            or reply.get("account_id") != account_id
            or reply.get("model_id") != model_id
            or type(reply.get("account_revision")) is not int
            or reply["account_revision"] < 1
            or type(reply.get("usable")) is not bool
            or reply.get("reason") not in ("usable", "account_disabled", "model_not_permitted")
            or reply["usable"] != (reply["reason"] == "usable")
        ):
            raise IntegrationClientError("PROTOCOL_INVALID", retry_guidance="query_first")
        if self.version == "2" and (
            not _valid(reply.get("eligibility_id"), self.schema["id"], self.schema)
            or not _valid(reply.get("evaluated_at"), self.schema["utc"], self.schema)
            or type(reply.get("eligibility_digest")) is not str
            or re.fullmatch(r"sha256:[0-9a-f]{64}", reply["eligibility_digest"]) is None
        ):
            raise IntegrationClientError("PROTOCOL_INVALID", retry_guidance="query_first")
        if self.version == "2":
            signed = {key: item for key, item in reply.items() if key != "eligibility_digest"}
            expected = (
                "sha256:"
                + hashlib.sha256(
                    json.dumps(
                        signed, ensure_ascii=False, separators=(",", ":"), sort_keys=True
                    ).encode("utf-8")
                ).hexdigest()
            )
            if reply["eligibility_digest"] != expected:
                raise IntegrationClientError("PROTOCOL_INVALID", retry_guidance="query_first")
        return reply

    def operation_eligibility(
        self, dataset_id: str, account_id: str, selector: dict[str, Any]
    ) -> dict[str, Any]:
        if (
            self.version != "3"
            or not all(_valid(x, self.schema["id"], self.schema) for x in (dataset_id, account_id))
            or type(selector) is not dict
            or selector.get("selection_kind")
            not in ("known_model", "provider_selected", "not_applicable")
            or selector.get("operation_family") not in self.schema["operation_family"]["enum"]
            or selector.get("capability")
            != (
                "transcription"
                if selector["operation_family"] == "speech_input"
                else "synthesis"
                if selector["operation_family"] == "speech_output"
                else selector["operation_family"]
            )
            or (selector["selection_kind"] == "known_model") != ("model_id" in selector)
            or "model_id" in selector
            and not _valid(selector["model_id"], self.schema["id"], self.schema)
            or selector["selection_kind"] != "known_model"
            and selector["operation_family"] not in ("speech_input", "speech_output")
        ):
            raise IntegrationInputError("SCHEMA_INVALID") from ValueError(
                "invalid operation eligibility selector"
            )
        query = "?dataset_id=" + quote(dataset_id, safe="")
        for key in ("operation_family", "capability", "selection_kind", "model_id"):
            if key in selector:
                query += "&" + key + "=" + quote(selector[key], safe="")
        reply = self._request(
            "GET",
            self.base_path + "/accounts/" + quote(account_id, safe="") + "/eligibility" + query,
            None,
            (200,),
        )
        if (
            reply.get("dataset_id") != dataset_id
            or reply.get("account_id") != account_id
            or any(
                reply.get(key) != selector.get(key)
                for key in ("operation_family", "capability", "selection_kind", "model_id")
            )
            or not all(
                _valid(reply.get(key), self.schema["id"], self.schema)
                for key in ("provider_id", "credential_ref", "eligibility_id")
            )
            or type(reply.get("account_revision")) is not int
            or reply["account_revision"] < 1
            or type(reply.get("usable")) is not bool
            or reply.get("reason")
            not in ("usable", "account_disabled", "model_not_permitted", "operation_not_permitted")
            or reply["usable"] != (reply["reason"] == "usable")
            or not _valid(reply.get("evaluated_at"), self.schema["utc"], self.schema)
            or type(reply.get("eligibility_digest")) is not str
            or re.fullmatch(r"sha256:[0-9a-f]{64}", reply["eligibility_digest"]) is None
        ):
            raise IntegrationClientError("PROTOCOL_INVALID", retry_guidance="query_first")
        signed = {key: item for key, item in reply.items() if key != "eligibility_digest"}
        expected = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(
                    signed, ensure_ascii=False, separators=(",", ":"), sort_keys=True
                ).encode("utf-8")
            ).hexdigest()
        )
        if reply["eligibility_digest"] != expected:
            raise IntegrationClientError("PROTOCOL_INVALID", retry_guidance="query_first")
        return reply

    def report(self, dataset_id: str) -> dict[str, Any]:
        if not _valid(dataset_id, self.schema["id"], self.schema):
            raise IntegrationInputError("SCHEMA_INVALID") from ValueError("invalid dataset")
        return self._request(
            "GET",
            self.base_path + "/reports/usage?dataset_id=" + quote(dataset_id, safe=""),
            None,
            (200,),
        )

    def submit_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        if (
            type(snapshot) is not dict
            or self.version not in ("2", "3")
            or snapshot.get("integration_version") != self.version
            or not _snapshot_valid(snapshot)
        ):
            raise IntegrationInputError("SCHEMA_INVALID") from ValueError("invalid snapshot")
        digest = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(
                    snapshot, ensure_ascii=False, separators=(",", ":"), sort_keys=True
                ).encode("utf-8")
            ).hexdigest()
        )
        reply = self._request("POST", self.base_path + "/snapshots", snapshot, (200, 201))
        if (
            reply.get("snapshot_id") != snapshot["snapshot_id"]
            or reply.get("snapshot_digest") != digest
        ):
            raise IntegrationClientError("PROTOCOL_INVALID", retry_guidance="query_first")
        return reply

    def snapshot(self, dataset_id: str, snapshot_id: Any) -> dict[str, Any]:
        if self.version not in ("2", "3") or not all(
            _valid(item, self.schema["id"], self.schema) for item in (dataset_id, snapshot_id)
        ):
            raise IntegrationInputError("SCHEMA_INVALID") from ValueError(
                "invalid snapshot selector"
            )
        return self._request(
            "GET",
            self.base_path
            + "/snapshots/"
            + quote(snapshot_id, safe="")
            + "?dataset_id="
            + quote(dataset_id, safe=""),
            None,
            (200,),
        )

    def export_dataset(self, dataset_id: str) -> dict[str, Any]:
        if self.version not in ("2", "3") or not _valid(dataset_id, self.schema["id"], self.schema):
            raise IntegrationInputError("SCHEMA_INVALID") from ValueError(
                "invalid dataset selector"
            )
        return self._request(
            "GET",
            self.base_path + "/reports/dataset?dataset_id=" + quote(dataset_id, safe=""),
            None,
            (200,),
        )
