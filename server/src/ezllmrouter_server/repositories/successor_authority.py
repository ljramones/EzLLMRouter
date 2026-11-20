"""SQL owned by the successor_authority repository."""

from ..database import Query


ACTION_UPDATE_DEV12_AUTHORITY = Query("UPDATE dev12_authority SET state=? WHERE authority_id=?")

ACTION_INSERT_DEV12_AUTHORITY_AUDIT = Query(
    "INSERT INTO dev12_authority_audit(authority_id,record) VALUES (?,?)"
)

INIT_SELECT_DEV12_AUTHORITY = Query(
    "SELECT state FROM dev12_authority WHERE authority_id='standalone.synthetic'"
)

INIT_INSERT_DEV12_AUTHORITY = Query("INSERT INTO dev12_authority VALUES (?,?)")
