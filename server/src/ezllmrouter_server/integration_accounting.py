"""Durable accounting of externally executed work; no sender or submission path."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, cast
from .records import Record
from .store import Store, decode_record
from .accounting_types import RecordIndex, EventGroups, SnapshotData, SnapshotIndex

if TYPE_CHECKING:
    from .registry import Registry

import hashlib
import re
from dataclasses import dataclass
from datetime import timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import unquote_to_bytes

from .errors import RequestError
from .formatting import utc_timestamp
from .observability import log_failure
from .repositories import integration_accounting as _queries
from .store import encode

VERSION = "1"
SCHEMA = decode_record((Path(__file__).parent / "integration_schema.json").read_text())
SCHEMA_V2 = decode_record((Path(__file__).parent / "integration_schema_v2.json").read_text())
SCHEMA_V3 = decode_record((Path(__file__).parent / "integration_schema_v3.json").read_text())
SCHEMAS = {"1": SCHEMA, "2": SCHEMA_V2, "3": SCHEMA_V3}
_CAPABILITIES: dict[str, tuple[str, ...]] = {
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
    def __init__(self, code: str, status: int = 400, retry_guidance: str = "never") -> None:
        super().__init__(code, status)
        self.retry_guidance = retry_guidance


def _cohort_expiry(dataset: Record, days: object, activated_at: object) -> datetime:
    try:
        if (
            type(days) is not int
            or not 1 <= days <= 397
            or not _utc(activated_at)
            or dataset["activated_at"] != activated_at
        ):
            raise ValueError("invalid accounting retention metadata")
        return datetime.fromisoformat(cast(str, activated_at).replace("Z", "+00:00")) + timedelta(
            days=days
        )
    except (ValueError, KeyError, TypeError, OverflowError):
        raise ValueError("invalid accounting retention metadata") from None


def _dataset_available(dataset: Record, days: object, activated_at: object, at: datetime) -> bool:
    if not dataset["dataset_id"].startswith("dataset.local.real."):
        return True
    try:
        return _cohort_expiry(dataset, days, activated_at) > at
    except ValueError:
        return False


def _snapshot_record(metadata: object, content: object, digest: object, at: str) -> SnapshotData:
    meta = decode_record(metadata)
    if meta["status"] == "captured" and meta["retention_until"] <= at:
        content = None
    return meta, cast(str | None, content), cast(str | None, digest)


def _shape(value: object, schema: Record, definitions: Record | None = None) -> bool:
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


def _utc(value: object) -> bool:
    if type(value) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
        return False
    try:
        return datetime.fromisoformat(
            value.replace("Z", "+00:00")
        ).utcoffset() == timezone.utc.utcoffset(None)
    except ValueError:
        return False


def _time() -> str:
    return utc_timestamp(datetime.now(timezone.utc))


def _eligibility_assessment(
    event: Record, observed: Record | None, history: Sequence[Record]
) -> str:
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
    return _eligibility_freshness(event, observed, history)


def _lineage_projection(
    start: Record, link: Record | None, starts: RecordIndex, links: RecordIndex
) -> tuple[str | None, str | None, str]:
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


def _checked(value: object, definition: str, version: str = "1") -> Record:
    definitions = SCHEMAS[version]["$defs"]
    if not _shape(value, definitions[definition], definitions):
        raise IntegrationError("SCHEMA_INVALID")

    value = cast(Record, value)
    _walk_values(value)
    if definition == "event":
        _check_event_semantics(value, version)
    if definition == "snapshot":
        _check_snapshot_semantics(value)
    return value


def route_id(raw: str) -> str:
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

    attempts: list[Record]
    all_starts: RecordIndex
    events: list[Record]
    runs: dict[str, str | None]
    snapshots: SnapshotIndex
    eligibility_reads: RecordIndex
    account_history: EventGroups


from . import accounting_datasets
from . import accounting_events
from . import accounting_lineage
from . import accounting_snapshots
from . import accounting_reports
from . import accounting_exports


class ExternalAccounting:
    def __init__(
        self: ExternalAccounting,
        registry: Registry,
        *,
        feature_policy: Record | None = None,
        accounting_retention_days: int | None = None,
    ) -> None:
        self.feature_policy = feature_policy
        self.accounting_retention_days = accounting_retention_days
        self.registry: Registry = registry
        self.store: Store = registry.store
        self._expire_snapshots()

    _expire_snapshots = accounting_snapshots._expire_snapshots

    def maintain(self: ExternalAccounting) -> dict[str, int]:
        """Explicit physical cleanup; read methods enforce expiry without writing."""
        return {
            "expired_datasets": self.expire_datasets(),
            "expired_snapshots": self._expire_snapshots(),
        }

    def expire_datasets(self: ExternalAccounting) -> int:
        """Purge adopted local real cohorts at T0 plus the configured horizon.

        The default service has no accounting expiry, preserving historical
        synthetic datasets and accepted releases. A tombstone prevents an
        expired dataset ID from being recreated or backfilled.
        """
        now = datetime.fromisoformat(_time().replace("Z", "+00:00"))

        db = self.store.database

        def due(raw: object, days: object, activated_at: object) -> bool:
            try:
                return _cohort_expiry(decode_record(raw), days, activated_at) <= now
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

        def action() -> int:
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

    _dataset = accounting_datasets._dataset

    _authorize = accounting_datasets._authorize

    create_dataset = accounting_datasets.create_dataset

    create_account = accounting_datasets.create_account

    set_account_state = accounting_datasets.set_account_state

    set_account_permissions = accounting_datasets.set_account_permissions

    eligibility = accounting_datasets.eligibility

    datasets = accounting_datasets.datasets

    accounts = accounting_datasets.accounts

    _bind_run = accounting_lineage._bind_run

    _check_lineage = accounting_lineage._check_lineage

    _check_decision_evidence = accounting_events._check_decision_evidence

    _check_snapshot_reference = accounting_events._check_snapshot_reference

    append_event = accounting_events.append_event

    receipt = accounting_events.receipt

    append_snapshot = accounting_snapshots.append_snapshot

    snapshot = accounting_snapshots.snapshot

    dataset_export = accounting_exports.dataset_export

    report = accounting_reports.report

    _enrich_report_row = accounting_reports._enrich_report_row

    _report_attempt_row = accounting_reports._report_attempt_row

    _read_report_snapshot = accounting_reports._read_report_snapshot


def _walk_values(item: object) -> None:
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
            ) and (not _utc(child)):
                raise IntegrationError("SCHEMA_INVALID")
            _walk_values(child)
    elif isinstance(item, list):
        for child in item:
            _walk_values(child)
    elif type(item) is str and any((ord(c) < 32 or 55296 <= ord(c) <= 57343 for c in item)):
        raise IntegrationError("SCHEMA_INVALID")


def _check_event_semantics(value: Record, version: str) -> None:
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


def _check_snapshot_semantics(value: Record) -> None:
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


def _eligibility_freshness(event: Record, observed: Record, history: Sequence[Record]) -> str:
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
