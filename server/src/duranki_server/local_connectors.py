"""Local model-server inventory and explicit connection/model selection."""
from __future__ import annotations

from .observability import log_failure

import hashlib
import http.client
import ipaddress
import json
from pathlib import Path
import socket
import ssl
import time
import uuid
from urllib.parse import urlsplit, urlunsplit

from .secret_box import SecretBox, validate_secret

from .registry import timestamp
from .store import encode
from .connector_availability import AvailabilityMonitor


KINDS = {
    "ollama": {"name": "Ollama", "default_url": "http://localhost:11434", "api": "ollama"},
    "lmstudio": {"name": "LM Studio", "default_url": "http://localhost:1234", "api": "openai"},
    "vllm": {"name": "vLLM", "default_url": "http://localhost:8000", "api": "openai"},
    "llamacpp": {"name": "llama.cpp", "default_url": "http://localhost:8080", "api": "openai"},
    "localai": {"name": "LocalAI", "default_url": "http://localhost:8080", "api": "openai"},
    "openai_compatible": {"name": "Other OpenAI-compatible server", "default_url": "http://localhost:8000", "api": "openai"},
}
MAX_MODELS = 1000
MAX_RESPONSE = 1024 * 1024
ROUTES = {"/api/tags", "/api/ps", "/api/version", "/v1/models"}
NETWORKS = tuple(ipaddress.ip_network(value) for value in
                 ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "::1/128", "fc00::/7"))
COMMON_SERVERS = (
    ("ollama", 11434, "Ollama API", "Ollama"),
    ("openai_compatible", 1234, "Local model API :1234", "Often LM Studio"),
    ("openai_compatible", 8080, "Local model API :8080", "Often llama.cpp or LocalAI"),
    ("openai_compatible", 8081, "Local model API :8081", "LocalAI test port"),
    ("openai_compatible", 8000, "Local model API :8000", "Often vLLM"),
    ("openai_compatible", 9997, "Local model API :9997", "Often Xinference"),
    ("openai_compatible", 30000, "Local model API :30000", "Often SGLang"),
)


class ConnectorError(ValueError):
    def __init__(self, code, status=400):
        super().__init__(code)
        self.code, self.status = code, status


def allowed_address(value):
    try:
        address = ipaddress.ip_address(value)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        return any(address.version == network.version and address in network for network in NETWORKS)
    except ValueError:
        return False


def normalize_url(value, kind="openai_compatible"):
    if type(value) is not str or not value.strip() or len(value) > 512:
        raise ConnectorError("INVALID_SERVER_URL")
    value = value.strip()
    if any(ord(char) < 33 for char in value) or "\\" in value:
        raise ConnectorError("INVALID_SERVER_URL")
    try:
        url = urlsplit(value)
        port = url.port
        if (url.scheme not in ("http", "https") or not url.hostname or url.username is not None or
                url.password is not None or url.query or url.fragment or
                (port is not None and not 1 <= port <= 65535) or "%" in url.hostname):
            raise ValueError()
        host = url.hostname.encode("idna").decode("ascii").lower()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if any(char not in "abcdefghijklmnopqrstuvwxyz0123456789.-_" for char in host):
                raise ValueError()
        else:
            if not allowed_address(host):
                raise ConnectorError("LOCAL_ADDRESS_REQUIRED")
        path = url.path.rstrip("/")
        if path not in (("",) if kind == "ollama" else ("", "/v1")):
            raise ConnectorError("USE_SERVER_ORIGIN_OR_V1")
        authority = "[" + host + "]" if ":" in host else host
        if port is not None:
            authority += ":" + str(port)
        return urlunsplit((url.scheme, authority, path, "", ""))
    except (ValueError, UnicodeError) as exc:
        if isinstance(exc, ConnectorError):
            raise
        raise ConnectorError("INVALID_SERVER_URL") from exc


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ConnectorError("INVALID_SERVER_RESPONSE", 502)
        result[key] = value
    return result


def _reject_constant(_value):
    raise ConnectorError("INVALID_SERVER_RESPONSE", 502)


def _read_json(base_url, path, api_key, *, timeout=3):
    """GET one fixed inventory path, with pinned local DNS and a bounded body."""
    if path not in ROUTES:
        raise ConnectorError("INVALID_DISCOVERY_PATH")
    url = urlsplit(normalize_url(base_url))
    host, port = url.hostname, url.port or (443 if url.scheme == "https" else 80)
    deadline = time.monotonic() + timeout
    raw = stream = None
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        if not addresses or any(not allowed_address(item[4][0]) for item in addresses):
            raise ConnectorError("LOCAL_ADDRESS_REQUIRED")
        addresses = sorted(addresses, key=lambda item: item[0] != socket.AF_INET)
        last_error = None
        for family, socktype, protocol, _, address in addresses[:8]:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError()
            raw = socket.socket(family, socktype, protocol)
            raw.settimeout(remaining)
            try:
                raw.connect(address)
                break
            except OSError as exc:
                last_error = exc
                raw.close()
                raw = None
        if raw is None:
            raise last_error or OSError()
        stream = raw
        if url.scheme == "https":
            stream = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError()
        stream.settimeout(remaining)
        authority = ("[" + host + "]") if ":" in host else host
        if port != (443 if url.scheme == "https" else 80):
            authority += ":" + str(port)
        request = (f"GET {path} HTTP/1.1\r\nHost: {authority}\r\nAccept: application/json\r\n"
                   "Accept-Encoding: identity\r\nConnection: close\r\n")
        if api_key:
            request += "Authorization: Bearer " + api_key + "\r\n"
        stream.sendall((request + "\r\n").encode("ascii"))
        response = http.client.HTTPResponse(stream)
        response.begin()
        if 300 <= response.status <= 399:
            raise ConnectorError("REDIRECT_NOT_ALLOWED", 502)
        if response.status in (401, 403):
            raise ConnectorError("SERVER_AUTHENTICATION_REQUIRED", 502)
        if response.status == 404:
            raise ConnectorError("DISCOVERY_ENDPOINT_NOT_FOUND", 502)
        if response.status == 429:
            raise ConnectorError("SERVER_RATE_LIMITED", 502)
        if response.status != 200:
            raise ConnectorError("SERVER_UNAVAILABLE", 502)
        content_type = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
        if not (content_type == "application/json" or content_type.startswith("application/") and content_type.endswith("+json")):
            raise ConnectorError("INVALID_SERVER_RESPONSE", 502)
        if response.getheader("Content-Encoding", "identity").lower() != "identity":
            raise ConnectorError("COMPRESSED_RESPONSE_NOT_SUPPORTED", 502)
        if response.length is not None and response.length > MAX_RESPONSE:
            raise ConnectorError("SERVER_RESPONSE_TOO_LARGE", 502)
        data = bytearray()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError()
            stream.settimeout(remaining)
            chunk = response.read1(min(16384, MAX_RESPONSE + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > MAX_RESPONSE:
                raise ConnectorError("SERVER_RESPONSE_TOO_LARGE", 502)
        return json.loads(data, object_pairs_hook=_pairs, parse_constant=_reject_constant)
    except ConnectorError:
        raise
    except socket.gaierror as exc:
        raise ConnectorError("SERVER_NAME_NOT_RESOLVED", 502) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise ConnectorError("SERVER_TIMEOUT", 502) from exc
    except ssl.SSLError as exc:
        raise ConnectorError("SERVER_TLS_FAILED", 502) from exc
    except (ValueError, UnicodeError, http.client.HTTPException) as exc:
        raise ConnectorError("INVALID_SERVER_RESPONSE", 502) from exc
    except PermissionError as exc:
        raise ConnectorError("SERVER_CHECK_BLOCKED", 502) from exc
    except OSError as exc:
        raise ConnectorError("SERVER_UNREACHABLE", 502) from exc
    finally:
        if stream is not None:
            stream.close()
        if raw is not None and raw is not stream:
            raw.close()


def _text(value, secret, *, required=False, limit=240):
    if value is None and not required:
        return None
    if (type(value) is not str or not value or len(value) > limit or
            any(ord(char) < 32 for char in value)):
        raise ConnectorError("INVALID_SERVER_RESPONSE", 502)
    if secret and secret in value:
        if required:
            raise ConnectorError("INVALID_SERVER_RESPONSE", 502)
        return None
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ConnectorError("INVALID_SERVER_RESPONSE", 502) from exc
    return value


def _integer(value):
    return value if type(value) is int and 0 <= value <= 2**53 - 1 else None


def discover(kind, base_url, api_key="", *, read=None):
    read = read or _read_json
    base_url = normalize_url(base_url, kind)
    spec = KINDS[kind]
    value = read(base_url, "/api/tags" if spec["api"] == "ollama" else "/v1/models", api_key)
    rows = value.get("models" if spec["api"] == "ollama" else "data") if type(value) is dict else None
    if type(rows) is not list or any(type(row) is not dict for row in rows):
        raise ConnectorError("INVALID_SERVER_RESPONSE", 502)
    result = {"state": "observed", "models": [], "checked_at": timestamp(),
              "complete": len(rows) <= MAX_MODELS and not bool(value.get("has_more") or value.get("next_page")),
              "server_version": None, "loaded_inventory_available": False, "warnings": []}
    seen = set()
    for row in rows[:MAX_MODELS]:
        model_id = _text((row.get("model") or row.get("name")) if spec["api"] == "ollama" else row.get("id"), api_key, required=True)
        if model_id in seen:
            raise ConnectorError("DUPLICATE_MODEL_ID", 502)
        seen.add(model_id)
        details = row.get("details") if type(row.get("details")) is dict else {}
        model = {"id": model_id, "loaded": None}
        if spec["api"] == "ollama":
            model.update(size_bytes=_integer(row.get("size")), modified_at=_text(row.get("modified_at"), api_key),
                         digest=_text(row.get("digest"), api_key), family=_text(details.get("family"), api_key),
                         format=_text(details.get("format"), api_key),
                         parameter_size=_text(details.get("parameter_size"), api_key),
                         quantization=_text(details.get("quantization_level"), api_key))
        else:
            model.update(owned_by=_text(row.get("owned_by"), api_key),
                         context_window=_integer(row.get("max_model_len") or row.get("context_length")))
        result["models"].append(model)
    if spec["api"] == "ollama":
        try:
            loaded = read(base_url, "/api/ps", api_key)
            if type(loaded) is not dict or type(loaded.get("models")) is not list or len(loaded["models"]) > MAX_MODELS:
                raise ConnectorError("INVALID_SERVER_RESPONSE", 502)
            loaded_models = {}
            for row in loaded["models"]:
                if type(row) is not dict:
                    raise ConnectorError("INVALID_SERVER_RESPONSE", 502)
                model_id = _text(row.get("model") or row.get("name"), api_key, required=True)
                if model_id in loaded_models:
                    raise ConnectorError("DUPLICATE_MODEL_ID", 502)
                loaded_models[model_id] = _integer(row.get("size_vram"))
            for model in result["models"]:
                model["loaded"] = model["id"] in loaded_models
                model["vram_bytes"] = loaded_models.get(model["id"])
            result["loaded_inventory_available"] = True
        except ConnectorError as exc:
            result["warnings"].append({"operation": "loaded_models", "code": exc.code})
        try:
            version = read(base_url, "/api/version", api_key)
            result["server_version"] = _text(version.get("version") if type(version) is dict else None, api_key, required=True)
        except ConnectorError as exc:
            result["warnings"].append({"operation": "server_version", "code": exc.code})
    return result


def connector_key_path(database):
    if str(database) == ":memory:":
        raise ValueError("an explicit connector key path is required for an in-memory store")
    return Path(str(database) + ".secrets") / "local-connectors.keys.json"


def connector_context(connector_id):
    return encode({"connector_id": connector_id}).encode()


def reencrypt_connectors(store, box):
    def rewrite():
        changed = 0
        for identifier, raw in store.db.execute(
                "SELECT id,secret FROM local_connectors WHERE secret IS NOT NULL").fetchall():
            envelope = json.loads(raw)
            context = connector_context(identifier)
            value = box.open(envelope, context)
            if envelope["key_id"] != box.active_id:
                store.db.execute("UPDATE local_connectors SET secret=? WHERE id=?",
                                 (encode(box.seal(value, context)), identifier))
                changed += 1
        return changed
    return store._transaction(rewrite)


class LocalConnectors:
    def __init__(self, registry, *, discover_fn=None, availability_read=None, key_path=None):
        self.registry, self.store = registry, registry.store
        self.discover_fn = discover_fn or discover
        self.availability_read = availability_read
        self.monitor = AvailabilityMonitor()
        def migrate():
            self.store.db.execute("CREATE TABLE IF NOT EXISTS local_connectors "
                                  "(id TEXT PRIMARY KEY,record TEXT NOT NULL,secret TEXT)")
        self.store._transaction(migrate)
        with self.store._lock:
            rows = self.store.db.execute("SELECT secret FROM local_connectors WHERE secret IS NOT NULL").fetchall()
        known = {json.loads(row[0])["key_id"] for row in rows}
        self.key_path = Path(key_path) if key_path else connector_key_path(self.store.path)
        self.box = SecretBox(self.key_path, "local-connector-credentials", required_ids=known)

    def _authorize(self, db, actor, *, write=False):
        row = db.execute("SELECT record FROM registry_principals WHERE id=?", (actor,)).fetchone()
        principal = json.loads(row[0]) if row else None
        roles = ("registry_admin",) if write else ("registry_admin", "read_only_operator")
        if not principal or principal["status"] != "active" or principal["role"] not in roles:
            raise ConnectorError("ADMIN_REQUIRED" if write else "OPERATOR_REQUIRED", 403)

    def _load(self, db, connector_id):
        row = db.execute("SELECT record,secret FROM local_connectors WHERE id=?", (connector_id,)).fetchone()
        if not row:
            raise ConnectorError("CONNECTOR_NOT_FOUND", 404)
        record = json.loads(row[0])
        if record.get("deleted"):
            raise ConnectorError("CONNECTOR_NOT_FOUND", 404)
        return record, row[1]

    def _seal(self, connector_id, value):
        if value == "":
            return None
        try:
            validate_secret(value)
        except ValueError as exc:
            raise ConnectorError("INVALID_API_KEY") from exc
        try:
            return encode(self.box.seal(value, connector_context(connector_id)))
        except Exception as exc:
            log_failure('local_connectors.LocalConnectors._seal.failed')
            raise ConnectorError("CREDENTIAL_STORAGE_UNAVAILABLE", 503) from exc

    def _resolve(self, connector_id, sealed):
        if not sealed:
            return ""
        try:
            return self.box.open(json.loads(sealed), connector_context(connector_id))
        except Exception as exc:
            log_failure('local_connectors.LocalConnectors._resolve.failed')
            raise ConnectorError("CREDENTIAL_UNAVAILABLE", 503) from exc

    def reencrypt_secrets(self):
        return reencrypt_connectors(self.store, self.box)

    def rotate_encryption_key(self):
        identifier = self.box.rotate()
        return {"key_id": identifier, "rewritten": self.reencrypt_secrets()}

    @staticmethod
    def _configuration(record):
        return hashlib.sha256(encode({key: record[key] for key in
            ("kind", "base_url", "credential_version")}).encode()).hexdigest()

    def _public(self, record):
        discovery = record["discovery"]
        current = discovery.get("configuration") == self._configuration(record)
        available = {model["id"] for model in discovery.get("models", [])}
        usable = bool(record["enabled"] and current and discovery["state"] == "observed" and
                      discovery.get("complete") and record["selected_models"] and
                      set(record["selected_models"]) <= available)
        return {**record, "status": "connected" if usable else "needs_attention" if record["enabled"] else
                "disabled" if record["selected_models"] else "not_configured", "usable": usable,
                "availability": self.monitor.get(record["connector_id"], self._configuration(record))}

    def close(self):
        self.monitor.close()

    @staticmethod
    def _availability_error(exc):
        if exc.code in ("CONNECTOR_CHANGED", "CONNECTOR_NOT_FOUND", "ADMIN_REQUIRED", "OPERATOR_REQUIRED"):
            return {"state": "unknown", "reason": "CHECK_CANCELLED", "reachable": None}
        if exc.code == "SERVER_CHECK_BLOCKED":
            return {"state": "blocked", "reason": exc.code, "reachable": None}
        if exc.code in ("SERVER_UNREACHABLE", "SERVER_TIMEOUT", "SERVER_NAME_NOT_RESOLVED"):
            return {"state": "offline", "reason": exc.code, "reachable": False}
        reached = exc.code in ("SERVER_AUTHENTICATION_REQUIRED", "DISCOVERY_ENDPOINT_NOT_FOUND", "SERVER_UNAVAILABLE",
                               "SERVER_RATE_LIMITED", "SERVER_TLS_FAILED", "INVALID_SERVER_RESPONSE",
                               "REDIRECT_NOT_ALLOWED", "SERVER_RESPONSE_TOO_LARGE", "COMPRESSED_RESPONSE_NOT_SUPPORTED")
        return {"state": "attention", "reason": exc.code, "reachable": True if reached else None}

    def _probe_availability(self, record, key):
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
            models = value.get("models" if path == "/api/tags" else "data") if type(value) is dict else None
            if type(models) is not list or any(type(model) is not dict for model in models):
                raise ConnectorError("INVALID_SERVER_RESPONSE", 502)
            return {"state": "online", "reason": "API_RESPONDED", "reachable": True, "model_count": len(models)}
        except ConnectorError as exc:
            return self._availability_error(exc)

    def _saved_check(self, actor, record):
        try:
            with self.store._lock:
                self._authorize(self.store.db, actor)
                current, sealed = self._load(self.store.db, record["connector_id"])
                if self._configuration(current) != self._configuration(record):
                    raise ConnectorError("CONNECTOR_CHANGED", 409)
            return self._probe_availability(record, self._resolve(record["connector_id"], sealed))
        except ConnectorError as exc:
            return self._availability_error(exc)

    def availability(self, actor, body=None):
        """Read cached status, or queue bounded checks without changing records."""
        with self.store._lock:
            self._authorize(self.store.db, actor)
            if body is not None:
                self._fields(body, (), ("connector_ids", "force"))
                ids = body.get("connector_ids")
                if (ids is not None and (type(ids) is not list or len(ids) > 64 or
                        any(type(value) is not str for value in ids) or len(set(ids)) != len(ids)) or
                        type(body.get("force", False)) is not bool):
                    raise ConnectorError("INVALID_AVAILABILITY_CHECK")
            else:
                ids = None
            rows = self.store.db.execute("SELECT record FROM local_connectors ORDER BY id").fetchall()
            records = [record for row in rows if not (record := json.loads(row[0])).get("deleted")]
            if ids is not None:
                found = {record["connector_id"] for record in records}
                if not set(ids) <= found:
                    raise ConnectorError("CONNECTOR_NOT_FOUND", 404)
                records = [record for record in records if record["connector_id"] in ids]
        items = []
        # Give never-checked and older entries room when the bounded queue is full.
        records.sort(key=lambda record: self.monitor.get(record["connector_id"], self._configuration(record)).get("checked_at") or "")
        for record in records:
            identifier, configuration = record["connector_id"], self._configuration(record)
            status = self.monitor.get(identifier, configuration)
            if body is not None:
                status = self.monitor.request(identifier, configuration,
                    lambda record=record: self._saved_check(actor, record), force=body.get("force", False))
            items.append({"connector_id": identifier, "availability": status})
        return {"items": items, "refresh_seconds": 15}

    @staticmethod
    def _endpoint(record):
        url = urlsplit(record["base_url"])
        host = "localhost" if url.hostname in ("localhost", "127.0.0.1", "::1") else url.hostname
        return KINDS[record["kind"]]["api"], url.scheme, host, url.port or (443 if url.scheme == "https" else 80)

    def nearby(self, actor, body=None):
        """Check a fixed set of loopback APIs only after an administrator asks."""
        with self.store._lock:
            self._authorize(self.store.db, actor, write=True)
            if body is not None:
                self._fields(body, (), ("force",))
                if type(body.get("force", False)) is not bool:
                    raise ConnectorError("INVALID_AVAILABILITY_CHECK")
            rows = [json.loads(row[0]) for row in self.store.db.execute("SELECT record FROM local_connectors ORDER BY id")]
            saved = {self._endpoint(record): record["connector_id"] for record in rows if not record.get("deleted")}
        items = []
        for kind, port, name, hint in COMMON_SERVERS:
            record = {"connector_id": "nearby." + str(port), "kind": kind,
                      "base_url": "http://localhost:" + str(port), "credential_version": 0}
            identifier, configuration = record["connector_id"], self._configuration(record)
            status = self.monitor.get(identifier, configuration)
            if body is not None:
                def check(record=record):
                    try:
                        with self.store._lock:
                            self._authorize(self.store.db, actor, write=True)
                        return self._probe_availability(record, "")
                    except ConnectorError as exc:
                        return self._availability_error(exc)
                status = self.monitor.request(identifier, configuration, check, force=body.get("force", False))
            items.append({"candidate_id": identifier, "kind": kind, "base_url": record["base_url"],
                          "display_name": name, "hint": hint, "availability": status,
                          "saved_connector_id": saved.get(self._endpoint(record))})
        return {"items": items}

    def list(self, actor):
        with self.store._lock:
            self._authorize(self.store.db, actor)
            records = [json.loads(row[0]) for row in self.store.db.execute("SELECT record FROM local_connectors ORDER BY id")]
            return {"items": [self._public(record) for record in records if not record.get("deleted")], "kinds": KINDS}

    def get(self, actor, connector_id):
        with self.store._lock:
            self._authorize(self.store.db, actor)
            return self._public(self._load(self.store.db, connector_id)[0])

    @staticmethod
    def _fields(body, required, optional=()):
        if type(body) is not dict or set(body) - set(required) - set(optional) or set(required) - set(body):
            raise ConnectorError("INVALID_CONNECTOR_CHANGE")

    @staticmethod
    def _profile(body):
        name, kind = body["display_name"], body["kind"]
        if type(name) is not str or not name.strip() or len(name) > 120 or any(ord(char) < 32 for char in name):
            raise ConnectorError("INVALID_CONNECTOR_NAME")
        try:
            name.encode("utf-8")
        except UnicodeError as exc:
            raise ConnectorError("INVALID_CONNECTOR_NAME") from exc
        if type(kind) is not str or kind not in KINDS:
            raise ConnectorError("UNSUPPORTED_CONNECTOR")
        return name.strip(), kind, normalize_url(body["base_url"], kind)

    @staticmethod
    def _expected(record, body):
        if type(body["expected_revision"]) is not int or body["expected_revision"] != record["revision"]:
            raise ConnectorError("CONNECTOR_CHANGED", 409)

    def _write(self, actor, action, connector_id, change):
        with self.registry.send_authority.gate:
            def transaction():
                db = self.store.db
                self._authorize(db, actor, write=True)
                record, secret = change(db)
                old = record["revision"]
                record.update(revision=old + 1, updated_at=timestamp())
                db.execute("INSERT INTO local_connectors VALUES (?,?,?) ON CONFLICT(id) DO UPDATE "
                           "SET record=excluded.record,secret=excluded.secret", (connector_id, encode(record), secret))
                revision = int(db.execute("SELECT value FROM registry_meta WHERE key='authority_revision'").fetchone()[0]) + 1
                db.execute("UPDATE registry_meta SET value=? WHERE key='authority_revision'", (str(revision),))
                db.execute("INSERT INTO registry_audit (actor,action,subject,old_revision,new_revision,authority_revision,at) "
                           "VALUES (?,?,?,?,?,?,?)", (actor, action, connector_id, old or None, record["revision"], revision, timestamp()))
                return self._public(record), revision
            result, revision = self.store._transaction(transaction)
            self.registry.send_authority.epoch = revision
            return result

    def create(self, actor, body):
        self._fields(body, ("display_name", "kind", "base_url"), ("api_key",))
        name, kind, url = self._profile(body)
        connector_id = "connector.local." + uuid.uuid4().hex
        def change(db):
            sealed = self._seal(connector_id, body.get("api_key", ""))
            return {"connector_id": connector_id, "display_name": name, "kind": kind, "base_url": url,
                    "revision": 0, "created_at": timestamp(), "enabled": False, "selected_models": [],
                    "credential_present": bool(sealed), "credential_version": 1 if sealed else 0,
                    "discovery": {"state": "not_checked", "models": []}}, sealed
        return self._write(actor, "create_local_connector", connector_id, change)

    def update(self, actor, connector_id, body):
        self._fields(body, ("display_name", "kind", "base_url", "expected_revision"), ("api_key",))
        name, kind, url = self._profile(body)
        def change(db):
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
            record.update(display_name=name, kind=kind, base_url=url, credential_present=bool(sealed))
            if changed:
                record.update(enabled=False, selected_models=[], discovery={"state": "not_checked", "models": []})
            return record, sealed
        return self._write(actor, "update_local_connector", connector_id, change)

    def discover(self, actor, connector_id, body):
        self._fields(body, ("expected_revision",))
        with self.store._lock:
            self._authorize(self.store.db, actor, write=True)
            record, sealed = self._load(self.store.db, connector_id)
            self._expected(record, body)
        try:
            result = self.discover_fn(record["kind"], record["base_url"], self._resolve(connector_id, sealed))
        except ConnectorError as exc:
            result = {"state": "failed", "reason": exc.code, "checked_at": timestamp(), "models": [], "complete": False}
        result["configuration"] = self._configuration(record)
        def change(db):
            current, current_secret = self._load(db, connector_id)
            self._expected(current, body)
            current["discovery"] = result
            return current, current_secret
        return self._write(actor, "discover_local_models", connector_id, change)

    def configure(self, actor, connector_id, body):
        self._fields(body, ("expected_revision", "selected_models", "enabled"))
        models = body["selected_models"]
        if (type(models) is not list or len(models) > MAX_MODELS or
                any(type(model) is not str for model in models) or len(set(models)) != len(models) or
                type(body["enabled"]) is not bool):
            raise ConnectorError("INVALID_MODEL_SELECTION")
        def change(db):
            record, sealed = self._load(db, connector_id)
            self._expected(record, body)
            available = {model["id"] for model in record["discovery"].get("models", [])}
            if body["enabled"] and (not models or record["discovery"]["state"] != "observed" or
                    not record["discovery"].get("complete") or not set(models) <= available or
                    record["discovery"].get("configuration") != self._configuration(record)):
                raise ConnectorError("DISCOVER_AND_SELECT_MODELS_FIRST", 409)
            if not set(models) <= available and models != record["selected_models"]:
                raise ConnectorError("INVALID_MODEL_SELECTION")
            record.update(selected_models=models, enabled=body["enabled"])
            return record, sealed
        return self._write(actor, "configure_local_models", connector_id, change)

    def delete(self, actor, connector_id, body):
        self._fields(body, ("expected_revision",))
        def change(db):
            record, _ = self._load(db, connector_id)
            self._expected(record, body)
            record.update(deleted=True, enabled=False, credential_present=False)
            return record, None
        return self._write(actor, "delete_local_connector", connector_id, change)
