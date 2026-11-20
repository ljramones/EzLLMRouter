"""Credential recovery requirements for the execution service startup."""

from ..database import Query

PROTECTED_PROVIDER_CREDENTIALS = Query(
    "SELECT json_extract(record,'$.connection_id'),json_extract(record,'$.credential_version') "
    "FROM registry_connections WHERE json_extract(record,'$.credential_state')='present'"
)

USED_PROVIDER_VAULT = Query(
    "SELECT 1 FROM registry_connections WHERE json_extract(record,'$.credential_version')>0 LIMIT 1"
)
