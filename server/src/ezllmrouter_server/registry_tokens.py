"""Registry registry_tokens operations; caller owns the existing authority context."""

from __future__ import annotations

import hashlib
import secrets
import time
from copy import deepcopy


def _prune_operator_tokens(self, at):
    # Caller owns the memory lock; never wait for the database while holding it.
    for verifier, (_, expiry) in tuple(self._operator_tokens.items()):
        if expiry <= at:
            self._operator_tokens.pop(verifier, None)


def issue_local_operator_token(self, principal_id):
    """Server-only wire credential for one authenticated loopback session."""
    principal = self.principal(principal_id)
    if not principal or principal["status"] != "active" or principal["role"] != "registry_admin":
        raise PermissionError("ADMIN_REQUIRED")
    token = secrets.token_urlsafe(48)
    with self._token_lock:
        self._prune_operator_tokens(time.monotonic())
        if len(self._operator_tokens) >= 4096:
            raise RuntimeError("operator credential capacity exhausted")
        self._operator_tokens[hashlib.sha256(token.encode()).hexdigest()] = (
            principal_id,
            time.monotonic() + 1800,
        )
    return token


def revoke_local_operator_token(self, token: str) -> None:
    with self._token_lock:
        self._operator_tokens.pop(hashlib.sha256(token.encode()).hexdigest(), None)


def authenticate(self, token, template):
    principal = self.credential_principal(token)
    trusted = deepcopy(template)
    trusted["principal_id"] = principal["principal_id"]
    trusted["charging_owner_id"] = principal["owner"]
    return trusted
