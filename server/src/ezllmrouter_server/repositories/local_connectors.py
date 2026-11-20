"""SQL owned by the local_connectors repository."""

from ..database import Query


REWRITE_SELECT_LOCAL_CONNECTORS = Query(
    "SELECT id,secret FROM local_connectors WHERE secret IS NOT NULL"
)

REWRITE_UPDATE_LOCAL_CONNECTORS = Query("UPDATE local_connectors SET secret=? WHERE id=?")

AUTHORIZE_SELECT_REGISTRY_PRINCIPALS = Query("SELECT record FROM registry_principals WHERE id=?")

LOAD_SELECT_LOCAL_CONNECTORS = Query("SELECT record,secret FROM local_connectors WHERE id=?")

TRANSACTION_INSERT_LOCAL_CONNECTORS = Query(
    "INSERT INTO local_connectors VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET "
    "record=excluded.record,secret=excluded.secret"
)

TRANSACTION_UPDATE_REGISTRY_META = Query(
    "UPDATE registry_meta SET value=? WHERE key='authority_revision'"
)

TRANSACTION_INSERT_REGISTRY_AUDIT = Query(
    "INSERT INTO registry_audit "
    "(actor,action,subject,old_revision,new_revision,authority_revision,at) VALUES "
    "(?,?,?,?,?,?,?)"
)

INIT_SELECT_LOCAL_CONNECTORS = Query("SELECT secret FROM local_connectors WHERE secret IS NOT NULL")

AVAILABILITY_SELECT_LOCAL_CONNECTORS = Query("SELECT record FROM local_connectors ORDER BY id")

TRANSACTION_SELECT_REGISTRY_META = Query(
    "SELECT value FROM registry_meta WHERE key='authority_revision'"
)
