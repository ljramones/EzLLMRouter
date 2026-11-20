"""Synchronous external-observation HTTP client, without automatic delivery retry."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
import re
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit

from ._http import DEFAULT_TIMEOUT, INTEGRATION_RESPONSE_LIMIT, bounded_request
from ._deadline import DEFAULT_TOTAL_TIMEOUT, DeadlineHTTPTransport, total_timeout as _total_timeout
from ._json import strict_reply

SCHEMAS = {version: json.loads((Path(__file__).parent / filename).read_text())["$defs"]
           for version, filename in (("1", "integration_schema.json"), ("2", "integration_schema_v2.json"),
                                     ("3", "integration_schema_v3.json"))}
SCHEMA = SCHEMAS["1"]


def _valid(value, shape, definitions=SCHEMA):
    if "$ref" in shape:
        definition = shape["$ref"].rsplit("/", 1)[1]
        if definition == "utc":
            if type(value) is not str or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value) is None:
                return False
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() == timezone.utc.utcoffset(None)
            except ValueError:
                return False
        return _valid(value, definitions[definition], definitions)
    if "oneOf" in shape:
        return sum(_valid(value, item, definitions) for item in shape["oneOf"]) == 1
    if "const" in shape and value != shape["const"]:
        return False
    if "enum" in shape and value not in shape["enum"]:
        return False
    kind = shape.get("type")
    if kind == "object":
        return (type(value) is dict and set(shape.get("required", ())) <= set(value) and
                (shape.get("additionalProperties") is not False or set(value) <= set(shape["properties"])) and
                all(_valid(item, shape["properties"][key], definitions) for key, item in value.items()
                    if key in shape["properties"]))
    if kind == "array":
        return (type(value) is list and shape.get("minItems", 0) <= len(value) <= shape.get("maxItems", 10**9)
                and (not shape.get("uniqueItems") or len({json.dumps(x, sort_keys=True) for x in value}) == len(value))
                and all(_valid(item, shape["items"], definitions) for item in value))
    if kind == "integer":
        return type(value) is int and shape.get("minimum", -10**30) <= value <= shape.get("maximum", 10**30)
    if kind == "string":
        return type(value) is str and ("pattern" not in shape or re.fullmatch(shape["pattern"], value) is not None)
    return True


def _event_valid(event):
    definitions = SCHEMAS.get(event.get("integration_version")) if type(event) is dict else None
    if definitions is None or not _valid(event, definitions["event"], definitions):
        return False
    if event["kind"] in ("activity", "attempt_started") and (
            (event["root_run_id"] == event["run_id"]) == ("parent_run_id" in event) or
            event.get("parent_run_id") == event["run_id"]):
        return False
    if event["integration_version"] in ("2", "3"):
        if event["kind"] == "activity" and event["activity_kind"] == "outcome" and "outcome" not in event:
            return False
        if event["kind"] == "attempt_started" and (
                (event["model_identity_state"] == "known") != ("model_id" in event) or
                (event["attempt_role"] in ("retry", "fallback")) != ("predecessor_attempt_id" in event)):
            return False
        if event["kind"] == "decision" and (
                (event["eligibility_evidence"]["status"] in ("verified", "stale", "denied")) !=
                ("eligibility_id" in event["eligibility_evidence"])):
            return False
        if event["integration_version"] == "3" and event["kind"] == "decision" and (
                (event["selection_kind"] == "known_model") != ("selected_model_id" in event) or
                event["capability"] != ("transcription" if event["operation_family"] == "speech_input" else
                    "synthesis" if event["operation_family"] == "speech_output" else event["operation_family"])):
            return False
        if event["kind"] == "usage":
            known_units, known_cost = event["usage_state"] == "known", event["cost_state"] == "known"
            units = event.get("native_units", ())
            fields = ("currency", "amount_decimal", "cost_basis", "price_ref", "price_version")
            if (len({x["unit"] for x in units}) != len(units) or
                    known_units != ("native_units" in event and "usage_provenance" in event) or
                    not known_units and ("native_units" in event or "usage_provenance" in event) or
                    known_cost != all(key in event for key in fields) or
                    not known_cost and any(key in event for key in fields + ("zero_basis",)) or
                    known_cost and ((event["amount_decimal"].strip("0.") == "") !=
                                    ("zero_basis" in event))):
                return False
    elif event["kind"] == "usage" and event["usage_state"] == "known" and (
            len({x["unit"] for x in event["native_units"]}) != len(event["native_units"]) or
            (event["amount_decimal"].strip("0.") == "") != ("zero_basis" in event)):
        return False
    return True


def _snapshot_valid(snapshot):
    schema = SCHEMAS.get(snapshot.get("integration_version")) if type(snapshot) is dict else None
    if schema is None or snapshot["integration_version"] not in ("2", "3"):
        return False
    if not _valid(snapshot, schema["snapshot"], schema):
        return False
    content_key = "features" if snapshot["snapshot_kind"] == "feature" else "selected_action"
    if ((snapshot["status"] == "captured") != (content_key in snapshot) or
            ({"features", "selected_action"} - {content_key}) & set(snapshot) or
            snapshot["source_at"] > snapshot["available_at"] or
            snapshot["available_at"] > snapshot["retention_until"] or
            snapshot.get("source_expires_at", snapshot["retention_until"]) < snapshot["retention_until"]):
        return False
    if "selected_action" in snapshot:
        evidence = snapshot["selected_action"]["eligibility_evidence"]
        if (evidence["status"] in ("verified", "stale", "denied")) != ("eligibility_id" in evidence):
            return False
        action = snapshot["selected_action"]
        if snapshot["integration_version"] == "3" and (
                (action["selection_kind"] == "known_model") != ("selected_model_id" in action) or
                action["capability"] != ("transcription" if action["operation_family"] == "speech_input" else
                    "synthesis" if action["operation_family"] == "speech_output" else action["operation_family"])):
            return False
    return True


class IntegrationClientError(Exception):
    def __init__(self, code, http_status=None, retry_guidance="never"):
        super().__init__(code)
        self.code, self.http_status, self.retry_guidance = code, http_status, retry_guidance


def _decode(raw):
    if len(raw) > INTEGRATION_RESPONSE_LIMIT:
        raise ValueError("response limit")
    return strict_reply(raw)


def _receipt_valid(value, dataset_id, event_id, kind=None, digest=None):
    return (type(value) is dict and value.get("dataset_id") == dataset_id and
            value.get("event_id") == event_id and
            value.get("kind") in ("activity", "attempt_started", "decision", "result", "usage", "lineage", "account_resolution") and
            (kind is None or value["kind"] == kind) and
            (digest is None or value.get("event_digest") == digest) and
            type(value.get("event_digest")) is str and
            re.fullmatch(r"sha256:[0-9a-f]{64}", value["event_digest"]) is not None and
            value.get("membership_at_receipt") in
            ("included", "excluded_before_activation", "pending_start"))


class IntegrationClient:
    def __init__(self, base_url, token, *, transport=None, timeout=DEFAULT_TIMEOUT, version="1",
                 total_timeout=DEFAULT_TOTAL_TIMEOUT):
        if type(base_url) is not str or type(token) is not str:
            raise TypeError("invalid integration client configuration")
        parsed = urlsplit(base_url)
        if (type(base_url) is not str or type(token) is not str or not token or
                parsed.scheme not in ("http", "https") or not parsed.hostname or
                parsed.username or parsed.password or parsed.query or parsed.fragment or version not in SCHEMAS):
            raise TypeError("invalid integration client configuration")
        self.base_url, self.token = base_url.rstrip("/"), token
        self._total_timeout = _total_timeout(total_timeout)
        self.version, self.schema, self.base_path = version, SCHEMAS[version], "/integration/v" + version
        if transport is None:
            import httpx
            self.transport = httpx.Client(timeout=timeout, transport=DeadlineHTTPTransport(),
                                          follow_redirects=False, trust_env=False)
        else:
            if not callable(getattr(transport, "request", None)):
                raise TypeError("transport must provide request")
            self.transport = transport
        self.closed = False

    def close(self):
        if not self.closed:
            self.closed = True
            close = getattr(self.transport, "close", None)
            if callable(close):
                close()

    def __enter__(self):
        if self.closed:
            raise RuntimeError("client closed")
        return self

    def __exit__(self, *_):
        self.close()

    def _request(self, method, path, body, expected):
        if self.closed:
            raise RuntimeError("client closed")
        headers = {"Authorization": "Bearer " + self.token, "EzLLMRouter-Integration-Version": self.version}
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        else:
            data = None
        try:
            response = bounded_request(self.transport, method, self.base_url + path,
                headers=headers, content=data, limit=INTEGRATION_RESPONSE_LIMIT, total_timeout=self._total_timeout)
        except Exception as exc:
            raise IntegrationClientError("TRANSPORT_OUTCOME_UNKNOWN", getattr(exc, "status_code", None), "query_first") from exc
        try:
            value = _decode(response.content)
        except (ValueError, UnicodeError, TypeError, RecursionError) as exc:
            raise IntegrationClientError("TRANSPORT_OUTCOME_UNKNOWN", response.status_code, "query_first") from exc
        if type(value) is not dict or response.headers.get("EzLLMRouter-Integration-Version") != self.version or value.get("integration_version") != self.version:
            raise IntegrationClientError("UNSUPPORTED_VERSION", response.status_code)
        if response.status_code >= 400:
            error = value.get("error")
            if type(error) is not dict or type(error.get("code")) is not str:
                raise IntegrationClientError("TRANSPORT_OUTCOME_UNKNOWN", response.status_code, "query_first")
            raise IntegrationClientError(error["code"], response.status_code, error.get("retry_guidance", "never"))
        if response.status_code not in expected:
            raise IntegrationClientError("PROTOCOL_INVALID", response.status_code, "query_first")
        return value

    def create_dataset(self, body):
        if not _valid(body, self.schema["dataset"], self.schema):
            raise TypeError("invalid dataset")
        return self._request("POST", self.base_path + "/datasets", body, (200, 201))

    def register_account(self, body):
        if not _valid(body, self.schema["account"], self.schema):
            raise TypeError("invalid account")
        return self._request("POST", self.base_path + "/accounts", body, (200, 201))

    def set_account_state(self, account_id, body):
        if not _valid(account_id, self.schema["id"], self.schema) or not _valid(body, self.schema["account_state"], self.schema):
            raise TypeError("invalid account state")
        return self._request("POST", self.base_path + "/accounts/" + quote(account_id, safe="") + "/state", body, (200,))

    def set_account_permissions(self, account_id, body):
        if (self.version != "3" or not _valid(account_id, self.schema["id"], self.schema) or
                not _valid(body, self.schema["account_permissions"], self.schema)):
            raise TypeError("invalid account permissions")
        return self._request("POST", self.base_path + "/accounts/" + quote(account_id, safe="") +
                             "/permissions", body, (200,))

    def submit_observation(self, event):
        if type(event) is not dict or event.get("integration_version") != self.version or not _event_valid(event):
            raise TypeError("invalid observation")
        snapshot = json.loads(json.dumps(event, ensure_ascii=False))
        digest = "sha256:" + hashlib.sha256(json.dumps(snapshot, ensure_ascii=False,
            separators=(",", ":"), sort_keys=True).encode("utf-8")).hexdigest()
        reply = self._request("POST", self.base_path + "/events", snapshot, (200, 201))
        if not _receipt_valid(reply, snapshot["dataset_id"], snapshot["event_id"], snapshot["kind"], digest):
            raise IntegrationClientError("PROTOCOL_INVALID", retry_guidance="query_first")
        return reply

    def recover_receipt(self, dataset_id, event_id):
        if not _valid(dataset_id, self.schema["id"], self.schema) or not _valid(event_id, self.schema["id"], self.schema):
            raise TypeError("invalid receipt selector")
        reply = self._request("GET", self.base_path + "/events/" + quote(event_id, safe="") +
                              "/receipt?dataset_id=" + quote(dataset_id, safe=""), None, (200,))
        if not _receipt_valid(reply, dataset_id, event_id):
            raise IntegrationClientError("PROTOCOL_INVALID", retry_guidance="query_first")
        return reply

    def eligibility(self, dataset_id, account_id, model_id):
        if self.version == "3":
            return self.operation_eligibility(dataset_id, account_id, {
                "operation_family": "generation", "capability": "generation",
                "selection_kind": "known_model", "model_id": model_id})
        if not all(_valid(item, self.schema["id"], self.schema) for item in (dataset_id, account_id, model_id)):
            raise TypeError("invalid eligibility selector")
        reply = self._request("GET", self.base_path + "/accounts/" + quote(account_id, safe="") +
                              "/eligibility?dataset_id=" + quote(dataset_id, safe="") +
                              "&model_id=" + quote(model_id, safe=""), None, (200,))
        if (reply.get("dataset_id") != dataset_id or reply.get("account_id") != account_id or
                reply.get("model_id") != model_id or type(reply.get("account_revision")) is not int or
                reply["account_revision"] < 1 or type(reply.get("usable")) is not bool or
                reply.get("reason") not in ("usable", "account_disabled", "model_not_permitted") or
                reply["usable"] != (reply["reason"] == "usable")):
            raise IntegrationClientError("PROTOCOL_INVALID", retry_guidance="query_first")
        if self.version == "2" and (not _valid(reply.get("eligibility_id"), self.schema["id"], self.schema) or
                                    not _valid(reply.get("evaluated_at"), self.schema["utc"], self.schema) or
                                    type(reply.get("eligibility_digest")) is not str or
                                    re.fullmatch(r"sha256:[0-9a-f]{64}", reply["eligibility_digest"]) is None):
            raise IntegrationClientError("PROTOCOL_INVALID", retry_guidance="query_first")
        if self.version == "2":
            signed = {key: item for key, item in reply.items() if key != "eligibility_digest"}
            expected = "sha256:" + hashlib.sha256(json.dumps(signed, ensure_ascii=False,
                separators=(",", ":"), sort_keys=True).encode("utf-8")).hexdigest()
            if reply["eligibility_digest"] != expected:
                raise IntegrationClientError("PROTOCOL_INVALID", retry_guidance="query_first")
        return reply

    def operation_eligibility(self, dataset_id, account_id, selector):
        if (self.version != "3" or not all(_valid(x, self.schema["id"], self.schema)
                for x in (dataset_id, account_id)) or type(selector) is not dict or
                selector.get("selection_kind") not in ("known_model", "provider_selected", "not_applicable") or
                selector.get("operation_family") not in self.schema["operation_family"]["enum"] or
                selector.get("capability") != ("transcription" if selector["operation_family"] == "speech_input" else
                    "synthesis" if selector["operation_family"] == "speech_output" else selector["operation_family"]) or
                (selector["selection_kind"] == "known_model") != ("model_id" in selector) or
                "model_id" in selector and not _valid(selector["model_id"], self.schema["id"], self.schema) or
                selector["selection_kind"] != "known_model" and
                selector["operation_family"] not in ("speech_input", "speech_output")):
            raise TypeError("invalid operation eligibility selector")
        query = "?dataset_id=" + quote(dataset_id, safe="")
        for key in ("operation_family", "capability", "selection_kind", "model_id"):
            if key in selector:
                query += "&" + key + "=" + quote(selector[key], safe="")
        reply = self._request("GET", self.base_path + "/accounts/" + quote(account_id, safe="") +
                              "/eligibility" + query, None, (200,))
        if (reply.get("dataset_id") != dataset_id or reply.get("account_id") != account_id or
                any(reply.get(key) != selector.get(key) for key in
                    ("operation_family", "capability", "selection_kind", "model_id")) or
                not all(_valid(reply.get(key), self.schema["id"], self.schema) for key in
                    ("provider_id", "credential_ref", "eligibility_id")) or
                type(reply.get("account_revision")) is not int or reply["account_revision"] < 1 or
                type(reply.get("usable")) is not bool or
                reply.get("reason") not in ("usable", "account_disabled", "model_not_permitted", "operation_not_permitted") or
                reply["usable"] != (reply["reason"] == "usable") or
                not _valid(reply.get("evaluated_at"), self.schema["utc"], self.schema) or
                type(reply.get("eligibility_digest")) is not str or
                re.fullmatch(r"sha256:[0-9a-f]{64}", reply["eligibility_digest"]) is None):
            raise IntegrationClientError("PROTOCOL_INVALID", retry_guidance="query_first")
        signed = {key: item for key, item in reply.items() if key != "eligibility_digest"}
        expected = "sha256:" + hashlib.sha256(json.dumps(signed, ensure_ascii=False,
            separators=(",", ":"), sort_keys=True).encode("utf-8")).hexdigest()
        if reply["eligibility_digest"] != expected:
            raise IntegrationClientError("PROTOCOL_INVALID", retry_guidance="query_first")
        return reply

    def report(self, dataset_id):
        if not _valid(dataset_id, self.schema["id"], self.schema):
            raise TypeError("invalid dataset")
        return self._request("GET", self.base_path + "/reports/usage?dataset_id=" +
                             quote(dataset_id, safe=""), None, (200,))

    def submit_snapshot(self, snapshot):
        if type(snapshot) is not dict or self.version not in ("2", "3") or snapshot.get("integration_version") != self.version or not _snapshot_valid(snapshot):
            raise TypeError("invalid snapshot")
        digest = "sha256:" + hashlib.sha256(json.dumps(snapshot, ensure_ascii=False,
            separators=(",", ":"), sort_keys=True).encode("utf-8")).hexdigest()
        reply = self._request("POST", self.base_path + "/snapshots", snapshot, (200, 201))
        if reply.get("snapshot_id") != snapshot["snapshot_id"] or reply.get("snapshot_digest") != digest:
            raise IntegrationClientError("PROTOCOL_INVALID", retry_guidance="query_first")
        return reply

    def snapshot(self, dataset_id, snapshot_id):
        if self.version not in ("2", "3") or not all(_valid(item, self.schema["id"], self.schema)
                                          for item in (dataset_id, snapshot_id)):
            raise TypeError("invalid snapshot selector")
        return self._request("GET", self.base_path + "/snapshots/" + quote(snapshot_id, safe="") +
                             "?dataset_id=" + quote(dataset_id, safe=""), None, (200,))

    def export_dataset(self, dataset_id):
        if self.version not in ("2", "3") or not _valid(dataset_id, self.schema["id"], self.schema):
            raise TypeError("invalid dataset selector")
        return self._request("GET", self.base_path + "/reports/dataset?dataset_id=" +
                             quote(dataset_id, safe=""), None, (200,))
