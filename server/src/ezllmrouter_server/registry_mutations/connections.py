"""Registry connections operations; caller owns the existing authority context."""

from __future__ import annotations

from typing import cast
from ..database import Row

from typing import TYPE_CHECKING
from ..database import Database
from ..records import Record
from ..store import decode_record

if TYPE_CHECKING:
    from ..registry import Registry

from ..errors import RegistryConflict
from ..identifiers import require_text as nonempty
from ..repositories import registry as _queries
from ..provider_adapters import ADAPTERS, PROVIDERS, validate_settings
from ..store import encode
from ..registry_values import timestamp, identifier


def _apply_create_connection(
    self: Registry, db: Database, actor: str, action: str, subject: str, expected: int, data: Record
) -> Record:
    if (
        expected
        or set(data)
        not in (
            {"display_name", "adapter_id", "settings", "owner"},
            {"display_name", "adapter_id", "settings", "owner", "funding_kind"},
        )
        or not subject.startswith("conn.")
    ):
        raise ValueError("invalid connection creation")
    if db.execute(_queries.CONNECTION_EXISTS, (subject,)).fetchone():
        raise RegistryConflict("connection exists")
    adapter_id = identifier(data["adapter_id"])
    settings = data["settings"]
    provider = validate_settings(adapter_id, settings, controlled=self.controlled_provider_proof)
    funding_kind = data.get("funding_kind", "unspecified_legacy")
    if funding_kind not in (
        "unspecified_legacy",
        "personal_testing",
        "organization",
        "controlled",
    ):
        raise ValueError("invalid funding provenance")
    if funding_kind == "personal_testing" and data["owner"] != self.identity.owner_id:
        raise ValueError("personal testing must use the existing owner identity")
    record = {
        "connection_id": subject,
        "display_name": nonempty(data["display_name"]),
        "provider_id": provider,
        "provider_name": PROVIDERS[provider],
        "adapter_id": adapter_id,
        "adapter_version": adapter_id.rsplit(".", 1)[-1],
        "settings": settings,
        "owner": identifier(data["owner"]),
        "funding_kind": funding_kind,
        "status": "draft",
        "revision": 1,
        "credential_ref": None,
        "credential_version": 0,
        "credential_state": "absent",
        "created_at": timestamp(),
        "network_policy": "commercial_public_only"
        if provider != "vllm"
        else "approved_private_lab",
        "checks_scheduled": False,
        "scheduled_operation": None,
        "check_interval_seconds": None,
    }
    db.execute(_queries.APPLY_INSERT_REGISTRY_CONNECTIONS, (subject, encode(record)))
    return record


def _apply_connection_change(
    self: Registry, db: Database, actor: str, action: str, subject: str, expected: int, data: Record
) -> Record:
    record = self._load_for_update(db, "registry_connections", "id", subject, expected)
    if record["status"] == "archived":
        raise RegistryConflict("archived connection is immutable")
    if action == "edit_connection":
        if set(data) != {"display_name"}:
            raise ValueError(
                "connection endpoint and protocol are immutable; create a new connection"
            )
        record["display_name"] = nonempty(data["display_name"])
    elif action == "connection_state":
        if set(data) != {"status", "reason"} or data["status"] not in (
            "draft",
            "active",
            "disabled",
            "archived",
        ):
            raise ValueError("invalid connection state")
        if data["status"] == "active" and record["credential_state"] != "present":
            raise ValueError("credential required before connection activation")
        record["status"] = data["status"]
        record["state_reason"] = nonempty(data["reason"], 300)
    elif action == "probe_schedule":
        _set_probe_schedule(db, record, data)
    else:
        if (
            set(data) != {"deployment_id", "model_ref", "serving_id", "site", "status"}
            or data["status"] != "catalogued"
        ):
            raise ValueError("invalid model association")
        deployment_id = identifier(data["deployment_id"])
        model_ref = identifier(data["model_ref"])
        model_row = db.execute(_queries.MODEL_FOR_UPDATE, (model_ref,)).fetchone()
        if not model_row or decode_record(model_row[0]).get("kind") != "real_catalogue":
            raise ValueError("association requires existing real catalogue model")
        if db.execute(_queries.DEPLOYMENT_EXISTS, (deployment_id,)).fetchone():
            raise RegistryConflict("deployment identity exists")
        deployment = {
            "deployment_id": deployment_id,
            "connection_id": subject,
            "model_ref": model_ref,
            "serving_id": identifier(data["serving_id"]),
            "site": nonempty(data["site"]),
            "status": "catalogued",
            "revision": 1,
            "execution_approved": False,
            "created_at": timestamp(),
        }
        db.execute(_queries.APPLY_INSERT_REGISTRY_DEPLOYMENTS, (deployment_id, encode(deployment)))
    record["revision"] += 1
    db.execute(_queries.APPLY_UPDATE_REGISTRY_CONNECTIONS, (encode(record), subject))
    return record


def _set_probe_schedule(db: Database, record: Record, data: Record) -> None:
    if (
        set(data) != {"enabled", "operation", "interval_seconds"}
        or type(data["enabled"]) is not bool
    ):
        raise ValueError("invalid probe schedule")
    if data["enabled"]:
        if (
            data["operation"] not in ("access", "inventory", "readiness")
            or ADAPTERS[record["adapter_id"]].get(data["operation"]) is None
            or type(data["interval_seconds"]) is not int
            or not 300 <= data["interval_seconds"] <= 86400
        ):
            raise ValueError("unsupported scheduled probe")
        if (
            not record["checks_scheduled"]
            and cast(int, cast(Row, db.execute(_queries.SCHEDULED_CONNECTION_COUNT).fetchone())[0])
            >= 16
        ):
            raise ValueError("scheduled connection limit")
    elif data["operation"] is not None or data["interval_seconds"] is not None:
        raise ValueError("disabled schedule must be empty")
    record.update(
        checks_scheduled=data["enabled"],
        scheduled_operation=data["operation"],
        check_interval_seconds=data["interval_seconds"],
    )
