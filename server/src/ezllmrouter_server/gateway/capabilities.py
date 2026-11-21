"""Capabilities at the owned sender's revocation and response-body boundaries."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractContextManager
from typing import Protocol


class SendAuthority(Protocol):
    @property
    def gate(self) -> AbstractContextManager[object]: ...
    @property
    def revoked(self) -> bool: ...
    @property
    def epoch(self) -> int: ...
    def snapshot_epoch(self) -> int: ...


class AsyncResponseBody(Protocol):
    def __aiter__(self) -> AsyncIterator[bytes]: ...
    async def aclose(self) -> None: ...
