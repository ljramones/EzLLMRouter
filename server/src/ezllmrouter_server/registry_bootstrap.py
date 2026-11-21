"""Private bootstrap steps, called inside the original Registry transaction."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING
from .database import Database
from .records import Record
from .store import encode
from .repositories import registry as _queries
from .registry_values import DESTINATION, timestamp

if TYPE_CHECKING:
    from .registry import Registry


def _bootstrap_records(
    self: Registry, destination: Record, trusted: Record, at: str
) -> tuple[Record, Record, Record, Record]:
    model = {
        "configuration_ref": destination["configuration_ref"],
        "display_name": "Legacy synthetic demo",
        "status": "enabled",
        "revision": 1,
        "destination": {k: destination[k] for k in DESTINATION},
        "owner": self.identity.owner_id,
        "capabilities": ["text", "tools"],
        "purposes": ["execution"],
        "task_classes": [self.identity.task_class],
        "handling": ["no.content.store"],
        "approved_by": self.identity.owner_id,
        "approved_at": at,
        "legacy_unpriced": True,
    }
    owner = {
        "principal_id": self.identity.owner_id,
        "display_name": "Local owner",
        "kind": "human",
        "owner": self.identity.owner_id,
        "status": "active",
        "role": "registry_admin",
        "revision": 1,
        "credential_state": "local_operator",
    }
    demo = {
        "principal_id": trusted["principal_id"],
        "display_name": "Local demo service",
        "kind": "service",
        "owner": trusted["charging_owner_id"],
        "status": "active",
        "role": "ordinary",
        "revision": 1,
        "credential_state": "bound",
    }
    grant = {
        "principal_id": demo["principal_id"],
        "configuration_ref": model["configuration_ref"],
        "status": "active",
        "revision": 1,
        "purposes": ["execution"],
        "task_classes": [self.identity.task_class],
        "actor": self.identity.owner_id,
        "at": at,
    }
    return model, owner, demo, grant


def _seed_bootstrap(
    self: Registry,
    db: Database,
    destination: Record | None,
    token: str | None,
    trusted: Record | None,
) -> None:
    if destination is None or token is None or trusted is None:
        raise RuntimeError("private bootstrap inputs required")
    at = timestamp()
    model, owner, demo, grant = _bootstrap_records(self, destination, trusted, at)
    db.execute(
        _queries.APPLY_INSERT_REGISTRY_MODELS,
        (model["configuration_ref"], encode(model)),
    )
    for principal in (owner, demo):
        db.execute(
            _queries.APPLY_INSERT_REGISTRY_PRINCIPALS,
            (principal["principal_id"], encode(principal)),
        )
    db.execute(
        _queries.ACTION_INSERT_REGISTRY_GRANTS,
        (demo["principal_id"], model["configuration_ref"], encode(grant)),
    )
    db.execute(
        _queries.ACTION_INSERT_REGISTRY_CREDENTIALS,
        (
            hashlib.sha256(token.encode()).hexdigest(),
            demo["principal_id"],
            "legacy.demo",
        ),
    )
    for key, value in (
        ("bootstrap_version", "1"),
        ("authority_revision", "1"),
        ("bootstrap_source", "private-dev06-local"),
    ):
        db.execute(_queries.ACTION_INSERT_REGISTRY_META, (key, value))
    db.execute(
        _queries.ACTION_INSERT_REGISTRY_AUDIT,
        (self.identity.owner_id, "bootstrap", "local.synthetic", None, 1, 1, at),
    )
