"""Registry grants operations; caller owns the existing authority context."""

from __future__ import annotations

import json
from ..errors import RegistryConflict
from ..repositories import registry as _queries
from ..store import encode
from ..registry_values import timestamp, identifier


def _apply_grant(self, db, actor, action, subject, expected, data):
    if set(data) != {"configuration_ref", "status", "purposes", "task_classes"} or data[
        "status"
    ] not in ("active", "removed"):
        raise ValueError("invalid grant")
    ref = identifier(data["configuration_ref"])
    principal_row = db.execute(
        _queries.REQUIRE_ADMIN_SELECT_REGISTRY_PRINCIPALS, (subject,)
    ).fetchone()
    model_row = db.execute(_queries.MODEL_FOR_UPDATE, (ref,)).fetchone()
    if not principal_row or not model_row:
        raise ValueError("unregistered grant target")
    principal, model = json.loads(principal_row[0]), json.loads(model_row[0])
    if principal["status"] == "revoked":
        raise ValueError("revoked principal cannot receive grants")
    if data["status"] == "active" and (
        model.get("kind") == "real_catalogue" or model["status"] != "enabled"
    ):
        raise ValueError("model has no executable grant route")
    if (
        data["status"] == "active"
        and model.get("kind") == "provider_deployment"
        and not self.source_model_allowed(
            model["destination"]["connection_id"], model["destination"]["model"]
        )
    ):
        raise ValueError("source model disallowed")
    if data["status"] == "active" and model.get("kind") == "provider_deployment":
        destination = model["destination"]
        connection_row = db.execute(
            _queries.APPLY_SELECT_REGISTRY_CONNECTIONS, (destination["connection_id"],)
        ).fetchone()
        connection = json.loads(connection_row[0]) if connection_row else None
        if (
            not connection
            or connection["status"] != "active"
            or connection["revision"] != destination["connection_revision"]
            or connection["credential_version"] != destination["credential_version"]
        ):
            raise ValueError("provider connection unavailable for new grant")
    row = db.execute(_queries.APPLY_SELECT_REGISTRY_GRANTS, (subject, ref)).fetchone()
    old = json.loads(row[0]) if row else None
    if expected != (old["revision"] if old else 0):
        raise RegistryConflict("stale grant")
    for field in ("purposes", "task_classes"):
        if type(data[field]) is not list or not data[field]:
            raise ValueError("invalid grant scope")
    record = {
        "principal_id": subject,
        "configuration_ref": ref,
        "status": data["status"],
        "revision": expected + 1,
        "purposes": sorted({identifier(x) for x in data["purposes"]}),
        "task_classes": sorted({identifier(x) for x in data["task_classes"]}),
        "actor": actor,
        "at": timestamp(),
    }
    db.execute(_queries.APPLY_INSERT_REGISTRY_GRANTS, (subject, ref, encode(record)))
    return record
