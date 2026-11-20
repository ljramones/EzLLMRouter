"""Explicit instance identity defaults; persisted identities are never renamed."""

from dataclasses import dataclass

from .identifiers import require_identifier


@dataclass(frozen=True)
class InstanceIdentity:
    owner_id: str = "owner.local"
    task_class: str = "class.demo"
    credential_consumer_id: str = "svc.vega.credential-consumer"
    credential_release_purpose: str = "vega-provider-dispatch"

    def __post_init__(self) -> None:
        for value in (
            self.owner_id,
            self.task_class,
            self.credential_consumer_id,
            self.credential_release_purpose,
        ):
            require_identifier(value)
        if self.owner_id == self.credential_consumer_id:
            raise ValueError("owner and credential consumer must be distinct identities")


DEFAULT_IDENTITY = InstanceIdentity()
