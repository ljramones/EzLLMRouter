"""Resumable local service identities with private tokens saved before binding."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .private_files import read_private, secret_text
from .registry import Registry, RegistryConflict


class BootstrapError(ValueError):
    """Startup cannot safely reconcile an identity with its saved credential."""


@dataclass(frozen=True)
class ServiceIdentity:
    principal_id: str
    display_name: str
    token_file: str
    operation_prefix: str
    reason: str


SERVICES = (
    ServiceIdentity(
        "svc.integration",
        "External integration sender",
        "ingest.token",
        "op.integration.bootstrap",
        "isolated local integration",
    ),
    ServiceIdentity(
        "svc.vega.credential-consumer",
        "Vega credential consumer",
        "consumer.token",
        "op.integration.consumer",
        "local credential consumer",
    ),
)


def _read_token(path: Path) -> str:
    try:
        token = read_private(path).decode("ascii").strip()
        if not 32 <= len(token) <= 4096 or any(not 33 <= ord(char) <= 126 for char in token):
            raise ValueError("invalid credential")
        return token
    except FileNotFoundError:
        raise BootstrapError(
            f"{path.name} is missing; restore the original private token file"
        ) from None
    except (OSError, ValueError, UnicodeError):
        raise BootstrapError(
            f"{path.name} must be an owner-only regular file containing a valid token"
        ) from None


def ensure_services(registry: Registry, directory: Path) -> None:
    """Complete only unfinished bootstrap; preserve existing tokens and account states.

    A private file can survive a rolled-back credential transaction and is reused
    on retry. A bound identity requires its matching file: losing an already used
    credential requires restoration, never an implicit rotation at startup.
    """
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_mode & 0o077:
        raise BootstrapError("secrets directory must be owner-only and must not be a symlink")
    with registry.send_authority.gate:
        for service in SERVICES:
            try:
                _ensure_service(registry, directory, service)
            except RegistryConflict as exc:
                raise BootstrapError(
                    f"{service.principal_id} conflicts with the saved bootstrap operation; inspect its account state"
                ) from exc


def _ensure_service(registry: Registry, directory: Path, service: ServiceIdentity) -> None:
    path = directory / service.token_file
    principal = registry.principal(service.principal_id)
    if path.exists() or path.is_symlink():
        _read_token(path)  # Reject unsafe existing files before any account change.
    if principal and principal["credential_state"] == "bound":
        token = _read_token(path)
        if not registry.credential_bound_to(service.principal_id, token):
            raise BootstrapError(
                f"{path.name} does not match the database; restore its original token file"
            )
        if principal["status"] != "inactive" or principal["revision"] != 2:
            return  # A suspended/revoked account must stay disabled across restart.
    else:
        if principal and (principal["status"] != "inactive" or principal["revision"] != 1):
            raise BootstrapError(f"{service.principal_id} has an unexpected bootstrap state")
        # Replaying the original command proves this is our unfinished account,
        # rather than an unrelated identity using a reserved bootstrap name.
        registry.mutate(
            "owner.local",
            {
                "operation_id": service.operation_prefix + ".principal",
                "action": "create_principal",
                "subject": service.principal_id,
                "expected_revision": 0,
                "data": {
                    "display_name": service.display_name,
                    "kind": "service",
                    "owner": "owner.local",
                    "role": "ordinary",
                },
            },
        )
    # For an already-bound inactive identity, this must replay the committed
    # operation; its old expected revision prevents accidental replacement.
    registry.provision_credential(
        "owner.local",
        service.principal_id,
        1,
        service.operation_prefix + ".credential",
        secret_factory=lambda: secret_text(path),
    )
    token = _read_token(path)
    if not registry.credential_bound_to(service.principal_id, token):
        raise BootstrapError(
            f"{path.name} does not match the database; restore its original token file"
        )
    registry.mutate(
        "owner.local",
        {
            "operation_id": service.operation_prefix + ".activate",
            "action": "principal_state",
            "subject": service.principal_id,
            "expected_revision": 2,
            "data": {"status": "active", "reason": service.reason},
        },
    )
