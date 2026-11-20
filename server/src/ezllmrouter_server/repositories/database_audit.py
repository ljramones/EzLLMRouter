"""Read-only database integrity queries; return counts without private row contents."""

from ..database import Query

QUICK_CHECK = Query("PRAGMA quick_check")
FOREIGN_KEY_CHECK = Query("PRAGMA foreign_key_check")
OWNERSHIP_COUNTS = Query("""
SELECT 'integration_accounts',COUNT(*) FROM integration_accounts c WHERE NOT EXISTS (SELECT 1 FROM integration_datasets d WHERE d.id=c.dataset_id)
UNION ALL
SELECT 'integration_account_history',COUNT(*) FROM integration_account_history c WHERE NOT EXISTS (SELECT 1 FROM integration_datasets d WHERE d.id=c.dataset_id)
UNION ALL
SELECT 'integration_runs',COUNT(*) FROM integration_runs c WHERE NOT EXISTS (SELECT 1 FROM integration_datasets d WHERE d.id=c.dataset_id)
UNION ALL
SELECT 'integration_attempts',COUNT(*) FROM integration_attempts c WHERE NOT EXISTS (SELECT 1 FROM integration_datasets d WHERE d.id=c.dataset_id)
UNION ALL
SELECT 'integration_events',COUNT(*) FROM integration_events c WHERE NOT EXISTS (SELECT 1 FROM integration_datasets d WHERE d.id=c.dataset_id)
UNION ALL
SELECT 'integration_snapshots',COUNT(*) FROM integration_snapshots c WHERE NOT EXISTS (SELECT 1 FROM integration_datasets d WHERE d.id=c.dataset_id)
UNION ALL
SELECT 'integration_eligibility_reads',COUNT(*) FROM integration_eligibility_reads c WHERE NOT EXISTS (SELECT 1 FROM integration_datasets d WHERE d.id=c.dataset_id)
UNION ALL
SELECT 'integration_dataset_retention',COUNT(*) FROM integration_dataset_retention c WHERE NOT EXISTS (SELECT 1 FROM integration_datasets d WHERE d.id=c.dataset_id)
UNION ALL
SELECT 'integration_credential_bindings',COUNT(*) FROM integration_credential_bindings c WHERE NOT EXISTS (SELECT 1 FROM integration_datasets d WHERE d.id=c.dataset_id)
UNION ALL
SELECT 'integration_credential_versions',COUNT(*) FROM integration_credential_versions c WHERE NOT EXISTS (SELECT 1 FROM integration_credential_bindings b WHERE b.account_id=c.account_id)
UNION ALL
SELECT 'integration_credential_operations',COUNT(*) FROM integration_credential_operations c WHERE NOT EXISTS (SELECT 1 FROM integration_credential_bindings b WHERE b.account_id=c.account_id)
""")
