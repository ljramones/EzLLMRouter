"""SQL owned by the local_connectors repository."""

from . import shared
from ..database import Query


REWRITE_SELECT_LOCAL_CONNECTORS = Query(
    "SELECT id,secret FROM local_connectors WHERE secret IS NOT NULL"
)

REWRITE_UPDATE_LOCAL_CONNECTORS = Query("UPDATE local_connectors SET secret=? WHERE id=?")


LOAD_SELECT_LOCAL_CONNECTORS = Query("SELECT record,secret FROM local_connectors WHERE id=?")

TRANSACTION_INSERT_LOCAL_CONNECTORS = Query(
    "INSERT INTO local_connectors VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET "
    "record=excluded.record,secret=excluded.secret"
)


INIT_SELECT_LOCAL_CONNECTORS = shared.LOCAL_CONNECTOR_SECRETS

AVAILABILITY_SELECT_LOCAL_CONNECTORS = Query("SELECT record FROM local_connectors ORDER BY id")
