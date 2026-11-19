"""SQL owned by the successor_service repository."""
from ..database import Query


RECOVER_INCOMPLETE_SELECT_DEV12_SUBMISSIONS = Query(
    'SELECT record FROM dev12_submissions WHERE '
    "json_extract(record,'$.submission_state')='pending' AND "
    "json_extract(record,'$.campaign_id')=?"
)

SEND_COMMITTED_SELECT_DEV12_SEND_OWNERSHIP = Query('SELECT 1 FROM dev12_send_ownership WHERE submission_id=? AND attempt_id=?')

COLLECT_RECEIVER_RECEIPT_SELECT_DEV12_SEND_OWNERSHIP = Query('SELECT guard_receipt FROM dev12_send_ownership WHERE attempt_id=? AND submission_id=?')

COLLECT_RECEIVER_RECEIPT_SELECT_DEV12_EVIDENCE_EVENTS = Query(
    'SELECT evidence FROM dev12_evidence_events WHERE submission_id=? AND '
    "event_kind='late_receiver_receipt_collected'"
)

EXECUTE_SELECT_DEV12_SEND_OWNERSHIP = Query('SELECT 1 FROM dev12_send_ownership WHERE attempt_id=?')
