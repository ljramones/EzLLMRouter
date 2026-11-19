"""SQL owned by the store repository."""
from ..database import Query


CLAIM_WORK_IN_TX_INSERT_WORK_KEY_OWNERS = Query('INSERT INTO work_key_owners VALUES (?,?,?,?)')

UPDATE_IN_TX_UPDATE_SUBMISSIONS = Query('UPDATE submissions SET record=? WHERE submission_id=?')

ACTION_INSERT_DEV12_SUBMISSIONS = Query('INSERT INTO dev12_submissions VALUES (?,?,?,?,?)')

ACTION_INSERT_DEV12_EVIDENCE_EVENTS = Query(
    'INSERT INTO dev12_evidence_events(submission_id,event_kind,observed_at,evidence) VALUES '
    '(?,?,?,?)'
)

ACTION_UPDATE_DEV12_SUBMISSIONS = Query('UPDATE dev12_submissions SET record=? WHERE submission_id=?')

ACTION_INSERT_DEV12_SEND_OWNERSHIP = Query('INSERT INTO dev12_send_ownership VALUES (?,?,?,?)')

ACTION_INSERT_DEV12_USAGE_REVISIONS = Query('INSERT INTO dev12_usage_revisions VALUES (?,?,?,?)')

ACTION_INSERT_SUBMISSIONS = Query('INSERT INTO submissions VALUES (?,?,?,?,?,?)')

ACTION_INSERT_INTENTS = Query('INSERT INTO intents VALUES (?,?,?)')

ACTION_INSERT_GUARD_DISPATCHES = Query('INSERT INTO guard_dispatches VALUES (?,?,?)')

UPDATE_IN_TX_SELECT_SUBMISSIONS = Query('SELECT record FROM submissions WHERE submission_id=?')

ACTION_INSERT_USAGE_REVISIONS = Query('INSERT INTO usage_revisions VALUES (?,?,?,?)')

WORK_OWNER_SELECT_WORK_KEY_OWNERS = Query(
    'SELECT contract_version,submission_id FROM work_key_owners WHERE principal_id=? AND '
    'work_key=?'
)

SUCCESSOR_GET_SELECT_DEV12_SUBMISSIONS = Query('SELECT record FROM dev12_submissions WHERE submission_id=?')

SUCCESSOR_BY_WORK_SELECT_DEV12_SUBMISSIONS = Query('SELECT record FROM dev12_submissions WHERE principal_id=? AND work_key=?')

ACTION_SELECT_DEV12_USAGE_REVISIONS = Query('SELECT usage FROM dev12_usage_revisions WHERE attempt_id=? AND revision=?')

ACTION_SELECT_DEV12_USAGE_REVISIONS_2 = Query(
    'SELECT revision FROM dev12_usage_revisions WHERE attempt_id=? ORDER BY revision DESC '
    'LIMIT 1'
)

SUCCESSOR_LATEST_USAGE_SELECT_DEV12_USAGE_REVISIONS = Query(
    'SELECT usage FROM dev12_usage_revisions WHERE attempt_id=? ORDER BY revision DESC LIMIT '
    '1'
)

SUCCESSOR_TOTALS_SELECT_DEV12_SUBMISSIONS = Query(
    'SELECT s.record, u.usage FROM dev12_submissions s LEFT JOIN dev12_usage_revisions u ON '
    "u.attempt_id=json_extract(s.record,'$.attempt_id') AND u.revision=(SELECT "
    'MAX(x.revision) FROM dev12_usage_revisions x WHERE '
    "x.attempt_id=json_extract(s.record,'$.attempt_id')) WHERE s.principal_id=?"
)

ACTION_SELECT_DEV12_SUBMISSIONS = Query(
    'SELECT submission_id,record FROM dev12_submissions WHERE '
    "json_extract(record,'$.candidate_access')='present'"
)

ACTION_SELECT_INTENTS = Query('SELECT intent FROM intents WHERE submission_id=? AND attempt_id=?')

GUARD_RECORD_SELECT_GUARD_DISPATCHES = Query('SELECT receipt FROM guard_dispatches WHERE attempt_id=?')

GET_SELECT_USAGE_REVISIONS = Query('SELECT usage FROM usage_revisions WHERE attempt_id=? ORDER BY revision DESC LIMIT 1')

BY_WORK_SELECT_SUBMISSIONS = Query('SELECT submission_id FROM submissions WHERE principal_id=? AND work_key=?')

HAS_AUTHORIZED_TOOL_CALL_SELECT_SUBMISSIONS = Query('SELECT record FROM submissions WHERE principal_id=? AND task_id=?')

ACTION_SELECT_DEV12_SUBMISSIONS_2 = Query('SELECT 1 FROM dev12_submissions WHERE submission_id=?')

INTENT_COUNT_SELECT_INTENTS = Query('SELECT COUNT(*) FROM intents WHERE submission_id=?')

ACTION_SELECT_USAGE_REVISIONS = Query('SELECT MAX(revision) FROM usage_revisions WHERE attempt_id=?')
