"""Local model-server inventory and explicit connection/model selection."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Protocol, cast
from .database import Database
from .records import Record
from .store import Store

if TYPE_CHECKING:
    from .registry import Registry


class InventoryReader(Protocol):
    def __call__(self, base_url: str, path: str, api_key: str, *, timeout: float = 3) -> object: ...


class Discoverer(Protocol):
    def __call__(self, kind: str, base_url: str, api_key: str = "") -> Record: ...


import hashlib as hashlib
import ipaddress as ipaddress
import json as json
import socket as socket
import ssl as ssl
import time as time
import uuid as uuid
from pathlib import Path as Path
from urllib.parse import urlsplit as urlsplit, urlunsplit as urlunsplit

from .connector_availability import AvailabilityMonitor as AvailabilityMonitor
from .errors import RequestError as RequestError
from .formatting import utc_timestamp as _connector_timestamp
from .json_validation import unique_pairs as unique_pairs, MAX_SAFE_INTEGER as MAX_SAFE_INTEGER
from .observability import log_failure as log_failure
from .repositories import authority as authority
from .repositories import local_connectors as _connector_queries
from .secret_box import SecretBox as SecretBox, validate_secret as validate_secret
from .store import encode as encode

import http.client as _http_client
import http as _http_root

_http_client = _http_client
http = _http_root
timestamp = _connector_timestamp
_queries = _connector_queries

KINDS = {
    "ollama": {"name": "Ollama", "default_url": "http://localhost:11434", "api": "ollama"},
    "lmstudio": {"name": "LM Studio", "default_url": "http://localhost:1234", "api": "openai"},
    "vllm": {"name": "vLLM", "default_url": "http://localhost:8000", "api": "openai"},
    "llamacpp": {"name": "llama.cpp", "default_url": "http://localhost:8080", "api": "openai"},
    "localai": {"name": "LocalAI", "default_url": "http://localhost:8080", "api": "openai"},
    "openai_compatible": {
        "name": "Other OpenAI-compatible server",
        "default_url": "http://localhost:8000",
        "api": "openai",
    },
}
MAX_MODELS = 1000
MAX_RESPONSE = 1024 * 1024
ROUTES = {"/api/tags", "/api/ps", "/api/version", "/v1/models"}
NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in (
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "::1/128",
        "fc00::/7",
    )
)
COMMON_SERVERS = (
    ("ollama", 11434, "Ollama API", "Ollama"),
    ("openai_compatible", 1234, "Local model API :1234", "Often LM Studio"),
    ("openai_compatible", 8080, "Local model API :8080", "Often llama.cpp or LocalAI"),
    ("openai_compatible", 8081, "Local model API :8081", "LocalAI test port"),
    ("openai_compatible", 8000, "Local model API :8000", "Often vLLM"),
    ("openai_compatible", 9997, "Local model API :9997", "Often Xinference"),
    ("openai_compatible", 30000, "Local model API :30000", "Often SGLang"),
)


class ConnectorError(RequestError):
    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code, status)


from ezllmrouter_server import local_connector_http as _local_connector_http
from ezllmrouter_server import local_connector_inventory as _local_connector_inventory


allowed_address = _local_connector_http.allowed_address


normalize_url = _local_connector_http.normalize_url


_pairs = _local_connector_http._pairs


_reject_constant = _local_connector_http._reject_constant


_read_json = _local_connector_http._read_json


_text = _local_connector_inventory._text


_integer = _local_connector_inventory._integer


discover = _local_connector_inventory.discover


def connector_key_path(database: str | Path) -> Path:
    if str(database) == ":memory:":
        raise ValueError("an explicit connector key path is required for an in-memory store")
    return Path(str(database) + ".secrets") / "local-connectors.keys.json"


def connector_context(connector_id: str) -> bytes:
    return encode({"connector_id": connector_id}).encode()


def reencrypt_connectors(store: Store, box: SecretBox, *, verify_only: bool = False) -> int:
    def rewrite() -> int:
        changed = 0
        for identifier, raw in store.database.execute(
            _queries.REWRITE_SELECT_LOCAL_CONNECTORS
        ).fetchall():
            envelope = json.loads(cast(str, raw))
            context = connector_context(cast(str, identifier))
            value = box.open(envelope, context)
            if not verify_only and envelope["key_id"] != box.active_id:
                store.database.execute(
                    _queries.REWRITE_UPDATE_LOCAL_CONNECTORS,
                    (encode(box.seal(value, context)), identifier),
                )
                changed += 1
        return changed

    return store.database.transaction(rewrite)


class LocalConnectors:
    def __init__(
        self,
        registry: Registry,
        *,
        discover_fn: Discoverer | None = None,
        availability_read: InventoryReader | None = None,
        key_path: str | Path | None = None,
    ) -> None:
        self.registry, self.store = registry, registry.store
        self.discover_fn = discover_fn or discover
        self.availability_read = availability_read
        self.monitor = AvailabilityMonitor()
        with self.store.database.read():
            rows = self.store.database.execute(_queries.INIT_SELECT_LOCAL_CONNECTORS).fetchall()
        known = {json.loads(cast(str, row[0]))["key_id"] for row in rows}
        self.key_path = Path(key_path) if key_path else connector_key_path(self.store.path)
        self.box = SecretBox(self.key_path, "local-connector-credentials", required_ids=known)

    def _authorize(self, db: Database, actor: str, *, write: bool = False) -> None:
        roles = ("registry_admin",) if write else ("registry_admin", "read_only_operator")
        if not authority.authorized(db, actor, roles):
            raise ConnectorError("ADMIN_REQUIRED" if write else "OPERATOR_REQUIRED", 403)

    def _load(self, db: Database, connector_id: str) -> tuple[Record, str | None]:
        row = db.execute(_queries.LOAD_SELECT_LOCAL_CONNECTORS, (connector_id,)).fetchone()
        if not row:
            raise ConnectorError("CONNECTOR_NOT_FOUND", 404)
        record = json.loads(cast(str, row[0]))
        if record.get("deleted"):
            raise ConnectorError("CONNECTOR_NOT_FOUND", 404)
        return cast(Record, record), cast(str | None, row[1])

    def _seal(self, connector_id: str, value: str) -> str | None:
        if value == "":
            return None
        try:
            validate_secret(value)
        except ValueError as exc:
            raise ConnectorError("INVALID_API_KEY") from exc
        try:
            return encode(self.box.seal(value, connector_context(connector_id)))
        except Exception as exc:
            log_failure("local_connectors.LocalConnectors._seal.failed")
            raise ConnectorError("CREDENTIAL_STORAGE_UNAVAILABLE", 503) from exc

    def _resolve(self, connector_id: str, sealed: str | None) -> str:
        if not sealed:
            return ""
        try:
            return self.box.open(json.loads(sealed), connector_context(connector_id))
        except Exception as exc:
            log_failure("local_connectors.LocalConnectors._resolve.failed")
            raise ConnectorError("CREDENTIAL_UNAVAILABLE", 503) from exc

    def reencrypt_secrets(self) -> int:
        return reencrypt_connectors(self.store, self.box)

    def rotate_encryption_key(self) -> Record:
        identifier = self.box.rotate()
        return {"key_id": identifier, "rewritten": self.reencrypt_secrets()}

    @staticmethod
    def _configuration(record: Record) -> str:
        return hashlib.sha256(
            encode(
                {key: record[key] for key in ("kind", "base_url", "credential_version")}
            ).encode()
        ).hexdigest()

    def _public(self, record: Record) -> Record:
        discovery = record["discovery"]
        current = discovery.get("configuration") == self._configuration(record)
        available = {model["id"] for model in discovery.get("models", [])}
        usable = bool(
            record["enabled"]
            and current
            and discovery["state"] == "observed"
            and discovery.get("complete")
            and record["selected_models"]
            and set(record["selected_models"]) <= available
        )
        return {
            **record,
            "status": "connected"
            if usable
            else "needs_attention"
            if record["enabled"]
            else "disabled"
            if record["selected_models"]
            else "not_configured",
            "usable": usable,
            "availability": self.monitor.get(record["connector_id"], self._configuration(record)),
        }

    def close(self) -> None:
        self.monitor.close()

    @staticmethod
    def _availability_error(exc: ConnectorError) -> Record:
        if exc.code in (
            "CONNECTOR_CHANGED",
            "CONNECTOR_NOT_FOUND",
            "ADMIN_REQUIRED",
            "OPERATOR_REQUIRED",
        ):
            return {"state": "unknown", "reason": "CHECK_CANCELLED", "reachable": None}
        if exc.code == "SERVER_CHECK_BLOCKED":
            return {"state": "blocked", "reason": exc.code, "reachable": None}
        if exc.code in ("SERVER_UNREACHABLE", "SERVER_TIMEOUT", "SERVER_NAME_NOT_RESOLVED"):
            return {"state": "offline", "reason": exc.code, "reachable": False}
        reached = exc.code in (
            "SERVER_AUTHENTICATION_REQUIRED",
            "DISCOVERY_ENDPOINT_NOT_FOUND",
            "SERVER_UNAVAILABLE",
            "SERVER_RATE_LIMITED",
            "SERVER_TLS_FAILED",
            "INVALID_SERVER_RESPONSE",
            "REDIRECT_NOT_ALLOWED",
            "SERVER_RESPONSE_TOO_LARGE",
            "COMPRESSED_RESPONSE_NOT_SUPPORTED",
        )
        return {"state": "attention", "reason": exc.code, "reachable": True if reached else None}

    def _probe_availability(self, record: Record, key: str) -> Record:
        read = self.availability_read or _read_json
        path = "/api/version" if record["kind"] == "ollama" else "/v1/models"
        try:
            try:
                value = read(record["base_url"], path, key, timeout=1.5)
            except ConnectorError as exc:
                if record["kind"] != "ollama" or exc.code != "DISCOVERY_ENDPOINT_NOT_FOUND":
                    raise
                value = read(record["base_url"], "/api/tags", key, timeout=1.5)
                path = "/api/tags"
            if path == "/api/version":
                _text(value.get("version") if type(value) is dict else None, key, required=True)
                return {"state": "online", "reason": "API_RESPONDED", "reachable": True}
            models = (
                value.get("models" if path == "/api/tags" else "data")
                if type(value) is dict
                else None
            )
            if type(models) is not list or any(type(model) is not dict for model in models):
                raise ConnectorError("INVALID_SERVER_RESPONSE", 502)
            return {
                "state": "online",
                "reason": "API_RESPONDED",
                "reachable": True,
                "model_count": len(models),
            }
        except ConnectorError as exc:
            return self._availability_error(exc)

    def _saved_check(self, actor: str, record: Record) -> Record:
        try:
            with self.store.database.read():
                self._authorize(self.store.database, actor)
                current, sealed = self._load(self.store.database, record["connector_id"])
                if self._configuration(current) != self._configuration(record):
                    raise ConnectorError("CONNECTOR_CHANGED", 409)
            return self._probe_availability(record, self._resolve(record["connector_id"], sealed))
        except ConnectorError as exc:
            return self._availability_error(exc)

    def availability(self, actor: str, body: Record | None = None) -> Record:
        """Read cached status, or queue bounded checks without changing records."""
        with self.store.database.read():
            self._authorize(self.store.database, actor)
            if body is not None:
                self._fields(body, (), ("connector_ids", "force"))
                ids = body.get("connector_ids")
                if (
                    ids is not None
                    and (
                        type(ids) is not list
                        or len(ids) > 64
                        or any(type(value) is not str for value in ids)
                        or len(set(ids)) != len(ids)
                    )
                    or type(body.get("force", False)) is not bool
                ):
                    raise ConnectorError("INVALID_AVAILABILITY_CHECK")
            else:
                ids = None
            rows = self.store.database.execute(
                _queries.AVAILABILITY_SELECT_LOCAL_CONNECTORS
            ).fetchall()
            records = [
                record
                for row in rows
                if not (record := json.loads(cast(str, row[0]))).get("deleted")
            ]
            if ids is not None:
                found = {record["connector_id"] for record in records}
                if not set(ids) <= found:
                    raise ConnectorError("CONNECTOR_NOT_FOUND", 404)
                records = [record for record in records if record["connector_id"] in ids]
        items = []
        # Give never-checked and older entries room when the bounded queue is full.
        records.sort(
            key=lambda record: self.monitor.get(
                record["connector_id"], self._configuration(record)
            ).get("checked_at")
            or ""
        )
        for record in records:
            identifier, configuration = record["connector_id"], self._configuration(record)
            status = self.monitor.get(identifier, configuration)
            if body is not None:

                def check(record: Record = record) -> Record:
                    return self._saved_check(actor, record)

                status = self.monitor.request(
                    identifier,
                    configuration,
                    check,
                    force=body.get("force", False),
                )
            items.append({"connector_id": identifier, "availability": status})
        return {"items": items, "refresh_seconds": 15}

    @staticmethod
    def _endpoint(record: Record) -> tuple[str, str, str | None, int]:
        url = urlsplit(record["base_url"])
        host = "localhost" if url.hostname in ("localhost", "127.0.0.1", "::1") else url.hostname
        return (
            KINDS[record["kind"]]["api"],
            url.scheme,
            host,
            url.port or (443 if url.scheme == "https" else 80),
        )

    def nearby(self, actor: str, body: Record | None = None) -> Record:
        """Check a fixed set of loopback APIs only after an administrator asks."""
        with self.store.database.read():
            self._authorize(self.store.database, actor, write=True)
            if body is not None:
                self._fields(body, (), ("force",))
                if type(body.get("force", False)) is not bool:
                    raise ConnectorError("INVALID_AVAILABILITY_CHECK")
            rows = [
                json.loads(cast(str, row[0]))
                for row in self.store.database.execute(
                    _queries.AVAILABILITY_SELECT_LOCAL_CONNECTORS
                )
            ]
            saved = {
                self._endpoint(record): record["connector_id"]
                for record in rows
                if not record.get("deleted")
            }
        items = []
        for kind, port, name, hint in COMMON_SERVERS:
            record: Record = {
                "connector_id": "nearby." + str(port),
                "kind": kind,
                "base_url": "http://localhost:" + str(port),
                "credential_version": 0,
            }
            identifier, configuration = record["connector_id"], self._configuration(record)
            status = self.monitor.get(identifier, configuration)
            if body is not None:

                def check(record: Record = record) -> Record:
                    try:
                        with self.store.database.read():
                            self._authorize(self.store.database, actor, write=True)
                        return self._probe_availability(record, "")
                    except ConnectorError as exc:
                        return self._availability_error(exc)

                status = self.monitor.request(
                    identifier, configuration, check, force=body.get("force", False)
                )
            items.append(
                {
                    "candidate_id": identifier,
                    "kind": kind,
                    "base_url": record["base_url"],
                    "display_name": name,
                    "hint": hint,
                    "availability": status,
                    "saved_connector_id": saved.get(self._endpoint(record)),
                }
            )
        return {"items": items}

    def list(self, actor: str) -> Record:
        with self.store.database.read():
            self._authorize(self.store.database, actor)
            records = [
                json.loads(cast(str, row[0]))
                for row in self.store.database.execute(
                    _queries.AVAILABILITY_SELECT_LOCAL_CONNECTORS
                )
            ]
            return {
                "items": [self._public(record) for record in records if not record.get("deleted")],
                "kinds": KINDS,
            }

    def get(self, actor: str, connector_id: str) -> Record:
        with self.store.database.read():
            self._authorize(self.store.database, actor)
            return self._public(self._load(self.store.database, connector_id)[0])

    @staticmethod
    def _fields(body: Record, required: Iterable[str], optional: Iterable[str] = ()) -> None:
        if (
            type(body) is not dict
            or set(body) - set(required) - set(optional)
            or set(required) - set(body)
        ):
            raise ConnectorError("INVALID_CONNECTOR_CHANGE")

    @staticmethod
    def _profile(body: Record) -> tuple[str, str, str]:
        name, kind = body["display_name"], body["kind"]
        if (
            type(name) is not str
            or not name.strip()
            or len(name) > 120
            or any(ord(char) < 32 for char in name)
        ):
            raise ConnectorError("INVALID_CONNECTOR_NAME")
        try:
            name.encode("utf-8")
        except UnicodeError as exc:
            raise ConnectorError("INVALID_CONNECTOR_NAME") from exc
        if type(kind) is not str or kind not in KINDS:
            raise ConnectorError("UNSUPPORTED_CONNECTOR")
        return name.strip(), kind, normalize_url(body["base_url"], kind)

    @staticmethod
    def _expected(record: Record, body: Record) -> None:
        if (
            type(body["expected_revision"]) is not int
            or body["expected_revision"] != record["revision"]
        ):
            raise ConnectorError("CONNECTOR_CHANGED", 409)

    def _write(
        self,
        actor: str,
        action: str,
        connector_id: str,
        change: Callable[[Database], tuple[Record, str | None]],
    ) -> Record:
        with self.registry.send_authority.gate:

            def transaction() -> tuple[Record, int]:
                db = self.store.database
                self._authorize(db, actor, write=True)
                record, secret = change(db)
                old = record["revision"]
                record.update(revision=old + 1, updated_at=timestamp())
                db.execute(
                    _queries.TRANSACTION_INSERT_LOCAL_CONNECTORS,
                    (connector_id, encode(record), secret),
                )
                revision = authority.record_change(
                    db,
                    actor=actor,
                    action=action,
                    subject=connector_id,
                    old_revision=old or None,
                    new_revision=record["revision"],
                    at=timestamp(),
                )
                return self._public(record), revision

            result, revision = self.store.database.transaction(transaction)
            self.registry.send_authority.epoch = revision
            return result

    def create(self, actor: str, body: Record) -> Record:
        self._fields(body, ("display_name", "kind", "base_url"), ("api_key",))
        name, kind, url = self._profile(body)
        connector_id = "connector.local." + uuid.uuid4().hex

        def change(db: Database) -> tuple[Record, str | None]:
            sealed = self._seal(connector_id, body.get("api_key", ""))
            return {
                "connector_id": connector_id,
                "display_name": name,
                "kind": kind,
                "base_url": url,
                "revision": 0,
                "created_at": timestamp(),
                "enabled": False,
                "selected_models": [],
                "credential_present": bool(sealed),
                "credential_version": 1 if sealed else 0,
                "discovery": {"state": "not_checked", "models": []},
            }, sealed

        return self._write(actor, "create_local_connector", connector_id, change)

    def update(self, actor: str, connector_id: str, body: Record) -> Record:
        self._fields(body, ("display_name", "kind", "base_url", "expected_revision"), ("api_key",))
        name, kind, url = self._profile(body)

        def change(db: Database) -> tuple[Record, str | None]:
            record, sealed = self._load(db, connector_id)
            self._expected(record, body)
            changed = record["kind"] != kind or record["base_url"] != url or "api_key" in body
            if "api_key" in body:
                sealed = self._seal(connector_id, body["api_key"])
                record["credential_version"] += 1
            elif changed and sealed:
                # A key approved for one endpoint must not follow an address edit.
                sealed = None
                record["credential_version"] += 1
            record.update(
                display_name=name, kind=kind, base_url=url, credential_present=bool(sealed)
            )
            if changed:
                record.update(
                    enabled=False,
                    selected_models=[],
                    discovery={"state": "not_checked", "models": []},
                )
            return record, sealed

        return self._write(actor, "update_local_connector", connector_id, change)

    def discover(self, actor: str, connector_id: str, body: Record) -> Record:
        self._fields(body, ("expected_revision",))
        with self.store.database.read():
            self._authorize(self.store.database, actor, write=True)
            record, sealed = self._load(self.store.database, connector_id)
            self._expected(record, body)
        try:
            result = self.discover_fn(
                record["kind"], record["base_url"], self._resolve(connector_id, sealed)
            )
        except ConnectorError as exc:
            result = {
                "state": "failed",
                "reason": exc.code,
                "checked_at": timestamp(),
                "models": [],
                "complete": False,
            }
        result["configuration"] = self._configuration(record)

        def change(db: Database) -> tuple[Record, str | None]:
            current, current_secret = self._load(db, connector_id)
            self._expected(current, body)
            current["discovery"] = result
            return current, current_secret

        return self._write(actor, "discover_local_models", connector_id, change)

    def configure(self, actor: str, connector_id: str, body: Record) -> Record:
        self._fields(body, ("expected_revision", "selected_models", "enabled"))
        models = body["selected_models"]
        if (
            type(models) is not list
            or len(models) > MAX_MODELS
            or any(type(model) is not str for model in models)
            or len(set(models)) != len(models)
            or type(body["enabled"]) is not bool
        ):
            raise ConnectorError("INVALID_MODEL_SELECTION")

        def change(db: Database) -> tuple[Record, str | None]:
            record, sealed = self._load(db, connector_id)
            self._expected(record, body)
            available = {model["id"] for model in record["discovery"].get("models", [])}
            if body["enabled"] and (
                not models
                or record["discovery"]["state"] != "observed"
                or not record["discovery"].get("complete")
                or not set(models) <= available
                or record["discovery"].get("configuration") != self._configuration(record)
            ):
                raise ConnectorError("DISCOVER_AND_SELECT_MODELS_FIRST", 409)
            if not set(models) <= available and models != record["selected_models"]:
                raise ConnectorError("INVALID_MODEL_SELECTION")
            record.update(selected_models=models, enabled=body["enabled"])
            return record, sealed

        return self._write(actor, "configure_local_models", connector_id, change)

    def delete(self, actor: str, connector_id: str, body: Record) -> Record:
        self._fields(body, ("expected_revision",))

        def change(db: Database) -> tuple[Record, str | None]:
            record, _ = self._load(db, connector_id)
            self._expected(record, body)
            record.update(deleted=True, enabled=False, credential_present=False)
            return record, None

        return self._write(actor, "delete_local_connector", connector_id, change)
