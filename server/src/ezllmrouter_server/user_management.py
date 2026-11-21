"""Persistent console accounts tied to the existing permission registry."""

from __future__ import annotations

from typing import cast
from .database import Database
from .records import Record

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path

from .errors import RequestError
from .formatting import utc_timestamp as timestamp
from .private_files import secret_text
from .repositories import authority
from .repositories import user_management as _queries
from .store import encode

DEFAULT_ADMIN_USERNAME = "admin"
PASSWORD_HASH_SLOTS = threading.BoundedSemaphore(2)
ROLE_PERMISSIONS = {
    "ordinary": ("activity.read_own", "models.read_allowed", "models.use_granted"),
    "read_only_operator": (
        "activity.read_all",
        "reports.read_all",
        "registry.read",
        "settings.read",
    ),
    "registry_admin": (
        "activity.read_all",
        "reports.read_all",
        "registry.read",
        "settings.read",
        "users.manage",
        "registry.manage",
        "connections.manage",
    ),
}
USERNAME = re.compile(r"[a-z0-9][a-z0-9_.-]{2,63}\Z")


class UserError(RequestError):
    def __init__(self, code, status=400):
        super().__init__(code, status)


def username(value):
    if type(value) is not str or not USERNAME.fullmatch(value.strip().lower()):
        raise UserError("INVALID_USERNAME")
    return value.strip().lower()


def validate_password(value):
    if type(value) is not str or not 12 <= len(value) <= 256:
        raise UserError("PASSWORD_LENGTH_12_TO_256")
    return value


def password_hash(value):
    salt = secrets.token_bytes(16)
    with PASSWORD_HASH_SLOTS:
        digest = hashlib.scrypt(
            validate_password(value).encode(),
            salt=salt,
            n=32768,
            r=8,
            p=1,
            maxmem=64 * 1024 * 1024,
            dklen=32,
        )
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def password_matches(value, encoded):
    if type(value) is not str or len(value) > 256:
        return False
    try:
        algorithm, salt, expected = encoded.split("$")
        if algorithm != "scrypt":
            return False
        with PASSWORD_HASH_SLOTS:
            digest = hashlib.scrypt(
                value.encode(),
                salt=base64.b64decode(salt, validate=True),
                n=32768,
                r=8,
                p=1,
                maxmem=64 * 1024 * 1024,
                dklen=32,
            )
        return hmac.compare_digest(digest, base64.b64decode(expected, validate=True))
    except (ValueError, TypeError):
        return False


class LoginThrottle:
    """Bound peer/account guesses without letting one peer lock out another."""

    def __init__(self, clock=time.monotonic):
        self.clock, self.lock = clock, threading.Lock()
        self.attempts = defaultdict(deque)
        self.unknown_attempts = defaultdict(deque)
        self.pending = {}
        self._unknown_pending = set()
        self._key = secrets.token_bytes(32)

    def begin(self, peer, subject=None, *, known=True):
        identity = (
            ("peer\0" + peer + ("\0account\0" + subject if subject is not None else "\0credential"))
            if known
            else "unknown\0" + peer
        )
        key = hmac.new(self._key, identity.encode(), hashlib.sha256).hexdigest()
        now = self.clock()
        with self.lock:
            for bucket in (self.attempts, self.unknown_attempts):
                for old in tuple(bucket):
                    while bucket[old] and bucket[old][0] <= now - 60:
                        bucket[old].popleft()
                    if not bucket[old]:
                        del bucket[old]
            bucket = self.attempts if known else self.unknown_attempts
            active = list(self.pending.values())
            bucket_active = {
                value
                for ticket, value in self.pending.items()
                if (ticket in self._unknown_pending) == (not known)
            }
            failures = bucket.get(key, ())
            backoff = min(2.0, 0.05 * 2 ** min(len(failures) - 5, 6)) if len(failures) >= 5 else 0
            if (
                len(active) >= 8
                or active.count(key) >= (2 if known else 1)
                or (not known and self._unknown_pending)
                or len(failures) + active.count(key) >= (20 if known else 10)
                or (failures and now - failures[-1] < backoff)
            ):
                return None
            if (
                key not in bucket
                and key not in active
                and len(set(bucket) | bucket_active) >= (512 if known else 64)
            ):
                oldest = min(
                    (old for old in bucket if old not in active),
                    key=lambda old: bucket[old][-1],
                    default=None,
                )
                if oldest is None:
                    return None
                del bucket[oldest]
            ticket = object()
            self.pending[ticket] = key
            if not known:
                self._unknown_pending.add(ticket)
            return ticket

    def finish(self, ticket, *, failed=False, success=False):
        with self.lock:
            key = self.pending.pop(ticket)
            bucket = self.unknown_attempts if ticket in self._unknown_pending else self.attempts
            self._unknown_pending.discard(ticket)
            if success:
                bucket.pop(key, None)
            elif failed:
                bucket[key].append(self.clock())


class UserManager:
    def __init__(self, registry, *, bootstrap_password_file=None, bootstrap_password=None):
        self.registry, self.store = registry, registry.store
        self.password_throttle = LoginThrottle()
        self.bootstrap_password_file = (
            Path(bootstrap_password_file)
            if bootstrap_password_file
            else Path(self.store.path).parent / ".console-secrets" / "admin.password"
        )
        self._dummy_hash = password_hash(secrets.token_urlsafe(24))
        self._bootstrap(bootstrap_password)
        registry.users = self

    def _bootstrap(self, bootstrap_password=None):
        def action():
            db = self.store.database
            if db.execute(_queries.ACTION_SELECT_CONSOLE_USERS).fetchone():
                return
            principals = [
                json.loads(row[0])
                for row in db.execute(
                    _queries.ACTION_SELECT_REGISTRY_PRINCIPALS, (self.registry.identity.owner_id,)
                )
            ]
            principal = next(
                (
                    p
                    for p in principals
                    if p["role"] == "registry_admin"
                    and p["kind"] == "human"
                    and p["status"] == "active"
                ),
                None,
            )
            if not principal:
                raise RuntimeError(
                    "an existing active administrator is required for console bootstrap"
                )
            name = username(os.environ.get("EZLLMROUTER_ADMIN_USERNAME", DEFAULT_ADMIN_USERNAME))
            secret = bootstrap_password
            if secret is None:
                secret = secret_text(self.bootstrap_password_file, preserve=True)
            try:
                validate_password(secret)
            except UserError as exc:
                raise UserError("BOOTSTRAP_PASSWORD_REQUIRES_12_TO_256_CHARACTERS") from exc
            at = timestamp()
            db.execute(
                _queries.ACTION_INSERT_CONSOLE_USERS,
                (principal["principal_id"], name, password_hash(secret), 1, 1, at, at),
            )

        with self.registry.send_authority.gate:
            self.store.database.transaction(action)

    def _load(self, db, principal_id):
        row = db.execute(_queries.LOAD_SELECT_CONSOLE_USERS, (principal_id,)).fetchone()
        if not row:
            raise UserError("USER_NOT_FOUND", 404)
        return row, json.loads(row[6])

    @staticmethod
    def _public(row, principal):
        return {
            **{
                key: principal[key]
                for key in (
                    "principal_id",
                    "display_name",
                    "kind",
                    "owner",
                    "role",
                    "status",
                    "revision",
                )
            },
            "username": row[0],
            "must_change_password": bool(row[2]),
            "created_at": row[4],
            "updated_at": row[5],
            "permissions": list(ROLE_PERMISSIONS.get(principal["role"], ())),
        }

    def context(self, principal_id):
        with self.store.database.read():
            try:
                row, principal = self._load(self.store.database, principal_id)
            except UserError:
                return None
            if principal["status"] != "active":
                return None
            return {**self._public(row, principal), "auth_version": row[3]}

    def authenticate(self, name, password):
        try:
            name = username(name)
        except UserError:
            name = ""
        with self.store.database.read():
            row = self.store.database.execute(
                _queries.AUTHENTICATE_SELECT_CONSOLE_USERS, (name,)
            ).fetchone()
        matched = password_matches(password, row[1] if row else self._dummy_hash)
        context = self.context(row[0]) if row and matched else None
        if not context or context["auth_version"] != row[2]:
            raise UserError("AUTH_FAILED", 401)
        return context

    def has_username(self, name):
        with self.store.database.read():
            return (
                self.store.database.execute(
                    _queries.AUTHENTICATE_SELECT_CONSOLE_USERS, (name,)
                ).fetchone()
                is not None
            )

    def _admin(self, db, actor):
        if not authority.authorized(db, actor):
            raise UserError("ADMIN_REQUIRED", 403)

    def get(self, actor, principal_id):
        with self.store.database.read():
            self._admin(self.store.database, actor)
            return self._public(*self._load(self.store.database, principal_id))

    def list(self, actor):
        with self.store.database.read():
            self._admin(self.store.database, actor)
            ids = [
                row[0] for row in self.store.database.execute(_queries.LIST_SELECT_CONSOLE_USERS)
            ]
            users = [self._load(self.store.database, principal_id) for principal_id in ids]
            return {
                "items": [
                    self._public(row, principal)
                    for row, principal in users
                    if principal["status"] != "revoked"
                ],
                "roles": {key: list(value) for key, value in ROLE_PERMISSIONS.items()},
            }

    def validate_principal_change(
        self, db: Database, principal: Record, role: str, status: str
    ) -> None:
        if (
            principal["role"] != "registry_admin"
            or principal["status"] != "active"
            or (role == "registry_admin" and status == "active")
            or not db.execute(
                _queries.CONSOLE_USER_EXISTS,
                (principal["principal_id"],),
            ).fetchone()
        ):
            return
        count = cast(
            int,
            cast(
                tuple[object, ...],
                db.execute(_queries.VALIDATE_PRINCIPAL_CHANGE_SELECT_CONSOLE_USERS).fetchone(),
            )[0],
        )
        if count <= 1:
            raise UserError("LAST_ACTIVE_ADMIN", 409)

    def _save(self, db, actor, action, principal, old_revision):
        principal["revision"] = old_revision + 1
        db.execute(
            _queries.SAVE_INSERT_REGISTRY_PRINCIPALS, (principal["principal_id"], encode(principal))
        )
        revision = authority.record_change(
            db,
            actor=actor,
            action=action,
            subject=principal["principal_id"],
            old_revision=old_revision or None,
            new_revision=principal["revision"],
            at=timestamp(),
        )
        return revision

    def _write(self, actor, action, change, *, admin=True):
        with self.registry.send_authority.gate:

            def transaction():
                db = self.store.database
                if admin:
                    self._admin(db, actor)
                principal, old_revision = change(db)
                revision = self._save(db, actor, action, principal, old_revision)
                result = self._public(*self._load(db, principal["principal_id"]))
                return result, revision

            try:
                result, revision = self.store.database.transaction(transaction)
            except sqlite3.IntegrityError as exc:
                raise UserError("USERNAME_EXISTS", 409) from exc
            self.registry.send_authority.epoch = revision
            return result

    @staticmethod
    def _fields(data, required):
        if type(data) is not dict or set(data) != set(required):
            raise UserError("INVALID_USER_CHANGE")

    @staticmethod
    def _profile(data):
        name = username(data["username"])
        display = data["display_name"]
        if type(display) is not str or not display.strip() or len(display) > 160:
            raise UserError("INVALID_DISPLAY_NAME")
        if (
            type(data["role"]) is not str
            or data["role"] not in ROLE_PERMISSIONS
            or data["status"] not in ("active", "suspended")
        ):
            raise UserError("INVALID_ROLE_OR_STATUS")
        return name, display.strip()

    @staticmethod
    def _expected(data, principal):
        if (
            type(data["expected_revision"]) is not int
            or data["expected_revision"] != principal["revision"]
        ):
            raise UserError("USER_CONFLICT", 409)
        if principal["status"] == "revoked":
            raise UserError("USER_DELETED", 409)

    def create(self, actor, data):
        self._fields(data, ("username", "display_name", "role", "status", "password"))
        name, display = self._profile(data)
        hashed = password_hash(data["password"])

        def change(db):
            principal = {
                "principal_id": "user." + uuid.uuid4().hex,
                "display_name": display,
                "kind": "human",
                "owner": self.registry.identity.owner_id,
                "status": data["status"],
                "role": data["role"],
                "credential_state": "console_password",
                "record_origin": "operator_entered",
            }
            # Insert the principal before its referencing account in this transaction.
            principal["revision"] = 0
            db.execute(
                _queries.CHANGE_INSERT_REGISTRY_PRINCIPALS,
                (principal["principal_id"], encode(principal)),
            )
            at = timestamp()
            db.execute(
                _queries.ACTION_INSERT_CONSOLE_USERS,
                (principal["principal_id"], name, hashed, 1, 1, at, at),
            )
            return principal, 0

        return self._write(actor, "create_console_user", change)

    def update(self, actor, principal_id, data):
        self._fields(data, ("username", "display_name", "role", "status", "expected_revision"))
        name, display = self._profile(data)

        def change(db):
            row, principal = self._load(db, principal_id)
            self._expected(data, principal)
            self.validate_principal_change(db, principal, data["role"], data["status"])
            invalidate = (
                name != row[0]
                or data["role"] != principal["role"]
                or data["status"] != principal["status"]
            )
            revision = principal["revision"]
            principal.update(display_name=display, role=data["role"], status=data["status"])
            db.execute(
                _queries.CHANGE_UPDATE_CONSOLE_USERS,
                (name, int(invalidate), timestamp(), principal_id),
            )
            return principal, revision

        return self._write(actor, "update_console_user", change)

    def delete(self, actor, principal_id, data):
        self._fields(data, ("expected_revision",))

        def change(db):
            _, principal = self._load(db, principal_id)
            self._expected(data, principal)
            self.validate_principal_change(db, principal, principal["role"], "revoked")
            revision = principal["revision"]
            principal.update(status="revoked", state_reason="Administrator deleted console account")
            db.execute(
                _queries.UPDATE_PASSWORD_PRESERVING_STATE,
                (self._dummy_hash, timestamp(), principal_id),
            )
            db.execute(_queries.CHANGE_DELETE_REGISTRY_CREDENTIALS, (principal_id,))
            return principal, revision

        return self._write(actor, "delete_console_user", change)

    def reset_password(self, actor, principal_id, data):
        self._fields(data, ("password", "expected_revision"))
        with self.store.database.read():
            self._admin(self.store.database, actor)
            row, principal = self._load(self.store.database, principal_id)
            self._expected(data, principal)
            prior_hash, auth_version = row[1], row[3]
        if password_matches(data["password"], prior_hash):
            raise UserError("PASSWORD_MUST_DIFFER")
        hashed = password_hash(data["password"])

        def change(db):
            row, principal = self._load(db, principal_id)
            self._expected(data, principal)
            if row[3] != auth_version:
                raise UserError("USER_CONFLICT", 409)
            db.execute(
                _queries.RESET_PASSWORD_REQUIRING_CHANGE, (hashed, timestamp(), principal_id)
            )
            return principal, principal["revision"]

        return self._write(actor, "reset_console_password", change)

    def change_password(self, principal_id, data, *, peer="local"):
        self._fields(data, ("current_password", "new_password"))
        validate_password(data["new_password"])
        context = self.context(principal_id)
        if not context:
            raise UserError("AUTH_REQUIRED", 401)
        ticket = self.password_throttle.begin(peer, principal_id)
        if ticket is None:
            raise UserError("PASSWORD_RATE_LIMITED", 429)
        failed = False
        verified = False
        try:
            try:
                self.authenticate(context["username"], data["current_password"])
                verified = True
            except UserError as exc:
                failed = exc.status == 401
                raise UserError("CURRENT_PASSWORD_INCORRECT") from exc
        finally:
            self.password_throttle.finish(ticket, failed=failed, success=verified)
        if data["current_password"] == data["new_password"]:
            raise UserError("PASSWORD_MUST_DIFFER")
        hashed = password_hash(data["new_password"])

        def change(db):
            row, principal = self._load(db, principal_id)
            if principal["status"] != "active" or row[3] != context["auth_version"]:
                raise UserError("AUTH_REQUIRED", 401)
            db.execute(_queries.CHANGE_PASSWORD_COMPLETED, (hashed, timestamp(), principal_id))
            return principal, principal["revision"]

        return self._write(principal_id, "change_console_password", change, admin=False)
