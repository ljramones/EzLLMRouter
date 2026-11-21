"""External accounting datasets operations under the existing service context."""

from __future__ import annotations

from .database import Row

from datetime import datetime
from typing import TYPE_CHECKING, cast
from .records import Record
from .store import decode_record
from .accounting_types import ReceiptResult

if TYPE_CHECKING:
    from .integration_accounting import ExternalAccounting

import hashlib
import uuid
from .repositories import integration_accounting as _queries
from .store import encode
from . import integration_accounting as _api


def _dataset(self: ExternalAccounting, dataset_id: str) -> Record:
    with self.store.database.read():
        row = self.store.database.execute(
            _queries.DATASET_SELECT_INTEGRATION_DATASETS, (dataset_id,)
        ).fetchone()
    if not row:
        raise _api.IntegrationError("NOT_FOUND_OR_FORBIDDEN", 404)
    dataset = decode_record(row[0])
    if not _api._dataset_available(
        dataset, row[1], row[2], datetime.fromisoformat(_api._time().replace("Z", "+00:00"))
    ):
        raise _api.IntegrationError("NOT_FOUND_OR_FORBIDDEN", 404)
    return dataset


def _authorize(self: ExternalAccounting, principal: Record, dataset: Record, action: str) -> None:
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
        raise _api.IntegrationError("NOT_FOUND_OR_FORBIDDEN", 404)


def create_dataset(
    self: ExternalAccounting, principal: Record, body: Record, version: str = "1"
) -> ReceiptResult:
    body = _api._checked(body, "dataset", version)
    if (
        principal["principal_id"] != body["owner_id"]
        or principal["owner"] != body["owner_id"]
        or principal["role"] != "registry_admin"
    ):
        raise _api.IntegrationError("POLICY_DENIED", 403)
    ingest = self.registry.principal(body["ingest_principal_id"])
    if (
        not ingest
        or ingest["status"] != "active"
        or ingest["owner"] != body["owner_id"]
        or ingest["kind"] != "service"
    ):
        raise _api.IntegrationError("POLICY_DENIED", 403)

    def action() -> ReceiptResult:
        db = self.store.database
        local_real = body["dataset_id"].startswith("dataset.local.real.")
        if local_real and self.accounting_retention_days is None:
            raise _api.IntegrationError("POLICY_DENIED", 403)
        if db.execute(
            _queries.ACTION_SELECT_INTEGRATION_EXPIRED_DATASETS, (body["dataset_id"],)
        ).fetchone():
            raise _api.IntegrationError("DATASET_EXPIRED", 410)
        old = db.execute(_queries.DATASET_FOR_UPDATE, (body["dataset_id"],)).fetchone()
        if old:
            if local_real:
                retention = db.execute(
                    _queries.ACTION_SELECT_INTEGRATION_DATASET_RETENTION, (body["dataset_id"],)
                ).fetchone()
                if not retention:
                    raise _api.IntegrationError("POLICY_DENIED", 403)
                try:
                    expiry = _api._cohort_expiry(decode_record(old[0]), *retention)
                except ValueError:
                    raise _api.IntegrationError("POLICY_DENIED", 403) from None
                if expiry <= datetime.fromisoformat(_api._time().replace("Z", "+00:00")):
                    raise _api.IntegrationError("DATASET_EXPIRED", 410)
            if decode_record(old[0]) != body:
                raise _api.IntegrationError("EVENT_CONFLICT", 409)
            return 200, {"integration_version": version, **body}
        if local_real:
            try:
                expiry = _api._cohort_expiry(
                    body, self.accounting_retention_days, body["activated_at"]
                )
            except ValueError:
                raise _api.IntegrationError("POLICY_DENIED", 403) from None
            if expiry <= datetime.fromisoformat(_api._time().replace("Z", "+00:00")):
                raise _api.IntegrationError("DATASET_EXPIRED", 410)
        db.execute(_queries.ACTION_INSERT_INTEGRATION_DATASETS, (body["dataset_id"], encode(body)))
        if local_real:
            db.execute(
                _queries.ACTION_INSERT_INTEGRATION_DATASET_RETENTION,
                (body["dataset_id"], self.accounting_retention_days, body["activated_at"]),
            )
        return 201, {"integration_version": version, **body}

    return self.store.database.transaction(action)


def create_account(
    self: ExternalAccounting, principal: Record, body: Record, version: str = "1"
) -> ReceiptResult:
    body = _api._checked(body, "account", version)
    dataset = self._dataset(body["dataset_id"])
    self._authorize(principal, dataset, "admin")

    def action() -> ReceiptResult:
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
            record = decode_record(cast(Row, original)[0])
            if {k: record[k] for k in body} != body:
                raise _api.IntegrationError("EVENT_CONFLICT", 409)
            return 200, {"integration_version": version, **record}
        record = {
            **body,
            "owner_id": dataset["owner_id"],
            "revision": 1,
            "registered_at": _api._time(),
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


def set_account_state(
    self: ExternalAccounting, principal: Record, account_id: str, body: Record, version: str = "1"
) -> ReceiptResult:
    body = _api._checked(body, "account_state", version)
    dataset = self._dataset(body["dataset_id"])
    self._authorize(principal, dataset, "admin")

    def action() -> ReceiptResult:
        db = self.store.database
        self._authorize(principal, self._dataset(body["dataset_id"]), "admin")
        row = db.execute(
            _queries.ACTION_SELECT_INTEGRATION_ACCOUNTS, (account_id, body["dataset_id"])
        ).fetchone()
        if not row:
            raise _api.IntegrationError("NOT_FOUND_OR_FORBIDDEN", 404)
        record = decode_record(row[0])
        if record["revision"] != body["expected_revision"]:
            raise _api.IntegrationError("STALE_REVISION", 409)
        record.update(state=body["state"], revision=record["revision"] + 1, changed_at=_api._time())
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


def set_account_permissions(
    self: ExternalAccounting, principal: Record, account_id: str, body: Record
) -> ReceiptResult:
    """Explicit v3 opt-in; an existing v1/v2 account starts with no speech permissions."""
    body = _api._checked(body, "account_permissions", "3")
    dataset = self._dataset(body["dataset_id"])
    self._authorize(principal, dataset, "admin")

    def action() -> ReceiptResult:
        db = self.store.database
        self._authorize(principal, self._dataset(body["dataset_id"]), "admin")
        row = db.execute(
            _queries.ACTION_SELECT_INTEGRATION_ACCOUNTS, (account_id, body["dataset_id"])
        ).fetchone()
        if not row:
            raise _api.IntegrationError("NOT_FOUND_OR_FORBIDDEN", 404)
        record = decode_record(row[0])
        if record["revision"] != body["expected_revision"]:
            raise _api.IntegrationError("STALE_REVISION", 409)
        record.update(
            allowed_models=body["allowed_models"],
            allowed_operations=body["allowed_operations"],
            revision=record["revision"] + 1,
            changed_at=_api._time(),
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
    self: ExternalAccounting,
    principal: Record,
    dataset_id: str,
    account_id: str,
    model_id: str | None,
    version: str = "1",
    operation_family: str | None = None,
    capability: str | None = None,
    selection_kind: str | None = None,
) -> Record:
    dataset = self._dataset(dataset_id)
    self._authorize(principal, dataset, "eligibility")
    _validate_eligibility_selection(model_id, version, operation_family, capability, selection_kind)

    def action() -> Record:
        self._authorize(principal, self._dataset(dataset_id), "eligibility")
        row = self.store.database.execute(
            _queries.ACTION_SELECT_INTEGRATION_ACCOUNTS, (account_id, dataset_id)
        ).fetchone()
        if not row:
            raise _api.IntegrationError("NOT_FOUND_OR_FORBIDDEN", 404)
        record = decode_record(row[0])
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
                eligibility_id="eligibility." + uuid.uuid4().hex, evaluated_at=_api._time()
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


def datasets(self: ExternalAccounting, principal: Record) -> Record:
    if principal["role"] not in ("registry_admin", "read_only_operator"):
        raise _api.IntegrationError("POLICY_DENIED", 403)
    with self.store.database.read():
        rows = self.store.database.execute(_queries.DATASETS_SELECT_INTEGRATION_DATASETS).fetchall()
    at = datetime.fromisoformat(_api._time().replace("Z", "+00:00"))
    items = []
    for raw, days, activated_at in rows:
        item = decode_record(raw)
        if item["owner_id"] == principal["owner"] and _api._dataset_available(
            item, days, activated_at, at
        ):
            items.append(item)
    return {"integration_version": _api.VERSION, "items": items}


def accounts(self: ExternalAccounting, principal: Record, dataset_id: str) -> Record:
    dataset = self._dataset(dataset_id)
    self._authorize(principal, dataset, "report")
    with self.store.database.read():
        rows = [
            decode_record(row[0])
            for row in self.store.database.execute(
                _queries.ACCOUNTS_SELECT_INTEGRATION_ACCOUNTS, (dataset_id,)
            )
        ]
    return {"integration_version": _api.VERSION, "dataset_id": dataset_id, "items": rows}


def _validate_eligibility_selection(
    model_id: str | None,
    version: str,
    operation_family: str | None,
    capability: str | None,
    selection_kind: str | None,
) -> None:
    if version == "3":
        if (
            operation_family not in _api._CAPABILITIES
            or capability not in _api._CAPABILITIES[operation_family]
            or selection_kind not in ("known_model", "provider_selected", "not_applicable")
            or (selection_kind == "known_model") != (model_id is not None)
            or selection_kind != "known_model"
            and operation_family not in ("speech_input", "speech_output")
        ):
            raise _api.IntegrationError("SCHEMA_INVALID")
    if (
        model_id is not None
        and not _api._shape(model_id, _api.SCHEMA["$defs"]["id"])
        or version != "3"
        and model_id is None
    ):
        raise _api.IntegrationError("SCHEMA_INVALID")
