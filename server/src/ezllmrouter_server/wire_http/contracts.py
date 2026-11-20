"""Minimal service interfaces required by the work HTTP surface."""

from typing import Any, Protocol
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
