-- Indexed query paths and prospective ownership constraints. No historical rows are rewritten.
CREATE INDEX dev12_submissions_attempt ON dev12_submissions(json_extract(record,'$.attempt_id'));
CREATE INDEX submissions_principal ON submissions(principal_id);
CREATE INDEX submissions_state ON submissions(json_extract(record,'$.submission_state'));
CREATE INDEX submissions_principal_state ON submissions(principal_id,json_extract(record,'$.submission_state'));
CREATE INDEX submissions_attribution_step ON submissions(json_extract(record,'$.attribution.run_id'),json_extract(record,'$.work_key.step_id'),json_extract(record,'$.work_key.step_revision'),json_extract(record,'$.work_key.execution_generation'));
CREATE INDEX intents_submission ON intents(submission_id);
CREATE INDEX guard_dispatches_submission ON guard_dispatches(submission_id);
CREATE INDEX personal_campaign_attempts_campaign ON personal_campaign_attempts(campaign_id);
CREATE INDEX personal_campaign_attempts_state ON personal_campaign_attempts(state);
CREATE INDEX integration_account_history_dataset ON integration_account_history(dataset_id,id,revision);
CREATE INDEX integration_runs_parent ON integration_runs(dataset_id,parent_run_id);
CREATE INDEX integration_attempts_identity ON integration_attempts(attempt_id,dataset_id);
CREATE INDEX integration_attempts_predecessor ON integration_attempts(dataset_id,json_extract(record,'$.predecessor_attempt_id'));
CREATE INDEX integration_attempts_context ON integration_attempts(dataset_id,json_extract(record,'$.context_ref'));
CREATE INDEX integration_attempts_included ON integration_attempts(dataset_id,included,attempt_id);
CREATE INDEX integration_events_predecessor ON integration_events(dataset_id,json_extract(record,'$.predecessor_attempt_id')) WHERE kind='lineage';
CREATE INDEX integration_events_decision_ref ON integration_events(dataset_id,json_extract(record,'$.decision_ref')) WHERE kind='decision';
CREATE INDEX integration_snapshots_attempt ON integration_snapshots(dataset_id,attempt_id);
CREATE INDEX integration_snapshots_expiry ON integration_snapshots(json_extract(metadata,'$.retention_until')) WHERE content IS NOT NULL;
CREATE INDEX integration_credentials_dataset ON integration_credential_bindings(dataset_id);
CREATE INDEX integration_credential_operations_account ON integration_credential_operations(account_id);
CREATE INDEX registry_grants_config ON registry_grants(config_ref,principal_id);
CREATE INDEX registry_principals_role_status ON registry_principals(json_extract(record,'$.role'),json_extract(record,'$.status'));
CREATE INDEX registry_deployments_connection ON registry_deployments(json_extract(record,'$.connection_id'));
CREATE INDEX registry_permissions_connection ON registry_source_permissions(json_extract(record,'$.connection_id'));

CREATE INDEX dev12_submissions_result_expiry ON dev12_submissions(json_extract(record,'$.result_available_at'))
WHERE json_extract(record,'$.candidate_access')='present' AND json_extract(record,'$.submission_state')='completed';

CREATE TRIGGER integration_accounts_dataset_insert
BEFORE INSERT ON integration_accounts
WHEN NOT EXISTS (SELECT 1 FROM integration_datasets WHERE id=NEW.dataset_id)
BEGIN
    SELECT RAISE(ABORT, 'integration dataset ownership violation');
END;

CREATE TRIGGER integration_accounts_dataset_update
BEFORE UPDATE OF dataset_id ON integration_accounts
WHEN NOT EXISTS (SELECT 1 FROM integration_datasets WHERE id=NEW.dataset_id)
BEGIN
    SELECT RAISE(ABORT, 'integration dataset ownership violation');
END;

CREATE TRIGGER integration_account_history_dataset_insert
BEFORE INSERT ON integration_account_history
WHEN NOT EXISTS (SELECT 1 FROM integration_datasets WHERE id=NEW.dataset_id)
BEGIN
    SELECT RAISE(ABORT, 'integration dataset ownership violation');
END;

CREATE TRIGGER integration_account_history_dataset_update
BEFORE UPDATE OF dataset_id ON integration_account_history
WHEN NOT EXISTS (SELECT 1 FROM integration_datasets WHERE id=NEW.dataset_id)
BEGIN
    SELECT RAISE(ABORT, 'integration dataset ownership violation');
END;

CREATE TRIGGER integration_runs_dataset_insert
BEFORE INSERT ON integration_runs
WHEN NOT EXISTS (SELECT 1 FROM integration_datasets WHERE id=NEW.dataset_id)
BEGIN
    SELECT RAISE(ABORT, 'integration dataset ownership violation');
END;

CREATE TRIGGER integration_runs_dataset_update
BEFORE UPDATE OF dataset_id ON integration_runs
WHEN NOT EXISTS (SELECT 1 FROM integration_datasets WHERE id=NEW.dataset_id)
BEGIN
    SELECT RAISE(ABORT, 'integration dataset ownership violation');
END;

CREATE TRIGGER integration_attempts_dataset_insert
BEFORE INSERT ON integration_attempts
WHEN NOT EXISTS (SELECT 1 FROM integration_datasets WHERE id=NEW.dataset_id)
BEGIN
    SELECT RAISE(ABORT, 'integration dataset ownership violation');
END;

CREATE TRIGGER integration_attempts_dataset_update
BEFORE UPDATE OF dataset_id ON integration_attempts
WHEN NOT EXISTS (SELECT 1 FROM integration_datasets WHERE id=NEW.dataset_id)
BEGIN
    SELECT RAISE(ABORT, 'integration dataset ownership violation');
END;

CREATE TRIGGER integration_events_dataset_insert
BEFORE INSERT ON integration_events
WHEN NOT EXISTS (SELECT 1 FROM integration_datasets WHERE id=NEW.dataset_id)
BEGIN
    SELECT RAISE(ABORT, 'integration dataset ownership violation');
END;

CREATE TRIGGER integration_events_dataset_update
BEFORE UPDATE OF dataset_id ON integration_events
WHEN NOT EXISTS (SELECT 1 FROM integration_datasets WHERE id=NEW.dataset_id)
BEGIN
    SELECT RAISE(ABORT, 'integration dataset ownership violation');
END;

CREATE TRIGGER integration_snapshots_dataset_insert
BEFORE INSERT ON integration_snapshots
WHEN NOT EXISTS (SELECT 1 FROM integration_datasets WHERE id=NEW.dataset_id)
BEGIN
    SELECT RAISE(ABORT, 'integration dataset ownership violation');
END;

CREATE TRIGGER integration_snapshots_dataset_update
BEFORE UPDATE OF dataset_id ON integration_snapshots
WHEN NOT EXISTS (SELECT 1 FROM integration_datasets WHERE id=NEW.dataset_id)
BEGIN
    SELECT RAISE(ABORT, 'integration dataset ownership violation');
END;

CREATE TRIGGER integration_eligibility_reads_dataset_insert
BEFORE INSERT ON integration_eligibility_reads
WHEN NOT EXISTS (SELECT 1 FROM integration_datasets WHERE id=NEW.dataset_id)
BEGIN
    SELECT RAISE(ABORT, 'integration dataset ownership violation');
END;

CREATE TRIGGER integration_eligibility_reads_dataset_update
BEFORE UPDATE OF dataset_id ON integration_eligibility_reads
WHEN NOT EXISTS (SELECT 1 FROM integration_datasets WHERE id=NEW.dataset_id)
BEGIN
    SELECT RAISE(ABORT, 'integration dataset ownership violation');
END;

CREATE TRIGGER integration_dataset_retention_dataset_insert
BEFORE INSERT ON integration_dataset_retention
WHEN NOT EXISTS (SELECT 1 FROM integration_datasets WHERE id=NEW.dataset_id)
BEGIN
    SELECT RAISE(ABORT, 'integration dataset ownership violation');
END;

CREATE TRIGGER integration_dataset_retention_dataset_update
BEFORE UPDATE OF dataset_id ON integration_dataset_retention
WHEN NOT EXISTS (SELECT 1 FROM integration_datasets WHERE id=NEW.dataset_id)
BEGIN
    SELECT RAISE(ABORT, 'integration dataset ownership violation');
END;

CREATE TRIGGER integration_credential_bindings_dataset_insert
BEFORE INSERT ON integration_credential_bindings
WHEN NOT EXISTS (SELECT 1 FROM integration_datasets WHERE id=NEW.dataset_id)
BEGIN
    SELECT RAISE(ABORT, 'integration dataset ownership violation');
END;

CREATE TRIGGER integration_credential_bindings_dataset_update
BEFORE UPDATE OF dataset_id ON integration_credential_bindings
WHEN NOT EXISTS (SELECT 1 FROM integration_datasets WHERE id=NEW.dataset_id)
BEGIN
    SELECT RAISE(ABORT, 'integration dataset ownership violation');
END;

CREATE TRIGGER integration_dataset_restrict_delete
BEFORE DELETE ON integration_datasets
WHEN EXISTS (SELECT 1 FROM integration_accounts WHERE dataset_id=OLD.id) OR
    EXISTS (SELECT 1 FROM integration_account_history WHERE dataset_id=OLD.id) OR
    EXISTS (SELECT 1 FROM integration_runs WHERE dataset_id=OLD.id) OR
    EXISTS (SELECT 1 FROM integration_attempts WHERE dataset_id=OLD.id) OR
    EXISTS (SELECT 1 FROM integration_events WHERE dataset_id=OLD.id) OR
    EXISTS (SELECT 1 FROM integration_snapshots WHERE dataset_id=OLD.id) OR
    EXISTS (SELECT 1 FROM integration_eligibility_reads WHERE dataset_id=OLD.id) OR
    EXISTS (SELECT 1 FROM integration_dataset_retention WHERE dataset_id=OLD.id) OR
    EXISTS (SELECT 1 FROM integration_credential_bindings WHERE dataset_id=OLD.id)
BEGIN
    SELECT RAISE(ABORT, 'integration dataset still owns records');
END;

CREATE TRIGGER integration_dataset_restrict_update
BEFORE UPDATE OF id ON integration_datasets
WHEN EXISTS (SELECT 1 FROM integration_accounts WHERE dataset_id=OLD.id) OR
    EXISTS (SELECT 1 FROM integration_account_history WHERE dataset_id=OLD.id) OR
    EXISTS (SELECT 1 FROM integration_runs WHERE dataset_id=OLD.id) OR
    EXISTS (SELECT 1 FROM integration_attempts WHERE dataset_id=OLD.id) OR
    EXISTS (SELECT 1 FROM integration_events WHERE dataset_id=OLD.id) OR
    EXISTS (SELECT 1 FROM integration_snapshots WHERE dataset_id=OLD.id) OR
    EXISTS (SELECT 1 FROM integration_eligibility_reads WHERE dataset_id=OLD.id) OR
    EXISTS (SELECT 1 FROM integration_dataset_retention WHERE dataset_id=OLD.id) OR
    EXISTS (SELECT 1 FROM integration_credential_bindings WHERE dataset_id=OLD.id)
BEGIN
    SELECT RAISE(ABORT, 'integration dataset still owns records');
END;

CREATE TRIGGER integration_credential_versions_binding_insert
BEFORE INSERT ON integration_credential_versions
WHEN NOT EXISTS (SELECT 1 FROM integration_credential_bindings WHERE account_id=NEW.account_id)
BEGIN
    SELECT RAISE(ABORT, 'integration credential binding violation');
END;

CREATE TRIGGER integration_credential_versions_binding_update
BEFORE UPDATE OF account_id ON integration_credential_versions
WHEN NOT EXISTS (SELECT 1 FROM integration_credential_bindings WHERE account_id=NEW.account_id)
BEGIN
    SELECT RAISE(ABORT, 'integration credential binding violation');
END;

CREATE TRIGGER integration_credential_operations_binding_insert
BEFORE INSERT ON integration_credential_operations
WHEN NOT EXISTS (SELECT 1 FROM integration_credential_bindings WHERE account_id=NEW.account_id)
BEGIN
    SELECT RAISE(ABORT, 'integration credential binding violation');
END;

CREATE TRIGGER integration_credential_operations_binding_update
BEFORE UPDATE OF account_id ON integration_credential_operations
WHEN NOT EXISTS (SELECT 1 FROM integration_credential_bindings WHERE account_id=NEW.account_id)
BEGIN
    SELECT RAISE(ABORT, 'integration credential binding violation');
END;

CREATE TRIGGER integration_binding_restrict_delete
BEFORE DELETE ON integration_credential_bindings
WHEN EXISTS (SELECT 1 FROM integration_credential_versions WHERE account_id=OLD.account_id)
  OR EXISTS (SELECT 1 FROM integration_credential_operations WHERE account_id=OLD.account_id)
BEGIN
    SELECT RAISE(ABORT, 'integration binding still owns credentials');
END;

CREATE TRIGGER integration_binding_restrict_update
BEFORE UPDATE OF account_id ON integration_credential_bindings
WHEN EXISTS (SELECT 1 FROM integration_credential_versions WHERE account_id=OLD.account_id)
  OR EXISTS (SELECT 1 FROM integration_credential_operations WHERE account_id=OLD.account_id)
BEGIN
    SELECT RAISE(ABORT, 'integration binding still owns credentials');
END;
