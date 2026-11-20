"""Identical cross-domain SQL has one immutable query definition."""

from ..database import Query

INTEGRATION_KEY_IDS = Query("SELECT DISTINCT key_id FROM integration_credential_versions")
INSERT_INTEGRATION_ACCOUNT = Query("INSERT INTO integration_accounts VALUES (?,?,?)")
APPEND_ACCOUNT_HISTORY = Query("INSERT INTO integration_account_history VALUES (?,?,?,?)")
UPDATE_INTEGRATION_ACCOUNT = Query(
    "UPDATE integration_accounts SET record=? WHERE id=? AND dataset_id=?"
)
GET_INTEGRATION_ACCOUNT = Query(
    "SELECT record FROM integration_accounts WHERE id=? AND dataset_id=?"
)
AUTHORITY_REVISION = Query("SELECT value FROM registry_meta WHERE key='authority_revision'")
LOCAL_CONNECTOR_SECRETS = Query("SELECT secret FROM local_connectors WHERE secret IS NOT NULL")
INSERT_PRINCIPAL = Query("INSERT INTO registry_principals VALUES (?,?)")
GET_PRINCIPAL = Query("SELECT record FROM registry_principals WHERE id=?")
SET_AUTHORITY_REVISION = Query("UPDATE registry_meta SET value=? WHERE key='authority_revision'")
APPEND_AUTHORITY_AUDIT = Query(
    "INSERT INTO registry_audit (actor,action,subject,old_revision,new_revision,authority_revision,at) VALUES (?,?,?,?,?,?,?)"
)
DELETE_PRINCIPAL_CREDENTIALS = Query("DELETE FROM registry_credentials WHERE principal_id=?")
