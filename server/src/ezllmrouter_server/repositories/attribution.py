"""SQL owned by the attribution repository."""
from ..database import Query, identifier


def RECORD_SELECT_RECORD(*, key, table):
    identifier(key)
    identifier(table)
    return Query(f'SELECT record FROM {table} WHERE {key}=?')

SAVE_INSERT_ATTRIBUTION_RUNS = Query('INSERT INTO attribution_runs VALUES (?,?)')

APPLY_ADMIN_INSERT_REGISTRY_AGENTS = Query('INSERT INTO registry_agents VALUES (?,?)')

APPLY_ADMIN_UPDATE_REGISTRY_AGENTS = Query('UPDATE registry_agents SET record=? WHERE id=?')

APPLY_ADMIN_INSERT_REGISTRY_OUTCOME_AUTHORITIES = Query('INSERT OR REPLACE INTO registry_outcome_authorities VALUES (?,?)')

SAVE_INSERT_ATTRIBUTION_OUTCOMES = Query('INSERT INTO attribution_outcomes VALUES (?,?,?,?,?,?,?,?)')

APPLY_ADMIN_UPDATE_REGISTRY_AGENT_PERMISSIONS = Query('UPDATE registry_agent_permissions SET record=? WHERE id=?')

APPLY_ADMIN_INSERT_REGISTRY_AGENT_PERMISSIONS = Query('INSERT INTO registry_agent_permissions VALUES (?,?,?,?,?)')

SAVE_UPDATE_ATTRIBUTION_RUNS = Query('UPDATE attribution_runs SET record=? WHERE id=?')

AGENTS_SELECT_REGISTRY_AGENTS = Query('SELECT record FROM registry_agents ORDER BY id')

PERMISSION_SELECT_REGISTRY_AGENT_PERMISSIONS = Query(
    'SELECT record FROM registry_agent_permissions WHERE caller_id=? AND agent_id=? AND '
    'user_id=?'
)

APPLY_ADMIN_SELECT_REGISTRY_AGENT_PERMISSIONS = Query(
    'SELECT id FROM registry_agent_permissions WHERE caller_id=? AND agent_id=? AND user_id=?'
)

SAVE_SELECT_ATTRIBUTION_OUTCOMES = Query('SELECT digest,receipt FROM attribution_outcomes WHERE principal_id=? AND event_id=?')

OUTCOME_RECEIPT_SELECT_ATTRIBUTION_OUTCOMES = Query('SELECT receipt FROM attribution_outcomes WHERE principal_id=? AND event_id=?')

APPEND_OUTCOME_SELECT_SUBMISSIONS = Query('SELECT record FROM submissions')

SAVE_SELECT_ATTRIBUTION_OUTCOMES_2 = Query('SELECT MAX(revision) FROM attribution_outcomes WHERE subject=?')
