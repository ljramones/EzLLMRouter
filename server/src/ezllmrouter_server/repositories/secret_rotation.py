"""SQL owned by the secret_rotation repository."""

from . import shared
from ..database import Query


MAIN_SELECT_REGISTRY_CONNECTIONS = Query("SELECT record FROM registry_connections")

MAIN_SELECT_INTEGRATION_CREDENTIAL_VERSIONS = shared.INTEGRATION_KEY_IDS

MAIN_SELECT_LOCAL_CONNECTORS = shared.LOCAL_CONNECTOR_SECRETS
