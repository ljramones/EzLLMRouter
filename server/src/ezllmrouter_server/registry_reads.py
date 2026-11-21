"""Registry registry_reads operations; caller owns the existing authority context."""

from __future__ import annotations

import json
from .repositories import registry as _queries
from .registry_values import identifier, ConnectionSchedule


def _record(self, table, where, args):
    with self.store.database.read():
        row = self.store.database.execute(
            _queries.RECORD_SELECT_RECORD(table=table, where=where), args
        ).fetchone()
    return json.loads(row[0]) if row else None


def model(self, ref):
    identifier(ref)
    return self._record("registry_models", "ref=?", (ref,))


def principal(self, principal_id):
    identifier(principal_id)
    return self._record("registry_principals", "id=?", (principal_id,))


def grant(self, principal_id, ref):
    return self._record("registry_grants", "principal_id=? AND config_ref=?", (principal_id, ref))


def grants(self, *, principal_id=None, configuration_ref=None):
    values = []
    if principal_id is not None:
        identifier(principal_id)
        values.append(principal_id)
    if configuration_ref is not None:
        identifier(configuration_ref)
        values.append(configuration_ref)
    with self.store.database.read():
        rows = self.store.database.execute(
            _queries.grants(principal_id=principal_id, configuration_ref=configuration_ref),
            values,
        ).fetchall()
    return [json.loads(row[0]) for row in rows]


def prices(self, ref):
    identifier(ref)
    with self.store.database.read():
        rows = self.store.database.execute(
            _queries.PRICES_SELECT_REGISTRY_PRICES, (ref,)
        ).fetchall()
    return [json.loads(row[0]) for row in rows]


def list_models(self):
    with self.store.database.read():
        rows = self.store.database.execute(_queries.LIST_MODELS_SELECT_REGISTRY_MODELS).fetchall()
    return [json.loads(row[0]) for row in rows]


def list_principals(self):
    with self.store.database.read():
        rows = self.store.database.execute(
            _queries.LIST_PRINCIPALS_SELECT_REGISTRY_PRINCIPALS
        ).fetchall()
    return [json.loads(row[0]) for row in rows]


def connection(self, connection_id):
    identifier(connection_id)
    return self._record("registry_connections", "id=?", (connection_id,))


def list_connections(self) -> list[ConnectionSchedule]:
    with self.store.database.read():
        rows = self.store.database.execute(
            _queries.LIST_CONNECTIONS_SELECT_REGISTRY_CONNECTIONS
        ).fetchall()
    return [json.loads(row[0]) for row in rows]


def deployments(self, connection_id):
    identifier(connection_id)
    with self.store.database.read():
        rows = self.store.database.execute(
            _queries.DEPLOYMENTS_SELECT_REGISTRY_DEPLOYMENTS, (connection_id,)
        ).fetchall()
    return [json.loads(row[0]) for row in rows]


def observations(self, connection_id):
    identifier(connection_id)
    with self.store.database.read():
        rows = self.store.database.execute(
            _queries.OBSERVATIONS_SELECT_REGISTRY_OBSERVATIONS, (connection_id,)
        ).fetchall()
    return [json.loads(row[0]) for row in rows]


def history(self, subject):
    identifier(subject)
    with self.store.database.read():
        rows = self.store.database.execute(
            _queries.HISTORY_SELECT_REGISTRY_AUDIT, (subject,)
        ).fetchall()
    return [
        {
            **dict(
                zip(
                    (
                        "actor",
                        "action",
                        "old_revision",
                        "new_revision",
                        "authority_revision",
                        "at",
                    ),
                    row[:6],
                    strict=True,
                )
            ),
            "before": json.loads(row[6]) if row[6] else None,
            "after": json.loads(row[7]) if row[7] else None,
        }
        for row in rows
    ]
