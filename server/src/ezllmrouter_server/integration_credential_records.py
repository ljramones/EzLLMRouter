"""Integration credential binding, discovery and pending-record lifecycle operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast
from .store import Store, Record

if TYPE_CHECKING:
    from .integration_credentials import DatabaseCredentialStore
    from .registry import Registry


SealedRecord = tuple[str, bytes, bytes]


class CredentialBox(Protocol):
    def seal_parts(self, value: str, context: bytes) -> SealedRecord: ...
    def open_parts(
        self, identifier: str, nonce: bytes, ciphertext: bytes, context: bytes
    ) -> str: ...


class Discovery(Protocol):
    def __call__(
        self,
        adapter_id: str,
        settings: Record,
        credential: str | None,
        operation: str,
        *,
        controlled: bool,
    ) -> Record: ...


class CredentialRecordsContext(Protocol):
    @property
    def store(self) -> Store: ...
    @property
    def registry(self) -> Registry: ...
    @property
    def box(self) -> CredentialBox: ...
    @property
    def controlled(self) -> bool: ...
    @property
    def discover(self) -> Discovery: ...
    def _owner(self, principal: Record, dataset_id: str) -> Record: ...
    def _binding(self, account_id: str) -> Record: ...
    def _settings(self, provider: str) -> Record: ...
    def _resolve(self, binding: Record, version: int | None = None) -> str: ...


if TYPE_CHECKING:

    def _check_record_context(store: DatabaseCredentialStore) -> CredentialRecordsContext:
        return store


def _binding(self: CredentialRecordsContext, account_id: str) -> Record:
    from . import integration_credentials as _api

    with self.store.database.read():
        row = self.store.database.execute(
            _api._queries.BINDING_SELECT_INTEGRATION_CREDENTIAL_BINDINGS, (account_id,)
        ).fetchone()
    if not row:
        raise _api.IntegrationError("NOT_FOUND_OR_FORBIDDEN", 404)
    return cast(Record, _api.json.loads(cast(str, row[0])))


def _seal(
    self: CredentialRecordsContext, account_id: str, version: int, provider: str, secret: str
) -> SealedRecord:
    from . import integration_credentials as _api

    try:
        _api.validate_secret(secret)
    except ValueError as exc:
        raise _api.IntegrationError("INVALID_CREDENTIAL") from exc
    return self.box.seal_parts(secret, _api.credential_context(account_id, version, provider))


def _resolve(self: CredentialRecordsContext, binding: Record, version: int | None = None) -> str:
    from . import integration_credentials as _api

    selected = version or binding["selected_version"]
    with self.store.database.read():
        row = self.store.database.execute(
            _api._queries.RESOLVE_SELECT_INTEGRATION_CREDENTIAL_VERSIONS,
            (binding["account_id"], selected),
        ).fetchone()
    if not row:
        raise _api.IntegrationError("CREDENTIAL_KEY_UNAVAILABLE", 503)
    try:
        return self.box.open_parts(
            *cast(SealedRecord, row),
            _api.credential_context(binding["account_id"], selected, binding["provider"]),
        )
    except Exception as exc:
        _api.log_failure("integration_credentials.DatabaseCredentialStore._resolve.failed")
        raise _api.IntegrationError("CREDENTIAL_DECRYPT_FAILED", 503) from exc


def _settings(self: CredentialRecordsContext, provider: str) -> Record:
    from . import integration_credentials as _api

    return {
        "origin": _api.PROVIDERS[provider][1],
        "location": "commercial",
        "site": self.registry.identity.owner_id,
    }


def _discover(
    self: CredentialRecordsContext,
    binding: Record,
    version: int | None = None,
    *,
    secret: str | None = None,
) -> Record:
    from . import integration_credentials as _api

    result = self.discover(
        _api.PROVIDERS[binding["provider"]][0],
        self._settings(binding["provider"]),
        self._resolve(binding, version) if secret is None else secret,
        "inventory",
        controlled=self.controlled,
    )
    if result["state"] == "observed" and not result.get("models"):
        result = {"state": "empty", "reason": "empty_catalogue", "models": []}
    return {
        "state": result["state"],
        "reason": result["reason"],
        "models": result.get("models", []),
        "details": result.get("details", []),
        "has_more": bool(result.get("has_more")),
        "checked_at": _api._time(),
        "credential_version": version or binding["selected_version"],
        "record_revision": binding["revision"],
    }


def _public(self: CredentialRecordsContext, binding: Record) -> Record:
    return {key: value for key, value in binding.items() if key not in ("request_hash",)}


def _current(
    self: CredentialRecordsContext,
    principal: Record,
    dataset_id: str,
    account_id: str,
    expected_revision: int,
) -> Record:
    """Call within the write transaction when publishing a changed binding."""
    from . import integration_credentials as _api

    self._owner(principal, dataset_id)
    item = self._binding(account_id)
    if (
        type(expected_revision) is not int
        or item["dataset_id"] != dataset_id
        or item["revision"] != expected_revision
    ):
        raise _api.IntegrationError("STALE_REVISION", 409)
    return item


def _clean_pending(self: CredentialRecordsContext) -> None:
    from . import integration_credentials as _api

    cutoff = _api.utc_timestamp(_api.datetime.now(_api.timezone.utc) - _api.timedelta(days=1))

    def clean() -> None:
        db = self.store.database
        rows = db.execute(_api._queries.CLEAN_SELECT_INTEGRATION_CREDENTIAL_BINDINGS).fetchall()
        for account_id, raw in rows:
            item = _api.json.loads(cast(str, raw))
            if (
                item["state"] == "pending"
                and item["discovery"]["state"] == "not_checked"
                and item["created_at"] < cutoff
            ):
                db.execute(
                    _api._queries.CLEAN_DELETE_INTEGRATION_CREDENTIAL_VERSIONS, (account_id,)
                )
                db.execute(
                    _api._queries.CLEAN_DELETE_INTEGRATION_CREDENTIAL_OPERATIONS, (account_id,)
                )
                db.execute(
                    _api._queries.CLEAN_DELETE_INTEGRATION_CREDENTIAL_BINDINGS, (account_id,)
                )

    self.store.database.transaction(clean)
