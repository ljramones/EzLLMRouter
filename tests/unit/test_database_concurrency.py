"""Credential discovery and expiry races, synchronized without sockets or sleeps."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from ezllmrouter_server.integration_accounting import IntegrationError
from tests.operator_console import test_integration_credentials as fixtures

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = json.loads(
    (ROOT / "tests/fixtures/contracts/integration-readiness-v2/examples.json").read_text()
)


class CredentialConcurrencyTests(unittest.TestCase):
    setUp = fixtures.CredentialTests.setUp
    connect = fixtures.CredentialTests.connect

    def connected(self):
        item = self.connect()
        return self.credentials.save(
            self.owner,
            item["account_id"],
            {
                "dataset_id": self.dataset,
                "expected_revision": item["revision"],
                "selected_models": ["claude-opus-4-8"],
                "allowed_operations": [],
            },
        )

    def release_key(self, account):
        return self.credentials.resolve_for(
            self.consumer,
            self.dataset,
            account,
            "claude-opus-4-8",
            "generation",
            "vega-provider-dispatch",
        )

    def hold_discovery(self, *, key=None):
        entered, release = threading.Event(), threading.Event()
        original = self.credentials.discover

        def discover(*args, **kwargs):
            if key is None or args[2] == key:
                entered.set()
                if not release.wait(10):
                    raise AssertionError("test did not release the controlled discovery")
            return original(*args, **kwargs)

        self.credentials.discover = discover
        return entered, release

    def test_slow_refresh_does_not_block_release_of_the_current_credential(self):
        item = self.connected()
        account = item["account_id"]
        entered, release = self.hold_discovery()
        with ThreadPoolExecutor(max_workers=2) as executor:
            pending = executor.submit(
                self.credentials.refresh,
                self.owner,
                account,
                {"dataset_id": self.dataset, "expected_revision": item["revision"]},
            )
            try:
                self.assertTrue(entered.wait(3))
                key = executor.submit(self.release_key, account).result(timeout=3)
                self.assertEqual(key["api_key"], "known-fixture-api-key-0001")
                self.assertEqual(key["credential_version"], 1)
                self.assertFalse(pending.done())
            finally:
                release.set()
            refreshed = pending.result(timeout=3)
        self.assertEqual(refreshed["revision"], item["revision"] + 1)
        self.assertEqual(refreshed["selected_models"], item["selected_models"])

    def test_disable_wins_against_a_late_replacement_and_discards_the_unused_version(self):
        item = self.connected()
        account = item["account_id"]
        entered, release = self.hold_discovery()
        with ThreadPoolExecutor(max_workers=2) as executor:
            pending = executor.submit(
                self.credentials.replace,
                self.owner,
                account,
                {
                    "dataset_id": self.dataset,
                    "expected_revision": item["revision"],
                    "api_key": "known-fixture-replacement-key",
                },
            )
            try:
                self.assertTrue(entered.wait(3))
                self.assertEqual(
                    executor.submit(self.release_key, account).result(timeout=3)[
                        "credential_version"
                    ],
                    1,
                )
                disabled = executor.submit(
                    self.credentials.disable,
                    self.owner,
                    account,
                    {"dataset_id": self.dataset, "expected_revision": item["revision"]},
                ).result(timeout=3)
                self.assertEqual(disabled["state"], "disabled")
            finally:
                release.set()
            with self.assertRaises(IntegrationError) as rejected:
                pending.result(timeout=3)
        self.assertEqual(rejected.exception.code, "STALE_REVISION")
        self.assertEqual(self.credentials._binding(account), disabled)
        self.assertEqual(
            self.store.db.execute(
                "SELECT version FROM integration_credential_versions WHERE account_id=?", (account,)
            ).fetchall(),
            [(1,)],
        )
        with self.assertRaises(IntegrationError):
            self.release_key(account)

    def test_late_refresh_does_not_overwrite_new_model_permissions(self):
        item = self.connected()
        account = item["account_id"]
        entered, release = self.hold_discovery()
        with ThreadPoolExecutor(max_workers=2) as executor:
            pending = executor.submit(
                self.credentials.refresh,
                self.owner,
                account,
                {"dataset_id": self.dataset, "expected_revision": item["revision"]},
            )
            try:
                self.assertTrue(entered.wait(3))
                saved = executor.submit(
                    self.credentials.save,
                    self.owner,
                    account,
                    {
                        "dataset_id": self.dataset,
                        "expected_revision": item["revision"],
                        "selected_models": ["claude-sonnet-4-5-20250929"],
                        "allowed_operations": [],
                    },
                ).result(timeout=3)
            finally:
                release.set()
            with self.assertRaises(IntegrationError) as rejected:
                pending.result(timeout=3)
        self.assertEqual(rejected.exception.code, "STALE_REVISION")
        self.assertEqual(self.credentials._binding(account), saved)
        with self.assertRaises(IntegrationError):
            self.release_key(account)

    def test_overlapping_replacements_allocate_distinct_versions_and_only_one_can_publish(self):
        item = self.connected()
        account = item["account_id"]
        first_key, second_key = (
            "known-fixture-first-replacement",
            "known-fixture-second-replacement",
        )
        entered, release = self.hold_discovery(key=first_key)
        first_body = {
            "dataset_id": self.dataset,
            "expected_revision": item["revision"],
            "api_key": first_key,
        }
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(
                self.credentials.replace,
                self.owner,
                account,
                first_body,
            )
            try:
                self.assertTrue(entered.wait(3))
                second = executor.submit(
                    self.credentials.replace,
                    self.owner,
                    account,
                    {
                        "dataset_id": self.dataset,
                        "expected_revision": item["revision"],
                        "api_key": second_key,
                    },
                ).result(timeout=3)
                self.assertEqual(second["selected_version"], 3)
                # A caller mutating its request cannot rewrite the revision
                # captured by the first discovery operation.
                first_body["expected_revision"] = second["revision"]
            finally:
                release.set()
            with self.assertRaises(IntegrationError) as rejected:
                first.result(timeout=3)
        self.assertEqual(rejected.exception.code, "STALE_REVISION")
        self.assertEqual(self.release_key(account)["api_key"], second_key)
        self.assertEqual(
            self.store.db.execute(
                "SELECT version FROM integration_credential_versions WHERE account_id=? ORDER BY version",
                (account,),
            ).fetchall(),
            [(1,), (3,)],
        )

    def test_pending_connection_cannot_resurrect_after_disable_during_discovery(self):
        entered, release = self.hold_discovery()
        with ThreadPoolExecutor(max_workers=2) as executor:
            pending = executor.submit(self.connect)
            try:
                self.assertTrue(entered.wait(3))
                (item,) = self.credentials.list(self.owner, self.dataset)["items"]
                disabled = executor.submit(
                    self.credentials.disable,
                    self.owner,
                    item["account_id"],
                    {"dataset_id": self.dataset, "expected_revision": item["revision"]},
                ).result(timeout=3)
            finally:
                release.set()
            result = pending.result(timeout=3)
        self.assertEqual(result, disabled)
        self.assertEqual(result["state"], "disabled")
        self.assertEqual(result["discovery"]["state"], "not_checked")

    def test_key_rotation_and_credential_release_continue_during_discovery(self):
        item = self.connected()
        entered, release = self.hold_discovery()
        with ThreadPoolExecutor(max_workers=2) as executor:
            pending = executor.submit(
                self.credentials.refresh,
                self.owner,
                item["account_id"],
                {"dataset_id": self.dataset, "expected_revision": item["revision"]},
            )
            try:
                self.assertTrue(entered.wait(3))
                rotation = executor.submit(self.credentials.rotate_encryption_key).result(timeout=3)
                self.assertEqual(rotation["rewritten"], 1)
                self.assertEqual(
                    executor.submit(self.release_key, item["account_id"]).result(timeout=3)[
                        "credential_version"
                    ],
                    1,
                )
            finally:
                release.set()
            pending.result(timeout=3)


class DatasetPurgeRaceTests(unittest.TestCase):
    setUp = fixtures.CredentialTests.setUp
    connect = fixtures.CredentialTests.connect
    connected = CredentialConcurrencyTests.connected
    hold_discovery = CredentialConcurrencyTests.hold_discovery

    def dataset_record(self, suffix):
        accounting = self.registry.integration
        accounting.accounting_retention_days = 1
        item = {
            **accounting._dataset(self.dataset),
            "dataset_id": "dataset.local.real.race." + suffix,
            "activated_at": "2026-11-03T00:00:00Z",
        }
        accounting.create_dataset(self.owner, item)
        return item

    def test_late_discovery_cannot_restore_bindings_or_staged_secrets_after_purge(self):
        original_dataset = self.dataset
        with patch(
            "ezllmrouter_server.integration_accounting._time", return_value="2026-11-03T12:00:00Z"
        ) as clock:
            for operation in ("refresh", "replace"):
                with self.subTest(operation=operation):
                    clock.return_value = "2026-11-03T12:00:00Z"
                    self.dataset = original_dataset
                    self.dataset = self.dataset_record("late-" + operation)["dataset_id"]
                    self.credentials.discover = lambda *_args, **_kwargs: {
                        "state": "observed",
                        "reason": "synthetic",
                        "models": ["claude-opus-4-8"],
                    }
                    item = self.connected()
                    entered, release = self.hold_discovery()
                    body = {"dataset_id": self.dataset, "expected_revision": item["revision"]}
                    if operation == "replace":
                        body["api_key"] = "known-fixture-staged-key"
                    with ThreadPoolExecutor(max_workers=1) as executor:
                        pending = executor.submit(
                            getattr(self.credentials, operation),
                            self.owner,
                            item["account_id"],
                            body,
                        )
                        try:
                            self.assertTrue(entered.wait(3))
                            clock.return_value = "2026-11-04T00:00:00Z"
                            self.assertEqual(self.registry.integration.expire_datasets(), 1)
                            self.assertEqual(
                                self.store.db.execute(
                                    "SELECT COUNT(*) FROM integration_credential_versions"
                                ).fetchone(),
                                (0,),
                            )
                        finally:
                            release.set()
                        with self.assertRaises(IntegrationError) as rejected:
                            pending.result(timeout=3)
                    self.assertEqual(rejected.exception.status, 404)
                    for table in (
                        "integration_credential_versions",
                        "integration_credential_bindings",
                        "integration_credential_operations",
                    ):
                        self.assertEqual(
                            self.store.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone(), (0,)
                        )

    def test_writers_that_passed_the_first_check_cannot_recreate_purged_data(self):
        accounting = self.registry.integration
        ingest = self.registry.principal("svc.integration")
        methods = (
            "account",
            "state",
            "permissions",
            "event",
            "snapshot",
            "eligibility2",
            "eligibility3",
            "credential_connect",
            "credential_save",
            "credential_disable",
            "credential_retire",
        )
        with patch(
            "ezllmrouter_server.integration_accounting._time", return_value="2026-11-03T12:00:00Z"
        ) as clock:
            for name in methods:
                with self.subTest(writer=name):
                    clock.return_value = "2026-11-03T12:00:00Z"
                    dataset = self.dataset_record(name)
                    did = dataset["dataset_id"]
                    account = {
                        "account_id": "account.race." + name,
                        "dataset_id": did,
                        "provider_id": "provider.synthetic",
                        "credential_ref": "credential.synthetic",
                        "allowed_models": ["model.synthetic"],
                        "allowed_operations": [],
                        "state": "usable",
                    }
                    if name != "account":
                        accounting.create_account(self.owner, account, "3")
                    event = deepcopy(EXAMPLES["events"][0])
                    event["dataset_id"] = did
                    snapshot = deepcopy(EXAMPLES["snapshots"][0])
                    snapshot["dataset_id"] = did
                    actions = {
                        "account": lambda *, account=account: accounting.create_account(
                            self.owner, account, "3"
                        ),
                        "state": lambda *, account=account, did=did: accounting.set_account_state(
                            self.owner,
                            account["account_id"],
                            {"dataset_id": did, "expected_revision": 1, "state": "disabled"},
                            "3",
                        ),
                        "permissions": lambda *,
                        account=account,
                        did=did: accounting.set_account_permissions(
                            self.owner,
                            account["account_id"],
                            {
                                "dataset_id": did,
                                "expected_revision": 1,
                                "allowed_models": [],
                                "allowed_operations": [],
                            },
                        ),
                        "event": lambda *, event=event: accounting.append_event(ingest, event),
                        "snapshot": lambda *, snapshot=snapshot: accounting.append_snapshot(
                            ingest, snapshot
                        ),
                        "eligibility2": lambda *, did=did, account=account: accounting.eligibility(
                            ingest, did, account["account_id"], "model.synthetic", "2"
                        ),
                        "eligibility3": lambda *, did=did, account=account: accounting.eligibility(
                            ingest,
                            did,
                            account["account_id"],
                            "model.synthetic",
                            "3",
                            operation_family="generation",
                            capability="generation",
                            selection_kind="known_model",
                        ),
                    }
                    binding = None
                    connect_body = {
                        "dataset_id": did,
                        "provider": "anthropic",
                        "friendly_name": "Synthetic race",
                        "api_key": "known-fixture-api-key-0001",
                        "operation_id": "op.race." + name,
                    }
                    if name.startswith("credential_") and name != "credential_connect":
                        binding = self.credentials.connect(self.owner, connect_body)
                        if name in ("credential_disable", "credential_retire"):
                            binding = self.credentials.save(
                                self.owner,
                                binding["account_id"],
                                {
                                    "dataset_id": did,
                                    "expected_revision": binding["revision"],
                                    "selected_models": ["claude-opus-4-8"],
                                    "allowed_operations": [],
                                },
                            )
                        if name == "credential_retire":
                            binding = self.credentials.replace(
                                self.owner,
                                binding["account_id"],
                                {
                                    "dataset_id": did,
                                    "expected_revision": binding["revision"],
                                    "api_key": "known-fixture-new-key",
                                },
                            )
                    if name == "credential_connect":
                        actions[name] = (
                            lambda *, connect_body=connect_body: self.credentials.connect(
                                self.owner, connect_body
                            )
                        )
                    elif name == "credential_save":
                        actions[name] = lambda *, binding=binding, did=did: self.credentials.save(
                            self.owner,
                            binding["account_id"],
                            {
                                "dataset_id": did,
                                "expected_revision": binding["revision"],
                                "selected_models": ["claude-opus-4-8"],
                                "allowed_operations": [],
                            },
                        )
                    elif name == "credential_disable":
                        actions[name] = (
                            lambda *, binding=binding, did=did: self.credentials.disable(
                                self.owner,
                                binding["account_id"],
                                {"dataset_id": did, "expected_revision": binding["revision"]},
                            )
                        )
                    elif name == "credential_retire":
                        actions[name] = lambda *, binding=binding, did=did: self.credentials.retire(
                            self.owner,
                            binding["account_id"],
                            {
                                "dataset_id": did,
                                "expected_revision": binding["revision"],
                                "version": 1,
                                "acknowledged_version": binding["selected_version"],
                            },
                        )
                    self.assert_purge_wins(actions[name], did, clock)

    def assert_purge_wins(self, action, dataset_id, clock):
        entered, release = threading.Event(), threading.Event()
        transaction = self.store.database.transaction
        main_thread = threading.get_ident()

        def pause(action):
            if threading.get_ident() != main_thread:
                entered.set()
                if not release.wait(10):
                    raise AssertionError("test did not release the pending transaction")
            return transaction(action)

        with (
            patch.object(self.store.database, "transaction", side_effect=pause),
            ThreadPoolExecutor(max_workers=1) as executor,
        ):
            pending = executor.submit(action)
            try:
                if not entered.wait(3):
                    pending.result(timeout=1)
                    self.fail("writer did not reach its transaction")
                clock.return_value = "2026-11-04T00:00:00Z"
                self.assertEqual(self.registry.integration.expire_datasets(), 1)
            finally:
                release.set()
            with self.assertRaises(IntegrationError) as rejected:
                pending.result(timeout=3)
        self.assertEqual(rejected.exception.status, 404)
        for table in (
            "integration_accounts",
            "integration_account_history",
            "integration_events",
            "integration_runs",
            "integration_attempts",
            "integration_snapshots",
            "integration_eligibility_reads",
            "integration_credential_bindings",
        ):
            self.assertEqual(
                self.store.db.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE dataset_id=?", (dataset_id,)
                ).fetchone(),
                (0,),
                table,
            )
        self.assertEqual(
            self.store.db.execute(
                "SELECT COUNT(*) FROM integration_credential_versions"
            ).fetchone(),
            (0,),
        )
        self.assertEqual(
            self.store.db.execute(
                "SELECT COUNT(*) FROM integration_credential_operations"
            ).fetchone(),
            (0,),
        )


if __name__ == "__main__":
    unittest.main()
