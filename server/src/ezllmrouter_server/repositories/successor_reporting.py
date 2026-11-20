"""SQL owned by the successor_reporting repository."""

from ..database import Query


USAGE_REPORT_SELECT_DEV12_SUBMISSIONS = Query("SELECT record FROM dev12_submissions ORDER BY rowid")

USAGE_REPORT_SELECT_DEV12_EVIDENCE_EVENTS = Query(
    "SELECT submission_id,evidence,observed_at FROM dev12_evidence_events WHERE "
    "event_kind='native_usage_accepted' ORDER BY event_id"
)
