"""Typed capabilities shared by Registry domain operations."""

from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol


class RegistryAuthority(Protocol):
    epoch: int

    @property
    def gate(self) -> AbstractContextManager[object]: ...


class CredentialVault(Protocol):
    def request_digest(self, value: bytes) -> str: ...
    def seal(
        self, connection_id: str, version: int, secret: str, *, committed_version: int | None = None
    ) -> Path: ...
    def resolve(self, connection_id: str, version: int) -> str: ...
    def remove(self, connection_id: str, version: int) -> None: ...
