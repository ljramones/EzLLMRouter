"""SQL owned by the integration_credentials repository."""

from . import shared
from ..database import Query


RELEASE_INSERT_REGISTRY_AUDIT = Query(
    "INSERT INTO "
    "registry_audit(actor,action,subject,old_revision,new_revision,authority_revision,at) "
    "VALUES (?,?,?,?,?,?,?)"
)

RELEASE_INSERT_REGISTRY_AUDIT_VALUES = Query(
    "INSERT INTO registry_audit_values(seq,before_json,after_json) VALUES (?,?,?)"
)

REWRITE_SELECT_INTEGRATION_CREDENTIAL_VERSIONS = Query(
    "SELECT v.account_id,v.version,v.key_id,v.nonce,v.ciphertext,b.record FROM "
    "integration_credential_versions v LEFT JOIN integration_credential_bindings b ON "
    "b.account_id=v.account_id"
)

REWRITE_UPDATE_INTEGRATION_CREDENTIAL_VERSIONS = Query(
    "UPDATE integration_credential_versions SET key_id=?,nonce=?,ciphertext=? WHERE "
    "account_id=? AND version=?"
)

CREATE_INSERT_INTEGRATION_CREDENTIAL_BINDINGS = Query(
    "INSERT INTO integration_credential_bindings VALUES (?,?,?)"
)

CREATE_INSERT_INTEGRATION_CREDENTIAL_VERSIONS = Query(
    "INSERT INTO integration_credential_versions VALUES (?,?,?,?,?)"
)

CREATE_INSERT_INTEGRATION_CREDENTIAL_OPERATIONS = Query(
    "INSERT INTO integration_credential_operations VALUES (?,?,?)"
)

COMMIT_UPDATE_INTEGRATION_CREDENTIAL_BINDINGS = Query(
    "UPDATE integration_credential_bindings SET record=? WHERE account_id=?"
)

COMMIT_DELETE_INTEGRATION_CREDENTIAL_VERSIONS = Query(
    "DELETE FROM integration_credential_versions WHERE account_id=? AND version=?"
)

NEXT_CREDENTIAL_VERSION = Query(
    "SELECT COALESCE(MAX(version),0) FROM integration_credential_versions WHERE account_id=?"
)

DISCARD_UNSELECTED_CREDENTIAL_VERSION = Query(
    "DELETE FROM integration_credential_versions WHERE account_id=?1 AND version=?2 "
    "AND NOT EXISTS (SELECT 1 FROM integration_credential_bindings WHERE account_id=?1 "
    "AND (json_extract(record,'$.selected_version')=?2 OR json_extract(record,'$.pending_version')=?2))"
)

INIT_SELECT_INTEGRATION_CREDENTIAL_META = Query(
    "SELECT value FROM integration_credential_meta WHERE key='keyring_id'"
)

INIT_SELECT_INTEGRATION_CREDENTIAL_VERSIONS = shared.INTEGRATION_KEY_IDS

INIT_INSERT_INTEGRATION_CREDENTIAL_META = Query(
    "INSERT INTO integration_credential_meta VALUES ('keyring_id',?)"
)

BINDING_SELECT_INTEGRATION_CREDENTIAL_BINDINGS = Query(
    "SELECT record FROM integration_credential_bindings WHERE account_id=?"
)

RESOLVE_SELECT_INTEGRATION_CREDENTIAL_VERSIONS = Query(
    "SELECT key_id,nonce,ciphertext FROM integration_credential_versions WHERE account_id=? "
    "AND version=?"
)

CLEAN_SELECT_INTEGRATION_CREDENTIAL_BINDINGS = Query(
    "SELECT account_id,record FROM integration_credential_bindings"
)

CLEAN_DELETE_INTEGRATION_CREDENTIAL_VERSIONS = Query(
    "DELETE FROM integration_credential_versions WHERE account_id=?"
)

CLEAN_DELETE_INTEGRATION_CREDENTIAL_OPERATIONS = Query(
    "DELETE FROM integration_credential_operations WHERE account_id=?"
)

CLEAN_DELETE_INTEGRATION_CREDENTIAL_BINDINGS = Query(
    "DELETE FROM integration_credential_bindings WHERE account_id=?"
)

LIST_SELECT_INTEGRATION_CREDENTIAL_BINDINGS = Query(
    "SELECT record FROM integration_credential_bindings WHERE dataset_id=? ORDER BY rowid DESC"
)

LIST_FOR_SELECT_INTEGRATION_CREDENTIAL_BINDINGS = Query(
    "SELECT record FROM integration_credential_bindings WHERE dataset_id=?"
)

COMMIT_INSERT_INTEGRATION_ACCOUNTS = shared.INSERT_INTEGRATION_ACCOUNT

COMMIT_INSERT_INTEGRATION_ACCOUNT_HISTORY = shared.APPEND_ACCOUNT_HISTORY

COMMIT_UPDATE_INTEGRATION_ACCOUNTS = shared.UPDATE_INTEGRATION_ACCOUNT

RELEASE_SELECT_INTEGRATION_ACCOUNTS = shared.GET_INTEGRATION_ACCOUNT

HAS_CREDENTIAL_VERSIONS = Query("SELECT 1 FROM integration_credential_versions LIMIT 1")

CONNECT_SELECT_INTEGRATION_CREDENTIAL_OPERATIONS = Query(
    "SELECT request_hash,account_id FROM integration_credential_operations WHERE operation_id=?"
)

RELEASE_SELECT_REGISTRY_META = shared.AUTHORITY_REVISION
