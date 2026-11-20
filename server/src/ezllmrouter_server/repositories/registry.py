"""SQL owned by the registry repository."""

from . import shared
from ..database import Query, identifier, predicate

_RECORD_KEYS = {
    "registry_models": "ref",
    "registry_principals": "id",
    "registry_connections": "id",
    "registry_source_permissions": "id",
    "registry_agents": "id",
    "registry_deployments": "id",
}


def _record_key(table: str) -> str:
    if table not in _RECORD_KEYS:
        raise ValueError("unsupported registry table")
    return _RECORD_KEYS[table]


APPLY_INSERT_REGISTRY_MODELS = Query("INSERT INTO registry_models VALUES (?,?)")

APPLY_UPDATE_REGISTRY_DEPLOYMENTS = Query("UPDATE registry_deployments SET record=? WHERE id=?")

APPLY_INSERT_REGISTRY_CONNECTIONS = Query("INSERT INTO registry_connections VALUES (?,?)")

APPLY_UPDATE_REGISTRY_CONNECTIONS = Query("UPDATE registry_connections SET record=? WHERE id=?")

APPLY_UPDATE_REGISTRY_MODELS = Query("UPDATE registry_models SET record=? WHERE ref=?")

APPLY_INSERT_REGISTRY_PRINCIPALS = shared.INSERT_PRINCIPAL

APPLY_UPDATE_REGISTRY_PRINCIPALS = Query("UPDATE registry_principals SET record=? WHERE id=?")

APPLY_INSERT_REGISTRY_GRANTS = Query(
    "INSERT INTO registry_grants VALUES (?,?,?) ON CONFLICT(principal_id,config_ref) DO "
    "UPDATE SET record=excluded.record"
)

APPLY_INSERT_REGISTRY_PRICES = Query("INSERT INTO registry_prices VALUES (?,?,?)")

REQUIRE_ADMIN_SELECT_REGISTRY_PRINCIPALS = shared.GET_PRINCIPAL

SAVE_INSERT_REGISTRY_OBSERVATIONS = Query("INSERT INTO registry_observations VALUES (?,?,?)")

ACTION_UPDATE_REGISTRY_META = shared.SET_AUTHORITY_REVISION

ACTION_INSERT_REGISTRY_AUDIT = shared.APPEND_AUTHORITY_AUDIT


ACTION_INSERT_REGISTRY_OPERATIONS = Query("INSERT INTO registry_operations VALUES (?,?,?,?)")

APPLY_INSERT_REGISTRY_SOURCE_PERMISSIONS = Query(
    "INSERT INTO registry_source_permissions VALUES (?,?) ON CONFLICT(id) DO UPDATE SET "
    "record=excluded.record"
)

APPLY_UPDATE_CONSOLE_USERS = Query(
    "UPDATE console_users SET auth_version=auth_version+1,updated_at=? WHERE principal_id=?"
)


def LOAD_FOR_UPDATE_SELECT_RECORD(*, column: str, table: str) -> Query:
    identifier(column)
    if column != _record_key(table):
        raise ValueError("unsupported registry key")
    return Query(f"SELECT record FROM {table} WHERE {column}=?")


ACTION_DELETE_REGISTRY_CREDENTIALS = shared.DELETE_PRINCIPAL_CREDENTIALS

ACTION_INSERT_REGISTRY_CREDENTIALS = Query("INSERT INTO registry_credentials VALUES (?,?,?)")

ACTION_INSERT_REGISTRY_GRANTS = Query("INSERT INTO registry_grants VALUES (?,?,?)")

VERSION_SELECT_REGISTRY_META = shared.AUTHORITY_REVISION


def RECORD_SELECT_RECORD(*, table: str, where: str) -> Query:
    predicate(where)
    expected = (
        "principal_id=? AND config_ref=?"
        if table == "registry_grants"
        else _record_key(table) + "=?"
    )
    if where != expected:
        raise ValueError("unsupported registry predicate")
    return Query(f"SELECT record FROM {table} WHERE {where}")


PRICES_SELECT_REGISTRY_PRICES = Query(
    "SELECT record FROM registry_prices WHERE config_ref=? ORDER BY rowid"
)

LIST_MODELS_SELECT_REGISTRY_MODELS = Query("SELECT record FROM registry_models ORDER BY ref")

LIST_PRINCIPALS_SELECT_REGISTRY_PRINCIPALS = Query(
    "SELECT record FROM registry_principals ORDER BY id"
)

LIST_CONNECTIONS_SELECT_REGISTRY_CONNECTIONS = Query(
    "SELECT record FROM registry_connections ORDER BY id"
)

DEPLOYMENTS_SELECT_REGISTRY_DEPLOYMENTS = Query(
    "SELECT record FROM registry_deployments WHERE json_extract(record,'$.connection_id')=? "
    "ORDER BY id"
)

OBSERVATIONS_SELECT_REGISTRY_OBSERVATIONS = Query(
    "SELECT record FROM registry_observations WHERE connection_id=? ORDER BY rowid DESC LIMIT 20"
)

HISTORY_SELECT_REGISTRY_AUDIT = Query(
    "SELECT "
    "a.actor,a.action,a.old_revision,a.new_revision,a.authority_revision,a.at,v.before_json,v.after_json"
    " FROM registry_audit a LEFT JOIN registry_audit_values v ON v.seq=a.seq WHERE "
    "a.subject=? ORDER BY a.seq DESC LIMIT 100"
)

CREDENTIAL_PRINCIPAL_SELECT_REGISTRY_CREDENTIALS = Query(
    "SELECT principal_id FROM registry_credentials WHERE verifier=?"
)

APPLY_SELECT_REGISTRY_CONNECTIONS = Query("SELECT record FROM registry_connections WHERE id=?")

APPLY_SELECT_REGISTRY_MODELS = Query("SELECT 1 FROM registry_models WHERE ref=?")

APPLY_SELECT_REGISTRY_DEPLOYMENTS = Query("SELECT record FROM registry_deployments WHERE id=?")

CONNECTION_EXISTS = Query("SELECT 1 FROM registry_connections WHERE id=?")

APPLY_SELECT_REGISTRY_PRINCIPALS = Query("SELECT 1 FROM registry_principals WHERE id=?")

MODEL_FOR_UPDATE = Query("SELECT record FROM registry_models WHERE ref=?")

APPLY_SELECT_REGISTRY_GRANTS = Query(
    "SELECT record FROM registry_grants WHERE principal_id=? AND config_ref=?"
)

APPLY_SELECT_REGISTRY_PRICES = Query(
    "SELECT 1 FROM registry_prices WHERE config_ref=? AND price_version=?"
)

ACTION_SELECT_REGISTRY_META = Query("SELECT value FROM registry_meta WHERE key='bootstrap_version'")

ACTION_INSERT_REGISTRY_META = Query("INSERT INTO registry_meta VALUES (?,?)")

SET_PROVIDER_CREDENTIAL_SELECT_REGISTRY_OPERATIONS = Query(
    "SELECT actor,request_hash,result FROM registry_operations WHERE operation_id=?"
)

PROBE_CONNECTION_SELECT_REGISTRY_OBSERVATIONS = Query(
    "SELECT record FROM registry_observations WHERE operation_id=?"
)

APPLY_SELECT_REGISTRY_SOURCE_PERMISSIONS = Query(
    "SELECT record FROM registry_source_permissions WHERE id=?"
)

APPLY_INSERT_REGISTRY_DEPLOYMENTS = Query("INSERT INTO registry_deployments VALUES (?,?)")

CREDENTIAL_BOUND_TO_SELECT_REGISTRY_CREDENTIALS = Query(
    "SELECT 1 FROM registry_credentials WHERE principal_id=? AND verifier=?"
)

_INVENTORY_ANCHORS = """
WITH latest AS (
    SELECT rowid FROM registry_observations WHERE connection_id=?1
    AND json_extract(record,'$.operation')='inventory' ORDER BY rowid DESC LIMIT 1
), usable AS (
    SELECT rowid FROM registry_observations WHERE connection_id=?1
    AND json_extract(record,'$.operation')='inventory'
    AND json_extract(record,'$.state') IN ('observed','partial') ORDER BY rowid DESC LIMIT 1
), complete AS (
    SELECT rowid FROM registry_observations WHERE connection_id=?1
    AND json_extract(record,'$.operation')='inventory'
    AND json_extract(record,'$.state')='observed' ORDER BY rowid DESC LIMIT 1
), anchors AS (
    SELECT rowid FROM latest UNION SELECT rowid FROM usable UNION SELECT rowid FROM complete
)
"""

SOURCE_INVENTORY_SELECT_REGISTRY_OBSERVATIONS = Query(
    _INVENTORY_ANCHORS
    + """
SELECT record FROM registry_observations WHERE rowid IN (SELECT rowid FROM anchors)
ORDER BY rowid DESC
"""
)

PRUNE_CONNECTION_OBSERVATIONS = Query(
    _INVENTORY_ANCHORS
    + """
DELETE FROM registry_observations WHERE connection_id=?1
AND rowid NOT IN (SELECT rowid FROM anchors)
AND rowid NOT IN (
    SELECT rowid FROM registry_observations WHERE connection_id=?1 ORDER BY rowid DESC LIMIT 20
)
"""
)

SOURCE_INVENTORY_SELECT_REGISTRY_SOURCE_PERMISSIONS = Query(
    "SELECT record FROM registry_source_permissions WHERE json_extract(record,'$.connection_id')=?"
)


def ACTION_SELECT_RECORD(*, table: str) -> Query:
    column = _record_key(table)
    return Query(f"SELECT record FROM {table} WHERE {column}=?")


DEPLOYMENTS_FOR_CONNECTION = Query(
    "SELECT record FROM registry_deployments WHERE json_extract(record,'$.connection_id')=?"
)

DEPLOYMENT_EXISTS = Query("SELECT 1 FROM registry_deployments WHERE id=?")

ACTIVE_ADMIN_COUNT = Query(
    "SELECT COUNT(*) FROM registry_principals WHERE "
    "json_extract(record,'$.role')='registry_admin' AND "
    "json_extract(record,'$.status')='active'"
)

SCHEDULED_CONNECTION_COUNT = Query(
    "SELECT COUNT(*) FROM registry_connections WHERE json_extract(record,'$.checks_scheduled')=1"
)

MODEL_HAS_PRICE = Query("SELECT 1 FROM registry_prices WHERE config_ref=?")


def grants(*, principal_id: str | None = None, configuration_ref: str | None = None) -> Query:
    filters = []
    if principal_id is not None:
        filters.append("g.principal_id=?")
    if configuration_ref is not None:
        filters.append("g.config_ref=?")
    return Query(
        "SELECT g.record FROM registry_grants g "
        "JOIN registry_principals p ON p.id=g.principal_id "
        + ("WHERE " + " AND ".join(filters) if filters else "")
        + " ORDER BY g.principal_id,g.config_ref"
    )


INVENTORY_MODELS = Query(
    "SELECT record FROM registry_models WHERE ref IN ("
    "SELECT json_extract(record,'$.model_ref') FROM registry_deployments "
    "WHERE json_extract(record,'$.connection_id')=?1 UNION "
    "SELECT json_extract(record,'$.configuration_ref') FROM registry_deployments "
    "WHERE json_extract(record,'$.connection_id')=?1)"
)
INVENTORY_PRICES = Query(
    "SELECT record FROM registry_prices WHERE config_ref IN ("
    "SELECT json_extract(record,'$.configuration_ref') FROM registry_deployments "
    "WHERE json_extract(record,'$.connection_id')=?) ORDER BY rowid"
)
INVENTORY_GRANTS = Query(
    "SELECT g.record FROM registry_grants g JOIN registry_principals p ON p.id=g.principal_id "
    "WHERE g.config_ref IN (SELECT json_extract(record,'$.configuration_ref') "
    "FROM registry_deployments WHERE json_extract(record,'$.connection_id')=?) "
    "ORDER BY g.principal_id"
)
