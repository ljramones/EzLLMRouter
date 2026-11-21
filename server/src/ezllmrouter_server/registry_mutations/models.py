"""Registry models operations; caller owns the existing authority context."""

from __future__ import annotations

from typing import cast
from ..database import Row

from typing import TYPE_CHECKING
from ..database import Database
from ..records import Record
from ..store import decode_record

if TYPE_CHECKING:
    from ..registry import Registry

import secrets
from copy import deepcopy
from ..errors import RegistryConflict
from ..identifiers import require_text as nonempty
from ..repositories import registry as _queries
from ..catalogue import operator_reference_price
from ..store import encode
from ..registry_values import MODELS, timestamp, identifier


def _apply_create_model(
    self: Registry, db: Database, actor: str, action: str, subject: str, expected: int, data: Record
) -> Record:
    if expected or set(data) != {
        "display_name",
        "model",
        "model_version",
        "owner",
        "capabilities",
        "purposes",
        "task_classes",
    }:
        raise ValueError("invalid model creation")
    if db.execute(_queries.APPLY_SELECT_REGISTRY_MODELS, (subject,)).fetchone():
        raise RegistryConflict("model exists")
    model_name = data["model"]
    # A non-synthetic name may be catalogued only as unsupported draft.
    identifier(model_name)
    for field in ("capabilities", "purposes", "task_classes"):
        if (
            type(data[field]) is not list
            or not data[field]
            or any(type(x) is not str for x in data[field])
        ):
            raise ValueError("invalid model constraints")
    if set(data["capabilities"]) - {"text", "tools"}:
        raise ValueError("unsupported model capability")
    record = {
        "configuration_ref": subject,
        "display_name": nonempty(data["display_name"]),
        "status": "draft",
        "revision": 1,
        "destination": {
            "configuration_ref": subject,
            "service": "litellm.dev04",
            "endpoint": "127.0.0.1",
            "model": model_name,
            "model_version": identifier(data["model_version"]),
            "processing_region": "local",
        },
        "owner": identifier(data["owner"]),
        "capabilities": sorted(set(data["capabilities"])),
        "purposes": sorted({identifier(x) for x in data["purposes"]}),
        "task_classes": sorted({identifier(x) for x in data["task_classes"]}),
        "handling": ["no.content.store"],
        "approved_by": None,
        "approved_at": None,
        "legacy_unpriced": False,
    }
    db.execute(_queries.APPLY_INSERT_REGISTRY_MODELS, (subject, encode(record)))
    return record


def _apply_model_change(
    self: Registry, db: Database, actor: str, action: str, subject: str, expected: int, data: Record
) -> Record:
    record = self._load_for_update(db, "registry_models", "ref", subject, expected)
    if record["status"] in ("revoked", "archived"):
        raise RegistryConflict("retired model cannot be changed")
    if action == "edit_model":
        _edit_model(self, db, actor, action, subject, record, data)
    elif action == "edit_catalogue_model":
        _edit_catalogue_model(self, db, actor, action, subject, record, data)
    elif action in ("publish_reference_price", "correct_reference_price"):
        _reference_price(self, db, actor, action, subject, record, data)
    elif action == "archive_model":
        _archive_model(self, db, actor, action, subject, record, data)
    else:
        _model_state(self, db, actor, action, subject, record, data)
    record["revision"] += 1
    db.execute(_queries.APPLY_UPDATE_REGISTRY_MODELS, (encode(record), subject))
    return record


def _edit_model(
    self: Registry,
    db: Database,
    actor: str,
    action: str,
    subject: str,
    record: Record,
    data: Record,
) -> None:
    if set(data) != {"display_name"}:
        raise ValueError("immutable deployment identity")
    record["display_name"] = nonempty(data["display_name"])
    if record.get("kind") == "real_catalogue":
        record.setdefault("original_research", deepcopy(record["catalogue"]))
        record["catalogue"]["display_name"] = record["display_name"]


def _edit_catalogue_model(
    self: Registry,
    db: Database,
    actor: str,
    action: str,
    subject: str,
    record: Record,
    data: Record,
) -> None:
    if record.get("kind") != "real_catalogue" or set(data) != {"display_name", "notes"}:
        raise ValueError("only local catalogue settings may be edited")
    record.setdefault("original_research", deepcopy(record["catalogue"]))
    record["display_name"] = nonempty(data["display_name"])
    record["catalogue"].update(
        display_name=record["display_name"], notes=[nonempty(data["notes"], 500)]
    )
    record["catalogue"]["operator_edited_at"] = timestamp()


def _reference_price(
    self: Registry,
    db: Database,
    actor: str,
    action: str,
    subject: str,
    record: Record,
    data: Record,
) -> None:
    if record.get("kind") != "real_catalogue" or record["status"] != "catalogued":
        raise ValueError("reference price requires catalogued model")
    at = timestamp()
    if action == "correct_reference_price":
        if set(data) != {"source_title", "source_url", "bands"}:
            raise ValueError("invalid price correction")
        data = {**data, "snapshot_id": "operator.corrected." + secrets.token_hex(16)}
    price, source = operator_reference_price(data, at)
    versions = {record["catalogue"]["price_reference"]["snapshot_id"]} | {
        item["price"]["snapshot_id"] for item in record.get("reference_price_history", [])
    }
    if price["snapshot_id"] in versions:
        raise RegistryConflict("reference price snapshot exists")
    record.setdefault("original_research", deepcopy(record["catalogue"]))
    record.setdefault("reference_price_history", []).append(
        {
            "price": deepcopy(record["catalogue"]["price_reference"]),
            "sources": deepcopy(record["source_links"]),
        }
    )
    record["catalogue"]["price_reference"] = price
    record["catalogue"]["source_refs"] = [source["id"]]
    record["source_links"] = [source]
    record["price_version"] = price["snapshot_id"]


def _archive_model(
    self: Registry,
    db: Database,
    actor: str,
    action: str,
    subject: str,
    record: Record,
    data: Record,
) -> None:
    if set(data) != {"reason"}:
        raise ValueError("invalid model archive")
    record["state_reason"] = nonempty(data["reason"])
    record["status"] = "archived" if record.get("kind") == "real_catalogue" else "revoked"


def _model_state(
    self: Registry,
    db: Database,
    actor: str,
    action: str,
    subject: str,
    record: Record,
    data: Record,
) -> None:
    if set(data) != {"status", "reason"} or data["status"] not in (
        "enabled",
        "disabled",
        "revoked",
    ):
        raise ValueError("invalid model state")
    nonempty(data["reason"])
    if data["status"] == "enabled":
        if record.get("kind") == "real_catalogue":
            raise ValueError("catalogued reference has no runtime binding")
        if record.get("kind") == "provider_deployment":
            if not self.source_model_allowed(
                record["destination"]["connection_id"], record["destination"]["model"]
            ):
                raise ValueError("source model not allowed")
            if not self.provider_execution_ready:
                raise ValueError("selected provider execution path not validated")
            destination = record["destination"]
            row = db.execute(
                _queries.APPLY_SELECT_REGISTRY_CONNECTIONS,
                (destination["connection_id"],),
            ).fetchone()
            connection = decode_record(row[0]) if row else None
            if (
                not connection
                or connection["status"] != "active"
                or connection["revision"] != destination["connection_revision"]
                or connection["credential_version"] != destination["credential_version"]
            ):
                raise ValueError("provider binding stale")
            deployment = decode_record(
                cast(
                    Row,
                    db.execute(
                        _queries.APPLY_SELECT_REGISTRY_DEPLOYMENTS,
                        (destination["deployment_id"],),
                    ).fetchone(),
                )[0]
            )
            deployment["execution_approved"] = True
            deployment["approved_by"] = actor
            deployment["approved_at"] = timestamp()
            deployment["revision"] += 1
            db.execute(
                _queries.APPLY_UPDATE_REGISTRY_DEPLOYMENTS,
                (encode(deployment), destination["deployment_id"]),
            )
        elif record["destination"]["model"] not in MODELS:
            raise ValueError("unsupported synthetic transport")
        if (
            not record["legacy_unpriced"]
            and not db.execute(_queries.MODEL_HAS_PRICE, (subject,)).fetchone()
        ):
            raise ValueError("price required before enable")
        record["approved_by"], record["approved_at"] = actor, timestamp()
    if record.get("kind") == "real_catalogue" and data["status"] != "revoked":
        raise ValueError("reference catalogue state is not executable")
    record["status"] = data["status"]
    record["state_reason"] = data["reason"]
