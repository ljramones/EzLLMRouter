"""Registry registry_reads operations; caller owns the existing authority context."""

from __future__ import annotations

from typing import cast

from typing import TYPE_CHECKING
from .database import Parameters
from .records import Record
from .store import decode_record

if TYPE_CHECKING:
    from .registry import Registry

from .repositories import registry as _queries
from .registry_values import identifier, ConnectionSchedule


def _record(self: Registry, table: str, where: str, args: Parameters) -> Record | None:
    with self.store.database.read():
        row = self.store.database.execute(
            _queries.RECORD_SELECT_RECORD(table=table, where=where), args
        ).fetchone()
    return decode_record(row[0]) if row else None


def model(self: Registry, ref: str) -> Record | None:
    identifier(ref)
    return self._record("registry_models", "ref=?", (ref,))


def principal(self: Registry, principal_id: str) -> Record | None:
    identifier(principal_id)
    return self._record("registry_principals", "id=?", (principal_id,))


def grant(self: Registry, principal_id: str, ref: str) -> Record | None:
    return self._record("registry_grants", "principal_id=? AND config_ref=?", (principal_id, ref))


def grants(
    self: Registry, *, principal_id: str | None = None, configuration_ref: str | None = None
) -> list[Record]:
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
    return [decode_record(row[0]) for row in rows]


def prices(self: Registry, ref: str) -> list[Record]:
    identifier(ref)
    with self.store.database.read():
        rows = self.store.database.execute(
            _queries.PRICES_SELECT_REGISTRY_PRICES, (ref,)
        ).fetchall()
    return [decode_record(row[0]) for row in rows]


def list_models(self: Registry) -> list[Record]:
    with self.store.database.read():
        rows = self.store.database.execute(_queries.LIST_MODELS_SELECT_REGISTRY_MODELS).fetchall()
    return [decode_record(row[0]) for row in rows]


def list_principals(self: Registry) -> list[Record]:
    with self.store.database.read():
        rows = self.store.database.execute(
            _queries.LIST_PRINCIPALS_SELECT_REGISTRY_PRINCIPALS
        ).fetchall()
    return [decode_record(row[0]) for row in rows]


def connection(self: Registry, connection_id: str) -> Record | None:
    identifier(connection_id)
    return self._record("registry_connections", "id=?", (connection_id,))


def list_connections(self: Registry) -> list[ConnectionSchedule]:
    with self.store.database.read():
        rows = self.store.database.execute(
            _queries.LIST_CONNECTIONS_SELECT_REGISTRY_CONNECTIONS
        ).fetchall()
    return [cast(ConnectionSchedule, decode_record(row[0])) for row in rows]


def deployments(self: Registry, connection_id: str) -> list[Record]:
    identifier(connection_id)
    with self.store.database.read():
        rows = self.store.database.execute(
            _queries.DEPLOYMENTS_SELECT_REGISTRY_DEPLOYMENTS, (connection_id,)
        ).fetchall()
    return [decode_record(row[0]) for row in rows]


def observations(self: Registry, connection_id: str) -> list[Record]:
    identifier(connection_id)
    with self.store.database.read():
        rows = self.store.database.execute(
            _queries.OBSERVATIONS_SELECT_REGISTRY_OBSERVATIONS, (connection_id,)
        ).fetchall()
    return [decode_record(row[0]) for row in rows]


def history(self: Registry, subject: str) -> list[Record]:
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
            "before": decode_record(row[6]) if row[6] else None,
            "after": decode_record(row[7]) if row[7] else None,
        }
        for row in rows
    ]
