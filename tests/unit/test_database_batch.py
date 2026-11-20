"""Migration preservation, query growth, ownership and composable transactions."""

from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from ezllmrouter_server import schema
from ezllmrouter_server.database_audit import audit
from ezllmrouter_server.integration_accounting import IntegrationError
from ezllmrouter_server.operator_projection import OperatorProjection
from ezllmrouter_server.repositories import attribution, integration_accounting as queries, registry
from ezllmrouter_server.store import SQLiteStore, encode
from tests.operator_console import test_integration_credentials as credential_fixtures
from tests.operator_console.test_projection import record

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = json.loads(
    (ROOT / "tests/fixtures/contracts/integration-readiness-v2/examples.json").read_text()
)


def steps(connection, action):
    count = 0

    def tick():
        nonlocal count
        count += 1
        return 0

    connection.set_progress_handler(tick, 1)
    try:
        result = action()
    finally:
        connection.set_progress_handler(None, 0)
    return count, result


def contents(connection):
    names = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {
        name: connection.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall()
        for (name,) in names
        if name != "schema_revisions"
    }


class MigrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "historical.sqlite"
        with closing(sqlite3.connect(self.path, isolation_level=None)) as db:
            with (
                patch.object(schema, "MIGRATIONS", schema.MIGRATIONS[:2]),
                patch.object(schema, "VERSION", 2),
            ):
                schema.initialize(db)
            db.execute(
                "INSERT INTO registry_prices VALUES (?,?,?)",
                ("cfg.exact", "price.exact", '{"amount_decimal":"0.000000000000123456789"}'),
            )
            db.execute(
                "INSERT INTO registry_grants VALUES (?,?,?)",
                ("principal.exact", "cfg.exact", '{"revision":37,"status":"revoked"}'),
            )
            # Orphan evidence from an earlier release must survive the upgrade.
            db.execute(
                "INSERT INTO integration_attempts VALUES (?,?,?,?,?)",
                (
                    "dataset.historical.missing",
                    "attempt.exact",
                    "event.exact",
                    '{"integration_version":"1"}',
                    1,
                ),
            )
            db.execute(
                "INSERT INTO registry_audit VALUES (?,?,?,?,?,?,?,?)",
                (42, "owner.exact", "historical", "subject.exact", 1, 2, 3, "2026-01-01T00:00:00Z"),
            )
            db.execute(
                "INSERT INTO registry_audit_values VALUES (?,?,?)",
                (42, '{"exact":"before"}', '{"exact":"after"}'),
            )
            self.before = contents(db)
            self.revisions = db.execute(
                "SELECT * FROM schema_revisions ORDER BY version"
            ).fetchall()

    def test_v2_upgrade_and_restart_preserve_every_historical_row_and_checksum(self):
        for _ in range(2):
            with closing(SQLiteStore(self.path)) as store:
                self.assertEqual(contents(store.db), self.before)
                self.assertEqual(
                    store.db.execute(
                        "SELECT * FROM schema_revisions WHERE version<3 ORDER BY version"
                    ).fetchall(),
                    self.revisions,
                )
                self.assertEqual(schema.validate(store.db), schema.VERSION)
                result = audit(store)
                self.assertFalse(result["ok"])
                self.assertEqual(result["ownership_violations"]["integration_attempts"], 1)

    def test_failed_v3_upgrade_rolls_back_indexes_triggers_and_version(self):
        original = schema.migration

        def broken(number):
            if number == 3:
                return original(number)[0] + "\nNOT VALID SQL;\n", "injected"
            return original(number)

        with patch.object(schema, "migration", side_effect=broken):
            with self.assertRaises(sqlite3.Error):
                SQLiteStore(self.path)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(contents(db), self.before)
            self.assertEqual(db.execute("PRAGMA user_version").fetchone(), (2,))
            self.assertEqual(
                db.execute("SELECT * FROM schema_revisions").fetchall(), self.revisions
            )
            self.assertFalse(
                db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='integration_attempts_context'"
                ).fetchone()
            )

    def test_readonly_audit_does_not_upgrade_or_rewrite_a_v2_database(self):
        before = self.path.read_bytes()
        with closing(SQLiteStore.open_existing(self.path, read_only=True)) as store:
            self.assertFalse(audit(store)["ok"])
            self.assertEqual(store.db.execute("PRAGMA user_version").fetchone(), (2,))
            with self.assertRaises(sqlite3.OperationalError):
                store.db.execute("DELETE FROM integration_attempts")
        self.assertEqual(self.path.read_bytes(), before)


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = SQLiteStore(Path(temporary.name) / "service.sqlite")
        self.addCleanup(self.store.close)

    def insert(self, key):
        self.store.database.execute(registry.ACTION_INSERT_REGISTRY_META, (key, key))

    def keys(self):
        return self.store.db.execute("SELECT key FROM registry_meta ORDER BY key").fetchall()

    def test_read_scopes_reject_writes_and_restore_connection_after_exceptions(self):
        with self.store.database.read(), self.store.database.read():
            with self.assertRaises(sqlite3.OperationalError):
                self.insert("forbidden")
            with self.assertRaises(RuntimeError):
                self.store.database.transaction(lambda: self.insert("forbidden"))
        with self.assertRaises(ValueError), self.store.database.read():
            raise ValueError("injected")
        self.store.database.transaction(lambda: self.insert("allowed"))
        self.assertEqual(self.keys(), [("allowed",)])
        self.assertFalse(self.store.db.in_transaction)

    def test_nested_failure_rolls_back_only_its_savepoint_when_caught(self):
        def inner():
            self.insert("inner")
            raise ValueError("injected")

        def outer():
            self.insert("before")
            with self.assertRaises(ValueError):
                self.store.database.transaction(inner)
            self.insert("after")

        self.store.database.transaction(outer)
        self.assertEqual(self.keys(), [("after",), ("before",)])

    def test_outer_failure_rolls_back_successful_nested_store_action(self):
        def outer():
            self.store.create(record("submission.nested", "attempt.nested", "step.nested"))
            self.store.database.transaction(lambda: self.insert("nested"))
            raise KeyboardInterrupt("injected")

        with self.assertRaises(KeyboardInterrupt):
            self.store.database.transaction(outer)
        self.assertEqual(self.keys(), [])
        self.assertIsNone(self.store.get("submission.nested"))
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM work_key_owners").fetchone(), (0,)
        )

    def test_read_snapshot_is_consistent_across_an_independent_wal_writer(self):
        self.store.database.transaction(lambda: self.insert("before"))
        with closing(sqlite3.connect(self.store.path, isolation_level=None)) as writer:
            with self.store.database.read():
                self.assertEqual(self.keys(), [("before",)])
                writer.execute("INSERT INTO registry_meta VALUES ('after','after')")
                self.assertEqual(self.keys(), [("before",)])
        self.assertEqual(self.keys(), [("after",), ("before",)])

    def test_expiring_get_uses_one_transaction_and_preserves_latest_usage(self):
        item = record("submission.expiry", "attempt.expiry", "step.expiry")
        item["content_expires_at"] = "2000-01-01T00:00:00Z"
        self.store.create(item)
        self.store.update(item["submission_id"], {}, usage={"cost": {"status": "unknown"}})
        trace = []
        self.store.db.set_trace_callback(trace.append)
        result = self.store.get(item["submission_id"])
        self.assertIsNone(result["candidate"])
        self.assertEqual(result["status_revision"], 3)
        self.assertEqual(result["usage"]["revision"]["revision"], 1)
        self.assertEqual(sum(sql == "BEGIN IMMEDIATE" for sql in trace), 1)
        trace.clear()
        self.assertEqual(self.store.get(item["submission_id"]), result)
        self.assertNotIn("BEGIN IMMEDIATE", trace)
        self.store.db.set_trace_callback(None)

    def test_finished_launch_cannot_be_overwritten_or_created_by_completion(self):
        projection = OperatorProjection(self.store, "svc.demo")
        self.assertFalse(projection.finish_launch("op.absent", "completed", []))
        projection.begin_launch("op.once", "text")
        self.assertTrue(projection.finish_launch("op.once", "completed", ["submission.original"]))
        self.assertFalse(projection.finish_launch("op.once", "failed", ["submission.late"]))
        self.assertEqual(projection.launch("op.once")["submission_ids"], ["submission.original"])

    def test_repository_tables_and_key_pairs_are_allowlisted(self):
        for action in (
            lambda: registry.RECORD_SELECT_RECORD(table="console_users", where="id=?"),
            lambda: registry.LOAD_FOR_UPDATE_SELECT_RECORD(table="registry_models", column="id"),
            lambda: attribution.RECORD_SELECT_RECORD(table="registry_meta", key="id"),
            lambda: queries.ACTION_DELETE_RECORD(table="console_users"),
        ):
            with self.assertRaises(ValueError):
                action()

    def test_usage_report_is_one_query_with_latest_revision_and_exact_decimal(self):
        for i in range(120):
            item = record(f"submission.{i}", f"attempt.{i}", f"step.{i}")
            self.store.create(item)
            for amount in ("1.000000000000000001", "0.000000000000000001"):
                self.store.update(
                    item["submission_id"],
                    {},
                    usage={
                        "cost": {
                            "status": "calculated",
                            "currency": "USD",
                            "amount_decimal": amount,
                        }
                    },
                )
        projection = OperatorProjection(self.store, "svc.demo")
        with patch.object(
            self.store.database, "execute", wraps=self.store.database.execute
        ) as execute:
            report = projection.usage()
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(report["attempts"], 120)
        self.assertEqual(report["usage_available"], 120)
        self.assertEqual(report["cost"]["known_subtotals"]["USD"], "0.000000000000000120")

    def test_read_scope_preserves_an_existing_readonly_setting(self):
        self.store.db.execute("PRAGMA query_only=ON")
        with self.store.database.read():
            self.assertEqual(self.keys(), [])
        self.assertEqual(self.store.db.execute("PRAGMA query_only").fetchone(), (1,))
        self.store.db.execute("PRAGMA query_only=OFF")

    def test_usage_report_keeps_its_cap_and_truncation_signal(self):
        item = record("submission.template", "attempt.template", "step.template")
        rows = []
        for i in range(10001):
            current = {
                **item,
                "submission_id": f"submission.cap.{i}",
                "attempt_id": f"attempt.cap.{i}",
            }
            rows.append(
                (
                    current["submission_id"],
                    "svc.demo",
                    "task.demo",
                    str(i),
                    "digest",
                    encode(current),
                )
            )
        self.store.db.executemany("INSERT INTO submissions VALUES (?,?,?,?,?,?)", rows)
        result = OperatorProjection(self.store, "svc.demo").usage()
        self.assertEqual(result["attempts"], 10000)
        self.assertTrue(result["truncated"])

    def test_successor_expiry_uses_exact_time_and_avoids_idle_writes(self):
        for name, fraction in (("due", "500000"), ("future", "700000")):
            item = record(
                "submission." + name, "attempt." + name, "step." + name, state="completed"
            )
            item.update(
                result={"content": "synthetic"},
                result_available_at="2026-11-01T00:00:00." + fraction + "Z",
            )
            self.store.successor_create(item)
        at = "2026-11-08T00:00:00.600000Z"
        self.assertEqual(self.store.successor_expire_results(at), ["submission.due"])
        rows = {
            sid: json.loads(raw)
            for sid, raw in self.store.db.execute(
                "SELECT submission_id,record FROM dev12_submissions"
            )
        }
        self.assertNotIn("result", rows["submission.due"])
        self.assertEqual(rows["submission.future"]["status_revision"], 1)
        trace = []
        self.store.db.set_trace_callback(trace.append)
        self.assertEqual(self.store.successor_expire_results(at), [])
        self.store.db.set_trace_callback(None)
        self.assertNotIn("BEGIN IMMEDIATE", trace)


class IntegrationQueryTests(unittest.TestCase):
    setUp = credential_fixtures.CredentialTests.setUp

    def start(self, name, predecessor=None):
        event = deepcopy(EXAMPLES["events"][0])
        event.update(
            dataset_id=self.dataset,
            event_id="event." + name,
            attempt_id="attempt." + name,
            run_id="run." + name,
            root_run_id="run." + name,
            context_ref="feature." + name,
            occurred_at="2026-11-04T00:00:10Z",
            started_at="2026-11-04T00:00:10Z",
        )
        if predecessor:
            event.update(attempt_role="retry", predecessor_attempt_id="attempt." + predecessor)
        return event

    def append(self, event):
        return self.registry.integration.append_event(
            self.registry.principal("svc.integration"), event
        )

    def seed_unrelated(self, count):
        self.store.db.executemany(
            "INSERT INTO integration_attempts VALUES (?,?,?,?,?)",
            [
                (
                    self.dataset,
                    "attempt.unrelated." + str(i),
                    "event.unrelated." + str(i),
                    encode(
                        {
                            "integration_version": "2",
                            "attempt_role": "initial",
                            "logical_operation_id": "logical.unrelated",
                        }
                    ),
                    1,
                )
                for i in range(count)
            ],
        )
        self.store.db.executemany(
            "INSERT INTO integration_events VALUES (?,?,?,?,?,?,?,?)",
            [
                (
                    self.dataset,
                    f"event.link.{i}",
                    "lineage",
                    f"attempt.unrelated.{i}",
                    None,
                    "synthetic",
                    encode(
                        {
                            "attempt_id": f"attempt.unrelated.{i}",
                            "attempt_role": "retry",
                            "predecessor_attempt_id": f"attempt.missing.{i}",
                            "logical_operation_id": "logical.unrelated",
                        }
                    ),
                    "{}",
                )
                for i in range(count)
            ],
        )

    def test_lineage_reads_only_the_affected_component_as_dataset_grows(self):
        event = self.start("new")
        small, _ = steps(
            self.store.db,
            lambda: self.registry.integration._check_lineage(self.store.database, event),
        )
        self.seed_unrelated(2000)
        large, _ = steps(
            self.store.db,
            lambda: self.registry.integration._check_lineage(self.store.database, event),
        )
        self.assertLess(large, small * 3, (small, large))
        self.assertEqual(self.append(event)[0], 201)
        self.assertEqual(self.append(event)[0], 200)

    def test_late_predecessor_and_cycle_conflict_leave_history_unchanged(self):
        self.append(self.start("child", "parent"))
        parent = self.start("parent")
        invalid = deepcopy(parent)
        invalid["logical_operation_id"] = "logical.conflict"
        with self.assertRaises(IntegrationError):
            self.append(invalid)
        self.assertEqual(self.append(parent)[0], 201)
        cycle = self.start("cycle", "child")
        # A separate pending component with a two-way cycle is rejected.
        self.append(self.start("a", "b"))
        with self.assertRaises(IntegrationError) as conflict:
            self.append(self.start("b", "a"))
        self.assertEqual(conflict.exception.code, "SEMANTIC_INVALID")
        self.assertEqual(self.append(cycle)[0], 201)
        self.assertEqual(
            self.store.db.execute(
                "SELECT COUNT(*) FROM integration_attempts WHERE attempt_id='attempt.b'"
            ).fetchone(),
            (0,),
        )

    def test_snapshot_binding_queries_ignore_unrelated_rows_and_reject_actual_conflicts(self):
        self.seed_unrelated(2000)
        start = self.start("snapshot")
        self.append(start)
        snapshot = deepcopy(EXAMPLES["snapshots"][0])
        snapshot.update(
            dataset_id=self.dataset,
            snapshot_id=start["context_ref"],
            attempt_id=start["attempt_id"],
        )
        self.assertEqual(
            self.registry.integration.append_snapshot(
                self.registry.principal("svc.integration"), snapshot
            )[0],
            201,
        )
        bad = deepcopy(snapshot)
        bad.update(attempt_id="attempt.wrong")
        bad["snapshot_id"] = "feature.pending"
        pending = self.start("pending")
        self.append(pending)
        with self.assertRaises(IntegrationError):
            self.registry.integration.append_snapshot(
                self.registry.principal("svc.integration"), bad
            )

    def test_history_is_dataset_scoped_and_noop_maintenance_starts_no_writer(self):
        other = "dataset.synthetic.foreign"
        self.store.db.execute("INSERT INTO integration_datasets VALUES (?,?)", (other, "{}"))
        self.store.db.execute(
            "INSERT INTO integration_account_history VALUES (?,?,?,?)",
            ("account.poison", other, 1, "not JSON"),
        )
        self.registry.integration.report(self.owner, self.dataset, version="2")
        self.registry.integration.dataset_export(self.owner, self.dataset)
        trace = []
        self.store.db.set_trace_callback(trace.append)
        self.assertEqual(
            self.registry.integration.maintain(), {"expired_datasets": 0, "expired_snapshots": 0}
        )
        self.store.db.set_trace_callback(None)
        self.assertNotIn("BEGIN IMMEDIATE", trace)

    def test_dataset_and_credential_ownership_restrict_orphan_writes_and_parent_deletion(self):
        db = self.store.db
        for sql, values in (
            (
                "INSERT INTO integration_attempts VALUES (?,?,?,?,?)",
                ("dataset.missing", "attempt.bad", "event.bad", "{}", 1),
            ),
            (
                "INSERT INTO integration_credential_operations VALUES (?,?,?)",
                ("op.orphan", "digest", "account.missing"),
            ),
            (
                "INSERT INTO integration_dataset_retention VALUES (?,?,?)",
                ("dataset.missing", 1, "2026-01-01T00:00:00Z"),
            ),
        ):
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(sql, values)
        self.append(self.start("owned"))
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute("DELETE FROM integration_datasets WHERE id=?", (self.dataset,))
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute("UPDATE integration_attempts SET dataset_id='dataset.missing'")
        self.assertTrue(audit(self.store)["ok"])

    def test_hot_paths_have_indexed_query_plans(self):
        cases = (
            (
                queries.SNAPSHOT_START_REFERENCES,
                (self.dataset, "snapshot.none"),
                "integration_attempts_context",
            ),
            (
                queries.SNAPSHOT_DECISION_REFERENCES,
                (self.dataset, "snapshot.none"),
                "integration_events_decision_ref",
            ),
            (
                queries.DATASET_EXPORT_SELECT_INTEGRATION_ACCOUNT_HISTORY,
                (self.dataset,),
                "integration_account_history_dataset",
            ),
            (
                attribution.APPEND_OUTCOME_SELECT_SUBMISSIONS,
                ("run.none", "step.none", 1, "gen.none"),
                "submissions_attribution_step",
            ),
            (
                queries.EXPIRED_SNAPSHOT_EXISTS,
                ("2026-01-01T00:00:00Z",),
                "integration_snapshots_expiry",
            ),
        )
        for query, values, index in cases:
            with self.subTest(index=index):
                plan = str(
                    self.store.db.execute("EXPLAIN QUERY PLAN " + query.sql, values).fetchall()
                )
                self.assertIn(index, plan)

    def test_late_lineage_link_is_rechecked_when_its_predecessor_arrives(self):
        child = self.start("unknown")
        child["attempt_role"] = "unknown"
        self.append(child)
        link = {
            "integration_version": "2",
            "event_id": "event.lineage",
            "dataset_id": self.dataset,
            "kind": "lineage",
            "occurred_at": "2026-11-04T00:00:20Z",
            "attempt_id": child["attempt_id"],
            "logical_operation_id": child["logical_operation_id"],
            "attempt_role": "fallback",
            "predecessor_attempt_id": "attempt.late",
        }
        self.assertEqual(self.append(link)[0], 201)
        late = self.start("late")
        bad = deepcopy(late)
        bad["logical_operation_id"] = "logical.conflict"
        with self.assertRaises(IntegrationError):
            self.append(bad)
        self.assertEqual(self.append(late)[0], 201)
        self.assertEqual(self.append(link)[0], 200)

    def test_snapshot_expiry_removes_only_content_and_then_becomes_readonly(self):
        start = self.start("retained")
        self.append(start)
        snapshot = deepcopy(EXAMPLES["snapshots"][0])
        snapshot.update(
            dataset_id=self.dataset,
            snapshot_id=start["context_ref"],
            attempt_id=start["attempt_id"],
        )
        self.registry.integration.append_snapshot(
            self.registry.principal("svc.integration"), snapshot
        )
        before = self.store.db.execute(
            "SELECT digest,metadata FROM integration_snapshots"
        ).fetchall()
        with patch(
            "ezllmrouter_server.integration_accounting._time", return_value="2028-01-01T00:00:00Z"
        ):
            self.assertEqual(self.registry.integration._expire_snapshots(), 1)
            trace = []
            self.store.db.set_trace_callback(trace.append)
            self.assertEqual(self.registry.integration._expire_snapshots(), 0)
            self.store.db.set_trace_callback(None)
        self.assertNotIn("BEGIN IMMEDIATE", trace)
        self.assertEqual(
            self.store.db.execute("SELECT digest,metadata FROM integration_snapshots").fetchall(),
            before,
        )
        self.assertEqual(
            self.store.db.execute("SELECT content FROM integration_snapshots").fetchall(), [(None,)]
        )

    def test_inventory_batches_models_prices_and_grants_for_many_deployments(self):
        connection_id = "connection.batch"
        self.store.db.execute(
            "INSERT INTO registry_connections VALUES (?,?)",
            (connection_id, encode({"connection_id": connection_id})),
        )
        for i in range(40):
            deployment = {
                "deployment_id": f"deployment.batch.{i}",
                "connection_id": connection_id,
                "serving_id": f"model.batch.{i}",
                "model_ref": "cfg.demo",
                "configuration_ref": "cfg.demo",
                "execution_approved": True,
            }
            self.store.db.execute(
                "INSERT INTO registry_deployments VALUES (?,?)",
                (deployment["deployment_id"], encode(deployment)),
            )
        for version, amount in (("price.old", "0.123456789"), ("price.latest", "0.000000001")):
            self.store.db.execute(
                "INSERT INTO registry_prices VALUES (?,?,?)",
                (
                    "cfg.demo",
                    version,
                    encode(
                        {
                            "configuration_ref": "cfg.demo",
                            "price_version": version,
                            "amount_decimal": amount,
                        }
                    ),
                ),
            )
        expected_grants = self.registry.grants(configuration_ref="cfg.demo")
        expected_price = self.registry.prices("cfg.demo")[-1]
        with (
            patch.object(
                self.registry, "grant", side_effect=AssertionError("per-row grant lookup")
            ),
            patch.object(
                self.registry, "model", side_effect=AssertionError("per-row model lookup")
            ),
            patch.object(
                self.registry, "prices", side_effect=AssertionError("per-row price lookup")
            ),
            patch.object(
                self.store.database, "execute", wraps=self.store.database.execute
            ) as execute,
        ):
            result = self.registry.source_inventory(connection_id)
        self.assertEqual(len(result["items"]), 40)
        self.assertLessEqual(execute.call_count, 8)
        self.assertTrue(
            all(
                row["grant_count"] == len(expected_grants) and row["price"] == expected_price
                for row in result["items"]
            )
        )

    def test_campaign_reconciliation_batches_latest_usage_and_remains_idempotent(self):
        from ezllmrouter_server.personal_campaign import PersonalCampaign

        campaign = PersonalCampaign(self.store, self.registry)
        self.store.db.execute(
            "INSERT INTO personal_campaigns VALUES (?,?)",
            ("campaign.batch", encode({"id": "campaign.batch", "state": "closed", "revision": 1})),
        )
        for i in range(40):
            item = record(f"submission.campaign.{i}", f"attempt.campaign.{i}", f"step.campaign.{i}")
            self.store.create(item)
            self.store.db.execute(
                "INSERT INTO personal_campaign_attempts VALUES (?,?,?,?,?,?,?)",
                (
                    item["attempt_id"],
                    item["submission_id"],
                    "campaign.batch",
                    "1",
                    None,
                    "unknown",
                    None,
                ),
            )
            for cost in ("0.010", "0.005"):
                self.store.update(
                    item["submission_id"],
                    {},
                    usage={
                        "cost": {"status": "calculated", "currency": "USD", "amount_decimal": cost}
                    },
                )
        with patch.object(
            self.store.database, "execute", wraps=self.store.database.execute
        ) as execute:
            self.assertEqual(campaign.reconcile_recorded_usage("owner.local"), 40)
        reads = [
            call
            for call in execute.call_args_list
            if call.args[0].sql.lstrip().startswith("SELECT")
        ]
        # One batched usage read plus constant campaign/epoch audit reads.
        self.assertLessEqual(len(reads), 5)
        self.assertEqual(sum("usage_revisions" in call.args[0].sql for call in reads), 1)
        self.assertEqual(
            self.store.db.execute(
                "SELECT DISTINCT cost_decimal,usage_revision FROM personal_campaign_attempts"
            ).fetchall(),
            [("0.005", 2)],
        )
        self.assertEqual(campaign.reconcile_recorded_usage("owner.local"), 0)


if __name__ == "__main__":
    unittest.main()
