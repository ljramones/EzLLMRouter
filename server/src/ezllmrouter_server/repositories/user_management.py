"""SQL owned by the user_management repository."""

from . import shared
from ..database import Query


SAVE_INSERT_REGISTRY_PRINCIPALS = Query(
    "INSERT INTO registry_principals VALUES (?,?) ON CONFLICT(id) DO UPDATE SET "
    "record=excluded.record"
)


ACTION_INSERT_CONSOLE_USERS = Query("INSERT INTO console_users VALUES (?,?,?,?,?,?,?)")

CHANGE_INSERT_REGISTRY_PRINCIPALS = shared.INSERT_PRINCIPAL

CHANGE_UPDATE_CONSOLE_USERS = Query(
    "UPDATE console_users SET username=?,auth_version=auth_version+?,updated_at=? WHERE "
    "principal_id=?"
)

UPDATE_PASSWORD_PRESERVING_STATE = Query(
    "UPDATE console_users SET password_hash=?,auth_version=auth_version+1,updated_at=? WHERE "
    "principal_id=?"
)

CHANGE_DELETE_REGISTRY_CREDENTIALS = shared.DELETE_PRINCIPAL_CREDENTIALS

RESET_PASSWORD_REQUIRING_CHANGE = Query(
    "UPDATE console_users SET "
    "password_hash=?,must_change_password=1,auth_version=auth_version+1,updated_at=? WHERE "
    "principal_id=?"
)

CHANGE_PASSWORD_COMPLETED = Query(
    "UPDATE console_users SET "
    "password_hash=?,must_change_password=0,auth_version=auth_version+1,updated_at=? WHERE "
    "principal_id=?"
)

LOAD_SELECT_CONSOLE_USERS = Query(
    "SELECT "
    "u.username,u.password_hash,u.must_change_password,u.auth_version,u.created_at,u.updated_at,p.record"
    " FROM console_users u JOIN registry_principals p ON p.id=u.principal_id WHERE "
    "u.principal_id=?"
)

ADMIN_SELECT_REGISTRY_PRINCIPALS = shared.GET_PRINCIPAL

ACTION_SELECT_CONSOLE_USERS = Query("SELECT 1 FROM console_users LIMIT 1")

ACTION_SELECT_REGISTRY_PRINCIPALS = Query(
    "SELECT record FROM registry_principals ORDER BY id=? DESC,id"
)

AUTHENTICATE_SELECT_CONSOLE_USERS = Query(
    "SELECT principal_id,password_hash,auth_version FROM console_users WHERE username=?"
)

LIST_SELECT_CONSOLE_USERS = Query("SELECT principal_id FROM console_users ORDER BY username")

VALIDATE_PRINCIPAL_CHANGE_SELECT_CONSOLE_USERS = Query(
    "SELECT COUNT(*) FROM console_users u JOIN registry_principals p ON p.id=u.principal_id "
    "WHERE json_extract(p.record,'$.role')='registry_admin' AND "
    "json_extract(p.record,'$.status')='active'"
)

CONSOLE_USER_EXISTS = Query("SELECT 1 FROM console_users WHERE principal_id=?")
