"""Persistent console accounts tied to the existing permission registry."""
from __future__ import annotations

from collections import defaultdict, deque
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
import uuid

from .registry import timestamp
from .store import encode
from .private_files import secret_text


DEFAULT_ADMIN_USERNAME = "admin"
PASSWORD_HASH_SLOTS = threading.BoundedSemaphore(2)
ROLE_PERMISSIONS = {
    "ordinary": ("activity.read_own", "models.read_allowed", "models.use_granted"),
    "read_only_operator": ("activity.read_all", "reports.read_all", "registry.read", "settings.read"),
    "registry_admin": ("activity.read_all", "reports.read_all", "registry.read", "settings.read",
                       "users.manage", "registry.manage", "connections.manage"),
}
USERNAME = re.compile(r"[a-z0-9][a-z0-9_.-]{2,63}\Z")


class UserError(ValueError):
    def __init__(self, code, status=400):
        super().__init__(code)
        self.code, self.status = code, status


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
        digest = hashlib.scrypt(validate_password(value).encode(), salt=salt,
                                n=32768, r=8, p=1, maxmem=64 * 1024 * 1024, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def password_matches(value, encoded):
    if type(value) is not str or len(value) > 256:
        return False
    try:
        algorithm, salt, expected = encoded.split("$")
        if algorithm != "scrypt":
            return False
        with PASSWORD_HASH_SLOTS:
            digest = hashlib.scrypt(value.encode(), salt=base64.b64decode(salt, validate=True),
                                    n=32768, r=8, p=1, maxmem=64 * 1024 * 1024, dklen=32)
        return hmac.compare_digest(digest, base64.b64decode(expected, validate=True))
    except (ValueError, TypeError):
        return False


class LoginThrottle:
    """Bound hashing work per client without permanently locking an account."""
    def __init__(self, clock=time.monotonic):
        self.clock, self.lock = clock, threading.Lock()
        self.attempts = defaultdict(deque)

    def allow(self, peer):
        now = self.clock()
        with self.lock:
            for key in tuple(self.attempts):
                while self.attempts[key] and self.attempts[key][0] <= now - 60:
                    self.attempts[key].popleft()
                if not self.attempts[key]:
                    del self.attempts[key]
            if peer not in self.attempts and len(self.attempts) >= 512:
                return False
            attempts = self.attempts[peer]
            if len(attempts) >= 20:
                return False
            attempts.append(now)
            return True


class UserManager:
    def __init__(self, registry, *, bootstrap_password_file=None):
        self.registry, self.store = registry, registry.store
        self.bootstrap_password_file = (Path(bootstrap_password_file) if bootstrap_password_file else
                                        Path(self.store.path).parent / ".console-secrets" / "admin.password")
        self._dummy_hash = password_hash(secrets.token_urlsafe(24))
        with self.store._lock:
            self.store.db.executescript("""
                CREATE TABLE IF NOT EXISTS console_users (
                    principal_id TEXT PRIMARY KEY REFERENCES registry_principals(id),
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    must_change_password INTEGER NOT NULL,
                    auth_version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)
        self._bootstrap()
        registry.users = self

    def _bootstrap(self):
        def action():
            db = self.store.db
            if db.execute("SELECT 1 FROM console_users LIMIT 1").fetchone():
                return
            principals = [json.loads(row[0]) for row in db.execute(
                "SELECT record FROM registry_principals ORDER BY id='owner.local' DESC,id")]
            principal = next((p for p in principals if p["role"] == "registry_admin" and
                              p["kind"] == "human" and p["status"] == "active"), None)
            if not principal:
                raise RuntimeError("an existing active administrator is required for console bootstrap")
            name = username(os.environ.get("EZLLMROUTER_ADMIN_USERNAME", DEFAULT_ADMIN_USERNAME))
            secret = os.environ.get("EZLLMROUTER_ADMIN_PASSWORD")
            if secret is None:
                secret = secret_text(self.bootstrap_password_file)
            try:
                validate_password(secret)
            except UserError as exc:
                raise UserError("BOOTSTRAP_PASSWORD_REQUIRES_12_TO_256_CHARACTERS") from exc
            at = timestamp()
            db.execute("INSERT INTO console_users VALUES (?,?,?,?,?,?,?)",
                       (principal["principal_id"], name, password_hash(secret), 1, 1, at, at))
        with self.registry.send_authority.gate:
            self.store._transaction(action)

    def _load(self, db, principal_id):
        row = db.execute("SELECT u.username,u.password_hash,u.must_change_password,u.auth_version,"
                         "u.created_at,u.updated_at,p.record FROM console_users u "
                         "JOIN registry_principals p ON p.id=u.principal_id WHERE u.principal_id=?",
                         (principal_id,)).fetchone()
        if not row:
            raise UserError("USER_NOT_FOUND", 404)
        return row, json.loads(row[6])

    @staticmethod
    def _public(row, principal):
        return {**{key: principal[key] for key in
                   ("principal_id", "display_name", "kind", "owner", "role", "status", "revision")},
                "username": row[0], "must_change_password": bool(row[2]),
                "created_at": row[4], "updated_at": row[5],
                "permissions": list(ROLE_PERMISSIONS.get(principal["role"], ()))}

    def context(self, principal_id):
        with self.store._lock:
            try:
                row, principal = self._load(self.store.db, principal_id)
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
        with self.store._lock:
            row = self.store.db.execute("SELECT principal_id,password_hash,auth_version FROM console_users "
                                        "WHERE username=?", (name,)).fetchone()
        matched = password_matches(password, row[1] if row else self._dummy_hash)
        context = self.context(row[0]) if row and matched else None
        if not context or context["auth_version"] != row[2]:
            raise UserError("AUTH_FAILED", 401)
        return context

    def _admin(self, db, actor):
        row = db.execute("SELECT record FROM registry_principals WHERE id=?", (actor,)).fetchone()
        principal = json.loads(row[0]) if row else None
        if not principal or principal["status"] != "active" or principal["role"] != "registry_admin":
            raise UserError("ADMIN_REQUIRED", 403)

    def get(self, actor, principal_id):
        with self.store._lock:
            self._admin(self.store.db, actor)
            return self._public(*self._load(self.store.db, principal_id))

    def list(self, actor):
        with self.store._lock:
            self._admin(self.store.db, actor)
            ids = [row[0] for row in self.store.db.execute("SELECT principal_id FROM console_users ORDER BY username")]
            users = [self._load(self.store.db, principal_id) for principal_id in ids]
            return {"items": [self._public(row, principal) for row, principal in users if principal["status"] != "revoked"],
                    "roles": {key: list(value) for key, value in ROLE_PERMISSIONS.items()}}

    def validate_principal_change(self, db, principal, role, status):
        if (principal["role"] != "registry_admin" or principal["status"] != "active" or
                (role == "registry_admin" and status == "active") or
                not db.execute("SELECT 1 FROM console_users WHERE principal_id=?",
                               (principal["principal_id"],)).fetchone()):
            return
        count = db.execute("SELECT COUNT(*) FROM console_users u JOIN registry_principals p ON p.id=u.principal_id "
                           "WHERE json_extract(p.record,'$.role')='registry_admin' "
                           "AND json_extract(p.record,'$.status')='active'").fetchone()[0]
        if count <= 1:
            raise UserError("LAST_ACTIVE_ADMIN", 409)

    def _save(self, db, actor, action, principal, old_revision):
        principal["revision"] = old_revision + 1
        db.execute("INSERT INTO registry_principals VALUES (?,?) ON CONFLICT(id) DO UPDATE SET record=excluded.record",
                   (principal["principal_id"], encode(principal)))
        revision = int(db.execute("SELECT value FROM registry_meta WHERE key='authority_revision'").fetchone()[0]) + 1
        db.execute("UPDATE registry_meta SET value=? WHERE key='authority_revision'", (str(revision),))
        db.execute("INSERT INTO registry_audit (actor,action,subject,old_revision,new_revision,authority_revision,at) "
                   "VALUES (?,?,?,?,?,?,?)", (actor, action, principal["principal_id"], old_revision or None,
                                             principal["revision"], revision, timestamp()))
        return revision

    def _write(self, actor, action, change, *, admin=True):
        with self.registry.send_authority.gate:
            def transaction():
                db = self.store.db
                if admin:
                    self._admin(db, actor)
                principal, old_revision = change(db)
                revision = self._save(db, actor, action, principal, old_revision)
                result = self._public(*self._load(db, principal["principal_id"]))
                return result, revision
            try:
                result, revision = self.store._transaction(transaction)
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
        if type(data["role"]) is not str or data["role"] not in ROLE_PERMISSIONS or data["status"] not in ("active", "suspended"):
            raise UserError("INVALID_ROLE_OR_STATUS")
        return name, display.strip()

    @staticmethod
    def _expected(data, principal):
        if type(data["expected_revision"]) is not int or data["expected_revision"] != principal["revision"]:
            raise UserError("USER_CONFLICT", 409)
        if principal["status"] == "revoked":
            raise UserError("USER_DELETED", 409)

    def create(self, actor, data):
        self._fields(data, ("username", "display_name", "role", "status", "password"))
        name, display = self._profile(data)
        hashed = password_hash(data["password"])
        def change(db):
            principal = {"principal_id": "user." + uuid.uuid4().hex, "display_name": display,
                         "kind": "human", "owner": "owner.local", "status": data["status"],
                         "role": data["role"], "credential_state": "console_password",
                         "record_origin": "operator_entered"}
            # Insert the principal before its referencing account in this transaction.
            principal["revision"] = 0
            db.execute("INSERT INTO registry_principals VALUES (?,?)", (principal["principal_id"], encode(principal)))
            at = timestamp()
            db.execute("INSERT INTO console_users VALUES (?,?,?,?,?,?,?)",
                       (principal["principal_id"], name, hashed, 1, 1, at, at))
            return principal, 0
        return self._write(actor, "create_console_user", change)

    def update(self, actor, principal_id, data):
        self._fields(data, ("username", "display_name", "role", "status", "expected_revision"))
        name, display = self._profile(data)
        def change(db):
            row, principal = self._load(db, principal_id)
            self._expected(data, principal)
            self.validate_principal_change(db, principal, data["role"], data["status"])
            invalidate = name != row[0] or data["role"] != principal["role"] or data["status"] != principal["status"]
            revision = principal["revision"]
            principal.update(display_name=display, role=data["role"], status=data["status"])
            db.execute("UPDATE console_users SET username=?,auth_version=auth_version+?,updated_at=? WHERE principal_id=?",
                       (name, int(invalidate), timestamp(), principal_id))
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
            db.execute("UPDATE console_users SET password_hash=?,auth_version=auth_version+1,updated_at=? WHERE principal_id=?",
                       (self._dummy_hash, timestamp(), principal_id))
            db.execute("DELETE FROM registry_credentials WHERE principal_id=?", (principal_id,))
            return principal, revision
        return self._write(actor, "delete_console_user", change)

    def reset_password(self, actor, principal_id, data):
        self._fields(data, ("password", "expected_revision"))
        hashed = password_hash(data["password"])
        def change(db):
            row, principal = self._load(db, principal_id)
            self._expected(data, principal)
            if password_matches(data["password"], row[1]):
                raise UserError("PASSWORD_MUST_DIFFER")
            db.execute("UPDATE console_users SET password_hash=?,must_change_password=1,"
                       "auth_version=auth_version+1,updated_at=? WHERE principal_id=?",
                       (hashed, timestamp(), principal_id))
            return principal, principal["revision"]
        return self._write(actor, "reset_console_password", change)

    def change_password(self, principal_id, data):
        self._fields(data, ("current_password", "new_password"))
        validate_password(data["new_password"])
        context = self.context(principal_id)
        if not context:
            raise UserError("AUTH_REQUIRED", 401)
        try:
            self.authenticate(context["username"], data["current_password"])
        except UserError as exc:
            raise UserError("CURRENT_PASSWORD_INCORRECT") from exc
        if data["current_password"] == data["new_password"]:
            raise UserError("PASSWORD_MUST_DIFFER")
        hashed = password_hash(data["new_password"])
        def change(db):
            row, principal = self._load(db, principal_id)
            if principal["status"] != "active" or row[3] != context["auth_version"]:
                raise UserError("AUTH_REQUIRED", 401)
            db.execute("UPDATE console_users SET password_hash=?,must_change_password=0,"
                       "auth_version=auth_version+1,updated_at=? WHERE principal_id=?",
                       (hashed, timestamp(), principal_id))
            return principal, principal["revision"]
        return self._write(principal_id, "change_console_password", change, admin=False)
