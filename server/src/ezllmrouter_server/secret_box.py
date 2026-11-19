"""Purpose-bound AES-GCM envelopes and durable, append-only key history.

Publish a new write key before rewriting any ciphertext. Retaining every old
key makes an interrupted rotation readable and resumable across processes.
"""
from __future__ import annotations

from contextlib import contextmanager
import base64
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import stat

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .private_files import read_private, write_private


class SecretBoxError(RuntimeError):
    pass


def validate_secret(value):
    if (type(value) is not str or not 16 <= len(value) <= 4096 or
            any(not 33 <= ord(char) <= 126 for char in value)):
        raise ValueError("invalid credential")


def private_directory(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise SecretBoxError("SECRET_DIRECTORY_PERMISSIONS")


def _unique(pairs):
    value = {}
    for name, item in pairs:
        if name in value:
            raise SecretBoxError("SECRET_KEYRING_INVALID")
        value[name] = item
    return value


def decode_envelope(raw):
    try:
        envelope = json.loads(raw, object_pairs_hook=_unique)
        if (type(envelope) is not dict or set(envelope) !=
                {"version", "purpose", "key_id", "nonce", "ciphertext"} or
                type(envelope["version"]) is not int or envelope["version"] != 1 or
                type(envelope["key_id"]) is not str):
            raise ValueError()
        return envelope
    except (ValueError, TypeError) as exc:
        raise SecretBoxError("SECRET_ENVELOPE_INVALID") from exc


class SecretBox:
    def __init__(self, path, purpose, *, required_ids=(), required=False):
        self.path, self.purpose = Path(path), purpose
        private_directory(self.path.parent)
        with self._locked():
            if not self.path.exists():
                if required or required_ids:
                    raise SecretBoxError("SECRET_KEYRING_MISSING")
                key = secrets.token_bytes(32)
                identifier = self._identifier(key)
                self._write({"version": 1, "purpose": purpose, "active_key_id": identifier,
                             "mac_key": base64.b64encode(secrets.token_bytes(32)).decode("ascii"),
                             "keys": {identifier: base64.b64encode(key).decode("ascii")}})
            state = self._read()
            if not set(required_ids) <= state["keys"].keys():
                raise SecretBoxError("SECRET_KEY_UNAVAILABLE")

    def _identifier(self, key):
        return "key." + hashlib.sha256(self.purpose.encode() + b"\0" + key).hexdigest()[:32]

    @contextmanager
    def _locked(self):
        descriptor = os.open(self.path.with_name(self.path.name + ".lock"),
                             os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
                raise SecretBoxError("SECRET_KEYRING_LOCK_PERMISSIONS")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            os.close(descriptor)

    def _read(self):
        try:
            state = json.loads(read_private(self.path, limit=1024 * 1024), object_pairs_hook=_unique)
            if (type(state) is not dict or set(state) !=
                    {"version", "purpose", "active_key_id", "mac_key", "keys"} or
                    type(state["version"]) is not int or state["version"] != 1 or
                    state["purpose"] != self.purpose or type(state["keys"]) is not dict or
                    state["active_key_id"] not in state["keys"]):
                raise ValueError()
            if len(base64.b64decode(state["mac_key"], validate=True)) != 32:
                raise ValueError()
            for identifier, encoded in state["keys"].items():
                key = base64.b64decode(encoded, validate=True)
                if len(key) != 32 or identifier != self._identifier(key):
                    raise ValueError()
            return state
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise SecretBoxError("SECRET_KEYRING_UNAVAILABLE") from exc

    def _write(self, state):
        content = (json.dumps(state, sort_keys=True) + "\n").encode()
        if len(content) > 1024 * 1024:
            raise SecretBoxError("SECRET_KEYRING_CAPACITY")
        write_private(self.path, content, replace=self.path.exists())

    @property
    def active_id(self):
        with self._locked():
            return self._read()["active_key_id"]

    @property
    def identity(self):
        with self._locked():
            key = base64.b64decode(self._read()["mac_key"], validate=True)
        return "ring." + hashlib.sha256(self.purpose.encode() + b"\0" + key).hexdigest()[:32]

    def request_digest(self, value):
        """Idempotency has its own key; rotating encryption preserves request identity."""
        with self._locked():
            key = base64.b64decode(self._read()["mac_key"], validate=True)
        return hmac.new(key, self.purpose.encode() + b"\0" + value, hashlib.sha256).hexdigest()

    def rotate(self):
        with self._locked():
            state = self._read()
            key = secrets.token_bytes(32)
            identifier = self._identifier(key)
            state["keys"][identifier] = base64.b64encode(key).decode("ascii")
            state["active_key_id"] = identifier
            self._write(state)
            return identifier

    def _aad(self, context, identifier):
        return json.dumps({"version": 1, "purpose": self.purpose, "key_id": identifier,
                           "context": base64.b64encode(context).decode("ascii")},
                          sort_keys=True, separators=(",", ":")).encode()

    def seal_parts(self, value, context):
        validate_secret(value)
        with self._locked():
            state = self._read()
            identifier = state["active_key_id"]
            key = base64.b64decode(state["keys"][identifier], validate=True)
        nonce = secrets.token_bytes(12)
        return identifier, nonce, AESGCM(key).encrypt(nonce, value.encode(), self._aad(context, identifier))

    def open_parts(self, identifier, nonce, ciphertext, context):
        try:
            if (type(identifier) is not str or type(nonce) is not bytes or len(nonce) != 12 or
                    type(ciphertext) is not bytes or not 32 <= len(ciphertext) <= 4112):
                raise ValueError()
            with self._locked():
                key = base64.b64decode(self._read()["keys"][identifier], validate=True)
            value = AESGCM(key).decrypt(nonce, ciphertext, self._aad(context, identifier)).decode()
            validate_secret(value)
            return value
        except Exception as exc:
            raise SecretBoxError("SECRET_DECRYPT_FAILED") from exc

    def seal(self, value, context):
        identifier, nonce, ciphertext = self.seal_parts(value, context)
        return {"version": 1, "purpose": self.purpose, "key_id": identifier,
                "nonce": base64.b64encode(nonce).decode("ascii"),
                "ciphertext": base64.b64encode(ciphertext).decode("ascii")}

    def open(self, envelope, context):
        try:
            if (type(envelope) is not dict or set(envelope) !=
                    {"version", "purpose", "key_id", "nonce", "ciphertext"} or
                    type(envelope["version"]) is not int or envelope["version"] != 1 or
                    envelope["purpose"] != self.purpose):
                raise ValueError()
            return self.open_parts(envelope["key_id"], base64.b64decode(envelope["nonce"], validate=True),
                                   base64.b64decode(envelope["ciphertext"], validate=True), context)
        except Exception as exc:
            raise SecretBoxError("SECRET_DECRYPT_FAILED") from exc
