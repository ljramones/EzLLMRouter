"""Registry registry_sources operations; caller owns the existing authority context."""

from __future__ import annotations

import hashlib
import json
from .errors import RegistryConflict
from .repositories import registry as _queries
from .store import encode
from .registry_values import timestamp, identifier


def _source_key(connection_id, serving_id):
    return hashlib.sha256(encode([connection_id, serving_id]).encode()).hexdigest()


def source_permission(self, connection_id, serving_id):
    identifier(connection_id)
    if type(serving_id) is not str or not 1 <= len(serving_id) <= 256:
        raise ValueError("invalid serving model ID")
    return self._record(
        "registry_source_permissions", "id=?", (self._source_key(connection_id, serving_id),)
    )


def source_model_allowed(self, connection_id, serving_id):
    permission = self.source_permission(connection_id, serving_id)
    if permission is not None:
        return permission["allowed"] is True
    # Older explicitly enabled deployments retain their reviewed permission.
    return any(
        item["serving_id"] == serving_id and item["execution_approved"] is True
        for item in self.deployments(connection_id)
    )


def source_inventory(self, connection_id):
    """Connection-scoped stored inventory; reads never probe or change authority."""
    connection = self.connection(connection_id)
    if not connection:
        raise ValueError("unknown connection")
    with self.store.database.read():
        observations = [
            json.loads(row[0])
            for row in self.store.database.execute(
                _queries.SOURCE_INVENTORY_SELECT_REGISTRY_OBSERVATIONS, (connection_id,)
            ).fetchall()
        ]
        permissions = {
            json.loads(row[0])["serving_id"]: json.loads(row[0])
            for row in self.store.database.execute(
                _queries.SOURCE_INVENTORY_SELECT_REGISTRY_SOURCE_PERMISSIONS, (connection_id,)
            ).fetchall()
        }
        deployments = self.deployments(connection_id)
        models = {
            item["configuration_ref"]: item
            for (raw,) in self.store.database.execute(_queries.INVENTORY_MODELS, (connection_id,))
            for item in (json.loads(raw),)
        }
        prices_by_ref = {}
        for (raw,) in self.store.database.execute(_queries.INVENTORY_PRICES, (connection_id,)):
            item = json.loads(raw)
            prices_by_ref.setdefault(item["configuration_ref"], []).append(item)
        grants_by_ref = {}
        for (raw,) in self.store.database.execute(_queries.INVENTORY_GRANTS, (connection_id,)):
            item = json.loads(raw)
            grants_by_ref.setdefault(item["configuration_ref"], []).append(item)
    latest = observations[0] if observations else None
    saved = next((item for item in observations if item["state"] in ("observed", "partial")), None)
    prior_complete = (
        next(
            (
                item
                for item in observations[observations.index(saved) + 1 :]
                if item["state"] == "observed"
            ),
            None,
        )
        if saved and saved["state"] == "partial"
        else None
    )
    snapshot_names = set(saved["models"] if saved else ())
    if prior_complete:
        snapshot_names.update(prior_complete["models"])
    by_id = {item["serving_id"]: item for item in deployments}
    names = snapshot_names | set(by_id)
    rows = []
    for serving_id in sorted(names):
        deployment = by_id.get(serving_id)
        model = (
            models.get(deployment["model_ref"])
            if deployment and deployment.get("model_ref")
            else None
        )
        configuration = (
            models.get(deployment["configuration_ref"])
            if deployment and deployment.get("configuration_ref")
            else None
        )
        permission = permissions.get(serving_id)
        allowed = (
            permission["allowed"]
            if permission is not None
            else bool(deployment and deployment["execution_approved"])
        )
        prices = prices_by_ref.get(configuration["configuration_ref"], []) if configuration else []
        price = prices[-1] if prices else None
        grants = grants_by_ref.get(configuration["configuration_ref"], []) if configuration else []
        rows.append(
            {
                "serving_id": serving_id,
                "display_name": model["display_name"] if model else serving_id,
                "model_ref": deployment.get("model_ref") if deployment else None,
                "deployment_id": deployment.get("deployment_id") if deployment else None,
                "configuration_ref": configuration["configuration_ref"] if configuration else None,
                "model_version": (model or {}).get("catalogue", {}).get("observed_serving_version"),
                "capabilities": (model or {})
                .get("catalogue", {})
                .get("provider_published_capabilities"),
                "reference_price": (model or {}).get("catalogue", {}).get("price_reference"),
                "inventory_provenance": (
                    "observed"
                    if saved and serving_id in saved["models"]
                    else "retained_previous_snapshot"
                    if serving_id in snapshot_names
                    else "manual_association"
                ),
                "allowed": allowed,
                "permission_revision": permission["revision"] if permission else 0,
                "readiness": self.readiness(configuration) if configuration else "unknown",
                "loaded_running": "unknown",
                "price": price,
                "active_grants": sum(g["status"] == "active" for g in grants),
                "grant_count": len(grants),
            }
        )
    completeness = (
        "never_run"
        if latest is None
        else "partial"
        if latest["state"] == "partial" or latest.get("has_more")
        else "complete"
        if latest["state"] == "observed"
        else latest["state"]
        if latest["state"] in ("failed", "unsupported")
        else "failed"
    )
    return {
        "connection": connection,
        "discovery": {
            "state": completeness,
            "observed_at": latest.get("observed_at") if latest else None,
            "reason": latest.get("reason") if latest else "never_run",
            "retained_snapshot_at": saved.get("observed_at") if saved else None,
            "snapshot_current": bool(
                saved
                and saved["connection_revision"] == connection["revision"]
                and saved["credential_version"] == connection["credential_version"]
            ),
            "snapshot_completeness": (
                "partial" if saved and saved.get("has_more") else "complete" if saved else "none"
            ),
        },
        "items": rows,
        "count": len(rows),
    }


def _apply_source_permissions(self, db, actor, action, subject, expected, data):
    if (
        expected != 0
        or set(data) != {"allowed", "items"}
        or type(data["allowed"]) is not bool
        or type(data["items"]) is not list
        or not 1 <= len(data["items"]) <= 100
    ):
        raise ValueError("invalid source-model selection")
    row = db.execute(_queries.APPLY_SELECT_REGISTRY_CONNECTIONS, (subject,)).fetchone()
    connection = json.loads(row[0]) if row else None
    if not connection or connection["status"] == "archived":
        raise ValueError("source connection unavailable")
    discoveries = [
        json.loads(item[0])
        for item in db.execute(
            _queries.SOURCE_INVENTORY_SELECT_REGISTRY_OBSERVATIONS, (subject,)
        ).fetchall()
    ]
    saved = next((item for item in discoveries if item["state"] in ("observed", "partial")), None)
    observed = set(saved["models"]) if saved else set()
    if saved and saved["state"] == "partial":
        prior = next(
            (
                item
                for item in discoveries[discoveries.index(saved) + 1 :]
                if item["state"] == "observed"
            ),
            None,
        )
        if prior:
            observed.update(prior["models"])
    associated = {
        json.loads(item[0])["serving_id"]
        for item in db.execute(_queries.DEPLOYMENTS_FOR_CONNECTION, (subject,)).fetchall()
    }
    changed = []
    seen = set()
    for item in data["items"]:
        if type(item) is not dict or set(item) != {"serving_id", "expected_revision"}:
            raise ValueError("invalid source-model row")
        serving_id, revision = item["serving_id"], item["expected_revision"]
        if (
            type(serving_id) is not str
            or not 1 <= len(serving_id) <= 256
            or any(ord(c) < 33 for c in serving_id)
            or serving_id in seen
            or serving_id not in observed | associated
            or type(revision) is not int
            or revision < 0
        ):
            raise ValueError("unknown or duplicate source-model row")
        seen.add(serving_id)
        key = self._source_key(subject, serving_id)
        prior = db.execute(_queries.APPLY_SELECT_REGISTRY_SOURCE_PERMISSIONS, (key,)).fetchone()
        old = json.loads(prior[0]) if prior else None
        if revision != (old["revision"] if old else 0):
            raise RegistryConflict("stale source-model permission")
        record = {
            "connection_id": subject,
            "serving_id": serving_id,
            "allowed": data["allowed"],
            "revision": revision + 1,
            "actor": actor,
            "at": timestamp(),
        }
        db.execute(_queries.APPLY_INSERT_REGISTRY_SOURCE_PERMISSIONS, (key, encode(record)))
        changed.append(record)
    return {
        "revision": 1,
        "connection_id": subject,
        "allowed": data["allowed"],
        "items": changed,
    }
