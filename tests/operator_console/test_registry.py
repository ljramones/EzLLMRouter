"""DEV-07 registry migration, authority and exact synthetic price checks."""

from __future__ import annotations

import json
import pathlib
import sqlite3
import tempfile
import threading
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


from ezllmrouter_server.core import usage_revision
from ezllmrouter_server.canonical import ContractError
from ezllmrouter_server.registry import Registry, RegistryConflict
from ezllmrouter_server.store import SQLiteStore


DEST = {
    "configuration_ref": "cfg.demo",
    "service": "litellm.dev04",
    "endpoint": "127.0.0.1",
    "model": "model.demo",
    "model_version": "v1",
    "processing_region": "local",
}
TRUSTED = {
    "principal_id": "svc.demo",
    "charging_owner_id": "team.demo",
    "context_id": "ctx.demo",
    "issuer_id": "issuer.synthetic",
    "source_authority_id": "srcauth.demo",
    "task_id": "task.demo",
    "prompt_id": "prompt.demo",
    "prompt_version": "v1",
    "expires_at": "2030-01-01T01:00:00Z",
}
TOKEN = "synthetic-local-service-token-only-for-test-000001"


class Authority:
    def __init__(self):
        self.gate = threading.RLock()
        self.epoch = 0


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SQLiteStore(pathlib.Path(self.temp.name) / "metadata.sqlite")
        self.addCleanup(self.store.close)
        self.authority = Authority()
        self.registry = Registry(
            self.store,
            self.authority,
            legacy_destination=DEST,
            legacy_token=TOKEN,
            legacy_trusted=TRUSTED,
        )
        self.number = 0

    def change(self, action, subject, expected, data, operation=None):
        self.number += 1
        return self.registry.mutate(
            "owner.local",
            {
                "operation_id": operation or f"op.{self.number}",
                "action": action,
                "subject": subject,
                "expected_revision": expected,
                "data": data,
            },
        )

    def model_b(self):
        self.change(
            "create_model",
            "cfg.beta",
            0,
            {
                "display_name": "Beta",
                "model": "model.demo.alt",
                "model_version": "v1",
                "owner": "owner.local",
                "capabilities": ["text", "tools"],
                "purposes": ["execution"],
                "task_classes": ["class.demo"],
            },
        )
        self.change(
            "publish_price",
            "cfg.beta",
            1,
            {
                "price_version": "beta.v1",
                "currency": "USD",
                "rates": {"input_uncached": "2", "output_text": "8"},
                "source": "synthetic fixture",
                "usage_semantics_version": "synthetic.text.v1",
            },
        )
        self.change("model_state", "cfg.beta", 2, {"status": "enabled", "reason": "Test approval"})

    def principal(self):
        self.change(
            "create_principal",
            "svc.beta",
            0,
            {"display_name": "Beta caller", "kind": "service", "owner": "team.beta"},
        )
        record, secret = self.registry.provision_credential(
            "owner.local", "svc.beta", 1, "op.provision.beta"
        )
        self.assertEqual(record["credential_state"], "bound")
        self.change(
            "principal_state", "svc.beta", 2, {"status": "active", "reason": "Test activation"}
        )
        return secret

    def test_additive_migration_preserves_dev06_rows_and_revocation(self):
        self.store.create(
            {
                "submission_id": "submission.old",
                "principal_id": "svc.demo",
                "task_id": "task.demo",
                "work_key": {"principal_id": "svc.demo", "task_id": "task.demo"},
                "work_digest": "sha256:old",
            }
        )
        self.change(
            "model_state", "cfg.demo", 1, {"status": "revoked", "reason": "Test persistence"}
        )
        reopened = Registry(
            self.store,
            self.authority,
            legacy_destination=DEST,
            legacy_token=TOKEN,
            legacy_trusted=TRUSTED,
        )
        self.assertEqual(reopened.model("cfg.demo")["status"], "revoked")
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0], 1)
        self.assertEqual(self.authority.epoch, reopened.version())
        with self.assertRaises(RegistryConflict):
            reopened.mutate(
                "owner.local",
                {
                    "operation_id": "op.restore",
                    "action": "model_state",
                    "subject": "cfg.demo",
                    "expected_revision": 2,
                    "data": {"status": "enabled", "reason": "Improper restoration"},
                },
            )

    def test_migration_on_consistent_copy_preserves_legacy_metadata(self):
        original = SQLiteStore(pathlib.Path(self.temp.name) / "legacy.sqlite")
        try:
            original.create(
                {
                    "submission_id": "submission.legacy",
                    "attempt_id": "attempt.legacy",
                    "principal_id": "svc.demo",
                    "task_id": "task.demo",
                    "work_key": {"principal_id": "svc.demo", "task_id": "task.demo"},
                    "work_digest": "sha256:legacy",
                    "candidate_access": "not_retained",
                    "content_store_allowed": False,
                }
            )
            original.db.execute(
                "INSERT INTO usage_revisions VALUES (?,?,?,?)",
                (
                    "attempt.legacy",
                    1,
                    "submission.legacy",
                    json.dumps(
                        {
                            "price_version": "synthetic.unpriced.v1",
                            "cost": {"status": "unknown", "currency": "USD"},
                        }
                    ),
                ),
            )
            copied_path = pathlib.Path(self.temp.name) / "copy.sqlite"
            copy = sqlite3.connect(copied_path)
            try:
                original.db.backup(copy)  # includes committed WAL pages
            finally:
                copy.close()
        finally:
            original.close()
        copied = SQLiteStore(copied_path)
        try:
            Registry(
                copied,
                Authority(),
                legacy_destination=DEST,
                legacy_token=TOKEN,
                legacy_trusted=TRUSTED,
            )
            self.assertEqual(copied.db.execute("PRAGMA quick_check").fetchone()[0], "ok")
            record = copied.get("submission.legacy")
            self.assertEqual(record["candidate_access"], "not_retained")
            self.assertFalse(record["content_store_allowed"])
            self.assertEqual(record["usage"]["revision"]["price_version"], "synthetic.unpriced.v1")
            from ezllmrouter_server.schema import VERSION

            self.assertEqual(copied.db.execute("PRAGMA user_version").fetchone()[0], VERSION)
        finally:
            copied.close()

    def test_grants_authentication_idempotency_and_current_authority(self):
        self.model_b()
        secret = self.principal()
        self.assertEqual(self.registry.authenticate(secret, TRUSTED)["principal_id"], "svc.beta")
        denied = self.registry.explain("svc.beta", "cfg.beta", "execution", "class.demo")
        self.assertEqual(denied["reason"], "GRANT_MISSING")
        request = {
            "operation_id": "op.grant.beta",
            "action": "set_grant",
            "subject": "svc.beta",
            "expected_revision": 0,
            "data": {
                "configuration_ref": "cfg.beta",
                "status": "active",
                "purposes": ["execution"],
                "task_classes": ["class.demo"],
            },
        }
        first = self.registry.mutate("owner.local", request)
        self.assertEqual(first, self.registry.mutate("owner.local", request))
        with self.assertRaises(RegistryConflict):
            self.registry.mutate(
                "owner.local", {**request, "data": {**request["data"], "status": "removed"}}
            )
        selected, decision = self.registry.admit("svc.beta", "cfg.beta", "execution", "class.demo")
        self.assertEqual(selected["model"], "model.demo.alt")
        before = self.authority.epoch
        self.change("set_grant", "svc.beta", 1, {**request["data"], "status": "removed"})
        self.assertEqual(self.authority.epoch, before + 1)
        with self.assertRaises(ContractError):
            self.registry.check_current("svc.beta", "cfg.beta", "execution", "class.demo", decision)
        self.change("set_grant", "svc.beta", 2, request["data"])
        with self.assertRaises(ContractError):
            self.registry.check_current("svc.beta", "cfg.beta", "execution", "class.demo", decision)
        self.change(
            "principal_state", "svc.beta", 3, {"status": "suspended", "reason": "Test suspension"}
        )
        with self.assertRaises(ContractError):
            self.registry.authenticate(secret, TRUSTED)

    def test_failed_audit_is_not_a_successful_change(self):
        before = self.authority.epoch
        self.store.db.execute(
            "CREATE TRIGGER deny_registry_audit BEFORE INSERT ON registry_audit "
            "BEGIN SELECT RAISE(ABORT,'test audit failure'); END"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.change(
                "create_principal",
                "svc.abort",
                0,
                {"display_name": "Abort", "kind": "service", "owner": "team.abort"},
            )
        self.assertIsNone(self.registry.principal("svc.abort"))
        self.assertEqual(self.authority.epoch, before)

    def test_last_admin_and_malformed_price_fail_closed(self):
        before = self.registry.version()
        with self.assertRaises(ValueError):
            self.change(
                "principal_state",
                "owner.local",
                1,
                {"status": "suspended", "reason": "Improper last-admin removal"},
            )
        self.assertEqual(self.registry.version(), before)
        self.model_b()
        with self.assertRaises(ValueError):
            self.change(
                "publish_price",
                "cfg.beta",
                3,
                {
                    "price_version": "beta.bad",
                    "currency": "USD",
                    "rates": {"input_uncached": "NaN", "output_text": "8"},
                    "source": "synthetic fixture",
                    "usage_semantics_version": "synthetic.text.v1",
                },
            )
        self.assertEqual(self.registry.model("cfg.beta")["revision"], 3)
        self.assertFalse(
            any(p["price_version"] == "beta.bad" for p in self.registry.prices("cfg.beta"))
        )
        for index, rates, currency in (
            (1, {"input_uncached": "-1", "output_text": "8"}, "USD"),
            (2, {"input_uncached": "Infinity", "output_text": "8"}, "USD"),
            (3, {"input_uncached": "2"}, "USD"),
            (4, {"input_uncached": "2", "output_text": "8"}, "EUR"),
        ):
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.change(
                    "publish_price",
                    "cfg.beta",
                    3,
                    {
                        "price_version": "beta.invalid." + str(index),
                        "currency": currency,
                        "rates": rates,
                        "source": "synthetic fixture",
                        "usage_semantics_version": "synthetic.text.v1",
                    },
                )
        self.assertEqual(self.registry.model("cfg.beta")["revision"], 3)

    def test_price_snapshot_uses_actual_usage_and_never_reprices_old_attempt(self):
        self.model_b()
        secret = self.principal()
        self.change(
            "set_grant",
            "svc.beta",
            0,
            {
                "configuration_ref": "cfg.beta",
                "status": "active",
                "purposes": ["execution"],
                "task_classes": ["class.demo"],
            },
        )
        _, before = self.registry.admit("svc.beta", "cfg.beta", "execution", "class.demo")
        # The trusted adapter normalizes the receiver's prompt/completion keys.
        report = {"input_tokens": 1000, "output_tokens": 100}
        old = usage_revision("attempt.before", report, decision=before)
        self.assertEqual(
            (old["cost"]["amount_decimal"], old["price_version"]), ("0.0028", "beta.v1")
        )
        self.change(
            "publish_price",
            "cfg.beta",
            3,
            {
                "price_version": "beta.v2",
                "currency": "USD",
                "rates": {"input_uncached": "3", "output_text": "12"},
                "source": "synthetic fixture",
                "usage_semantics_version": "synthetic.text.v1",
            },
        )
        _, after = self.registry.admit("svc.beta", "cfg.beta", "execution", "class.demo")
        new = usage_revision("attempt.after", report, decision=after)
        self.assertEqual(
            (new["cost"]["amount_decimal"], new["price_version"]), ("0.0042", "beta.v2")
        )
        self.assertEqual(
            usage_revision("attempt.before", report, decision=before)["cost"], old["cost"]
        )
        self.assertEqual(
            usage_revision("attempt.partial", {"input_tokens": 1000}, decision=after)["cost"][
                "status"
            ],
            "unknown",
        )
        self.assertEqual(
            usage_revision(
                "attempt.negative", {"input_tokens": -1, "output_tokens": 2}, decision=after
            )["cost"]["status"],
            "unknown",
        )
        self.assertEqual(
            usage_revision("attempt.zero", {"input_tokens": 0, "output_tokens": 0}, decision=after)[
                "cost"
            ]["zero_basis"],
            "provider_reported_free",
        )
        self.assertEqual(
            self.registry.authenticate(secret, TRUSTED)["charging_owner_id"], "team.beta"
        )

    def test_manual_catalogue_crud_preserves_prices_and_cannot_enable_or_grant(self):
        ref = "catalogue.operator.test-crud"
        price = {
            "snapshot_id": "test.price.v1",
            "source_title": "Operator test reference",
            "source_url": "https://example.org/test-prices",
            "bands": [
                {
                    "label": "Test band",
                    "conditions": {"definition": "Disposable test rate"},
                    "rates_usd_per_1000000_tokens": {
                        "input_uncached": "1.25",
                        "output": "4",
                        "input_cached": None,
                    },
                }
            ],
        }
        data = {
            "display_name": "Disposable model",
            "vendor": "Test vendor",
            "family": "Test family",
            "api_model_id": "test-model",
            "model_version": "test-v1",
            "owner": "owner.local",
            "capabilities": ["text"],
            "context_window": 1000,
            "max_output": 200,
            "notes": "Disposable test record",
            "price": price,
        }
        first = self.change("register_catalogue", ref, 0, data)["record"]
        self.assertEqual(
            (
                first["status"],
                first["destination"],
                first["catalogue"]["price_reference"]["verified_on"],
            ),
            ("catalogued", None, None),
        )
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM registry_grants").fetchone()[0], 1
        )
        with self.assertRaises(ValueError):
            self.change(
                "set_grant",
                "svc.demo",
                0,
                {
                    "configuration_ref": ref,
                    "status": "active",
                    "purposes": ["execution"],
                    "task_classes": ["class.demo"],
                },
            )
        with self.assertRaises(ValueError):
            self.change("model_state", ref, 1, {"status": "enabled", "reason": "No route"})
        edit = {"display_name": "Disposable model edited", "notes": data["notes"]}
        self.change("edit_catalogue_model", ref, 1, edit)
        newer = {
            **price,
            "snapshot_id": "test.price.v2",
            "bands": [
                {
                    **price["bands"][0],
                    "rates_usd_per_1000000_tokens": {
                        "input_uncached": "2",
                        "output": "5",
                        "input_cached": None,
                    },
                }
            ],
        }
        self.change("publish_reference_price", ref, 2, newer)
        model = self.registry.model(ref)
        self.assertEqual(model["catalogue"]["price_reference"]["snapshot_id"], "test.price.v2")
        self.assertEqual(
            model["reference_price_history"][0]["price"]["snapshot_id"], "test.price.v1"
        )
        self.assertEqual(
            model["original_research"]["price_reference"]["snapshot_id"], "test.price.v1"
        )
        with self.assertRaises(RegistryConflict):
            self.change("publish_reference_price", ref, 2, newer)
        with self.assertRaises(RegistryConflict):
            self.change("publish_reference_price", ref, 3, price)
        retired = self.change("archive_model", ref, 3, {"reason": "Disposable test deletion"})[
            "record"
        ]
        self.assertEqual(retired["status"], "archived")
        self.assertEqual(
            Registry(
                self.store,
                self.authority,
                legacy_destination=DEST,
                legacy_token=TOKEN,
                legacy_trusted=TRUSTED,
            ).model(ref)["status"],
            "archived",
        )
        with self.assertRaises(RegistryConflict):
            self.change("register_catalogue", ref, 0, data)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0], 0)

    def test_disposable_identity_crud_grant_removal_and_last_admin(self):
        self.model_b()
        created = self.change(
            "create_principal",
            "user.disposable",
            0,
            {
                "display_name": "Disposable test user",
                "kind": "human",
                "owner": "owner.local",
                "role": "ordinary",
            },
        )["record"]
        self.assertEqual(
            (created["status"], created["credential_state"], created["role"]),
            ("inactive", "unbound", "ordinary"),
        )
        self.change(
            "edit_principal",
            "user.disposable",
            1,
            {"display_name": "Edited disposable user", "owner": "team.beta"},
        )
        self.change(
            "set_grant",
            "user.disposable",
            0,
            {
                "configuration_ref": "cfg.beta",
                "status": "active",
                "purposes": ["execution"],
                "task_classes": ["class.demo"],
            },
        )
        self.assertEqual(
            self.registry.explain("user.disposable", "cfg.beta", "execution", "class.demo")[
                "allowed"
            ],
            False,
        )
        self.change(
            "set_grant",
            "user.disposable",
            1,
            {
                "configuration_ref": "cfg.beta",
                "status": "removed",
                "purposes": ["execution"],
                "task_classes": ["class.demo"],
            },
        )
        self.change(
            "principal_state",
            "user.disposable",
            2,
            {"status": "revoked", "reason": "Disposable test deletion"},
        )
        with self.assertRaises(ValueError):
            self.change(
                "set_grant",
                "user.disposable",
                2,
                {
                    "configuration_ref": "cfg.beta",
                    "status": "active",
                    "purposes": ["execution"],
                    "task_classes": ["class.demo"],
                },
            )
        with self.assertRaises(RegistryConflict):
            self.change(
                "create_principal",
                "user.disposable",
                0,
                {"display_name": "Reuse", "kind": "human", "owner": "owner.local"},
            )
        with self.assertRaises(ValueError):
            self.change(
                "principal_state",
                "owner.local",
                1,
                {"status": "revoked", "reason": "Last administrator"},
            )
        self.assertEqual(self.registry.principal("owner.local")["status"], "active")
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0], 0)

    def test_archived_executable_model_invalidates_prior_sender_decision(self):
        self.model_b()
        self.change(
            "set_grant",
            "svc.demo",
            0,
            {
                "configuration_ref": "cfg.beta",
                "status": "active",
                "purposes": ["execution"],
                "task_classes": ["class.demo"],
            },
        )
        _, decision = self.registry.admit("svc.demo", "cfg.beta", "execution", "class.demo")
        before = self.authority.epoch
        retired = self.change(
            "archive_model", "cfg.beta", 3, {"reason": "Disposable model retirement"}
        )["record"]
        self.assertEqual(retired["status"], "revoked")
        self.assertEqual(self.authority.epoch, before + 1)
        with self.assertRaises(ContractError):
            self.registry.check_current("svc.demo", "cfg.beta", "execution", "class.demo", decision)
        self.assertEqual(self.registry.grant("svc.demo", "cfg.beta")["status"], "active")
        self.assertEqual(len(self.registry.prices("cfg.beta")), 1)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
