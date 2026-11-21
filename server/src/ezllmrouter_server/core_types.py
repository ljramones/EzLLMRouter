"""Typed execution capabilities consumed by Coordinator steps."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, TypedDict
from collections.abc import Callable
from .database import Database
from .records import Record
from .wire_http.contracts import WorkService

Reply = tuple[int, Record]


class CampaignActions(Protocol):
    def check(self, attempt_id: str, revision: int) -> None: ...
    def reserve(
        self, db: Database, record: Record, messages_bytes: int, output_limit: int
    ) -> Record: ...
    def settle(
        self, attempt_id: str, usage: Record | None = None, *, before_transmit: bool = False
    ) -> None: ...


class AttributionBinder(Protocol):
    def bind(self, trusted: Record, req: Record, run_id: str | None) -> Record: ...


class RuntimeRegistry(Protocol):
    @property
    def personal_campaign(self) -> CampaignActions | None: ...
    @property
    def controlled_provider_proof(self) -> bool: ...
    @property
    def attribution(self) -> AttributionBinder: ...
    def principal(self, principal_id: str) -> Record | None: ...
    def authenticate(self, token: str, template: Record) -> Record: ...
    def admit(
        self,
        principal_id: str,
        ref: str,
        purpose: str,
        task_class: str,
        features: Sequence[str] = ("text",),
    ) -> tuple[Record, Record]: ...
    def check_current(
        self, principal_id: str, ref: str, purpose: str, task_class: str, decision: Record
    ) -> Record: ...


class PlanIssuer(Protocol):
    @property
    def policy(self) -> Record: ...
    def issue(
        self,
        projection: Record,
        work_digest: str,
        work_key: Record,
        classification: Record,
        retention: Record,
        /,
        decision_record_ref: str | None = None,
    ) -> Record: ...
    def verify(
        self, plan: Record, expected_digest: str, current_policy_version: str, /
    ) -> None: ...


class PreparationRecipe(Protocol):
    def expected(self, projected: Record, timeout_ms: int, /) -> tuple[bytes, Record]: ...


class SenderAdapter(Protocol):
    def prepare(self, body: Record, /) -> bytes: ...
    def describe(self, prepared: bytes, timeout_ms: int, config: Record, /) -> Record: ...


class DirectSenderAdapter(SenderAdapter, Protocol):
    def send(self, prepared: bytes, timeout_ms: int, expected_request: Record, /) -> Record: ...


class ContextSender(Protocol):
    def __call__(
        self, prepared: bytes, timeout_ms: int, expected_request: Record, context: Record, /
    ) -> Record: ...


class OwnedSuccessor(WorkService, Protocol):
    def close(self) -> None: ...


class Faults(TypedDict, total=False):
    mutate_after_binding: Callable[[bytes], bytes]
    reject_before_intent: bool


# Verify the concrete composition boundaries without importing them at runtime.
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .registry import Registry
    from .plans import PlanAuthority
    from .gateway.choice_b_sender import ChoiceBSenderAdapter

    def _registry_contract(value: Registry) -> RuntimeRegistry:
        return value

    def _authority_contract(value: PlanAuthority) -> PlanIssuer:
        return value

    def _sender_contract(value: ChoiceBSenderAdapter) -> SenderAdapter:
        return value

    def _context_sender_contract(value: ChoiceBSenderAdapter) -> ContextSender:
        return value.send_with_context
