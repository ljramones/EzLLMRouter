"""SQL owned by the personal_campaign repository."""

from ..database import Query


AUDIT_INSERT_PERSONAL_CAMPAIGN_AUDIT = Query(
    "INSERT INTO personal_campaign_audit(campaign_id,action,actor,at) VALUES (?,?,?,?)"
)

RESERVE_INSERT_PERSONAL_CAMPAIGN_ATTEMPTS = Query(
    "INSERT INTO personal_campaign_attempts VALUES (?,?,?,?,?,?,?)"
)

RECOVER_UPDATE_PERSONAL_CAMPAIGN_ATTEMPTS = Query(
    "UPDATE personal_campaign_attempts SET state='unknown' WHERE state='reserved'"
)

ACTION_INSERT_PERSONAL_CAMPAIGNS = Query(
    "INSERT INTO personal_campaigns VALUES (?,?) ON CONFLICT(id) DO UPDATE SET "
    "record=excluded.record"
)

ACTION_UPDATE_PERSONAL_CAMPAIGNS = Query("UPDATE personal_campaigns SET record=? WHERE id=?")

ACTION_UPDATE_PERSONAL_CAMPAIGN_ATTEMPTS = Query(
    "UPDATE personal_campaign_attempts SET state=?,cost_decimal=?,usage_revision=? WHERE "
    "attempt_id=?"
)

RECORD_SELECT_PERSONAL_CAMPAIGNS = Query(
    "SELECT record FROM personal_campaigns ORDER BY rowid DESC LIMIT 1"
)

RESERVE_SELECT_PERSONAL_CAMPAIGN_ATTEMPTS = Query(
    "SELECT bound_decimal,cost_decimal,state FROM personal_campaign_attempts WHERE campaign_id=?"
)

RECOVER_SELECT_PERSONAL_CAMPAIGN_ATTEMPTS = Query(
    "SELECT campaign_id FROM personal_campaign_attempts WHERE state='reserved'"
)

ACTION_SELECT_PERSONAL_CAMPAIGN_ATTEMPTS = Query(
    "SELECT 1 FROM personal_campaign_attempts WHERE state IN "
    "('reserved','unknown','over_bound') LIMIT 1"
)

CHECK_SELECT_PERSONAL_CAMPAIGN_ATTEMPTS = Query(
    "SELECT state,campaign_id FROM personal_campaign_attempts WHERE attempt_id=?"
)

ACTION_SELECT_PERSONAL_CAMPAIGN_ATTEMPTS_2 = Query(
    "SELECT bound_decimal,state,campaign_id FROM personal_campaign_attempts WHERE attempt_id=?"
)

ACTION_SELECT_PERSONAL_CAMPAIGN_ATTEMPTS_3 = Query(
    "SELECT p.attempt_id,p.bound_decimal,p.state,p.usage_revision,p.campaign_id,u.usage FROM "
    "personal_campaign_attempts p LEFT JOIN usage_revisions u ON u.attempt_id=p.attempt_id "
    "AND u.revision=(SELECT MAX(revision) FROM usage_revisions WHERE attempt_id=p.attempt_id) "
    "WHERE p.state <> 'released'"
)

RECOVER_SELECT_PERSONAL_CAMPAIGNS = Query("SELECT record FROM personal_campaigns WHERE id=?")

ACTION_SELECT_PERSONAL_CAMPAIGN_ATTEMPTS_4 = Query(
    "SELECT 1 FROM personal_campaign_attempts WHERE campaign_id=? LIMIT 1"
)

SUMMARY_SELECT_PERSONAL_CAMPAIGN_ATTEMPTS = Query(
    "SELECT attempt_id,submission_id,bound_decimal,cost_decimal,state,usage_revision FROM "
    "personal_campaign_attempts WHERE campaign_id=? ORDER BY rowid"
)

SUMMARY_SELECT_PERSONAL_CAMPAIGNS = Query("SELECT COUNT(*) FROM personal_campaigns")
