"""SQL owned by the operator_projection repository."""

from ..database import Query, predicate


INIT_UPDATE_OPERATOR_LAUNCHES = Query(
    "UPDATE operator_launches SET state='outcome_unknown' WHERE state='running'"
)

INIT_UPDATE_OPERATOR_PROVIDER_VALIDATIONS = Query(
    "UPDATE operator_provider_validations SET state='outcome_unknown' WHERE state='running'"
)

ACTION_INSERT_OPERATOR_LAUNCHES = Query("INSERT INTO operator_launches VALUES (?,?,?,?,?,?,?,?)")

FINISH_LAUNCH_UPDATE_OPERATOR_LAUNCHES = Query(
    "UPDATE operator_launches SET "
    "state=?,updated_at=?,submission_ids=?,caller_lookups=?,error_code=? WHERE operation_id=?"
)

ACTION_INSERT_OPERATOR_PROVIDER_VALIDATIONS = Query(
    "INSERT INTO operator_provider_validations VALUES (?,?,?,?,?,?,?,?,?,?,?)"
)

RECORD_PROVIDER_VALIDATION_SUBMISSION_UPDATE_OPERATOR_PROVIDER_VALIDATIONS = Query(
    "UPDATE operator_provider_validations SET submission_id=?,updated_at=? WHERE "
    "operation_id=? AND state='running'"
)

FINISH_PROVIDER_VALIDATION_UPDATE_OPERATOR_PROVIDER_VALIDATIONS = Query(
    "UPDATE operator_provider_validations SET state=?,updated_at=?,error_code=? WHERE "
    "operation_id=? AND state='running'"
)

LATEST_USAGE_SELECT_USAGE_REVISIONS = Query(
    "SELECT usage FROM usage_revisions WHERE attempt_id=? ORDER BY revision DESC LIMIT 1"
)

ACTION_UPDATE_OPERATOR_LAUNCHES = Query(
    "UPDATE operator_launches SET submission_ids=?,updated_at=? WHERE operation_id=?"
)


def ACTIVITY_ORDER_SUBMISSIONS(*, where: str) -> Query:
    predicate(where)
    return Query(
        "SELECT s.record,i.intent FROM submissions s LEFT JOIN intents i ON i.submission_id=s.submission_id WHERE "
        + where
        + " ORDER BY s.rowid DESC LIMIT ? OFFSET ?"
    )


def DETAIL_SELECT_SUBMISSIONS(*, principal_id: str) -> Query:
    return Query(
        "SELECT record FROM submissions WHERE submission_id=?"
        + ("" if principal_id == "*" else " AND principal_id=?")
    )


DETAIL_SELECT_INTENTS = Query("SELECT intent FROM intents WHERE attempt_id=? AND submission_id=?")

DETAIL_SELECT_GUARD_DISPATCHES = Query(
    "SELECT receipt FROM guard_dispatches WHERE attempt_id=? AND submission_id=?"
)


def USAGE_ORDER_SUBMISSIONS(*, principal_id: str) -> Query:
    return Query(
        "SELECT s.record,i.intent,g.receipt FROM submissions s LEFT JOIN intents i ON i.submission_id=s.submission_id LEFT JOIN guard_dispatches g ON g.submission_id=s.submission_id "
        + ("" if principal_id == "*" else "WHERE s.principal_id=? ")
        + "ORDER BY s.rowid DESC LIMIT 10001"
    )


def OVERVIEW_COUNTS_SELECT_SUBMISSIONS(*, principal_id: str) -> Query:
    return Query(
        "SELECT record FROM submissions" + ("" if principal_id == "*" else " WHERE principal_id=?")
    )


ACTION_SELECT_OPERATOR_LAUNCHES = Query("SELECT kind FROM operator_launches WHERE operation_id=?")

ACTION_SELECT_OPERATOR_LAUNCHES_2 = Query(
    "SELECT submission_ids FROM operator_launches WHERE operation_id=?"
)

LAUNCH_SELECT_OPERATOR_LAUNCHES = Query(
    "SELECT kind,state,created_at,updated_at,submission_ids,caller_lookups,error_code FROM "
    "operator_launches WHERE operation_id=?"
)

ACTION_SELECT_OPERATOR_PROVIDER_VALIDATIONS = Query(
    "SELECT "
    "connection_id,connection_revision,configuration_ref,configuration_revision,max_output_tokens"
    " FROM operator_provider_validations WHERE operation_id=?"
)

ACTION_SELECT_OPERATOR_PROVIDER_VALIDATIONS_2 = Query(
    "SELECT 1 FROM operator_provider_validations WHERE state='running' LIMIT 1"
)

PROVIDER_VALIDATION_SELECT_OPERATOR_PROVIDER_VALIDATIONS = Query(
    "SELECT "
    "connection_id,connection_revision,configuration_ref,configuration_revision,max_output_tokens,state,created_at,updated_at,submission_id,error_code"
    " FROM operator_provider_validations WHERE operation_id=?"
)


def ACTIVITY_SELECT_SUBMISSIONS(*, where: str) -> Query:
    predicate(where)
    return Query("SELECT COUNT(*) FROM submissions s WHERE " + where)


ACTION_SELECT_OPERATOR_LAUNCHES_3 = Query(
    "SELECT COUNT(*) FROM operator_launches WHERE state='running'"
)


def activity_filter(principal_id: str, state: str | None) -> tuple[str, list[str]]:
    where = "1=1" if principal_id == "*" else "s.principal_id=?"
    values = [] if principal_id == "*" else [principal_id]
    if state:
        where += " AND json_extract(s.record,'$.submission_state')=?"
        values.append(state)
    return where, values
