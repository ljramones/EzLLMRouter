"""Service-volume outbound secret store. Nothing in this module is mounted in the worker."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class ProviderVault:
    def __init__(self, root, *, require_existing=False):
        self.root = Path(root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.stat().st_mode & 0o077:
            raise RuntimeError("provider vault permissions")
        self.key_path = self.root / "master.key"
        if not self.key_path.exists():
            # A missing master key beside sealed credentials is a recovery
            # failure, not a fresh installation. Never mint a replacement key.
            if require_existing or any(self.root.glob("*.sealed")):
                raise RuntimeError("provider master key unavailable")
            try:
                fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, "wb") as file:
                    file.write(secrets.token_bytes(32))
                    file.flush()
                    os.fsync(file.fileno())
        if self.key_path.stat().st_mode & 0o077:
            raise RuntimeError("provider key permissions")
        self.key = self.key_path.read_bytes()
        if len(self.key) != 32:
            raise RuntimeError("provider master key unavailable")

    def _path(self, connection_id, version):
        name = hashlib.sha256(connection_id.encode()).hexdigest() + f".{version}.sealed"
        return self.root / name

    def seal(self, connection_id, version, secret):
        if type(secret) is not str or not 16 <= len(secret) <= 4096 or any(ord(c) < 33 or ord(c) > 126 for c in secret):
            raise ValueError("invalid outbound credential")
        nonce = secrets.token_bytes(12)
        bound = f"{connection_id}:{version}".encode()
        ciphertext = nonce + AESGCM(self.key).encrypt(nonce, secret.encode(), bound)
        path = self._path(connection_id, version)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as file:
            file.write(ciphertext)
            file.flush()
            os.fsync(file.fileno())
        return path

    def resolve(self, connection_id, version):
        path = self._path(connection_id, version)
        if path.stat().st_mode & 0o077:
            raise RuntimeError("provider credential permissions")
        content = path.read_bytes()
        if len(content) < 29:
            raise RuntimeError("provider credential unavailable")
        return AESGCM(self.key).decrypt(content[:12], content[12:],
                                       f"{connection_id}:{version}".encode()).decode()

    def remove(self, connection_id, version):
        if version:
            self._path(connection_id, version).unlink(missing_ok=True)
