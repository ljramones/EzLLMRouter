"""SQL owned by the successor_campaign repository."""
from ..database import Query


RESERVE_INSERT_DEV12_CAMPAIGN_ATTEMPTS = Query('INSERT INTO dev12_campaign_attempts VALUES (?,?,?,?,?)')

RESERVE_UPDATE_DEV12_CAMPAIGNS = Query('UPDATE dev12_campaigns SET record=? WHERE campaign_id=?')

ACTION_INSERT_DEV12_CAMPAIGNS = Query('INSERT INTO dev12_campaigns VALUES (?,?)')

ACTION_UPDATE_DEV12_CAMPAIGN_ATTEMPTS = Query('UPDATE dev12_campaign_attempts SET possible_send=1 WHERE attempt_id=?')

ACTION_UPDATE_DEV12_CAMPAIGN_ATTEMPTS_2 = Query("UPDATE dev12_campaign_attempts SET state='finished' WHERE attempt_id=?")

RECORD_SELECT_DEV12_CAMPAIGNS = Query('SELECT record FROM dev12_campaigns WHERE campaign_id=?')

DEFINITE_NO_SEND_SELECT_DEV12_EVIDENCE_EVENTS = Query('SELECT event_kind,evidence FROM dev12_evidence_events WHERE submission_id=?')

DEFINITE_NO_SEND_SELECT_DEV12_SEND_OWNERSHIP = Query('SELECT 1 FROM dev12_send_ownership WHERE attempt_id=? AND submission_id=?')

ACTION_INSERT_DEV12_CAMPAIGN_AUDIT = Query('INSERT INTO dev12_campaign_audit(campaign_id,record) VALUES (?,?)')

ACTION_SELECT_DEV12_CAMPAIGNS = Query('SELECT 1 FROM dev12_campaigns WHERE campaign_id=?')

ASSERT_ATTEMPT_RELEASABLE_SELECT_DEV12_CAMPAIGN_ATTEMPTS = Query(
    'SELECT state,possible_send,reservation_decimal FROM dev12_campaign_attempts WHERE '
    'attempt_id=? AND campaign_id=?'
)

ACTION_SELECT_DEV12_CAMPAIGN_ATTEMPTS = Query(
    'SELECT state, possible_send, reservation_decimal FROM dev12_campaign_attempts WHERE '
    'attempt_id=? AND campaign_id=?'
)

ACTION_SELECT_DEV12_SUBMISSIONS = Query("SELECT record FROM dev12_submissions WHERE json_extract(record,'$.attempt_id')=?")

ACTION_SELECT_DEV12_CAMPAIGN_ATTEMPTS_2 = Query('SELECT state FROM dev12_campaign_attempts WHERE attempt_id=? AND campaign_id=?')

ACTION_SELECT_DEV12_CAMPAIGN_ATTEMPTS_3 = Query(
    'SELECT a.attempt_id,s.record FROM dev12_campaign_attempts a JOIN dev12_submissions s ON '
    "json_extract(s.record,'$.attempt_id')=a.attempt_id WHERE a.campaign_id=?"
)

ACTION_UPDATE_DEV12_SUBMISSIONS = Query('UPDATE dev12_submissions SET record=? WHERE submission_id=?')

ACTION_INSERT_DEV12_EVIDENCE_EVENTS = Query(
    'INSERT INTO dev12_evidence_events(submission_id,event_kind,observed_at,evidence) VALUES '
    '(?,?,?,?)'
)

ACTION_SELECT_DEV12_USAGE_REVISIONS = Query(
    'SELECT usage FROM dev12_usage_revisions WHERE attempt_id=? ORDER BY revision DESC LIMIT '
    '1'
)

ACTION_SELECT_DEV12_EVIDENCE_EVENTS = Query(
    'SELECT evidence FROM dev12_evidence_events WHERE submission_id=? AND '
    "event_kind='late_receiver_receipt_collected'"
)
