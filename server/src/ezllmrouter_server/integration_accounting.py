"""Durable accounting of externally executed work; no sender or submission path."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import unquote_to_bytes

from .errors import RequestError
from .formatting import money as format_money
from .formatting import utc_timestamp
from .json_validation import JSONValue
from .observability import log_failure
from .repositories import integration_accounting as _queries
from .store import encode

VERSION = "1"
SCHEMA = json.loads((Path(__file__).parent / "integration_schema.json").read_text())
SCHEMA_V2 = json.loads((Path(__file__).parent / "integration_schema_v2.json").read_text())
SCHEMA_V3 = json.loads((Path(__file__).parent / "integration_schema_v3.json").read_text())
SCHEMAS = {"1": SCHEMA, "2": SCHEMA_V2, "3": SCHEMA_V3}
_CAPABILITIES = {
    name: (
        "transcription"
        if name == "speech_input"
        else "synthesis"
        if name == "speech_output"
        else name,
    )
    for name in SCHEMA_V3["$defs"]["operation_family"]["enum"]
}


class IntegrationError(RequestError):
    def __init__(self, code, status=400, retry_guidance="never"):
        super().__init__(code, status)
        self.retry_guidance = retry_guidance


def _cohort_expiry(dataset, days, activated_at):
    try:
        if (
            type(days) is not int
            or not 1 <= days <= 397
            or not _utc(activated_at)
            or dataset["activated_at"] != activated_at
        ):
            raise ValueError("invalid accounting retention metadata")
        return datetime.fromisoformat(activated_at.replace("Z", "+00:00")) + timedelta(days=days)
    except (ValueError, KeyError, TypeError, OverflowError):
        raise ValueError("invalid accounting retention metadata") from None


def _dataset_available(dataset, days, activated_at, at):
    if not dataset["dataset_id"].startswith("dataset.local.real."):
        return True
    try:
        return _cohort_expiry(dataset, days, activated_at) > at
    except ValueError:
        return False


def _snapshot_record(metadata, content, digest, at):
    meta = json.loads(metadata)
    if meta["status"] == "captured" and meta["retention_until"] <= at:
        content = None
    return meta, content, digest


def _shape(value, schema, definitions=None):
    definitions = definitions or SCHEMA["$defs"]
    if "$ref" in schema:
        return _shape(value, definitions[schema["$ref"].rsplit("/", 1)[1]], definitions)
    if "oneOf" in schema:
        return sum(_shape(value, item, definitions) for item in schema["oneOf"]) == 1
    if "const" in schema and value != schema["const"]:
        return False
    if "enum" in schema and value not in schema["enum"]:
        return False
    kind = schema.get("type")
    if kind == "object":
        return (
            type(value) is dict
            and set(schema.get("required", ())) <= set(value)
            and (
                schema.get("additionalProperties") is not False
                or set(value) <= set(schema["properties"])
            )
            and all(
                _shape(item, schema["properties"][key], definitions)
                for key, item in value.items()
                if key in schema["properties"]
            )
        )
    if kind == "array":
        return (
            type(value) is list
            and schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 10**9)
            and (not schema.get("uniqueItems") or len({encode(x) for x in value}) == len(value))
            and all(_shape(item, schema["items"], definitions) for item in value)
        )
    if kind == "integer":
        return type(value) is int and schema.get("minimum", -(10**30)) <= value <= schema.get(
            "maximum", 10**30
        )
    if kind == "string":
        return type(value) is str and (
            "pattern" not in schema or re.fullmatch(schema["pattern"], value) is not None
        )
    return True


def _utc(value):
    if type(value) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
        return False
    try:
        return datetime.fromisoformat(
            value.replace("Z", "+00:00")
        ).utcoffset() == timezone.utc.utcoffset(None)
    except ValueError:
        return False


def _time():
    return utc_timestamp(datetime.now(timezone.utc))


def _eligibility_assessment(event, observed, history):
    """Assess a reported answer without treating same-second mutations as ordered."""
    evidence = event.get("eligibility_evidence", {})
    if "eligibility_id" not in evidence:
        return "not_assessed"
    if (
        not observed
        or any(
            (
                observed.get(key) != value
                for key, value in (
                    ("dataset_id", event["dataset_id"]),
                    ("account_id", event["selected_account_id"]),
                    ("model_id", event.get("selected_model_id")),
                )
            )
        )
        or observed.get("evaluated_at", "9999") > event["occurred_at"]
    ):
        return "binding_conflict"
    if (observed.get("integration_version") == "3") != (event.get("integration_version") == "3"):
        return "binding_conflict"
    if observed.get("integration_version") == "3" and (
        event.get("integration_version") != "3"
        or any(
            observed.get(key) != event.get(key)
            for key in ("operation_family", "capability", "selection_kind")
        )
    ):
        return "binding_conflict"
    signed = {key: value for key, value in observed.items() if key != "eligibility_digest"}
    if (
        observed.get("eligibility_digest")
        != "sha256:" + hashlib.sha256(encode(signed).encode()).hexdigest()
    ):
        return "binding_conflict"
    bound = next(
        (item for item in history if item["revision"] == observed["account_revision"]), None
    )
    if not bound or bound["dataset_id"] != event["dataset_id"]:
        return "binding_conflict"
    if observed.get("integration_version") == "3":
        if (
            observed.get("provider_id") != bound["provider_id"]
            or observed.get("credential_ref") != bound["credential_ref"]
        ):
            return "binding_conflict"
        permitted = (
            observed["model_id"] in bound["allowed_models"]
            if observed["selection_kind"] == "known_model"
            else observed["operation_family"] in bound.get("allowed_operations", ())
            and observed["operation_family"] in ("speech_input", "speech_output")
        )
        denied_reason = (
            "model_not_permitted"
            if observed["selection_kind"] == "known_model"
            else "operation_not_permitted"
        )
    else:
        permitted = observed["model_id"] in bound["allowed_models"]
        denied_reason = "model_not_permitted"
    usable = bound["state"] == "usable" and permitted
    reason = (
        "usable" if usable else "account_disabled" if bound["state"] != "usable" else denied_reason
    )
    if usable != observed["usable"] or reason != observed.get("reason"):
        return "binding_conflict"
    if not usable:
        return "denied"
    later = [
        item.get("changed_at", item.get("registered_at"))
        for item in history
        if item["revision"] > observed["account_revision"]
    ]
    if any(moment < event["occurred_at"] for moment in later):
        return "stale"
    if observed["evaluated_at"] == event["occurred_at"] or any(
        moment == event["occurred_at"] for moment in later
    ):
        return "indeterminate"
    return "verified"


def _lineage_projection(start, link, starts, links):
    """Project accepted lineage without blessing contradictory historical records."""
    v2 = start.get("integration_version") in ("2", "3")
    if not v2:
        return None, None, "binding_conflict" if link else "legacy_absent"
    role, predecessor = start["attempt_role"], start.get("predecessor_attempt_id")
    if link:
        if role != "unknown" or link["logical_operation_id"] != start["logical_operation_id"]:
            return role, predecessor, "binding_conflict"
        role, predecessor = link["attempt_role"], link["predecessor_attempt_id"]
    if not predecessor:
        return role, None, "not_collected"
    seen = {start["attempt_id"]}
    cursor = predecessor
    while cursor:
        if cursor in seen:
            return start["attempt_role"], start.get("predecessor_attempt_id"), "binding_conflict"
        seen.add(cursor)
        prior = starts.get(cursor)
        if not prior:
            return role, predecessor, "pending_predecessor"
        if (
            prior.get("task_id") != start["task_id"]
            or prior.get("logical_operation_id") != start["logical_operation_id"]
        ):
            return start["attempt_role"], start.get("predecessor_attempt_id"), "binding_conflict"
        prior_link = links.get(cursor)
        if prior_link and (
            prior.get("attempt_role") != "unknown"
            or prior_link["logical_operation_id"] != prior["logical_operation_id"]
        ):
            return start["attempt_role"], start.get("predecessor_attempt_id"), "binding_conflict"
        cursor = (
            prior_link["predecessor_attempt_id"]
            if prior_link
            else prior.get("predecessor_attempt_id")
        )
    return role, predecessor, "linked"


def _checked(value, definition, version="1"):
    definitions = SCHEMAS[version]["$defs"]
    if not _shape(value, definitions[definition], definitions):
        raise IntegrationError("SCHEMA_INVALID")

    def walk(item):
        if isinstance(item, dict):
            for key, child in item.items():
                if key in (
                    "activated_at",
                    "occurred_at",
                    "started_at",
                    "source_at",
                    "available_at",
                    "retention_until",
                    "source_expires_at",
                ) and not _utc(child):
                    raise IntegrationError("SCHEMA_INVALID")
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)
        elif type(item) is str and any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in item):
            raise IntegrationError("SCHEMA_INVALID")

    walk(value)
    if definition == "event":
        if value["kind"] in ("activity", "attempt_started"):
            root = value["root_run_id"] == value["run_id"]
            if root == ("parent_run_id" in value) or value.get("parent_run_id") == value["run_id"]:
                raise IntegrationError("SEMANTIC_INVALID")
        if (
            version in ("2", "3")
            and value["kind"] == "activity"
            and value["activity_kind"] == "outcome"
            and "outcome" not in value
        ):
            raise IntegrationError("SEMANTIC_INVALID")
        if version in ("2", "3") and value["kind"] == "attempt_started":
            if (value["model_identity_state"] == "known") != ("model_id" in value) or (
                value["attempt_role"] in ("retry", "fallback")
            ) != ("predecessor_attempt_id" in value):
                raise IntegrationError("SEMANTIC_INVALID")
        if version in ("2", "3") and value["kind"] == "decision":
            evidence = value["eligibility_evidence"]
            if (evidence["status"] in ("verified", "stale", "denied")) != (
                "eligibility_id" in evidence
            ):
                raise IntegrationError("SEMANTIC_INVALID")
            if version == "3" and (
                (value["selection_kind"] == "known_model") != ("selected_model_id" in value)
                or value["capability"] not in _CAPABILITIES.get(value["operation_family"], ())
            ):
                raise IntegrationError("SEMANTIC_INVALID")
        if value["kind"] == "usage":
            if version == "1":
                units = [item["unit"] for item in value.get("native_units", ())]
                if value["usage_state"] == "known" and (
                    len(units) != len(set(units))
                    or (Decimal(value["amount_decimal"]) == 0) != ("zero_basis" in value)
                ):
                    raise IntegrationError("SEMANTIC_INVALID")
            else:
                units = [item["unit"] for item in value.get("native_units", ())]
                known_units = value["usage_state"] == "known"
                known_cost = value["cost_state"] == "known"
                fields = ("currency", "amount_decimal", "cost_basis", "price_ref", "price_version")
                if (
                    len(units) != len(set(units))
                    or known_units != ("native_units" in value and "usage_provenance" in value)
                    or not known_units
                    and ("native_units" in value or "usage_provenance" in value)
                    or known_cost != all(key in value for key in fields)
                    or not known_cost
                    and any(key in value for key in fields + ("zero_basis",))
                    or known_cost
                    and (Decimal(value["amount_decimal"]) == 0) != ("zero_basis" in value)
                ):
                    raise IntegrationError("SEMANTIC_INVALID")
    if definition == "snapshot":
        captured = value["status"] == "captured"
        content_key = "features" if value["snapshot_kind"] == "feature" else "selected_action"
        if (
            captured != (content_key in value)
            or any(key in value for key in ({"features", "selected_action"} - {content_key}))
            or value["source_at"] > value["available_at"]
            or value["available_at"] > value["retention_until"]
            or value.get("source_expires_at", value["retention_until"]) < value["retention_until"]
        ):
            raise IntegrationError("SEMANTIC_INVALID")
        if "selected_action" in value:
            evidence = value["selected_action"]["eligibility_evidence"]
            if (evidence["status"] in ("verified", "stale", "denied")) != (
                "eligibility_id" in evidence
            ):
                raise IntegrationError("SEMANTIC_INVALID")
            action = value["selected_action"]
            if value["integration_version"] == "3" and (
                (action["selection_kind"] == "known_model") != ("selected_model_id" in action)
                or action["capability"] not in _CAPABILITIES.get(action["operation_family"], ())
            ):
                raise IntegrationError("SEMANTIC_INVALID")
    return value


def route_id(raw):
    """Decode one URL path segment once, then apply the published ID grammar."""
    if re.search(r"%(?![0-9A-Fa-f]{2})", raw):
        raise IntegrationError("SCHEMA_INVALID")
    try:
        value = unquote_to_bytes(raw).decode("utf-8", "strict")
    except (UnicodeError, ValueError) as exc:
        raise IntegrationError("SCHEMA_INVALID") from exc
    if not _shape(value, SCHEMA["$defs"]["id"]):
        raise IntegrationError("SCHEMA_INVALID")
    return value


@dataclass(frozen=True)
class AccountingReportData:
    """One database snapshot used by all projections and aggregates in a report."""

    attempts: list[dict[str, JSONValue]]
    all_starts: dict[str, dict[str, JSONValue]]
    events: list[dict[str, JSONValue]]
    runs: dict[str, str | None]
    snapshots: dict[str, tuple[dict[str, JSONValue], str | None, str | None]]
    eligibility_reads: dict[str, dict[str, JSONValue]]
    account_history: dict[str, list[dict[str, JSONValue]]]


class ExternalAccounting:
    def __init__(self, registry):
        self.registry = registry
        self.store = registry.store
        self._expire_snapshots()

    def _expire_snapshots(self):
        # Avoid a write transaction when the indexed expiry range is empty.
        at = _time()
        with self.store.database.read():
            if not self.store.database.execute(_queries.EXPIRED_SNAPSHOT_EXISTS, (at,)).fetchone():
                return 0

        # Content is purged, while identity, digest and expiry evidence remain.
        def action():
            return self.store.database.execute(
                _queries.ACTION_UPDATE_INTEGRATION_SNAPSHOTS, (at,)
            ).rowcount

        return self.store.database.transaction(action)

    def maintain(self):
        """Explicit physical cleanup; read methods enforce expiry without writing."""
        return {
            "expired_datasets": self.expire_datasets(),
            "expired_snapshots": self._expire_snapshots(),
        }

    def expire_datasets(self):
        """Purge adopted local real cohorts at T0 plus the configured horizon.

        The default service has no accounting expiry, preserving historical
        synthetic datasets and accepted releases. A tombstone prevents an
        expired dataset ID from being recreated or backfilled.
        """
        now = datetime.fromisoformat(_time().replace("Z", "+00:00"))

        db = self.store.database

        def due(raw, days, activated_at):
            try:
                return _cohort_expiry(json.loads(raw), days, activated_at) <= now
            except (ValueError, KeyError, TypeError):
                log_failure("accounting_retention_metadata_invalid")
                return False

        with db.read():
            candidates = [
                did
                for did, raw, days, activated_at in db.execute(
                    _queries.ACTION_SELECT_INTEGRATION_DATASETS
                )
                if due(raw, days, activated_at)
            ]
        if not candidates:
            return 0

        def action():
            expired = []
            for did in candidates:
                row = db.execute(_queries.DATASET_SELECT_INTEGRATION_DATASETS, (did,)).fetchone()
                if row and due(*row):
                    expired.append(did)
            for did in expired:
                db.execute(_queries.ACTION_INSERT_INTEGRATION_EXPIRED_DATASETS, (did, _time()))
                db.execute(_queries.PURGE_CREDENTIAL_VERSIONS, (did,))
                db.execute(_queries.PURGE_CREDENTIAL_OPERATIONS, (did,))
                db.execute(_queries.PURGE_CREDENTIAL_BINDINGS, (did,))
                for table in (
                    "integration_events",
                    "integration_attempts",
                    "integration_runs",
                    "integration_snapshots",
                    "integration_eligibility_reads",
                    "integration_accounts",
                ):
                    db.execute(_queries.ACTION_DELETE_RECORD(table=table), (did,))
                db.execute(_queries.ACTION_DELETE_INTEGRATION_ACCOUNT_HISTORY, (did,))
                db.execute(_queries.ACTION_DELETE_INTEGRATION_DATASET_RETENTION, (did,))
                db.execute(_queries.ACTION_DELETE_INTEGRATION_DATASETS, (did,))
            return len(expired)

        return self.store.database.transaction(action)

    def _dataset(self, dataset_id):
        with self.store.database.read():
            row = self.store.database.execute(
                _queries.DATASET_SELECT_INTEGRATION_DATASETS, (dataset_id,)
            ).fetchone()
        if not row:
            raise IntegrationError("NOT_FOUND_OR_FORBIDDEN", 404)
        dataset = json.loads(row[0])
        if not _dataset_available(
            dataset, row[1], row[2], datetime.fromisoformat(_time().replace("Z", "+00:00"))
        ):
            raise IntegrationError("NOT_FOUND_OR_FORBIDDEN", 404)
        return dataset

    def _authorize(self, principal, dataset, action):
        same_owner = principal["owner"] == dataset["owner_id"]
        admin = (
            same_owner
            and principal["principal_id"] == dataset["owner_id"]
            and principal["role"] == "registry_admin"
        )
        report = admin or (same_owner and principal["role"] == "read_only_operator")
        ingest = principal["principal_id"] == dataset["ingest_principal_id"] and same_owner
        if not {
            "admin": admin,
            "report": report,
            "ingest": ingest,
            "receipt": ingest or admin,
            "eligibility": ingest or admin,
            "snapshot": ingest or report,
        }[action]:
            raise IntegrationError("NOT_FOUND_OR_FORBIDDEN", 404)

    def create_dataset(self, principal, body, version="1"):
        body = _checked(body, "dataset", version)
        if (
            principal["principal_id"] != body["owner_id"]
            or principal["owner"] != body["owner_id"]
            or principal["role"] != "registry_admin"
        ):
            raise IntegrationError("POLICY_DENIED", 403)
        ingest = self.registry.principal(body["ingest_principal_id"])
        if (
            not ingest
            or ingest["status"] != "active"
            or ingest["owner"] != body["owner_id"]
            or ingest["kind"] != "service"
        ):
            raise IntegrationError("POLICY_DENIED", 403)

        def action():
            db = self.store.database
            local_real = body["dataset_id"].startswith("dataset.local.real.")
            if local_real and getattr(self, "accounting_retention_days", None) is None:
                raise IntegrationError("POLICY_DENIED", 403)
            if db.execute(
                _queries.ACTION_SELECT_INTEGRATION_EXPIRED_DATASETS, (body["dataset_id"],)
            ).fetchone():
                raise IntegrationError("DATASET_EXPIRED", 410)
            old = db.execute(
                _queries.ACTION_SELECT_INTEGRATION_DATASETS_2, (body["dataset_id"],)
            ).fetchone()
            if old:
                if local_real:
                    retention = db.execute(
                        _queries.ACTION_SELECT_INTEGRATION_DATASET_RETENTION, (body["dataset_id"],)
                    ).fetchone()
                    if not retention:
                        raise IntegrationError("POLICY_DENIED", 403)
                    try:
                        expiry = _cohort_expiry(json.loads(old[0]), *retention)
                    except ValueError:
                        raise IntegrationError("POLICY_DENIED", 403) from None
                    if expiry <= datetime.fromisoformat(_time().replace("Z", "+00:00")):
                        raise IntegrationError("DATASET_EXPIRED", 410)
                if json.loads(old[0]) != body:
                    raise IntegrationError("EVENT_CONFLICT", 409)
                return 200, {"integration_version": version, **body}
            if local_real:
                try:
                    expiry = _cohort_expiry(
                        body, self.accounting_retention_days, body["activated_at"]
                    )
                except ValueError:
                    raise IntegrationError("POLICY_DENIED", 403) from None
                if expiry <= datetime.fromisoformat(_time().replace("Z", "+00:00")):
                    raise IntegrationError("DATASET_EXPIRED", 410)
            db.execute(
                _queries.ACTION_INSERT_INTEGRATION_DATASETS, (body["dataset_id"], encode(body))
            )
            if local_real:
                db.execute(
                    _queries.ACTION_INSERT_INTEGRATION_DATASET_RETENTION,
                    (body["dataset_id"], self.accounting_retention_days, body["activated_at"]),
                )
            return 201, {"integration_version": version, **body}

        return self.store.database.transaction(action)

    def create_account(self, principal, body, version="1"):
        body = _checked(body, "account", version)
        dataset = self._dataset(body["dataset_id"])
        self._authorize(principal, dataset, "admin")

        def action():
            db = self.store.database
            self._authorize(principal, self._dataset(body["dataset_id"]), "admin")
            old = db.execute(
                _queries.ACTION_SELECT_INTEGRATION_ACCOUNTS,
                (body["account_id"], body["dataset_id"]),
            ).fetchone()
            if old:
                original = db.execute(
                    _queries.ACTION_SELECT_INTEGRATION_ACCOUNT_HISTORY,
                    (body["account_id"], body["dataset_id"]),
                ).fetchone()
                record = json.loads(original[0])
                if {k: record[k] for k in body} != body:
                    raise IntegrationError("EVENT_CONFLICT", 409)
                return 200, {"integration_version": version, **record}
            record = {
                **body,
                "owner_id": dataset["owner_id"],
                "revision": 1,
                "registered_at": _time(),
            }
            db.execute(
                _queries.ACTION_INSERT_INTEGRATION_ACCOUNTS,
                (body["account_id"], body["dataset_id"], encode(record)),
            )
            db.execute(
                _queries.ACTION_INSERT_INTEGRATION_ACCOUNT_HISTORY,
                (body["account_id"], body["dataset_id"], 1, encode(record)),
            )
            return 201, {"integration_version": version, **record}

        return self.store.database.transaction(action)

    def set_account_state(self, principal, account_id, body, version="1"):
        body = _checked(body, "account_state", version)
        dataset = self._dataset(body["dataset_id"])
        self._authorize(principal, dataset, "admin")

        def action():
            db = self.store.database
            self._authorize(principal, self._dataset(body["dataset_id"]), "admin")
            row = db.execute(
                _queries.ACTION_SELECT_INTEGRATION_ACCOUNTS, (account_id, body["dataset_id"])
            ).fetchone()
            if not row:
                raise IntegrationError("NOT_FOUND_OR_FORBIDDEN", 404)
            record = json.loads(row[0])
            if record["revision"] != body["expected_revision"]:
                raise IntegrationError("STALE_REVISION", 409)
            record.update(state=body["state"], revision=record["revision"] + 1, changed_at=_time())
            db.execute(
                _queries.ACTION_UPDATE_INTEGRATION_ACCOUNTS,
                (encode(record), account_id, body["dataset_id"]),
            )
            db.execute(
                _queries.ACTION_INSERT_INTEGRATION_ACCOUNT_HISTORY,
                (account_id, body["dataset_id"], record["revision"], encode(record)),
            )
            return 200, {"integration_version": version, **record}

        return self.store.database.transaction(action)

    def set_account_permissions(self, principal, account_id, body):
        """Explicit v3 opt-in; an existing v1/v2 account starts with no speech permissions."""
        body = _checked(body, "account_permissions", "3")
        dataset = self._dataset(body["dataset_id"])
        self._authorize(principal, dataset, "admin")

        def action():
            db = self.store.database
            self._authorize(principal, self._dataset(body["dataset_id"]), "admin")
            row = db.execute(
                _queries.ACTION_SELECT_INTEGRATION_ACCOUNTS, (account_id, body["dataset_id"])
            ).fetchone()
            if not row:
                raise IntegrationError("NOT_FOUND_OR_FORBIDDEN", 404)
            record = json.loads(row[0])
            if record["revision"] != body["expected_revision"]:
                raise IntegrationError("STALE_REVISION", 409)
            record.update(
                allowed_models=body["allowed_models"],
                allowed_operations=body["allowed_operations"],
                revision=record["revision"] + 1,
                changed_at=_time(),
            )
            db.execute(
                _queries.ACTION_UPDATE_INTEGRATION_ACCOUNTS,
                (encode(record), account_id, body["dataset_id"]),
            )
            db.execute(
                _queries.ACTION_INSERT_INTEGRATION_ACCOUNT_HISTORY,
                (account_id, body["dataset_id"], record["revision"], encode(record)),
            )
            return 200, {"integration_version": "3", **record}

        return self.store.database.transaction(action)

    def eligibility(
        self,
        principal,
        dataset_id,
        account_id,
        model_id,
        version="1",
        operation_family=None,
        capability=None,
        selection_kind=None,
    ):
        dataset = self._dataset(dataset_id)
        self._authorize(principal, dataset, "eligibility")
        if version == "3":
            if (
                operation_family not in _CAPABILITIES
                or capability not in _CAPABILITIES[operation_family]
                or selection_kind not in ("known_model", "provider_selected", "not_applicable")
                or (selection_kind == "known_model") != (model_id is not None)
                or selection_kind != "known_model"
                and operation_family not in ("speech_input", "speech_output")
            ):
                raise IntegrationError("SCHEMA_INVALID")
        if (
            model_id is not None
            and not _shape(model_id, SCHEMA["$defs"]["id"])
            or version != "3"
            and model_id is None
        ):
            raise IntegrationError("SCHEMA_INVALID")

        def action():
            self._authorize(principal, self._dataset(dataset_id), "eligibility")
            row = self.store.database.execute(
                _queries.ACTION_SELECT_INTEGRATION_ACCOUNTS, (account_id, dataset_id)
            ).fetchone()
            if not row:
                raise IntegrationError("NOT_FOUND_OR_FORBIDDEN", 404)
            record = json.loads(row[0])
            permitted = (
                model_id in record["allowed_models"]
                if selection_kind == "known_model" or version != "3"
                else operation_family in record.get("allowed_operations", ())
            )
            reason = (
                "usable"
                if record["state"] == "usable" and permitted
                else (
                    "account_disabled"
                    if record["state"] != "usable"
                    else "model_not_permitted"
                    if version != "3" or selection_kind == "known_model"
                    else "operation_not_permitted"
                )
            )
            result = {
                "integration_version": version,
                "dataset_id": dataset_id,
                "account_id": account_id,
                "account_revision": record["revision"],
                "usable": reason == "usable",
                "reason": reason,
            }
            if model_id is not None:
                result["model_id"] = model_id
            if version == "3":
                result.update(
                    operation_family=operation_family,
                    capability=capability,
                    selection_kind=selection_kind,
                    provider_id=record["provider_id"],
                    credential_ref=record["credential_ref"],
                )
            if version in ("2", "3"):
                result.update(
                    eligibility_id="eligibility." + uuid.uuid4().hex, evaluated_at=_time()
                )
                result["eligibility_digest"] = (
                    "sha256:" + hashlib.sha256(encode(result).encode()).hexdigest()
                )
                self.store.database.execute(
                    _queries.ELIGIBILITY_INSERT_INTEGRATION_ELIGIBILITY_READS,
                    (dataset_id, result["eligibility_id"], encode(result)),
                )
            return result

        if version in ("2", "3"):
            return self.store.database.transaction(action)
        with self.store.database.read():
            return action()

    def datasets(self, principal):
        if principal["role"] not in ("registry_admin", "read_only_operator"):
            raise IntegrationError("POLICY_DENIED", 403)
        with self.store.database.read():
            rows = self.store.database.execute(
                _queries.DATASETS_SELECT_INTEGRATION_DATASETS
            ).fetchall()
        at = datetime.fromisoformat(_time().replace("Z", "+00:00"))
        items = []
        for raw, days, activated_at in rows:
            item = json.loads(raw)
            if item["owner_id"] == principal["owner"] and _dataset_available(
                item, days, activated_at, at
            ):
                items.append(item)
        return {"integration_version": VERSION, "items": items}

    def accounts(self, principal, dataset_id):
        dataset = self._dataset(dataset_id)
        self._authorize(principal, dataset, "report")
        with self.store.database.read():
            rows = [
                json.loads(row[0])
                for row in self.store.database.execute(
                    _queries.ACCOUNTS_SELECT_INTEGRATION_ACCOUNTS, (dataset_id,)
                )
            ]
        return {"integration_version": VERSION, "dataset_id": dataset_id, "items": rows}

    def _bind_run(self, db, event):
        dataset_id, run_id = event["dataset_id"], event["run_id"]
        root, parent, task = event["root_run_id"], event.get("parent_run_id"), event["task_id"]
        old = db.execute(
            _queries.BIND_RUN_SELECT_INTEGRATION_RUNS_2, (dataset_id, run_id)
        ).fetchone()
        if old:
            if old != (root, parent, task):
                raise IntegrationError("EVENT_CONFLICT", 409)
            return
        seen = {run_id}
        ancestor = parent
        while ancestor:
            if ancestor in seen:
                raise IntegrationError("SEMANTIC_INVALID")
            seen.add(ancestor)
            row = db.execute(
                _queries.BIND_RUN_SELECT_INTEGRATION_RUNS_2, (dataset_id, ancestor)
            ).fetchone()
            if not row:
                break  # Late parent delivery; binding is rechecked when that parent arrives.
            if row[0] != root or row[2] != task:
                raise IntegrationError("EVENT_CONFLICT", 409)
            ancestor = row[1]
        for child_root, child_task in db.execute(
            _queries.BIND_RUN_SELECT_INTEGRATION_RUNS, (dataset_id, run_id)
        ):
            if child_root != root or child_task != task:
                raise IntegrationError("EVENT_CONFLICT", 409)
        db.execute(
            _queries.BIND_RUN_INSERT_INTEGRATION_RUNS, (dataset_id, run_id, root, parent, task)
        )

    def _check_lineage(self, db, event):
        did = event["dataset_id"]
        aid = event["attempt_id"]
        component = db.execute(
            _queries.LINEAGE_COMPONENT, (did, aid, event.get("predecessor_attempt_id"))
        ).fetchall()
        starts = {key: json.loads(raw) for key, raw, _ in component if raw is not None}
        accepted_links = {key: json.loads(raw) for key, _, raw in component if raw is not None}
        if event["kind"] == "attempt_started":
            prior_link = accepted_links.get(aid)
            if prior_link and (
                event.get("integration_version") not in ("2", "3")
                or event["attempt_role"] != "unknown"
                or event["logical_operation_id"] != prior_link["logical_operation_id"]
            ):
                raise IntegrationError("EVENT_CONFLICT", 409)
            starts[aid] = event
        else:
            existing = starts.get(aid)
            if existing and (
                existing.get("attempt_role") != "unknown"
                or existing.get("logical_operation_id") != event["logical_operation_id"]
            ):
                raise IntegrationError("EVENT_CONFLICT", 409)
            accepted_links[aid] = event
        links = {
            aid: (
                start["attempt_role"],
                start.get("predecessor_attempt_id"),
                start["logical_operation_id"],
            )
            for aid, start in starts.items()
            if start.get("integration_version") in ("2", "3")
        }
        for link in accepted_links.values():
            links[link["attempt_id"]] = (
                link["attempt_role"],
                link["predecessor_attempt_id"],
                link["logical_operation_id"],
            )
        # A new start can settle a pending predecessor, while a new link can
        # affect its descendants. Validate that connected component only:
        # immutable contradictory history elsewhere must not veto new work.
        neighbors = {}
        for child, (_, predecessor, _) in links.items():
            if predecessor:
                neighbors.setdefault(child, set()).add(predecessor)
                neighbors.setdefault(predecessor, set()).add(child)
        affected = {aid}
        pending = [aid]
        while pending:
            for adjacent in neighbors.get(pending.pop(), ()):
                if adjacent not in affected:
                    affected.add(adjacent)
                    pending.append(adjacent)
        for current_aid in sorted(affected):
            start, link = starts.get(current_aid), accepted_links.get(current_aid)
            if (
                start
                and link
                and (
                    start.get("integration_version") not in ("2", "3")
                    or start["attempt_role"] != "unknown"
                    or start["logical_operation_id"] != link["logical_operation_id"]
                )
            ):
                raise IntegrationError("EVENT_CONFLICT", 409)
        for current_aid in sorted(affected):
            if current_aid not in links:
                continue
            _, predecessor, logical = links[current_aid]
            if not predecessor:
                continue
            if predecessor == current_aid:
                raise IntegrationError("SEMANTIC_INVALID")
            prior = starts.get(predecessor)
            current = starts.get(current_aid)
            if (
                prior
                and prior.get("logical_operation_id") != logical
                or current
                and current.get("logical_operation_id") != logical
                or prior
                and current
                and prior.get("task_id") != current.get("task_id")
            ):
                raise IntegrationError("EVENT_CONFLICT", 409)
            if (
                not prior
                and db.execute(
                    _queries.CHECK_LINEAGE_SELECT_INTEGRATION_ATTEMPTS, (did, predecessor)
                ).fetchone()
            ):
                raise IntegrationError("EVENT_CONFLICT", 409)
        # Visit each predecessor edge once, including long retry chains.
        checked = set()
        for current_aid in affected:
            path = set()
            cursor = current_aid
            while cursor and cursor not in checked:
                if cursor in path:
                    raise IntegrationError("SEMANTIC_INVALID")
                path.add(cursor)
                cursor = links.get(cursor, (None, None, None))[1]
            checked.update(path)

    def _check_decision_evidence(self, db, event):
        evidence = event["eligibility_evidence"]
        if "eligibility_id" not in evidence:
            return
        row = db.execute(
            _queries.CHECK_DECISION_EVIDENCE_SELECT_INTEGRATION_ELIGIBILITY_READS,
            (event["dataset_id"], evidence["eligibility_id"]),
        ).fetchone()
        if not row:
            raise IntegrationError("SEMANTIC_INVALID")
        observed = json.loads(row[0])
        history = [
            json.loads(r[0])
            for r in db.execute(
                _queries.CHECK_DECISION_EVIDENCE_SELECT_INTEGRATION_ACCOUNT_HISTORY,
                (event["selected_account_id"], event["dataset_id"]),
            )
        ]
        assessment = _eligibility_assessment(event, observed, history)
        if assessment == "binding_conflict":
            raise IntegrationError("EVENT_CONFLICT", 409)
        if (
            assessment == "indeterminate"
            and evidence["status"] not in ("verified", "stale")
            or assessment != "indeterminate"
            and evidence["status"] != assessment
        ):
            raise IntegrationError("SEMANTIC_INVALID")

    def _check_snapshot_reference(self, db, dataset_id, snapshot_id, attempt_id, kind):
        row = db.execute(
            _queries.CHECK_SNAPSHOT_REFERENCE_SELECT_INTEGRATION_SNAPSHOTS,
            (dataset_id, snapshot_id),
        ).fetchone()
        if row and row != (attempt_id, kind):
            raise IntegrationError("EVENT_CONFLICT", 409)

    def append_event(self, principal, event, required_version=None):
        version = event.get("integration_version") if type(event) is dict else None
        if version not in SCHEMAS or required_version and version != required_version:
            raise IntegrationError("UNSUPPORTED_VERSION", 426)
        event = _checked(event, "event", version)
        dataset = self._dataset(event["dataset_id"])
        self._authorize(principal, dataset, "ingest")
        digest = hashlib.sha256(encode(event).encode()).hexdigest()

        def action():
            db = self.store.database
            self._authorize(principal, self._dataset(event["dataset_id"]), "ingest")
            did, eid, kind = event["dataset_id"], event["event_id"], event["kind"]
            old = db.execute(_queries.ACTION_SELECT_INTEGRATION_EVENTS_3, (did, eid)).fetchone()
            if old:
                if old[0] != digest:
                    raise IntegrationError("EVENT_CONFLICT", 409)
                return 200, json.loads(old[1])
            attempt_id = event.get("attempt_id")
            start = None
            if attempt_id:
                row = db.execute(
                    _queries.ACTION_SELECT_INTEGRATION_ATTEMPTS_2, (did, attempt_id)
                ).fetchone()
                start = json.loads(row[0]) if row else None
            if kind in ("activity", "attempt_started"):
                self._bind_run(db, event)
            if kind in ("attempt_started", "lineage"):
                self._check_lineage(db, event)
            if kind == "attempt_started":
                if start:
                    raise IntegrationError("EVENT_CONFLICT", 409)
                account = db.execute(
                    _queries.ACTION_SELECT_INTEGRATION_ACCOUNTS, (event["provider_account_id"], did)
                ).fetchone()
                if not account and version == "1":
                    raise IntegrationError("NOT_FOUND_OR_FORBIDDEN", 404)
                if version in ("2", "3"):
                    self._check_snapshot_reference(
                        db, did, event["context_ref"], attempt_id, "feature"
                    )
                    for sid, snapshot_kind, metadata in db.execute(
                        _queries.ACTION_SELECT_INTEGRATION_SNAPSHOTS, (did, attempt_id)
                    ):
                        if snapshot_kind == "feature" and sid != event["context_ref"]:
                            raise IntegrationError("EVENT_CONFLICT", 409)
                        if (
                            snapshot_kind == "decision"
                            and json.loads(metadata)["available_at"] > event["started_at"]
                        ):
                            raise IntegrationError("SEMANTIC_INVALID")
                    for (raw,) in db.execute(
                        _queries.ACTION_SELECT_INTEGRATION_EVENTS_4, (did, attempt_id)
                    ):
                        if json.loads(raw)["resolved_account_id"] != event["provider_account_id"]:
                            raise IntegrationError("EVENT_CONFLICT", 409)
                for (raw,) in db.execute(
                    _queries.ACTION_SELECT_INTEGRATION_EVENTS_2, (did, attempt_id)
                ):
                    decision = json.loads(raw)
                    if (
                        decision["selected_account_id"] != event["provider_account_id"]
                        or decision.get("selected_model_id") != event.get("model_id")
                        or decision.get("integration_version") == "3"
                        and (
                            decision["operation_family"] != event.get("operation_family")
                            or decision["selection_kind"]
                            != (
                                "known_model"
                                if event.get("model_identity_state") == "known"
                                else "provider_selected"
                                if event.get("model_identity_state") == "unknown"
                                else "not_applicable"
                            )
                        )
                        or decision["occurred_at"] > event["started_at"]
                    ):
                        raise IntegrationError("EVENT_CONFLICT", 409)
                db.execute(
                    _queries.ACTION_INSERT_INTEGRATION_ATTEMPTS,
                    (
                        did,
                        attempt_id,
                        eid,
                        encode(event),
                        int(event["started_at"] >= dataset["activated_at"]),
                    ),
                )
            if kind == "decision":
                previous = db.execute(
                    _queries.ACTION_SELECT_INTEGRATION_EVENTS_5, (did, attempt_id)
                ).fetchone()
                if previous:
                    raise IntegrationError("EVENT_CONFLICT", 409)
                if start and (
                    event["selected_account_id"] != start["provider_account_id"]
                    or event.get("selected_model_id") != start.get("model_id")
                    or version == "3"
                    and (
                        event["operation_family"] != start.get("operation_family")
                        or event["selection_kind"]
                        != (
                            "known_model"
                            if start.get("model_identity_state") == "known"
                            else "provider_selected"
                            if start.get("model_identity_state") == "unknown"
                            else "not_applicable"
                        )
                    )
                    or event["occurred_at"] > start["started_at"]
                ):
                    raise IntegrationError("EVENT_CONFLICT", 409)
                if version in ("2", "3"):
                    self._check_decision_evidence(db, event)
                    self._check_snapshot_reference(
                        db, did, event["decision_ref"], attempt_id, "decision"
                    )
                    snapshot = db.execute(
                        _queries.ACTION_SELECT_INTEGRATION_SNAPSHOTS_3,
                        (did, event["decision_ref"], attempt_id),
                    ).fetchone()
                    if snapshot and snapshot[0]:
                        action = json.loads(snapshot[0])["selected_action"]
                        if any(
                            action.get(key) != event.get(key)
                            for key in (
                                "selected_account_id",
                                "selected_model_id",
                                "policy_version",
                                "eligibility_evidence",
                            )
                            + (
                                ("operation_family", "capability", "selection_kind")
                                if version == "3"
                                else ()
                            )
                        ):
                            raise IntegrationError("EVENT_CONFLICT", 409)
            if kind == "account_resolution":
                resolved = db.execute(
                    _queries.ACTION_SELECT_INTEGRATION_ACCOUNTS_2,
                    (event["resolved_account_id"], did),
                ).fetchone()
                if (
                    not resolved
                    or db.execute(
                        _queries.ACTION_SELECT_INTEGRATION_EVENTS_8, (did, attempt_id)
                    ).fetchone()
                ):
                    raise IntegrationError("EVENT_CONFLICT", 409)
                if start and start["provider_account_id"] != event["resolved_account_id"]:
                    raise IntegrationError("EVENT_CONFLICT", 409)
            if (
                kind == "lineage"
                and db.execute(
                    _queries.ACTION_SELECT_INTEGRATION_EVENTS_6, (did, attempt_id)
                ).fetchone()
            ):
                raise IntegrationError("EVENT_CONFLICT", 409)
            ordinal = event.get("usage_revision") if kind == "usage" else None
            if (
                ordinal is not None
                and db.execute(
                    _queries.ACTION_SELECT_INTEGRATION_EVENTS_7, (did, attempt_id, ordinal)
                ).fetchone()
            ):
                raise IntegrationError("EVENT_CONFLICT", 409)
            membership = (
                (
                    "included"
                    if event["started_at"] >= dataset["activated_at"]
                    else "excluded_before_activation"
                )
                if kind == "attempt_started"
                else (
                    "included"
                    if start and start["started_at"] >= dataset["activated_at"]
                    else "excluded_before_activation"
                    if start
                    else "pending_start"
                )
            )
            receipt = {
                "integration_version": version,
                "dataset_id": did,
                "event_id": eid,
                "event_digest": "sha256:" + digest,
                "kind": kind,
                "membership_at_receipt": membership,
                "received_at": _time(),
            }
            db.execute(
                _queries.ACTION_INSERT_INTEGRATION_EVENTS,
                (did, eid, kind, attempt_id, ordinal, digest, encode(event), encode(receipt)),
            )
            return 201, receipt

        return self.store.database.transaction(action)

    def receipt(self, principal, dataset_id, event_id):
        dataset = self._dataset(dataset_id)
        self._authorize(principal, dataset, "receipt")
        with self.store.database.read():
            row = self.store.database.execute(
                _queries.RECEIPT_SELECT_INTEGRATION_EVENTS, (dataset_id, event_id)
            ).fetchone()
        if not row:
            raise IntegrationError("NOT_FOUND_OR_FORBIDDEN", 404)
        return json.loads(row[0])

    def append_snapshot(self, principal, record):
        version = record.get("integration_version") if type(record) is dict else None
        if version not in ("2", "3"):
            raise IntegrationError("UNSUPPORTED_VERSION", 426)
        record = _checked(record, "snapshot", version)
        dataset = self._dataset(record["dataset_id"])
        self._authorize(principal, dataset, "ingest")
        if record["status"] == "captured":
            policy = getattr(self, "feature_policy", None)
            if policy is None:
                if record["provenance"] != "synthetic" or record["classification"] != "low":
                    raise IntegrationError("POLICY_DENIED", 403)
                days = 397
            else:
                if (
                    policy.get("mode") != "approved"
                    or policy.get("approved_by") != dataset["owner_id"]
                    or record["classification"] not in policy.get("max_days_by_class", {})
                    or record["provenance"] == "synthetic"
                ):
                    raise IntegrationError("POLICY_DENIED", 403)
                days = policy["max_days_by_class"][record["classification"]]
                if (
                    type(days) is not int
                    or not 1 <= days <= 397
                    or "source_expires_at" not in record
                ):
                    raise IntegrationError("POLICY_DENIED", 403)
            origin = datetime.fromisoformat(record["source_at"].replace("Z", "+00:00"))
            cutoff = datetime.fromisoformat(record["retention_until"].replace("Z", "+00:00"))
            if cutoff > origin + timedelta(days=days):
                raise IntegrationError("POLICY_DENIED", 403)
        did, sid = record["dataset_id"], record["snapshot_id"]
        digest = "sha256:" + hashlib.sha256(encode(record).encode()).hexdigest()
        content = {key: record[key] for key in ("features", "selected_action") if key in record}
        metadata = {key: value for key, value in record.items() if key not in content}

        def action():
            db = self.store.database
            self._authorize(principal, self._dataset(record["dataset_id"]), "ingest")
            old = db.execute(_queries.ACTION_SELECT_INTEGRATION_SNAPSHOTS_2, (did, sid)).fetchone()
            if old:
                if old[0] != digest:
                    raise IntegrationError("EVENT_CONFLICT", 409)
                return 200, {
                    "integration_version": version,
                    "snapshot_id": sid,
                    "snapshot_digest": digest,
                    "status": json.loads(old[1])["status"],
                }
            for aid, raw in db.execute(_queries.SNAPSHOT_START_REFERENCES, (did, sid)):
                attempt = json.loads(raw)
                if attempt.get("context_ref") == sid and (
                    aid != record["attempt_id"] or record["snapshot_kind"] != "feature"
                ):
                    raise IntegrationError("EVENT_CONFLICT", 409)
            for aid, raw in db.execute(_queries.SNAPSHOT_DECISION_REFERENCES, (did, sid)):
                decision = json.loads(raw)
                if decision.get("decision_ref") == sid and (
                    aid != record["attempt_id"] or record["snapshot_kind"] != "decision"
                ):
                    raise IntegrationError("EVENT_CONFLICT", 409)
            start = db.execute(
                _queries.ACTION_SELECT_INTEGRATION_ATTEMPTS_2, (did, record["attempt_id"])
            ).fetchone()
            if start:
                attempt = json.loads(start[0])
                expected = attempt["context_ref"] if record["snapshot_kind"] == "feature" else None
                if expected and expected != sid:
                    raise IntegrationError("EVENT_CONFLICT", 409)
                if (
                    record["snapshot_kind"] == "decision"
                    and record["available_at"] > attempt["started_at"]
                ):
                    raise IntegrationError("SEMANTIC_INVALID")
            if record["snapshot_kind"] == "decision" and "selected_action" in content:
                rows = db.execute(
                    _queries.ACTION_SELECT_INTEGRATION_EVENTS_2, (did, record["attempt_id"])
                ).fetchall()
                for (raw,) in rows:
                    decision = json.loads(raw)
                    if decision.get("decision_ref") != sid or any(
                        decision.get(key) != content["selected_action"].get(key)
                        for key in (
                            "selected_account_id",
                            "selected_model_id",
                            "policy_version",
                            "eligibility_evidence",
                        )
                        + (
                            ("operation_family", "capability", "selection_kind")
                            if version == "3"
                            else ()
                        )
                    ):
                        raise IntegrationError("EVENT_CONFLICT", 409)
            db.execute(
                _queries.ACTION_INSERT_INTEGRATION_SNAPSHOTS,
                (
                    did,
                    sid,
                    record["attempt_id"],
                    record["snapshot_kind"],
                    digest,
                    encode(metadata),
                    encode(content) if content and record["retention_until"] > _time() else None,
                ),
            )
            return 201, {
                "integration_version": version,
                "snapshot_id": sid,
                "snapshot_digest": digest,
                "status": record["status"],
            }

        return self.store.database.transaction(action)

    def snapshot(self, principal, dataset_id, snapshot_id, version="2"):
        dataset = self._dataset(dataset_id)
        self._authorize(principal, dataset, "snapshot")
        if not _shape(snapshot_id, SCHEMA_V2["$defs"]["id"]):
            raise IntegrationError("SCHEMA_INVALID")
        with self.store.database.read():
            row = self.store.database.execute(
                _queries.SNAPSHOT_SELECT_INTEGRATION_SNAPSHOTS, (dataset_id, snapshot_id)
            ).fetchone()
        if not row:
            raise IntegrationError("NOT_FOUND_OR_FORBIDDEN", 404)
        meta, content, digest = _snapshot_record(*row, _time())
        if (
            content
            and "sha256:"
            + hashlib.sha256(encode({**meta, **json.loads(content)}).encode()).hexdigest()
            != digest
        ):
            raise IntegrationError("SNAPSHOT_INTEGRITY_FAILED", 503, "query_first")
        status = "expired" if meta["status"] == "captured" and content is None else meta["status"]
        return {
            **meta,
            "integration_version": version,
            "status": status,
            "snapshot_digest": digest,
            **(json.loads(content) if content else {}),
        }

    def dataset_export(self, principal, dataset_id, version="2"):
        dataset = self._dataset(dataset_id)
        self._authorize(principal, dataset, "report")
        at = _time()
        with self.store.database.read():
            db = self.store.database
            attempts = [
                json.loads(r[0])
                for r in db.execute(
                    _queries.DATASET_EXPORT_SELECT_INTEGRATION_ATTEMPTS, (dataset_id,)
                )
            ]
            included = {item["attempt_id"] for item in attempts}
            events = [
                json.loads(r[0])
                for r in db.execute(
                    _queries.DATASET_EXPORT_SELECT_INTEGRATION_EVENTS, (dataset_id,)
                )
            ]
            eligible_ids = {
                e["eligibility_evidence"]["eligibility_id"]
                for e in events
                if e.get("attempt_id") in included
                and e["kind"] == "decision"
                and e.get("eligibility_evidence", {}).get("eligibility_id")
            }
            eligibility = [
                json.loads(r[0])
                for r in db.execute(
                    _queries.DATASET_EXPORT_SELECT_INTEGRATION_ELIGIBILITY_READS, (dataset_id,)
                )
                if json.loads(r[0])["eligibility_id"] in eligible_ids
            ]
            snapshots = [
                _snapshot_record(*r, at)
                for r in db.execute(
                    _queries.DATASET_EXPORT_SELECT_INTEGRATION_SNAPSHOTS, (dataset_id,)
                )
            ]
            history = defaultdict(list)
            for (raw,) in db.execute(
                _queries.DATASET_EXPORT_SELECT_INTEGRATION_ACCOUNT_HISTORY, (dataset_id,)
            ):
                item = json.loads(raw)
                if item["dataset_id"] == dataset_id:
                    history[item["account_id"]].append(item)
        snapshot_rows = []
        snapshot_by_id = {
            meta["snapshot_id"]: (meta, content, digest) for meta, content, digest in snapshots
        }
        for meta, content, digest in snapshots:
            if meta["attempt_id"] not in included:
                continue
            decoded = json.loads(content) if content else {}
            if (
                content
                and "sha256:" + hashlib.sha256(encode({**meta, **decoded}).encode()).hexdigest()
                != digest
            ):
                raise IntegrationError("SNAPSHOT_INTEGRITY_FAILED", 503, "query_first")
            snapshot_rows.append(
                {
                    **meta,
                    "status": "expired"
                    if meta["status"] == "captured" and content is None
                    else meta["status"],
                    "snapshot_digest": digest,
                    **decoded,
                }
            )
        reference_assessments = []
        for event in attempts:
            if event.get("integration_version") not in ("2", "3"):
                continue
            sid, kind = event["context_ref"], "feature"
            target = snapshot_by_id.get(sid)
            status = (
                "missing"
                if target is None
                else "binding_conflict"
                if target[0]["attempt_id"] != event["attempt_id"]
                or target[0]["snapshot_kind"] != kind
                else "expired"
                if target[0]["status"] == "captured" and target[1] is None
                else target[0]["status"]
            )
            reference_assessments.append(
                {
                    "attempt_id": event["attempt_id"],
                    "reference_kind": kind,
                    "snapshot_id": sid,
                    "status": status,
                }
            )
        for event in events:
            if (
                event.get("attempt_id") not in included
                or event["kind"] != "decision"
                or event.get("integration_version") not in ("2", "3")
            ):
                continue
            sid = event["decision_ref"]
            target = snapshot_by_id.get(sid)
            status = (
                "missing"
                if target is None
                else "binding_conflict"
                if target[0]["attempt_id"] != event["attempt_id"]
                or target[0]["snapshot_kind"] != "decision"
                else "expired"
                if target[0]["status"] == "captured" and target[1] is None
                else target[0]["status"]
            )
            reference_assessments.append(
                {
                    "attempt_id": event["attempt_id"],
                    "reference_kind": "decision",
                    "snapshot_id": sid,
                    "status": status,
                }
            )
        return {
            "integration_version": version,
            "dataset": dataset,
            "attempts": attempts,
            "events": [
                e
                for e in events
                if e.get("attempt_id") in included
                or e["kind"] == "activity"
                and e["task_id"] in {a["task_id"] for a in attempts}
            ],
            "eligibility_reads": eligibility,
            "snapshots": snapshot_rows,
            "snapshot_reference_assessments": reference_assessments,
            "eligibility_assessments": [
                {
                    "event_id": e["event_id"],
                    "attempt_id": e["attempt_id"],
                    "reported_status": e["eligibility_evidence"]["status"],
                    "assessment": _eligibility_assessment(
                        e,
                        next(
                            (
                                answer
                                for answer in eligibility
                                if answer["eligibility_id"]
                                == e["eligibility_evidence"].get("eligibility_id")
                            ),
                            None,
                        ),
                        history.get(e["selected_account_id"], ()),
                    ),
                }
                for e in events
                if e.get("attempt_id") in included
                and e["kind"] == "decision"
                and e.get("integration_version") in ("2", "3")
            ],
        }

    def report(self, principal, dataset_id, filters=None, version="1"):
        dataset = self._dataset(dataset_id)
        self._authorize(principal, dataset, "report")
        at = _time()
        filters = filters or {}
        if set(filters) - {
            "actor_id",
            "provider_account_id",
            "task_id",
            "model_id",
            "initiating_user_id",
            "root_run_id",
            "run_id",
            "from",
            "to",
        }:
            raise IntegrationError("SCHEMA_INVALID")
        if (
            any(
                not _shape(value, SCHEMA["$defs"]["id"])
                for key, value in filters.items()
                if key not in ("from", "to")
            )
            or any(not _utc(value) for key, value in filters.items() if key in ("from", "to"))
            or (filters.get("from") and filters.get("to") and filters["from"] > filters["to"])
        ):
            raise IntegrationError("SCHEMA_INVALID")
        data = self._read_report_snapshot(dataset_id, version, at)
        by_attempt = defaultdict(list)
        lineage_links = {
            event["attempt_id"]: event for event in data.events if event["kind"] == "lineage"
        }
        outcomes = defaultdict(list)
        for event in data.events:
            if "attempt_id" in event:
                by_attempt[event["attempt_id"]].append(event)
            if event["kind"] == "activity" and event["activity_kind"] == "outcome":
                outcomes[event["task_id"]].append(event)
        rows = []
        totals = defaultdict(Decimal)
        by_actor = defaultdict(lambda: defaultdict(Decimal))
        by_account = defaultdict(lambda: defaultdict(Decimal))
        by_root = defaultdict(lambda: defaultdict(Decimal))
        by_inclusive_run = defaultdict(lambda: defaultdict(Decimal))
        unknown = 0
        for start in data.attempts:
            row = self._report_attempt_row(
                data.account_history,
                data.all_starts,
                by_attempt,
                dataset,
                dataset_id,
                data.eligibility_reads,
                filters,
                lineage_links,
                outcomes,
                data.snapshots,
                start,
                version,
            )
            if row is None:
                continue
            status = row["cost_status"]
            rows.append(row)
            if status != "known":
                unknown += 1
                continue
            currency = row["currency"]
            amount = Decimal(row["amount_decimal"])
            totals[currency] += amount
            by_actor[start["actor_id"]][currency] += amount
            by_account[start["provider_account_id"]][currency] += amount
            by_root[start["root_run_id"]][currency] += amount
            run, seen = start["run_id"], set()
            while run and run not in seen:
                seen.add(run)
                by_inclusive_run[run][currency] += amount
                run = data.runs.get(run)
        money = lambda group: {
            key: {
                currency: format_money(amount, places=9)
                for currency, amount in sorted(values.items())
            }
            for key, values in sorted(group.items())
        }
        return {
            "integration_version": version,
            "dataset_id": dataset_id,
            "attempt_count": len(rows),
            "unknown_cost_attempts": unknown,
            "known_total_by_currency": {
                currency: format_money(value, places=9)
                for currency, value in sorted(totals.items())
            },
            "by_actor": money(by_actor),
            "by_account": money(by_account),
            "by_root_workflow": money(by_root),
            "by_run_including_descendants": money(by_inclusive_run),
            "attempts": rows,
        }

    def _enrich_report_row(
        self,
        row,
        account_history,
        all_starts,
        effective,
        eligibility_reads,
        lineage_links,
        related,
        snapshots,
        start,
    ):
        v2 = start.get("integration_version") in ("2", "3")
        decision = next((item for item in related if item["kind"] == "decision"), None)
        resolution = next((item for item in related if item["kind"] == "account_resolution"), None)
        role, predecessor, lineage_status = _lineage_projection(
            start, lineage_links.get(start["attempt_id"]), all_starts, lineage_links
        )
        history = account_history.get(start["provider_account_id"], ())
        registration = history[0]["registered_at"] if history else None
        if resolution:
            account_status = "resolved"
        elif not registration:
            account_status = "unresolved"
        elif registration > start["started_at"]:
            account_status = "registered_after_start_unconfirmed"
        else:
            account_status = "registered_at_start"

        def snapshot_state(sid, expected_kind, *, start=start):
            if not sid or sid not in snapshots:
                return "missing", None
            meta, content, digest = snapshots[sid]
            if meta["attempt_id"] != start["attempt_id"] or meta["snapshot_kind"] != expected_kind:
                return "binding_conflict", None
            return (
                "expired" if meta["status"] == "captured" and content is None else meta["status"],
                digest,
            )

        feature_status, feature_digest = snapshot_state(
            start.get("context_ref") if v2 else None, "feature"
        )
        decision_status, decision_digest = snapshot_state(
            decision.get("decision_ref") if decision else None, "decision"
        )
        evidence = decision.get("eligibility_evidence", {}) if decision else {}
        assessment = (
            _eligibility_assessment(
                decision,
                eligibility_reads.get(evidence.get("eligibility_id")),
                account_history.get(decision["selected_account_id"], ()),
            )
            if decision and decision.get("integration_version") in ("2", "3")
            else "legacy_absent"
            if decision
            else "missing"
        )
        selected_action = (
            {
                key: decision.get(key)
                for key in (
                    "selected_account_id",
                    "selected_model_id",
                    "operation_family",
                    "capability",
                    "selection_kind",
                    "policy_version",
                    "eligibility_evidence",
                )
            }
            if decision
            else None
        )
        row.update(
            operation_family_version=start.get("operation_family_version"),
            operation_family=start.get("operation_family"),
            model_identity_state=start.get("model_identity_state", "legacy_absent"),
            logical_operation_id=start.get("logical_operation_id"),
            attempt_role=role,
            predecessor_attempt_id=predecessor,
            lineage_status=lineage_status,
            account_resolution_status=account_status,
            resolved_account_id=resolution.get("resolved_account_id") if resolution else None,
            decision_ref=decision.get("decision_ref") if decision else None,
            selected_action=selected_action,
            eligibility_evidence_status=evidence.get("status", "missing"),
            eligibility_assessment=assessment,
            eligibility_record=eligibility_reads.get(evidence.get("eligibility_id")),
            feature_snapshot_status=feature_status,
            feature_snapshot_digest=feature_digest,
            feature_available_before_start=(
                snapshots[start["context_ref"]][0]["available_at"] <= start["started_at"]
                if feature_status == "captured"
                else None
            ),
            decision_snapshot_status=decision_status,
            decision_snapshot_digest=decision_digest,
            usage_provenance=effective.get("usage_provenance") if effective else None,
            usage_state=(effective["usage_state"] if effective else "not_observed")
            if v2
            else "legacy_absent",
        )

    def _report_attempt_row(
        self,
        account_history,
        all_starts,
        by_attempt,
        dataset,
        dataset_id,
        eligibility_reads,
        filters,
        lineage_links,
        outcomes,
        snapshots,
        start,
        version,
    ):
        if any(
            (key in filters and start.get(key) != filters[key])
            for key in (
                "actor_id",
                "provider_account_id",
                "task_id",
                "model_id",
                "initiating_user_id",
                "root_run_id",
                "run_id",
            )
        ):
            return None
        if filters.get("from") and start["started_at"] < filters["from"]:
            return None
        if filters.get("to") and start["started_at"] >= filters["to"]:
            return None
        related = by_attempt[start["attempt_id"]]
        usage = {item["usage_revision"]: item for item in related if item["kind"] == "usage"}
        ordinal = 0
        while ordinal + 1 in usage:
            ordinal += 1
        effective = usage.get(ordinal)
        results = [item for item in related if item["kind"] == "result"]
        latest_result = (
            max(results, key=lambda x: (x["occurred_at"], x["event_id"])) if results else None
        )
        task_outcome = (
            max(outcomes[start["task_id"]], key=lambda x: (x["occurred_at"], x["event_id"]))
            if (outcomes[start["task_id"]])
            else None
        )
        status = (
            effective.get("cost_state", effective["usage_state"]) if effective else "not_observed"
        )
        row = {
            "dataset_id": dataset_id,
            "platform_id": dataset["platform_id"],
            "environment_id": dataset["environment_id"],
            "owner_id": dataset["owner_id"],
            **{
                key: start.get(key)
                for key in (
                    "attempt_id",
                    "started_at",
                    "task_id",
                    "step_id",
                    "run_id",
                    "root_run_id",
                    "parent_run_id",
                    "actor_kind",
                    "actor_id",
                    "initiating_user_id",
                    "provider_account_id",
                    "model_id",
                    "context_ref",
                )
            },
            "result_state": latest_result["result_state"] if latest_result else "not_observed",
            "result_observed_at": latest_result["occurred_at"] if latest_result else None,
            "task_outcome": task_outcome.get("outcome", "not_observed")
            if task_outcome
            else "not_observed",
            "task_outcome_observed_at": task_outcome.get("occurred_at") if task_outcome else None,
            "usage_revision": ordinal or None,
            "cost_status": status,
            "usage_observed_at": effective.get("occurred_at") if effective else None,
            "currency": effective.get("currency") if effective else None,
            "amount_decimal": effective.get("amount_decimal") if effective else None,
            "native_units": effective.get("native_units") if effective else None,
            "cost_basis": effective.get("cost_basis") if effective else None,
            "price_ref": effective.get("price_ref") if effective else None,
            "price_version": effective.get("price_version") if effective else None,
        }
        if version in ("2", "3"):
            self._enrich_report_row(
                row,
                account_history,
                all_starts,
                effective,
                eligibility_reads,
                lineage_links,
                related,
                snapshots,
                start,
            )
        return row

    def _read_report_snapshot(self, dataset_id, version, at) -> AccountingReportData:
        snapshots, eligibility_reads, account_history = {}, {}, {}
        with self.store.database.read():
            attempts = [
                json.loads(row[0])
                for row in self.store.database.execute(
                    _queries.DATASET_EXPORT_SELECT_INTEGRATION_ATTEMPTS, (dataset_id,)
                )
            ]
            all_starts = {
                row[0]: json.loads(row[1])
                for row in self.store.database.execute(
                    _queries.ACTION_SELECT_INTEGRATION_ATTEMPTS, (dataset_id,)
                )
            }
            events = [
                json.loads(row[0])
                for row in self.store.database.execute(
                    _queries.DATASET_EXPORT_SELECT_INTEGRATION_EVENTS, (dataset_id,)
                )
            ]
            runs = {
                row[0]: row[1]
                for row in self.store.database.execute(
                    _queries.REPORT_SELECT_INTEGRATION_RUNS, (dataset_id,)
                )
            }
            if version in ("2", "3"):
                snapshots = {
                    row[0]: _snapshot_record(row[1], row[2], row[3], at)
                    for row in self.store.database.execute(
                        _queries.REPORT_SELECT_INTEGRATION_SNAPSHOTS, (dataset_id,)
                    )
                }
                eligibility_reads = {
                    row[0]: json.loads(row[1])
                    for row in self.store.database.execute(
                        _queries.REPORT_SELECT_INTEGRATION_ELIGIBILITY_READS, (dataset_id,)
                    )
                }
                account_history = defaultdict(list)
                for (raw,) in self.store.database.execute(
                    _queries.DATASET_EXPORT_SELECT_INTEGRATION_ACCOUNT_HISTORY, (dataset_id,)
                ):
                    item = json.loads(raw)
                    if item["dataset_id"] == dataset_id:
                        account_history[item["account_id"]].append(item)
        return AccountingReportData(
            attempts, all_starts, events, runs, snapshots, eligibility_reads, account_history
        )
