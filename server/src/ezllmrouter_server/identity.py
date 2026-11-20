"""Explicit instance identity defaults; persisted identities are never renamed."""

from dataclasses import asdict, dataclass
from collections.abc import Mapping
import json
from typing import cast
from .database import Database, Query

from .identifiers import require_identifier


@dataclass(frozen=True)
class InstanceIdentity:
    owner_id: str = "owner.local"
    task_class: str = "class.demo"
    credential_consumer_id: str = "svc.ezllmrouter.credential-consumer"
    credential_release_purpose: str = "ezllmrouter-provider-dispatch"

    def __post_init__(self) -> None:
        for value in (
            self.owner_id,
            self.task_class,
            self.credential_consumer_id,
            self.credential_release_purpose,
        ):
            require_identifier(value)
        if self.owner_id == self.credential_consumer_id:
            raise ValueError("owner and credential consumer must be distinct identities")


DEFAULT_IDENTITY = InstanceIdentity()


IDENTITY = Query("SELECT value FROM registry_meta WHERE key='instance_identity'")
SAVE_IDENTITY = Query("INSERT INTO registry_meta VALUES ('instance_identity', ?)")
LEGACY_CONSUMER = Query("SELECT 1 FROM registry_principals WHERE id='svc.vega.credential-consumer'")


def _stored(raw: object) -> InstanceIdentity:
    record = json.loads(cast(str, raw))
    if type(record) is not dict or set(record) != set(asdict(DEFAULT_IDENTITY)):
        raise ValueError("invalid persisted instance identity")
    return InstanceIdentity(**record)


def resolve_identity(
    database: Database,
    requested: InstanceIdentity | None = None,
    *,
    overrides: Mapping[str, str] | None = None,
) -> InstanceIdentity:
    with database.read():
        row = database.execute(IDENTITY).fetchone()
        if row is not None:
            stored = _stored(row[0])
            value = requested or stored
            if value != stored:
                raise ValueError(
                    "configured owner or service identity does not match the persisted instance"
                )
        else:
            legacy = database.execute(LEGACY_CONSUMER).fetchone()
            value = requested or (
                InstanceIdentity(
                    credential_consumer_id="svc.vega.credential-consumer",
                    credential_release_purpose="vega-provider-dispatch",
                )
                if legacy
                else DEFAULT_IDENTITY
            )
        if overrides:
            changed = InstanceIdentity(**{**asdict(value), **overrides})
            if row is not None and changed != value:
                raise ValueError(
                    "configured owner or service identity does not match the persisted instance"
                )
            value = changed
        return value


def persist_identity(database: Database, identity: InstanceIdentity) -> None:
    def action() -> None:
        row = database.execute(IDENTITY).fetchone()
        if row is not None:
            if _stored(row[0]) != identity:
                raise ValueError("persisted instance identity conflict")
            return
        database.execute(
            SAVE_IDENTITY, (json.dumps(asdict(identity), sort_keys=True, separators=(",", ":")),)
        )

    database.transaction(action)
