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


def _object_projection(alias: str, fields: tuple[str, ...], defaults: tuple[str, ...] = ()) -> str:
    parts: list[str] = []
    for field in fields:
        path = "'$." + field + "'"
        value = "json_extract(" + alias + "," + path + ")"
        if field in defaults:
            value = (
                "CASE WHEN json_type("
                + alias
                + ","
                + path
                + ") IS NULL THEN json('{}') ELSE "
                + value
                + " END"
            )
        parts.extend(("'" + field + "'", value))
    return "json_object(" + ",".join(parts) + ")"


_RECORD_FACTS = _object_projection(
    "s.record",
    (
        "attempt_id",
        "submission_id",
        "principal_id",
        "created_at",
        "attribution",
        "principal_kind",
        "selected_destination",
        "fixture_destination",
        "provenance",
        "submission_state",
        "dispatch_state",
        "provider_model_reported",
        "charging_owner_id",
        "registry_decision",
        "task_id",
        "task_class",
        "purpose",
    ),
    ("attribution", "registry_decision"),
)
_INTENT_FACTS = (
    "CASE WHEN i.intent IS NULL THEN NULL WHEN json(i.intent)='{}' THEN '{}' ELSE "
    + _object_projection("i.intent", ("destination",))
    + " END"
)
_USAGE_FACTS = (
    "CASE WHEN u.usage IS NULL THEN NULL WHEN json(u.usage)='{}' THEN '{}' ELSE "
    + _object_projection(
        "u.usage",
        ("cost", "normalized_usage", "price_version", "revision"),
        ("cost", "normalized_usage"),
    )
    + " END"
)

USAGE_FACTS = Query(
    "SELECT json_extract(s.record,'$.attempt_id'),"
    + _RECORD_FACTS
    + ","
    + _INTENT_FACTS
    + ","
    + _USAGE_FACTS
    + " FROM submissions s LEFT JOIN intents i ON i.submission_id=s.submission_id "
    "LEFT JOIN usage_revisions u ON u.attempt_id=json_extract(s.record,'$.attempt_id') "
    "AND u.revision=(SELECT MAX(v.revision) FROM usage_revisions v WHERE "
    "v.attempt_id=u.attempt_id AND json_extract(v.usage,'$.recorded_at')<=?) "
    "WHERE (json_extract(s.record,'$.created_at') IS NULL OR json_extract(s.record,'$.created_at')<=?) "
    "AND (?!='ordinary' OR s.principal_id=? OR json_extract(s.record,'$.attribution.initiating_user_id')=?) "
    "ORDER BY s.rowid"
)
