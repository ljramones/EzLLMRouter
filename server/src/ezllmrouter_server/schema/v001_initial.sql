-- Initial schema for a new EzLLMRouter instance.

CREATE TABLE submissions (
                submission_id TEXT PRIMARY KEY, principal_id TEXT NOT NULL, task_id TEXT NOT NULL,
                work_key TEXT NOT NULL, work_digest TEXT NOT NULL, record TEXT NOT NULL,
                UNIQUE(principal_id, work_key)
            );

CREATE TABLE intents (
                attempt_id TEXT PRIMARY KEY, submission_id TEXT NOT NULL REFERENCES submissions(submission_id),
                intent TEXT NOT NULL
            );

CREATE TABLE guard_dispatches (
                attempt_id TEXT PRIMARY KEY, submission_id TEXT NOT NULL REFERENCES submissions(submission_id),
                receipt TEXT NOT NULL
            );

CREATE TABLE usage_revisions (
                attempt_id TEXT NOT NULL, revision INTEGER NOT NULL, submission_id TEXT NOT NULL,
                usage TEXT NOT NULL, PRIMARY KEY(attempt_id, revision)
            );

CREATE TABLE dev12_submissions (
                submission_id TEXT PRIMARY KEY, principal_id TEXT NOT NULL,
                work_key TEXT NOT NULL, work_digest TEXT NOT NULL, record TEXT NOT NULL,
                UNIQUE(principal_id, work_key)
            );

CREATE TABLE dev12_usage_revisions (
                attempt_id TEXT NOT NULL, revision INTEGER NOT NULL,
                submission_id TEXT NOT NULL REFERENCES dev12_submissions(submission_id),
                usage TEXT NOT NULL, PRIMARY KEY(attempt_id, revision)
            );

CREATE TABLE dev12_evidence_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                submission_id TEXT NOT NULL REFERENCES dev12_submissions(submission_id),
                event_kind TEXT NOT NULL, observed_at TEXT NOT NULL, evidence TEXT NOT NULL
            );

CREATE TABLE dev12_send_ownership (
                attempt_id TEXT PRIMARY KEY,
                submission_id TEXT NOT NULL REFERENCES dev12_submissions(submission_id),
                committed_at TEXT NOT NULL, guard_receipt TEXT NOT NULL
            );

CREATE TABLE work_key_owners (
                principal_id TEXT NOT NULL, work_key TEXT NOT NULL,
                contract_version TEXT NOT NULL, submission_id TEXT NOT NULL,
                PRIMARY KEY(principal_id, work_key)
            );

CREATE TABLE registry_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE registry_models (ref TEXT PRIMARY KEY, record TEXT NOT NULL);

CREATE TABLE registry_principals (id TEXT PRIMARY KEY, record TEXT NOT NULL);

CREATE TABLE registry_grants (principal_id TEXT NOT NULL, config_ref TEXT NOT NULL, record TEXT NOT NULL, PRIMARY KEY(principal_id,config_ref));

CREATE TABLE registry_prices (config_ref TEXT NOT NULL, price_version TEXT NOT NULL, record TEXT NOT NULL, PRIMARY KEY(config_ref,price_version));

CREATE TABLE registry_credentials (verifier TEXT PRIMARY KEY, principal_id TEXT NOT NULL, credential_id TEXT NOT NULL);

CREATE TABLE registry_operations (operation_id TEXT PRIMARY KEY, actor TEXT NOT NULL, request_hash TEXT NOT NULL, result TEXT NOT NULL);

CREATE TABLE registry_connections (id TEXT PRIMARY KEY, record TEXT NOT NULL);

CREATE TABLE registry_deployments (id TEXT PRIMARY KEY, record TEXT NOT NULL);

CREATE TABLE registry_observations (operation_id TEXT PRIMARY KEY, connection_id TEXT NOT NULL, record TEXT NOT NULL);

CREATE TABLE registry_source_permissions (id TEXT PRIMARY KEY, record TEXT NOT NULL);

CREATE TABLE registry_audit (seq INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT NOT NULL, action TEXT NOT NULL, subject TEXT NOT NULL, old_revision INTEGER, new_revision INTEGER NOT NULL, authority_revision INTEGER NOT NULL, at TEXT NOT NULL);

CREATE TABLE registry_audit_values (seq INTEGER PRIMARY KEY REFERENCES registry_audit(seq), before_json TEXT, after_json TEXT);

CREATE TABLE registry_agents (id TEXT PRIMARY KEY, record TEXT NOT NULL);

CREATE TABLE registry_agent_permissions (id TEXT PRIMARY KEY, caller_id TEXT NOT NULL, agent_id TEXT NOT NULL, user_id TEXT NOT NULL, record TEXT NOT NULL, UNIQUE(caller_id,agent_id,user_id));

CREATE TABLE registry_outcome_authorities (id TEXT PRIMARY KEY, record TEXT NOT NULL);

CREATE TABLE attribution_runs (id TEXT PRIMARY KEY, record TEXT NOT NULL);

CREATE TABLE attribution_outcomes (principal_id TEXT NOT NULL, event_id TEXT NOT NULL, subject TEXT NOT NULL, revision INTEGER NOT NULL, digest TEXT NOT NULL, event TEXT NOT NULL, recorded_at TEXT NOT NULL, receipt TEXT NOT NULL, PRIMARY KEY(principal_id,event_id), UNIQUE(subject,revision));

CREATE TABLE integration_datasets (id TEXT PRIMARY KEY,record TEXT NOT NULL);

CREATE TABLE integration_accounts (id TEXT NOT NULL,dataset_id TEXT NOT NULL,record TEXT NOT NULL,PRIMARY KEY(id,dataset_id));

CREATE TABLE integration_account_history (id TEXT NOT NULL,dataset_id TEXT NOT NULL,revision INTEGER NOT NULL,record TEXT NOT NULL,PRIMARY KEY(id,dataset_id,revision));

CREATE TABLE integration_runs (dataset_id TEXT NOT NULL,run_id TEXT NOT NULL,root_run_id TEXT NOT NULL,parent_run_id TEXT,task_id TEXT NOT NULL,PRIMARY KEY(dataset_id,run_id));

CREATE TABLE integration_attempts (dataset_id TEXT NOT NULL,attempt_id TEXT NOT NULL,start_event_id TEXT NOT NULL,record TEXT NOT NULL,included INTEGER NOT NULL,PRIMARY KEY(dataset_id,attempt_id));

CREATE TABLE integration_events (dataset_id TEXT NOT NULL,event_id TEXT NOT NULL,kind TEXT NOT NULL,attempt_id TEXT,ordinal INTEGER,digest TEXT NOT NULL,record TEXT NOT NULL,receipt TEXT NOT NULL,PRIMARY KEY(dataset_id,event_id));

CREATE UNIQUE INDEX integration_usage_ordinal ON integration_events(dataset_id,attempt_id,ordinal) WHERE kind='usage';

CREATE TABLE integration_snapshots (dataset_id TEXT NOT NULL,snapshot_id TEXT NOT NULL,attempt_id TEXT NOT NULL,kind TEXT NOT NULL,digest TEXT NOT NULL,metadata TEXT NOT NULL,content TEXT,PRIMARY KEY(dataset_id,snapshot_id));

CREATE TABLE integration_eligibility_reads (dataset_id TEXT NOT NULL,eligibility_id TEXT NOT NULL,record TEXT NOT NULL,PRIMARY KEY(dataset_id,eligibility_id));

CREATE TABLE integration_expired_datasets (id TEXT PRIMARY KEY,expired_at TEXT NOT NULL);

CREATE TABLE integration_dataset_retention (dataset_id TEXT PRIMARY KEY,days INTEGER NOT NULL,activated_at TEXT NOT NULL);

CREATE TABLE integration_credential_bindings (account_id TEXT PRIMARY KEY,dataset_id TEXT NOT NULL,record TEXT NOT NULL);

CREATE TABLE integration_credential_versions (account_id TEXT NOT NULL,version INTEGER NOT NULL,key_id TEXT NOT NULL,nonce BLOB NOT NULL,ciphertext BLOB NOT NULL,PRIMARY KEY(account_id,version));

CREATE TABLE integration_credential_operations (operation_id TEXT PRIMARY KEY,request_hash TEXT NOT NULL,account_id TEXT NOT NULL);

CREATE TABLE integration_credential_meta (key TEXT PRIMARY KEY,value TEXT NOT NULL);

CREATE TABLE local_connectors (id TEXT PRIMARY KEY,record TEXT NOT NULL,secret TEXT);

CREATE TABLE operator_launches (
                    operation_id TEXT PRIMARY KEY, kind TEXT NOT NULL,
                    state TEXT NOT NULL, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, submission_ids TEXT NOT NULL,
                    caller_lookups INTEGER NOT NULL, error_code TEXT
                );

CREATE TABLE operator_provider_validations (
                    operation_id TEXT PRIMARY KEY, connection_id TEXT NOT NULL,
                    connection_revision INTEGER NOT NULL, configuration_ref TEXT NOT NULL,
                    configuration_revision INTEGER NOT NULL,
                    max_output_tokens INTEGER NOT NULL, state TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    submission_id TEXT, error_code TEXT
                );

CREATE TABLE console_users (
                    principal_id TEXT PRIMARY KEY REFERENCES registry_principals(id),
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    must_change_password INTEGER NOT NULL,
                    auth_version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

CREATE TABLE personal_campaigns (
                id TEXT PRIMARY KEY, record TEXT NOT NULL);

CREATE TABLE personal_campaign_attempts (
                attempt_id TEXT PRIMARY KEY, submission_id TEXT NOT NULL UNIQUE,
                campaign_id TEXT NOT NULL, bound_decimal TEXT NOT NULL,
                cost_decimal TEXT, state TEXT NOT NULL, usage_revision INTEGER);

CREATE TABLE personal_campaign_audit (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id TEXT NOT NULL,
                action TEXT NOT NULL, actor TEXT NOT NULL, at TEXT NOT NULL);

CREATE TABLE dev12_authority (
                authority_id TEXT PRIMARY KEY, state TEXT NOT NULL
            );

CREATE TABLE dev12_authority_audit (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                authority_id TEXT NOT NULL, record TEXT NOT NULL
            );

CREATE TABLE dev12_campaigns (
                campaign_id TEXT PRIMARY KEY, record TEXT NOT NULL
            );

CREATE TABLE dev12_campaign_attempts (
                attempt_id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL REFERENCES dev12_campaigns(campaign_id),
                state TEXT NOT NULL, possible_send INTEGER NOT NULL,
                reservation_decimal TEXT NOT NULL
            );

CREATE TABLE dev12_campaign_audit (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL REFERENCES dev12_campaigns(campaign_id),
                record TEXT NOT NULL
            );

CREATE TABLE schema_revisions (version INTEGER PRIMARY KEY, sha256 TEXT NOT NULL);
CREATE INDEX registry_audit_subject ON registry_audit(subject,seq);
CREATE INDEX registry_credentials_principal ON registry_credentials(principal_id);
CREATE INDEX submissions_attempt ON submissions(json_extract(record,'$.attempt_id'));
CREATE INDEX usage_revisions_submission ON usage_revisions(submission_id,attempt_id,revision);
CREATE INDEX integration_events_attempt ON integration_events(dataset_id,attempt_id,kind);
