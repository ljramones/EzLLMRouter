"""Minimal service interfaces required by the work HTTP surface."""

from __future__ import annotations

from typing import Any, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from ..registry import Registry
from ..records import Record


class WorkService(Protocol):
    def capabilities(self, trusted: Record) -> Record: ...
    def status(self, sid: str, trusted: Record) -> Record: ...
    def status_by_work(self, key: Record, trusted: Record) -> Record: ...
    def submit(
        self,
        request: object,
        trusted: Record,
        wait_ms: int = 1000,
        *,
        credential: str | None = None,
        run_id: str | None = None,
    ) -> tuple[int, Record]: ...


class WorkCoordinator(WorkService, Protocol):
    registry: Any
    successor: WorkService | None

    def authenticate(self, token: str) -> Record: ...


class RegistryCoordinator(Protocol):
    @property
    def registry(self) -> Registry: ...
