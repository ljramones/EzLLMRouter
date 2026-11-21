"""Trusted, versioned local authority for synthetic models and principals.

All successful mutations share the owned sender's first-byte gate. The SQLite
commit precedes the visible epoch change, and the gate is held until both are
complete. A failed commit leaves the old epoch and records untouched.
"""

from __future__ import annotations

from typing import cast
from .database import Row

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING
from .database import Database
from .records import Record
from .store import Store, decode_record
from .registry_context import RegistryAuthority, CredentialVault

import json as json
import threading
import time as time
from copy import deepcopy

from .errors import RegistryConflict
from .observability import log_failure
from .repositories import authority
from .repositories import registry as _queries

if TYPE_CHECKING:
    from .integration_credentials import DatabaseCredentialStore
    from .local_connectors import LocalConnectors
    from .personal_campaign import PersonalCampaign
    from .user_management import UserManager

from .attribution import AttributionLedger
from .canonical import ContractError
from .catalogue import validate_catalogue
from .identity import InstanceIdentity, persist_identity, resolve_identity
from .integration_accounting import ExternalAccounting
from .provider_adapters import probe as _provider_probe

from .store import encode


from .registry_mutations import mutation_request
from .registry_bootstrap import _seed_bootstrap
from .registry_values import (
    ConnectionSchedule as ConnectionSchedule,
    DESTINATION as DESTINATION,
    MODELS as MODELS,
    RATE_CATEGORIES as RATE_CATEGORIES,
    exact_rate as exact_rate,
    identifier as identifier,
    timestamp as timestamp,
)
from . import registry_reads
from . import registry_sources
from . import registry_credentials
from . import registry_tokens
from .registry_mutations import connections as registry_mutations_connections
from .registry_mutations import catalogue as registry_mutations_catalogue
from .registry_mutations import models as registry_mutations_models
from .registry_mutations import principals as registry_mutations_principals
from .registry_mutations import grants as registry_mutations_grants
from .registry_mutations import prices as registry_mutations_prices


provider_probe = _provider_probe


class Registry:
    """Single-process authority with additive DEV-06 SQLite migration."""

    def __init__(
        self: Registry,
        store: Store,
        send_authority: RegistryAuthority,
        *,
        legacy_destination: Record | None = None,
        legacy_token: str | None = None,
        legacy_trusted: Record | None = None,
        provider_vault: CredentialVault | None = None,
        provider_execution_ready: bool = False,
        controlled_provider_proof: bool = False,
        integration_feature_policy: Record | None = None,
        integration_accounting_retention_days: int | None = None,
        runtime_ready: Callable[[], bool] | None = None,
        identity: InstanceIdentity | None = None,
    ) -> None:
        self.identity = resolve_identity(store.database, identity)
        self.store: Store = store
        self.send_authority: RegistryAuthority = send_authority
        self.runtime_ready = (
            runtime_ready
            if runtime_ready is not None
            else lambda: not getattr(self.send_authority, "revoked", False)
        )
        self.users: UserManager | None = None
        self.local_connectors: LocalConnectors | None = None
        self.integration_credentials: DatabaseCredentialStore | None = None
        self.personal_campaign: PersonalCampaign | None = None
        self.provider_vault: CredentialVault | None = provider_vault
        self.provider_execution_ready = provider_execution_ready
        self.controlled_provider_proof = controlled_provider_proof
        self._probe_lock = threading.Lock()
        self._operator_tokens: dict[str, tuple[str, float]] = {}
        self._token_lock = threading.Lock()
        self._bootstrap(legacy_destination, legacy_token, legacy_trusted)
        if self.principal(self.identity.owner_id) is None:
            raise ValueError("configured owner does not match the persisted registry")
        persist_identity(store.database, self.identity)
        self.attribution = AttributionLedger(self)
        self.integration = ExternalAccounting(
            self,
            feature_policy=integration_feature_policy,
            accounting_retention_days=integration_accounting_retention_days,
        )
        self.integration.expire_datasets()

    def configure_integration_credentials(
        self: Registry, key_path: str | Path
    ) -> DatabaseCredentialStore:
        from .integration_credentials import DatabaseCredentialStore

        if self.integration_credentials is not None:
            raise RuntimeError("integration credentials already configured")
        self.integration_credentials = DatabaseCredentialStore(self, key_path)
        return self.integration_credentials

    def readiness(self: Registry, model: Record) -> str:
        if model.get("kind") == "real_catalogue":
            return "not_connected"
        if model.get("kind") == "provider_deployment":
            if not self.provider_execution_ready:
                return "provider_path_unvalidated"
            destination = model["destination"]
            connection = self.connection(destination["connection_id"])
            if (
                not connection
                or connection["status"] != "active"
                or connection["revision"] != destination["connection_revision"]
                or connection["credential_state"] != "present"
                or connection["credential_version"] != destination["credential_version"]
                or connection["adapter_id"] != destination["adapter_id"]
            ):
                return "provider_connection_stale"
            if not self.source_model_allowed(destination["connection_id"], destination["model"]):
                return "source_model_disallowed"
            return "provider_https_configured" if self.runtime_ready() else "transport_unavailable"
        if model["destination"]["model"] not in MODELS:
            return "unsupported"
        try:
            return "synthetic_http1_ready" if self.runtime_ready() else "transport_unavailable"
        except Exception:
            log_failure("registry.Registry.readiness.failed")
            return "transport_unavailable"

    def _bootstrap(
        self: Registry, destination: Record | None, token: str | None, trusted: Record | None
    ) -> None:
        with self.send_authority.gate:

            def action() -> int:
                db = self.store.database
                row = db.execute(_queries.ACTION_SELECT_REGISTRY_META).fetchone()
                if row and row[0] != "1":
                    raise RuntimeError("invalid registry bootstrap version")
                if not row:
                    _seed_bootstrap(self, db, destination, token, trusted)
                return int(
                    cast(
                        str,
                        cast(Row, db.execute(_queries.VERSION_SELECT_REGISTRY_META).fetchone())[0],
                    )
                )

            revision = self.store.database.transaction(action)
            self.send_authority.epoch = revision

    def version(self: Registry) -> int:
        with self.store.database.read():
            row = self.store.database.execute(_queries.VERSION_SELECT_REGISTRY_META).fetchone()
            if not row:
                raise RuntimeError("authority unavailable")
            return int(cast(str, row[0]))

    _record = registry_reads._record

    model = registry_reads.model

    principal = registry_reads.principal

    grant = registry_reads.grant

    grants = registry_reads.grants

    prices = registry_reads.prices

    list_models = registry_reads.list_models

    list_principals = registry_reads.list_principals

    connection = registry_reads.connection

    list_connections = registry_reads.list_connections

    deployments = registry_reads.deployments

    _source_key = staticmethod(registry_sources._source_key)

    source_permission = registry_sources.source_permission

    source_model_allowed = registry_sources.source_model_allowed

    source_inventory = registry_sources.source_inventory

    observations = registry_reads.observations

    def _require_admin(self: Registry, db: Database, actor: str) -> None:
        if not authority.authorized(db, actor):
            raise PermissionError("ADMIN_REQUIRED")

    set_provider_credential = registry_credentials.set_provider_credential

    probe_connection = registry_credentials.probe_connection

    history = registry_reads.history

    credential_principal = registry_credentials.credential_principal

    _prune_operator_tokens = registry_tokens._prune_operator_tokens

    issue_local_operator_token = registry_tokens.issue_local_operator_token

    revoke_local_operator_token = registry_tokens.revoke_local_operator_token

    authenticate = registry_tokens.authenticate

    def explain(
        self: Registry,
        principal_id: str,
        ref: str,
        purpose: str,
        task_class: str,
        features: Sequence[str] = ("text",),
    ) -> Record:
        with self.store.database.read():
            principal = self.principal(principal_id)
            model = self.model(ref)
            grant = self.grant(principal_id, ref)
            reason = (
                "PRINCIPAL_NOT_ACTIVE"
                if not principal or principal["status"] != "active"
                else "MODEL_NOT_ENABLED"
                if not model or model["status"] != "enabled"
                else "SOURCE_MODEL_DISALLOWED"
                if model and self.readiness(model) == "source_model_disallowed"
                else "TRANSPORT_UNAVAILABLE"
                if self.readiness(model)
                not in ("synthetic_http1_ready", "provider_https_configured")
                else "CAPABILITY_UNSUPPORTED"
                if not set(features) <= set(model["capabilities"])
                else "GRANT_MISSING"
                if not grant or grant["status"] != "active"
                else "PURPOSE_DENIED"
                if purpose not in grant["purposes"] or purpose not in model["purposes"]
                else "TASK_CLASS_DENIED"
                if task_class not in grant["task_classes"]
                or task_class not in model["task_classes"]
                else "ALLOWED"
            )
            return {
                "allowed": reason == "ALLOWED",
                "reason": reason,
                "principal_revision": principal["revision"] if principal else None,
                "model_revision": model["revision"] if model else None,
                "grant_revision": grant["revision"] if grant else None,
                "authority_revision": self.version(),
            }

    def admit(
        self: Registry,
        principal_id: str,
        ref: str,
        purpose: str,
        task_class: str,
        features: Sequence[str] = ("text",),
    ) -> tuple[Record, Record]:
        with self.store.database.read():
            decision = self.explain(principal_id, ref, purpose, task_class, features)
            if not decision["allowed"]:
                raise ContractError("POLICY_DENIED", 403)
            model = cast(Record, self.model(ref))
            prices = self.prices(ref)
            active = prices[-1] if prices else None
            if not model["legacy_unpriced"] and active is None:
                raise ContractError("POLICY_DENIED", 403)
            return deepcopy(model["destination"]), {
                **decision,
                "features": list(features),
                "price_version": active["price_version"] if active else "synthetic.unpriced.v1",
                "usage_semantics_version": active["usage_semantics_version"]
                if active
                else "synthetic.text.v1",
                "price_schedule": active,
            }

    def check_current(
        self: Registry, principal_id: str, ref: str, purpose: str, task_class: str, decision: Record
    ) -> Record:
        with self.store.database.read():
            current = self.explain(principal_id, ref, purpose, task_class, decision["features"])
            if (
                not current["allowed"]
                or current["authority_revision"] != decision["authority_revision"]
            ):
                raise ContractError("PLAN_INVALID_OR_STALE", 409)
            return cast(Record, cast(Record, self.model(ref))["destination"])

    def mutate(self: Registry, actor: str, request: Record) -> Record:
        """Strict idempotent management command; returns committed safe record."""
        op, action_name, subject, expected, data, request_hash = mutation_request(request)
        with self.send_authority.gate:

            def action() -> tuple[Record, int | None]:
                db = self.store.database
                self._require_admin(db, actor)
                prior = db.execute(
                    _queries.SET_PROVIDER_CREDENTIAL_SELECT_REGISTRY_OPERATIONS, (op,)
                ).fetchone()
                if prior:
                    if prior[0] != actor or prior[1] != request_hash:
                        raise RegistryConflict("operation reuse conflict")
                    return decode_record(prior[2]), None
                if action_name == "import_catalogue":
                    if expected != 0:
                        raise RegistryConflict("catalogue creation requires revision zero")
                    candidate = validate_catalogue(subject, data, owner_id=self.identity.owner_id)
                    row = db.execute(_queries.MODEL_FOR_UPDATE, (subject,)).fetchone()
                    if row:
                        existing = decode_record(row[0])
                        if (
                            existing.get("kind") == "real_catalogue"
                            and existing.get("catalogue") == candidate["catalogue"]
                            and existing.get("source_links") == candidate["source_links"]
                        ):
                            current = int(
                                cast(
                                    str,
                                    cast(
                                        Row,
                                        db.execute(
                                            _queries.VERSION_SELECT_REGISTRY_META
                                        ).fetchone(),
                                    )[0],
                                )
                            )
                            return {"record": existing, "authority_revision": current}, None
                        raise RegistryConflict("catalogue import conflicts with existing record")
                table = _mutation_subject_table(action_name)
                prior_row = (
                    db.execute(_queries.ACTION_SELECT_RECORD(table=table), (subject,)).fetchone()
                    if table
                    else None
                )
                before = decode_record(prior_row[0]) if prior_row else None
                result = self._apply(db, actor, action_name, subject, expected, data)
                revision = authority.record_change(
                    db,
                    actor=actor,
                    action=action_name,
                    subject=subject,
                    old_revision=expected or None,
                    new_revision=result["revision"],
                    at=timestamp(),
                    include_values=True,
                    before=before,
                    after=result,
                )
                reply = {"record": result, "authority_revision": revision}
                db.execute(
                    _queries.ACTION_INSERT_REGISTRY_OPERATIONS,
                    (op, actor, request_hash, encode(reply)),
                )
                return reply, revision

            reply, revision = self.store.database.transaction(action)
            if revision is not None:
                self.send_authority.epoch = revision
            return reply

    def _apply(
        self: Registry,
        db: Database,
        actor: str,
        action: str,
        subject: str,
        expected: int,
        data: Record,
    ) -> Record:
        handlers = {
            "register_agent": self._apply_attribution,
            "agent_state": self._apply_attribution,
            "agent_instrumentation": self._apply_attribution,
            "set_agent_permission": self._apply_attribution,
            "set_outcome_authority": self._apply_attribution,
            "set_source_permissions": self._apply_source_permissions,
            "create_provider_configuration": self._apply_provider_configuration,
            "create_connection": self._apply_create_connection,
            "edit_connection": self._apply_connection_change,
            "connection_state": self._apply_connection_change,
            "associate_deployment": self._apply_connection_change,
            "probe_schedule": self._apply_connection_change,
            "import_catalogue": self._apply_import_catalogue,
            "register_catalogue": self._apply_register_catalogue,
            "create_model": self._apply_create_model,
            "edit_model": self._apply_model_change,
            "edit_catalogue_model": self._apply_model_change,
            "model_state": self._apply_model_change,
            "archive_model": self._apply_model_change,
            "publish_reference_price": self._apply_model_change,
            "correct_reference_price": self._apply_model_change,
            "create_principal": self._apply_create_principal,
            "edit_principal": self._apply_principal_change,
            "principal_state": self._apply_principal_change,
            "set_role": self._apply_principal_change,
            "set_grant": self._apply_grant,
            "publish_price": self._apply_price,
        }
        if not isinstance(action, str) or action not in handlers:
            raise ValueError("unsupported management action")
        return handlers[action](db, actor, action, subject, expected, data)

    def _apply_attribution(
        self: Registry,
        db: Database,
        actor: str,
        action: str,
        subject: str,
        expected: int,
        data: Record,
    ) -> Record:
        return self.attribution.apply_admin(db, action, subject, expected, data)

    _apply_source_permissions = registry_sources._apply_source_permissions

    _apply_provider_configuration = registry_credentials._apply_provider_configuration

    _apply_create_connection = registry_mutations_connections._apply_create_connection

    _apply_connection_change = registry_mutations_connections._apply_connection_change

    _apply_import_catalogue = registry_mutations_catalogue._apply_import_catalogue

    _apply_register_catalogue = registry_mutations_catalogue._apply_register_catalogue

    _apply_create_model = registry_mutations_models._apply_create_model

    _apply_model_change = registry_mutations_models._apply_model_change

    _apply_create_principal = registry_mutations_principals._apply_create_principal

    _apply_principal_change = registry_mutations_principals._apply_principal_change

    _apply_grant = registry_mutations_grants._apply_grant

    _apply_price = registry_mutations_prices._apply_price

    @staticmethod
    def _load_for_update(
        db: Database, table: str, column: str, subject: str, expected: int
    ) -> Record:
        row = db.execute(
            _queries.LOAD_FOR_UPDATE_SELECT_RECORD(column=column, table=table), (subject,)
        ).fetchone()
        if not row:
            raise ValueError("unknown subject")
        record = decode_record(row[0])
        if record["revision"] != expected:
            raise RegistryConflict("stale revision")
        return record

    credential_bound_to = registry_credentials.credential_bound_to

    provision_credential = registry_credentials.provision_credential


def _mutation_subject_table(action_name: str) -> str | None:
    return (
        "registry_models"
        if action_name
        in (
            "edit_model",
            "edit_catalogue_model",
            "model_state",
            "archive_model",
            "publish_reference_price",
            "correct_reference_price",
        )
        else "registry_connections"
        if action_name
        in ("edit_connection", "connection_state", "probe_schedule", "associate_deployment")
        else "registry_principals"
        if action_name in ("edit_principal", "principal_state", "set_role")
        else "registry_agents"
        if action_name in ("register_agent", "agent_state", "agent_instrumentation")
        else None
    )
