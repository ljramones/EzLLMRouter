"""SQL owned by the integration_accounting repository."""

from . import shared
from ..database import Query

# Traverse only the connected component. UNION deduplicates even malformed
# historical cycles; predecessor starts may legitimately arrive later. CROSS
# JOIN keeps the small frontier outside indexed lookups even without ANALYZE.
LINEAGE_COMPONENT = Query("""
WITH RECURSIVE affected(attempt_id) AS (
    SELECT ?2 UNION SELECT ?3 WHERE ?3 IS NOT NULL
    UNION
    SELECT json_extract(a.record,'$.predecessor_attempt_id')
    FROM affected x CROSS JOIN integration_attempts a
      ON a.dataset_id=?1 AND a.attempt_id=x.attempt_id
    WHERE json_extract(a.record,'$.predecessor_attempt_id') IS NOT NULL
    UNION
    SELECT a.attempt_id FROM affected x CROSS JOIN integration_attempts a
      ON a.dataset_id=?1 AND json_extract(a.record,'$.predecessor_attempt_id')=x.attempt_id
    UNION
    SELECT json_extract(e.record,'$.predecessor_attempt_id')
    FROM affected x CROSS JOIN integration_events e
      ON e.dataset_id=?1 AND e.kind='lineage' AND e.attempt_id=x.attempt_id
    WHERE json_extract(e.record,'$.predecessor_attempt_id') IS NOT NULL
    UNION
    SELECT e.attempt_id FROM affected x CROSS JOIN integration_events e
      ON e.dataset_id=?1 AND e.kind='lineage'
      AND json_extract(e.record,'$.predecessor_attempt_id')=x.attempt_id
)
SELECT x.attempt_id,a.record,e.record FROM affected x
LEFT JOIN integration_attempts a ON a.dataset_id=?1 AND a.attempt_id=x.attempt_id
LEFT JOIN integration_events e
  ON e.dataset_id=?1 AND e.kind='lineage' AND e.attempt_id=x.attempt_id
""")

SNAPSHOT_START_REFERENCES = Query(
    "SELECT attempt_id,record FROM integration_attempts "
    "WHERE dataset_id=? AND json_extract(record,'$.context_ref')=?"
)
SNAPSHOT_DECISION_REFERENCES = Query(
    "SELECT attempt_id,record FROM integration_events "
    "WHERE dataset_id=? AND kind='decision' AND json_extract(record,'$.decision_ref')=?"
)

EXPIRED_SNAPSHOT_EXISTS = Query(
    "SELECT 1 FROM integration_snapshots WHERE content IS NOT NULL "
    "AND json_extract(metadata,'$.retention_until')<=? LIMIT 1"
)


BIND_RUN_SELECT_INTEGRATION_RUNS = Query(
    "SELECT root_run_id,task_id FROM integration_runs WHERE dataset_id=? AND parent_run_id=?"
)

BIND_RUN_INSERT_INTEGRATION_RUNS = Query("INSERT INTO integration_runs VALUES (?,?,?,?,?)")

ACTION_INSERT_INTEGRATION_DATASETS = Query("INSERT INTO integration_datasets VALUES (?,?)")

ACTION_INSERT_INTEGRATION_ACCOUNTS = shared.INSERT_INTEGRATION_ACCOUNT

ACTION_INSERT_INTEGRATION_ACCOUNT_HISTORY = shared.APPEND_ACCOUNT_HISTORY

ACTION_UPDATE_INTEGRATION_ACCOUNTS = shared.UPDATE_INTEGRATION_ACCOUNT

ACTION_INSERT_INTEGRATION_EVENTS = Query("INSERT INTO integration_events VALUES (?,?,?,?,?,?,?,?)")

ACTION_SELECT_INTEGRATION_ATTEMPTS = Query(
    "SELECT attempt_id,record FROM integration_attempts WHERE dataset_id=?"
)


ACTION_INSERT_INTEGRATION_SNAPSHOTS = Query(
    "INSERT INTO integration_snapshots VALUES (?,?,?,?,?,?,?)"
)

DATASET_EXPORT_SELECT_INTEGRATION_ACCOUNT_HISTORY = Query(
    "SELECT record FROM integration_account_history WHERE dataset_id=? ORDER BY id,revision"
)

ACTION_UPDATE_INTEGRATION_SNAPSHOTS = Query(
    "UPDATE integration_snapshots SET content=NULL WHERE content IS NOT NULL AND "
    "json_extract(metadata,'$.retention_until')<=?"
)

ACTION_INSERT_INTEGRATION_EXPIRED_DATASETS = Query(
    "INSERT OR IGNORE INTO integration_expired_datasets VALUES (?,?)"
)

ACTION_DELETE_INTEGRATION_ACCOUNT_HISTORY = Query(
    "DELETE FROM integration_account_history WHERE dataset_id=?"
)

ACTION_DELETE_INTEGRATION_DATASETS = Query("DELETE FROM integration_datasets WHERE id=?")

ACTION_DELETE_INTEGRATION_DATASET_RETENTION = Query(
    "DELETE FROM integration_dataset_retention WHERE dataset_id=?"
)

ACTION_INSERT_INTEGRATION_DATASET_RETENTION = Query(
    "INSERT INTO integration_dataset_retention VALUES (?,?,?)"
)

RUN_LINEAGE = Query(
    "SELECT root_run_id,parent_run_id,task_id FROM integration_runs WHERE dataset_id=? AND run_id=?"
)


CHECK_DECISION_EVIDENCE_SELECT_INTEGRATION_ELIGIBILITY_READS = Query(
    "SELECT record FROM integration_eligibility_reads WHERE dataset_id=? AND eligibility_id=?"
)

CHECK_DECISION_EVIDENCE_SELECT_INTEGRATION_ACCOUNT_HISTORY = Query(
    "SELECT record FROM integration_account_history WHERE id=? AND dataset_id=? ORDER BY revision"
)

CHECK_SNAPSHOT_REFERENCE_SELECT_INTEGRATION_SNAPSHOTS = Query(
    "SELECT attempt_id,kind FROM integration_snapshots WHERE dataset_id=? AND snapshot_id=?"
)

DECISION_EVENT_RECORD = Query(
    "SELECT record FROM integration_events WHERE dataset_id=? AND attempt_id=? AND kind='decision'"
)

ACTION_INSERT_INTEGRATION_ATTEMPTS = Query("INSERT INTO integration_attempts VALUES (?,?,?,?,?)")

ACTION_SELECT_INTEGRATION_DATASETS = Query(
    "SELECT d.id,d.record,r.days,r.activated_at FROM integration_datasets d LEFT JOIN "
    "integration_dataset_retention r ON r.dataset_id=d.id WHERE d.id GLOB "
    "'dataset.local.real.*'"
)


def ACTION_DELETE_RECORD(*, table: str) -> Query:
    if table not in {
        "integration_events",
        "integration_attempts",
        "integration_runs",
        "integration_snapshots",
        "integration_eligibility_reads",
        "integration_accounts",
    }:
        raise ValueError("unsupported integration table")
    return Query(f"DELETE FROM {table} WHERE dataset_id=?")


PURGE_CREDENTIAL_VERSIONS = Query(
    "DELETE FROM integration_credential_versions WHERE account_id IN "
    "(SELECT account_id FROM integration_credential_bindings WHERE dataset_id=?)"
)

PURGE_CREDENTIAL_OPERATIONS = Query(
    "DELETE FROM integration_credential_operations WHERE account_id IN "
    "(SELECT account_id FROM integration_credential_bindings WHERE dataset_id=?)"
)

PURGE_CREDENTIAL_BINDINGS = Query("DELETE FROM integration_credential_bindings WHERE dataset_id=?")

DATASET_SELECT_INTEGRATION_DATASETS = Query(
    "SELECT d.record,r.days,r.activated_at FROM integration_datasets d LEFT JOIN "
    "integration_dataset_retention r ON r.dataset_id=d.id WHERE d.id=?"
)

ACTION_SELECT_INTEGRATION_EXPIRED_DATASETS = Query(
    "SELECT 1 FROM integration_expired_datasets WHERE id=?"
)

DATASET_FOR_UPDATE = Query("SELECT record FROM integration_datasets WHERE id=?")

ACTION_SELECT_INTEGRATION_ACCOUNTS = shared.GET_INTEGRATION_ACCOUNT

ELIGIBILITY_INSERT_INTEGRATION_ELIGIBILITY_READS = Query(
    "INSERT INTO integration_eligibility_reads VALUES (?,?,?)"
)

DATASETS_SELECT_INTEGRATION_DATASETS = Query(
    "SELECT d.record,r.days,r.activated_at FROM integration_datasets d LEFT JOIN "
    "integration_dataset_retention r ON r.dataset_id=d.id ORDER BY d.id"
)

ACCOUNTS_SELECT_INTEGRATION_ACCOUNTS = Query(
    "SELECT record FROM integration_accounts WHERE dataset_id=? ORDER BY id"
)

EVENT_RECEIPT = Query(
    "SELECT digest,receipt FROM integration_events WHERE dataset_id=? AND event_id=?"
)

ACTION_SELECT_INTEGRATION_SNAPSHOTS = Query(
    "SELECT snapshot_id,kind,metadata FROM integration_snapshots WHERE dataset_id=? AND "
    "attempt_id=?"
)

ACCOUNT_RESOLUTION_RECORD = Query(
    "SELECT record FROM integration_events WHERE dataset_id=? AND attempt_id=? AND "
    "kind='account_resolution'"
)

RECEIPT_SELECT_INTEGRATION_EVENTS = Query(
    "SELECT receipt FROM integration_events WHERE dataset_id=? AND event_id=?"
)

SNAPSHOT_IDENTITY = Query(
    "SELECT digest,metadata FROM integration_snapshots WHERE dataset_id=? AND snapshot_id=?"
)

ATTEMPT_FOR_UPDATE = Query(
    "SELECT record FROM integration_attempts WHERE dataset_id=? AND attempt_id=?"
)

SNAPSHOT_SELECT_INTEGRATION_SNAPSHOTS = Query(
    "SELECT metadata,content,digest FROM integration_snapshots WHERE dataset_id=? AND snapshot_id=?"
)

DATASET_EXPORT_SELECT_INTEGRATION_ATTEMPTS = Query(
    "SELECT record FROM integration_attempts WHERE dataset_id=? AND included=1 ORDER BY attempt_id"
)

DATASET_EXPORT_SELECT_INTEGRATION_EVENTS = Query(
    "SELECT record FROM integration_events WHERE dataset_id=? ORDER BY event_id"
)

DATASET_EXPORT_SELECT_INTEGRATION_ELIGIBILITY_READS = Query(
    "SELECT record FROM integration_eligibility_reads WHERE dataset_id=? ORDER BY eligibility_id"
)

DATASET_EXPORT_SELECT_INTEGRATION_SNAPSHOTS = Query(
    "SELECT metadata,content,digest FROM integration_snapshots WHERE dataset_id=? ORDER BY "
    "snapshot_id"
)

REPORT_SELECT_INTEGRATION_RUNS = Query(
    "SELECT run_id,parent_run_id FROM integration_runs WHERE dataset_id=?"
)

ACTION_SELECT_INTEGRATION_ACCOUNT_HISTORY = Query(
    "SELECT record FROM integration_account_history WHERE id=? AND dataset_id=? AND revision=1"
)

CHECK_LINEAGE_SELECT_INTEGRATION_ATTEMPTS = Query(
    "SELECT 1 FROM integration_attempts WHERE dataset_id<>? AND attempt_id=?"
)

DECISION_EVENT_ID = Query(
    "SELECT event_id FROM integration_events WHERE dataset_id=? AND attempt_id=? AND "
    "kind='decision'"
)

INTEGRATION_ACCOUNT_EXISTS = Query("SELECT 1 FROM integration_accounts WHERE id=? AND dataset_id=?")

LINEAGE_EVENT_EXISTS = Query(
    "SELECT 1 FROM integration_events WHERE dataset_id=? AND attempt_id=? AND kind='lineage'"
)

USAGE_REVISION_EXISTS = Query(
    "SELECT 1 FROM integration_events WHERE dataset_id=? AND attempt_id=? AND kind='usage' "
    "AND ordinal=?"
)

REPORT_SELECT_INTEGRATION_SNAPSHOTS = Query(
    "SELECT snapshot_id,metadata,content,digest FROM integration_snapshots WHERE dataset_id=?"
)

REPORT_SELECT_INTEGRATION_ELIGIBILITY_READS = Query(
    "SELECT eligibility_id,record FROM integration_eligibility_reads WHERE dataset_id=?"
)

ACTION_SELECT_INTEGRATION_DATASET_RETENTION = Query(
    "SELECT days,activated_at FROM integration_dataset_retention WHERE dataset_id=?"
)

DECISION_SNAPSHOT_CONTENT = Query(
    "SELECT content FROM integration_snapshots WHERE dataset_id=? AND snapshot_id=? AND "
    "attempt_id=? AND kind='decision'"
)

ACCOUNT_RESOLUTION_EXISTS = Query(
    "SELECT 1 FROM integration_events WHERE dataset_id=? AND attempt_id=? AND "
    "kind='account_resolution'"
)
