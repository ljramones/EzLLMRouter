"""SQL owned by the reporting repository."""

from ..database import Query


LATEST_OUTCOMES_SELECT_ATTRIBUTION_OUTCOMES = Query(
    "SELECT event,recorded_at FROM attribution_outcomes WHERE recorded_at<=? ORDER BY "
    "recorded_at,revision"
)

USAGE_COSTS_SELECT_SUBMISSIONS = Query(
    "SELECT s.record,i.intent FROM submissions s LEFT JOIN intents i ON "
    "i.submission_id=s.submission_id WHERE "
    "(json_extract(s.record,'$.created_at') IS NULL OR json_extract(s.record,'$.created_at')<=?) "
    "AND (?!='ordinary' OR s.principal_id=? OR "
    "json_extract(s.record,'$.attribution.initiating_user_id')=?) ORDER BY s.rowid"
)

USAGE_COSTS_SELECT_USAGE_REVISIONS = Query(
    "SELECT u.attempt_id,u.usage FROM usage_revisions u JOIN submissions s "
    "ON json_extract(s.record,'$.attempt_id')=u.attempt_id WHERE u.revision=(SELECT MAX(v.revision) "
    "FROM usage_revisions v WHERE v.attempt_id=u.attempt_id "
    "AND json_extract(v.usage,'$.recorded_at')<=?) "
    "AND (?!='ordinary' OR s.principal_id=? OR "
    "json_extract(s.record,'$.attribution.initiating_user_id')=?)"
)

USAGE_COSTS_SELECT_ATTRIBUTION_RUNS = Query("SELECT record FROM attribution_runs")
