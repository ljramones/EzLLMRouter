"""SQL owned by the reporting repository."""

from ..database import Query


LATEST_OUTCOMES_SELECT_ATTRIBUTION_OUTCOMES = Query(
    "SELECT event,recorded_at FROM attribution_outcomes WHERE recorded_at<=? ORDER BY "
    "recorded_at,revision"
)

USAGE_COSTS_SELECT_SUBMISSIONS = Query(
    "SELECT s.record,i.intent FROM submissions s LEFT JOIN intents i ON "
    "i.submission_id=s.submission_id ORDER BY s.rowid"
)

USAGE_COSTS_SELECT_USAGE_REVISIONS = Query(
    "SELECT attempt_id,usage FROM usage_revisions WHERE "
    "json_extract(usage,'$.recorded_at')<=? ORDER BY attempt_id,revision"
)

USAGE_COSTS_SELECT_ATTRIBUTION_RUNS = Query("SELECT record FROM attribution_runs")
