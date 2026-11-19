"""SQL owned by the secret_rotation repository."""
from ..database import Query


MAIN_SELECT_REGISTRY_CONNECTIONS = Query('SELECT record FROM registry_connections')

MAIN_SELECT_INTEGRATION_CREDENTIAL_VERSIONS = Query('SELECT DISTINCT key_id FROM integration_credential_versions')

MAIN_SELECT_LOCAL_CONNECTORS = Query('SELECT secret FROM local_connectors WHERE secret IS NOT NULL')
