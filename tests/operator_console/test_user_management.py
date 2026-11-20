"""Real SQLite account lifecycle, password verification, and permission tests."""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]

from ezllmrouter_server.registry import Registry
from ezllmrouter_server.store import SQLiteStore
from ezllmrouter_server import user_management
from ezllmrouter_server.user_management import (
    LoginThrottle,
    UserError,
    UserManager,
)

DEST = {
    "configuration_ref": "cfg.demo",
    "service": "litellm.dev04",
    "endpoint": "127.0.0.1",
    "model": "model.demo",
    "model_version": "v1",
    "processing_region": "local",
}
TRUSTED = {"principal_id": "svc.demo", "charging_owner_id": "team.demo"}
PASSWORD = "A private test passphrase!"
DEFAULT_ADMIN_PASSWORD = "Synthetic bootstrap passphrase!"


class Authority:
    def __init__(self):
        self.gate, self.epoch = threading.RLock(), 0


class UserFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = SQLiteStore(Path(self.tmp.name) / "users.sqlite")
        self.addCleanup(self.store.close)
        self.registry = Registry(
            self.store,
            Authority(),
            legacy_destination=DEST,
            legacy_token="synthetic-legacy-token-for-users-000000000000",
            legacy_trusted=TRUSTED,
        )
        with patch.dict(
            os.environ, {"EZLLMROUTER_ADMIN_PASSWORD": DEFAULT_ADMIN_PASSWORD}, clear=True
        ):
            self.users = UserManager(self.registry, bootstrap_password=DEFAULT_ADMIN_PASSWORD)

    def create(self, name="alice", role="ordinary"):
        return self.users.create(
            "owner.local",
            {
                "username": name,
                "display_name": name.title(),
                "role": role,
                "status": "active",
                "password": PASSWORD,
            },
        )

    def update(self, user, **changes):
        data = {key: user[key] for key in ("username", "display_name", "role", "status")}
        data.update(expected_revision=user["revision"], **changes)
        return self.users.update("owner.local", user["principal_id"], data)


class UserTests(UserFixture):
    def test_bootstrap_persists_and_never_overwrites_password(self):
        first = self.users.authenticate("ADMIN", DEFAULT_ADMIN_PASSWORD)
        self.assertEqual(first["principal_id"], "owner.local")
        self.assertTrue(first["must_change_password"])
        self.users.change_password(
            "owner.local", {"current_password": DEFAULT_ADMIN_PASSWORD, "new_password": PASSWORD}
        )
        with patch.dict(
            os.environ,
            {
                "EZLLMROUTER_ADMIN_USERNAME": "replacement",
                "EZLLMROUTER_ADMIN_PASSWORD": "a different bootstrap password",
            },
        ):
            reopened = UserManager(self.registry)
        self.assertFalse(reopened.authenticate("admin", PASSWORD)["must_change_password"])
        with self.assertRaises(UserError):
            reopened.authenticate("admin", DEFAULT_ADMIN_PASSWORD)
        dump = "\n".join(self.store.db.iterdump())
        self.assertNotIn(PASSWORD, dump)
        self.assertNotIn(DEFAULT_ADMIN_PASSWORD, dump)
        self.assertIn("scrypt$", dump)

    def test_configurable_bootstrap_applies_only_to_empty_database(self):
        self.store.db.execute("DELETE FROM console_users")
        with patch.dict(
            os.environ,
            {"EZLLMROUTER_ADMIN_USERNAME": "local-admin", "EZLLMROUTER_ADMIN_PASSWORD": PASSWORD},
        ):
            configured = UserManager(self.registry, bootstrap_password=PASSWORD)
        self.assertTrue(configured.authenticate("local-admin", PASSWORD)["must_change_password"])

    def test_crud_preserves_attribution_and_records_audit(self):
        user = self.create()
        user = self.update(user, username="alice.changed", display_name="Alice Updated")
        self.assertEqual(
            self.users.get("owner.local", user["principal_id"])["display_name"], "Alice Updated"
        )
        self.assertIn("models.use_granted", user["permissions"])
        self.users.delete(
            "owner.local", user["principal_id"], {"expected_revision": user["revision"]}
        )
        self.assertNotIn(
            user["principal_id"],
            [row["principal_id"] for row in self.users.list("owner.local")["items"]],
        )
        self.assertEqual(self.registry.principal(user["principal_id"])["status"], "revoked")
        self.assertEqual(len(self.registry.history(user["principal_id"])), 3)
        with self.assertRaises(UserError):
            self.users.authenticate("alice.changed", PASSWORD)

    def test_duplicate_username_rolls_back_entire_creation(self):
        self.create()
        count = len(self.registry.list_principals())
        version = self.registry.version()
        with self.assertRaises(UserError) as exc:
            self.create("ALICE")
        self.assertEqual(exc.exception.code, "USERNAME_EXISTS")
        self.assertEqual(len(self.registry.list_principals()), count)
        self.assertEqual(self.registry.version(), version)

    def test_stale_update_is_rejected_without_partial_changes(self):
        old = self.create()
        self.update(old, display_name="New name")
        with self.assertRaises(UserError) as exc:
            self.update(old, role="registry_admin")
        self.assertEqual(exc.exception.code, "USER_CONFLICT")
        self.assertEqual(self.registry.principal(old["principal_id"])["role"], "ordinary")

    def test_last_login_admin_is_protected_across_both_management_apis(self):
        owner = self.users.get("owner.local", "owner.local")
        for changes in ({"status": "suspended"}, {"role": "ordinary"}):
            with self.assertRaises(UserError) as exc:
                self.update(owner, **changes)
            self.assertEqual(exc.exception.code, "LAST_ACTIVE_ADMIN")
        with self.assertRaises(UserError):
            self.users.delete(
                "owner.local", "owner.local", {"expected_revision": owner["revision"]}
            )
        self.registry.mutate(
            "owner.local",
            {
                "operation_id": "op.no-login-admin",
                "action": "create_principal",
                "subject": "user.no-login",
                "expected_revision": 0,
                "data": {
                    "display_name": "No login",
                    "kind": "human",
                    "owner": "owner.local",
                    "role": "registry_admin",
                },
            },
        )
        self.registry.provision_credential(
            "owner.local", "user.no-login", 1, "op.no-login-credential"
        )
        self.registry.mutate(
            "owner.local",
            {
                "operation_id": "op.no-login-activate",
                "action": "principal_state",
                "subject": "user.no-login",
                "expected_revision": 2,
                "data": {"status": "active", "reason": "Legacy credential only"},
            },
        )
        with self.assertRaises(UserError):
            self.registry.mutate(
                "owner.local",
                {
                    "operation_id": "op.demote",
                    "action": "set_role",
                    "subject": "owner.local",
                    "expected_revision": owner["revision"],
                    "data": {"role": "ordinary"},
                },
            )

    def test_second_admin_allows_demotion_and_invalidates_old_sessions(self):
        second = self.create("second-admin", "registry_admin")
        owner = self.users.get("owner.local", "owner.local")
        before = self.users.context("owner.local")["auth_version"]
        self.update(owner, role="read_only_operator")
        current = self.users.context("owner.local")
        self.assertGreater(current["auth_version"], before)
        self.assertNotIn("users.manage", current["permissions"])
        self.assertTrue(self.users.list(second["principal_id"])["items"])

    def test_nonadmins_cannot_manage_other_accounts(self):
        for role in ("ordinary", "read_only_operator"):
            user = self.create("account-" + role, role)
            for operation in (
                lambda *, user=user: self.users.list(user["principal_id"]),
                lambda *, user=user: self.users.get(user["principal_id"], "owner.local"),
                lambda *, user=user: self.users.delete(
                    user["principal_id"], "owner.local", {"expected_revision": 1}
                ),
            ):
                with self.assertRaises(UserError) as exc:
                    operation()
                self.assertEqual(exc.exception.status, 403)

    def test_disable_reenable_does_not_restore_old_session_version(self):
        user = self.create()
        old = self.users.authenticate("alice", PASSWORD)
        user = self.update(user, status="suspended")
        with self.assertRaises(UserError):
            self.users.authenticate("alice", PASSWORD)
        self.update(user, status="active")
        self.assertGreater(
            self.users.context(user["principal_id"])["auth_version"], old["auth_version"]
        )

    def test_password_reset_and_self_change_require_new_secret(self):
        user = self.create()
        before = self.users.context(user["principal_id"])["auth_version"]
        self.users.reset_password(
            "owner.local",
            user["principal_id"],
            {"expected_revision": user["revision"], "password": "Replacement test passphrase!"},
        )
        with self.assertRaises(UserError):
            self.users.authenticate("alice", PASSWORD)
        current = self.users.authenticate("alice", "Replacement test passphrase!")
        self.assertGreater(current["auth_version"], before)
        self.assertTrue(current["must_change_password"])
        self.users.change_password(
            user["principal_id"],
            {"current_password": "Replacement test passphrase!", "new_password": PASSWORD},
        )
        self.assertFalse(self.users.authenticate("alice", PASSWORD)["must_change_password"])

    def test_password_validation_and_failed_current_password_keep_account(self):
        for new in ("short", DEFAULT_ADMIN_PASSWORD):
            with self.assertRaises(UserError):
                self.users.change_password(
                    "owner.local", {"current_password": DEFAULT_ADMIN_PASSWORD, "new_password": new}
                )
        with self.assertRaises(UserError) as exc:
            self.users.change_password(
                "owner.local", {"current_password": "wrong", "new_password": PASSWORD}
            )
        self.assertEqual(exc.exception.code, "CURRENT_PASSWORD_INCORRECT")
        self.assertTrue(
            self.users.authenticate("admin", DEFAULT_ADMIN_PASSWORD)["must_change_password"]
        )

    def test_legacy_role_change_revokes_named_session_version(self):
        user = self.create()
        before = self.users.context(user["principal_id"])["auth_version"]
        self.registry.mutate(
            "owner.local",
            {
                "operation_id": "op.promote",
                "action": "set_role",
                "subject": user["principal_id"],
                "expected_revision": user["revision"],
                "data": {"role": "read_only_operator"},
            },
        )
        self.assertGreater(self.users.context(user["principal_id"])["auth_version"], before)

    def test_throttle_recovers_after_window(self):
        now = [0]
        throttle = LoginThrottle(clock=lambda: now[0])
        for _ in range(20):
            ticket = throttle.begin("local", "admin")
            self.assertIsNotNone(ticket)
            throttle.finish(ticket, failed=True)
            now[0] += 2
        self.assertIsNone(throttle.begin("local", "admin"))
        now[0] += 60
        self.assertIsNotNone(throttle.begin("local", "admin"))

    def test_password_reset_verification_does_not_hold_the_send_or_database_gate(self):
        user = self.create()
        entered, release = threading.Event(), threading.Event()
        original = user_management.password_matches

        def compare(*args):
            entered.set()
            self.assertTrue(release.wait(3))
            return original(*args)

        with (
            ThreadPoolExecutor(max_workers=2) as executor,
            patch.object(user_management, "password_matches", side_effect=compare),
        ):
            pending = executor.submit(
                self.users.reset_password,
                "owner.local",
                user["principal_id"],
                {
                    "password": "Replacement password outside locks",
                    "expected_revision": user["revision"],
                },
            )
            try:
                self.assertTrue(entered.wait(3))
                changed = executor.submit(
                    self.update, user, display_name="Changed during verification"
                ).result(timeout=1)
                self.assertGreater(changed["revision"], user["revision"])
            finally:
                release.set()
            with self.assertRaises(UserError) as stale:
                pending.result(timeout=3)
            self.assertEqual(stale.exception.code, "USER_CONFLICT")

    def test_password_change_verification_has_its_own_failure_backoff(self):
        user = self.create()
        now = [0]
        self.users.password_throttle = LoginThrottle(clock=lambda: now[0])
        for _ in range(5):
            with self.assertRaises(UserError) as rejected:
                self.users.change_password(
                    user["principal_id"],
                    {
                        "current_password": "incorrect",
                        "new_password": "Another password after verification",
                    },
                )
            self.assertEqual(rejected.exception.code, "CURRENT_PASSWORD_INCORRECT")
        with self.assertRaises(UserError) as throttled:
            self.users.change_password(
                user["principal_id"],
                {
                    "current_password": PASSWORD,
                    "new_password": "Another password after verification",
                },
            )
        self.assertEqual(throttled.exception.status, 429)
        now[0] = 60
        self.users.change_password(
            user["principal_id"],
            {
                "current_password": PASSWORD,
                "new_password": "Another password after verification",
            },
        )
