"""Registry registry_credentials operations; caller owns the existing authority context."""

from __future__ import annotations

from typing import cast
from .database import Row

from collections.abc import Callable
from typing import TYPE_CHECKING
from .database import Database
from .records import Record
from .store import decode_record

if TYPE_CHECKING:
    from .registry import Registry

import hashlib
import secrets
import time
from datetime import datetime, timedelta, timezone
from .errors import RegistryConflict
from .formatting import utc_timestamp
from .identifiers import require_text as nonempty
from .repositories import authority
from .repositories import registry as _queries
from .canonical import ContractError
from .provider_adapters import ADAPTERS
from .store import encode
from .registry_values import timestamp, identifier
from .registry_context import CredentialVault


def set_provider_credential(
    self: Registry,
    actor: str,
    connection_id: str,
    expected_revision: int,
    operation_id: str,
    mode: str,
    secret: str | None = None,
) -> Record:
    """Rotate/remove under the same first-write gate as registry authority mutations."""
    digest = _credential_request_digest(
        self, connection_id, expected_revision, operation_id, mode, secret
    )
    with self.send_authority.gate:
        db = self.store.database
        with self.store.database.read():
            self._require_admin(db, actor)
            prior = db.execute(
                _queries.SET_PROVIDER_CREDENTIAL_SELECT_REGISTRY_OPERATIONS, (operation_id,)
            ).fetchone()
            if prior:
                if prior[0] != actor or prior[1] != digest:
                    raise RegistryConflict("operation reuse conflict")
                reply = decode_record(prior[2])
            else:
                row = db.execute(
                    _queries.APPLY_SELECT_REGISTRY_CONNECTIONS, (connection_id,)
                ).fetchone()
                record = decode_record(row[0]) if row else None
                if (
                    not record
                    or record["revision"] != expected_revision
                    or record["status"] == "archived"
                ):
                    raise RegistryConflict("connection revision changed")
                old_version = record["credential_version"]
                next_version = old_version + 1
        if prior:
            self.send_authority.epoch = self.version()
            cast(CredentialVault, self.provider_vault).remove(
                connection_id, reply["record"]["credential_version"] - 1
            )
            return reply
        if mode == "replace":
            cast(CredentialVault, self.provider_vault).seal(
                connection_id, next_version, cast(str, secret), committed_version=old_version
            )
        try:

            def action() -> tuple[Record, int]:
                return _publish_provider_credential(
                    self,
                    db,
                    actor,
                    connection_id,
                    expected_revision,
                    operation_id,
                    mode,
                    next_version,
                    digest,
                    cast(Record, record),
                )

            reply, revision = self.store.database.transaction(action)
        except BaseException:
            # COMMIT may have succeeded even if its acknowledgement failed.
            # Retain the staged file; a later authorized retry can overwrite
            # it only while it is strictly ahead of the committed version.
            raise
        self.send_authority.epoch = revision
        cast(CredentialVault, self.provider_vault).remove(connection_id, old_version)
        return reply


def probe_connection(
    self: Registry,
    actor: str,
    connection_id: str,
    expected_revision: int,
    operation_id: str,
    operation: str,
) -> Record:
    from . import registry as _registry

    identifier(connection_id)
    identifier(operation_id)
    if operation not in ("access", "inventory", "readiness") or type(expected_revision) is not int:
        raise ValueError("invalid probe request")
    # Serialize probes, including duplicate operation IDs, without holding the send gate
    # over DNS, TLS or provider waits.
    with self._probe_lock:
        with self.store.database.read():
            self._require_admin(self.store.database, actor)
            old = self.store.database.execute(
                _queries.PROBE_CONNECTION_SELECT_REGISTRY_OBSERVATIONS, (operation_id,)
            ).fetchone()
            if old:
                saved = decode_record(old[0])
                if saved["connection_id"] != connection_id or saved["operation"] != operation:
                    raise RegistryConflict("probe operation reuse conflict")
                return saved
            connection = self.connection(connection_id)
            if (
                not connection
                or connection["revision"] != expected_revision
                or connection["status"] in ("disabled", "archived")
            ):
                raise RegistryConflict("connection unavailable or changed")
        spec = ADAPTERS[connection["adapter_id"]].get(operation)
        if spec is None:
            result = {
                "state": "unsupported",
                "reason": "operation_not_implemented",
                "models": [],
            }
        elif connection["credential_state"] != "present" and operation in (
            "access",
            "inventory",
        ):
            result = {"state": "failed", "reason": "credential_unavailable", "models": []}
        else:
            try:
                credential = (
                    cast(CredentialVault, self.provider_vault).resolve(
                        connection_id, connection["credential_version"]
                    )
                    if operation in ("access", "inventory")
                    else None
                )
            except (OSError, RuntimeError, ValueError):
                result = {"state": "failed", "reason": "credential_unavailable", "models": []}
            else:
                result = _registry.provider_probe(
                    connection["adapter_id"],
                    connection["settings"],
                    credential,
                    operation,
                    controlled=self.controlled_provider_proof,
                )
        observation = _probe_observation(operation_id, connection_id, connection, operation, result)
        current = cast(Record, self.connection(connection_id))
        if current["revision"] != connection["revision"]:
            observation.update(state="stale", reason="connection_changed_during_probe", models=[])

        def save() -> None:
            self.store.database.execute(
                _queries.SAVE_INSERT_REGISTRY_OBSERVATIONS,
                (operation_id, connection_id, encode(observation)),
            )
            self.store.database.execute(_queries.PRUNE_CONNECTION_OBSERVATIONS, (connection_id,))

        self.store.database.transaction(save)
        return observation


def credential_principal(self: Registry, token: str, kind: str | None = None) -> Record:
    if type(token) is not str or len(token) < 32:
        raise ContractError("AUTHENTICATION_FAILED", 401)
    verifier = hashlib.sha256(token.encode()).hexdigest()
    with self._token_lock:
        self._prune_operator_tokens(time.monotonic())
        ephemeral = self._operator_tokens.get(verifier)
    if ephemeral:
        principal = self.principal(ephemeral[0])
        with self._token_lock:
            current = self._operator_tokens.get(verifier)
            valid = current is ephemeral and current[1] > time.monotonic()
        if (
            valid
            and principal
            and principal["status"] == "active"
            and (not kind or principal["kind"] == kind)
        ):
            return principal
    with self.store.database.read():
        row = self.store.database.execute(
            _queries.CREDENTIAL_PRINCIPAL_SELECT_REGISTRY_CREDENTIALS, (verifier,)
        ).fetchone()
    principal = self.principal(cast(str, row[0])) if row else None
    if not principal or principal["status"] != "active" or (kind and principal["kind"] != kind):
        raise ContractError("AUTHENTICATION_FAILED", 401)
    return principal


def _apply_provider_configuration(
    self: Registry, db: Database, actor: str, action: str, subject: str, expected: int, data: Record
) -> Record:
    if (
        expected
        or not subject.startswith("cfg.provider.")
        or set(data) != {"display_name", "deployment_id", "owner", "purposes", "task_classes"}
    ):
        raise ValueError("invalid provider configuration")
    if db.execute(_queries.APPLY_SELECT_REGISTRY_MODELS, (subject,)).fetchone():
        raise RegistryConflict("configuration exists")
    deployment_id = identifier(data["deployment_id"])
    row = db.execute(_queries.APPLY_SELECT_REGISTRY_DEPLOYMENTS, (deployment_id,)).fetchone()
    deployment = decode_record(row[0]) if row else None
    if (
        not deployment
        or deployment["status"] != "catalogued"
        or deployment.get("configuration_ref")
    ):
        raise ValueError("deployment unavailable")
    row = db.execute(
        _queries.APPLY_SELECT_REGISTRY_CONNECTIONS, (deployment["connection_id"],)
    ).fetchone()
    connection = decode_record(row[0]) if row else None
    if (
        not connection
        or connection["status"] != "active"
        or connection["adapter_id"] != "openai.responses.v1"
        or connection["credential_state"] != "present"
        or connection["settings"].get("project")
    ):
        raise ValueError("selected connection unavailable")
    model = decode_record(
        cast(Row, db.execute(_queries.MODEL_FOR_UPDATE, (deployment["model_ref"],)).fetchone())[0]
    )
    if (
        model["status"] != "catalogued"
        or "text" not in model["catalogue"]["provider_published_capabilities"]
    ):
        raise ValueError("catalogue model does not support selected text profile")
    for field in ("purposes", "task_classes"):
        if type(data[field]) is not list or not data[field]:
            raise ValueError("provider configuration scope required")
    destination = {
        "configuration_ref": subject,
        "service": "openai.responses.v1",
        "endpoint": connection["settings"]["origin"],
        "model": deployment["serving_id"],
        "model_version": model["catalogue"]["observed_serving_version"],
        "processing_region": deployment["site"],
        "connection_id": connection["connection_id"],
        "connection_revision": connection["revision"],
        "credential_version": connection["credential_version"],
        "adapter_id": connection["adapter_id"],
        "deployment_id": deployment_id,
    }
    record = {
        "configuration_ref": subject,
        "kind": "provider_deployment",
        "display_name": nonempty(data["display_name"]),
        "status": "draft",
        "revision": 1,
        "destination": destination,
        "owner": identifier(data["owner"]),
        "capabilities": ["text"],
        "purposes": sorted({identifier(x) for x in data["purposes"]}),
        "task_classes": sorted({identifier(x) for x in data["task_classes"]}),
        "handling": ["no.content.store"],
        "approved_by": None,
        "approved_at": None,
        "legacy_unpriced": False,
        "catalogue_ref": deployment["model_ref"],
    }
    deployment["configuration_ref"] = subject
    deployment["revision"] += 1
    db.execute(_queries.APPLY_INSERT_REGISTRY_MODELS, (subject, encode(record)))
    db.execute(_queries.APPLY_UPDATE_REGISTRY_DEPLOYMENTS, (encode(deployment), deployment_id))
    return record


def credential_bound_to(self: Registry, principal_id: str, token: str) -> bool:
    """Compare a saved credential without authenticating an inactive identity."""
    if type(token) is not str or not 32 <= len(token) <= 4096:
        return False
    verifier = hashlib.sha256(token.encode()).hexdigest()
    with self.store.database.read():
        return (
            self.store.database.execute(
                _queries.CREDENTIAL_BOUND_TO_SELECT_REGISTRY_CREDENTIALS,
                (principal_id, verifier),
            ).fetchone()
            is not None
        )


def provision_credential(
    self: Registry,
    actor: str,
    principal_id: str,
    expected_revision: int,
    operation_id: str,
    *,
    secret_factory: Callable[[], str] | None = None,
) -> tuple[Record, str | None]:
    """Return a new secret once; an optional factory can persist it before binding.

    The factory runs after authorization and idempotency checks, inside the
    transaction. It must return the same saved secret when retried after an
    interruption. Ordinary provisioning continues to generate a random token.
    """
    identifier(operation_id)
    identifier(principal_id)
    if type(expected_revision) is not int or expected_revision < 1:
        raise ValueError("invalid expected revision")
    with self.send_authority.gate:

        def action() -> tuple[Record, int | None, str | None]:
            db = self.store.database
            request_hash = _authorize_provision(db, actor, principal_id, expected_revision)
            prior = db.execute(
                _queries.SET_PROVIDER_CREDENTIAL_SELECT_REGISTRY_OPERATIONS, (operation_id,)
            ).fetchone()
            if prior:
                if prior[0] != actor or prior[1] != request_hash:
                    raise RegistryConflict("operation reuse conflict")
                return decode_record(prior[2])["record"], None, None
            record = self._load_for_update(
                db, "registry_principals", "id", principal_id, expected_revision
            )
            if record["status"] == "revoked" or record["credential_state"] == "local_operator":
                raise ValueError("identity cannot be provisioned")
            secret = secret_factory() if secret_factory is not None else secrets.token_urlsafe(48)
            if (
                type(secret) is not str
                or not 32 <= len(secret) <= 4096
                or any(not 33 <= ord(character) <= 126 for character in secret)
            ):
                raise ValueError("invalid generated credential")
            verifier = hashlib.sha256(secret.encode()).hexdigest()
            db.execute(_queries.ACTION_DELETE_REGISTRY_CREDENTIALS, (principal_id,))
            db.execute(
                _queries.ACTION_INSERT_REGISTRY_CREDENTIALS,
                (verifier, principal_id, "cred." + verifier[:16]),
            )
            record["credential_state"] = "bound"
            record["revision"] += 1
            db.execute(_queries.APPLY_UPDATE_REGISTRY_PRINCIPALS, (encode(record), principal_id))
            revision = authority.record_change(
                db,
                actor=actor,
                action="provision_credential",
                subject=principal_id,
                old_revision=expected_revision,
                new_revision=record["revision"],
                at=timestamp(),
            )
            db.execute(
                _queries.ACTION_INSERT_REGISTRY_OPERATIONS,
                (
                    operation_id,
                    actor,
                    request_hash,
                    encode({"record": record, "authority_revision": revision}),
                ),
            )
            return record, revision, secret

        record, revision, secret = self.store.database.transaction(action)
        if revision is not None:
            self.send_authority.epoch = revision
    return record, secret


def _publish_provider_credential(
    self: Registry,
    db: Database,
    actor: str,
    connection_id: str,
    expected_revision: int,
    operation_id: str,
    mode: str,
    next_version: int,
    digest: str,
    record: Record,
) -> tuple[Record, int]:
    current = decode_record(
        cast(
            Row, db.execute(_queries.APPLY_SELECT_REGISTRY_CONNECTIONS, (connection_id,)).fetchone()
        )[0]
    )
    if current["revision"] != expected_revision:
        raise RegistryConflict("connection revision changed")
    current.update(
        credential_version=next_version,
        credential_ref=(hashlib.sha256(connection_id.encode()).hexdigest() + f".{next_version}")
        if mode == "replace"
        else None,
        credential_state="present" if mode == "replace" else "absent",
    )
    current["revision"] += 1
    db.execute(_queries.APPLY_UPDATE_REGISTRY_CONNECTIONS, (encode(current), connection_id))
    revision = authority.record_change(
        db,
        actor=actor,
        action="provider_credential_" + mode,
        subject=connection_id,
        old_revision=expected_revision,
        new_revision=current["revision"],
        at=timestamp(),
        include_values=True,
        before=record,
        after=current,
    )
    reply = {"record": current, "authority_revision": revision}
    db.execute(
        _queries.ACTION_INSERT_REGISTRY_OPERATIONS,
        (operation_id, actor, digest, encode(reply)),
    )
    return reply, revision


def _probe_observation(
    operation_id: str, connection_id: str, connection: Record, operation: str, result: Record
) -> Record:
    now = datetime.now(timezone.utc)
    observation = {
        "operation_id": operation_id,
        "connection_id": connection_id,
        "connection_revision": connection["revision"],
        "credential_version": connection["credential_version"],
        "adapter_id": connection["adapter_id"],
        "operation": operation,
        "scope": {
            "access": "credential_model_listing",
            "inventory": "model_inventory",
            "readiness": "service_reachability",
        }[operation],
        "observer": "trusted_local_service",
        "observed_at": utc_timestamp(now),
        "expires_at": utc_timestamp(now + timedelta(minutes=5)),
        **result,
    }
    return observation


def _authorize_provision(
    db: Database, actor: str, principal_id: str, expected_revision: int
) -> str:
    actor_row = db.execute(_queries.REQUIRE_ADMIN_SELECT_REGISTRY_PRINCIPALS, (actor,)).fetchone()
    admin = decode_record(actor_row[0]) if actor_row else None
    if not admin or admin["status"] != "active" or admin["role"] != "registry_admin":
        raise PermissionError("ADMIN_REQUIRED")
    request_hash = hashlib.sha256(
        encode(
            {
                "principal_id": principal_id,
                "expected_revision": expected_revision,
                "action": "provision_credential",
            }
        ).encode()
    ).hexdigest()
    return request_hash


def _credential_request_digest(
    self: Registry,
    connection_id: str,
    expected_revision: int,
    operation_id: str,
    mode: str,
    secret: str | None,
) -> str:
    identifier(connection_id)
    identifier(operation_id)
    if (
        not self.provider_vault
        or type(expected_revision) is not int
        or mode not in ("replace", "remove")
    ):
        raise ValueError("invalid credential operation")
    if mode == "remove" and secret is not None:
        raise ValueError("remove has no credential body")
    if mode == "replace" and type(secret) is not str:
        raise ValueError("credential required")
    digest = self.provider_vault.request_digest(
        encode(
            {
                "connection_id": connection_id,
                "expected_revision": expected_revision,
                "mode": mode,
                "secret": secret,
            }
        ).encode()
    )
    return digest
