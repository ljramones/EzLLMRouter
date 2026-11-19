"""Trusted, versioned local authority for synthetic models and principals.

All successful mutations share the owned sender's first-byte gate. The SQLite
commit precedes the visible epoch change, and the gate is held until both are
complete. A failed commit leaves the old epoch and records untouched.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from datetime import timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import json
import re
import secrets
import threading
import time

from .canonical import ContractError
from .catalogue import operator_reference_price, validate_catalogue
from .store import encode
from .provider_adapters import ADAPTERS, PROVIDERS, validate_settings
from .provider_adapters import probe as provider_probe
from .attribution import AttributionLedger
from .cache_accounting import SEMANTICS as CACHE_SEMANTICS, validate_contract
from .integration_accounting import ExternalAccounting


IDENT = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
MODELS = {"model.demo", "model.demo.alt"}
DESTINATION = ("configuration_ref", "service", "endpoint", "model", "model_version", "processing_region")
RATE_CATEGORIES = ("input_uncached", "input_cache_read", "input_cache_write", "output_text",
                   "output_reasoning", "other_billable")


def timestamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def identifier(value):
    if type(value) is not str or not IDENT.fullmatch(value):
        raise ValueError("invalid identifier")
    return value


def nonempty(value, limit=160):
    if type(value) is not str or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError("invalid text")
    return value.strip()


def exact_rate(value):
    if type(value) is not str or not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,12})?", value):
        raise ValueError("invalid decimal rate")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid decimal rate") from exc
    if not amount.is_finite() or amount < 0 or amount > Decimal("1000000"):
        raise ValueError("invalid decimal rate")
    return format(amount, "f")


def safe_audit_values(record):
    """Allowlist public management facts; never snapshot secrets or free-text payloads."""
    if not record:
        return None
    return {key: record[key] for key in ("display_name", "status", "role", "price_version",
                                          "credential_state", "credential_version") if key in record}


class RegistryConflict(ValueError):
    pass


class Registry:
    """Single-process authority with additive DEV-06 SQLite migration."""

    def __init__(self, store, send_authority, *, legacy_destination=None,
                 legacy_token=None, legacy_trusted=None, provider_vault=None,
                 provider_execution_ready=False, controlled_provider_proof=False,
                 integration_feature_policy=None, integration_accounting_retention_days=None):
        self.store = store
        self.send_authority = send_authority
        self.runtime_ready = lambda: not getattr(self.send_authority, "revoked", False)
        self.provider_vault = provider_vault
        self.provider_execution_ready = provider_execution_ready
        self.controlled_provider_proof = controlled_provider_proof
        self._probe_lock = threading.Lock()
        self._operator_tokens = {}
        self._migrate(legacy_destination, legacy_token, legacy_trusted)
        self.attribution = AttributionLedger(self)
        self.integration = ExternalAccounting(self)
        self.integration.feature_policy = integration_feature_policy
        self.integration.accounting_retention_days = integration_accounting_retention_days
        self.integration.expire_datasets()

    def readiness(self, model):
        if model.get("kind") == "real_catalogue":
            return "not_connected"
        if model.get("kind") == "provider_deployment":
            if not self.provider_execution_ready:
                return "provider_path_unvalidated"
            destination = model["destination"]
            connection = self.connection(destination["connection_id"])
            if (not connection or connection["status"] != "active" or
                    connection["revision"] != destination["connection_revision"] or
                    connection["credential_state"] != "present" or
                    connection["credential_version"] != destination["credential_version"] or
                    connection["adapter_id"] != destination["adapter_id"]):
                return "provider_connection_stale"
            if not self.source_model_allowed(destination["connection_id"], destination["model"]):
                return "source_model_disallowed"
            return "provider_https_configured" if self.runtime_ready() else "transport_unavailable"
        if model["destination"]["model"] not in MODELS:
            return "unsupported"
        try:
            return "synthetic_http1_ready" if self.runtime_ready() else "transport_unavailable"
        except Exception:
            return "transport_unavailable"

    def _migrate(self, destination, token, trusted):
        with self.send_authority.gate:
            def action():
                db = self.store.db
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, 7):
                    raise RuntimeError("unknown database schema version")
                for sql in (
                    "CREATE TABLE IF NOT EXISTS registry_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
                    "CREATE TABLE IF NOT EXISTS registry_models (ref TEXT PRIMARY KEY, record TEXT NOT NULL)",
                    "CREATE TABLE IF NOT EXISTS registry_principals (id TEXT PRIMARY KEY, record TEXT NOT NULL)",
                    "CREATE TABLE IF NOT EXISTS registry_grants (principal_id TEXT NOT NULL, config_ref TEXT NOT NULL, record TEXT NOT NULL, PRIMARY KEY(principal_id,config_ref))",
                    "CREATE TABLE IF NOT EXISTS registry_prices (config_ref TEXT NOT NULL, price_version TEXT NOT NULL, record TEXT NOT NULL, PRIMARY KEY(config_ref,price_version))",
                    "CREATE TABLE IF NOT EXISTS registry_credentials (verifier TEXT PRIMARY KEY, principal_id TEXT NOT NULL, credential_id TEXT NOT NULL)",
                    "CREATE TABLE IF NOT EXISTS registry_operations (operation_id TEXT PRIMARY KEY, actor TEXT NOT NULL, request_hash TEXT NOT NULL, result TEXT NOT NULL)",
                    "CREATE TABLE IF NOT EXISTS registry_connections (id TEXT PRIMARY KEY, record TEXT NOT NULL)",
                    "CREATE TABLE IF NOT EXISTS registry_deployments (id TEXT PRIMARY KEY, record TEXT NOT NULL)",
                    "CREATE TABLE IF NOT EXISTS registry_observations (operation_id TEXT PRIMARY KEY, connection_id TEXT NOT NULL, record TEXT NOT NULL)",
                    "CREATE TABLE IF NOT EXISTS registry_source_permissions (id TEXT PRIMARY KEY, record TEXT NOT NULL)",
                    "CREATE TABLE IF NOT EXISTS registry_audit (seq INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT NOT NULL, action TEXT NOT NULL, subject TEXT NOT NULL, old_revision INTEGER, new_revision INTEGER NOT NULL, authority_revision INTEGER NOT NULL, at TEXT NOT NULL)",
                    "CREATE TABLE IF NOT EXISTS registry_audit_values (seq INTEGER PRIMARY KEY REFERENCES registry_audit(seq), before_json TEXT, after_json TEXT)",
                    "CREATE TABLE IF NOT EXISTS registry_agents (id TEXT PRIMARY KEY, record TEXT NOT NULL)",
                    "CREATE TABLE IF NOT EXISTS registry_agent_permissions (id TEXT PRIMARY KEY, caller_id TEXT NOT NULL, agent_id TEXT NOT NULL, user_id TEXT NOT NULL, record TEXT NOT NULL, UNIQUE(caller_id,agent_id,user_id))",
                    "CREATE TABLE IF NOT EXISTS registry_outcome_authorities (id TEXT PRIMARY KEY, record TEXT NOT NULL)",
                    "CREATE TABLE IF NOT EXISTS attribution_runs (id TEXT PRIMARY KEY, record TEXT NOT NULL)",
                    "CREATE TABLE IF NOT EXISTS attribution_outcomes (principal_id TEXT NOT NULL, event_id TEXT NOT NULL, subject TEXT NOT NULL, revision INTEGER NOT NULL, digest TEXT NOT NULL, event TEXT NOT NULL, recorded_at TEXT NOT NULL, receipt TEXT NOT NULL, PRIMARY KEY(principal_id,event_id), UNIQUE(subject,revision))"
                ):
                    db.execute(sql)
                row = db.execute("SELECT value FROM registry_meta WHERE key='schema_version'").fetchone()
                if row and row[0] not in ("1", "2"):
                    raise RuntimeError("unknown registry schema version")
                if row and row[0] == "1":
                    db.execute("UPDATE registry_meta SET value='2' WHERE key='schema_version'")
                if not row:
                    if version == 7:
                        raise RuntimeError("registry marker missing")
                    if destination is None or token is None or trusted is None:
                        raise RuntimeError("private legacy bootstrap inputs required")
                    at = timestamp()
                    model = {"configuration_ref": destination["configuration_ref"],
                             "display_name": "Legacy synthetic demo", "status": "enabled",
                             "revision": 1, "destination": {k: destination[k] for k in DESTINATION},
                             "owner": "owner.local", "capabilities": ["text", "tools"],
                             "purposes": ["execution"], "task_classes": ["class.demo"],
                             "handling": ["no.content.store"], "approved_by": "owner.local",
                             "approved_at": at, "legacy_unpriced": True}
                    owner = {"principal_id": "owner.local", "display_name": "Local owner",
                             "kind": "human", "owner": "owner.local", "status": "active",
                             "role": "registry_admin", "revision": 1, "credential_state": "local_operator"}
                    demo = {"principal_id": trusted["principal_id"], "display_name": "Local demo service",
                            "kind": "service", "owner": trusted["charging_owner_id"],
                            "status": "active", "role": "ordinary", "revision": 1,
                            "credential_state": "bound"}
                    grant = {"principal_id": demo["principal_id"], "configuration_ref": model["configuration_ref"],
                             "status": "active", "revision": 1, "purposes": ["execution"],
                             "task_classes": ["class.demo"], "actor": "owner.local", "at": at}
                    db.execute("INSERT INTO registry_models VALUES (?,?)", (model["configuration_ref"], encode(model)))
                    for principal in (owner, demo):
                        db.execute("INSERT INTO registry_principals VALUES (?,?)",
                                   (principal["principal_id"], encode(principal)))
                    db.execute("INSERT INTO registry_grants VALUES (?,?,?)",
                               (demo["principal_id"], model["configuration_ref"], encode(grant)))
                    db.execute("INSERT INTO registry_credentials VALUES (?,?,?)",
                               (hashlib.sha256(token.encode()).hexdigest(), demo["principal_id"], "legacy.demo"))
                    for key, value in (("schema_version", "2"), ("authority_revision", "1"),
                                       ("bootstrap_source", "private-dev06-local")):
                        db.execute("INSERT INTO registry_meta VALUES (?,?)", (key, value))
                    db.execute("INSERT INTO registry_audit (actor,action,subject,old_revision,new_revision,authority_revision,at) VALUES (?,?,?,?,?,?,?)",
                               ("owner.local", "migrate_dev06", "local.synthetic", None, 1, 1, at))
                    db.execute("PRAGMA user_version=7")
                return int(db.execute("SELECT value FROM registry_meta WHERE key='authority_revision'").fetchone()[0])
            revision = self.store._transaction(action)
            self.send_authority.epoch = revision

    def version(self):
        with self.store._lock:
            row = self.store.db.execute("SELECT value FROM registry_meta WHERE key='authority_revision'").fetchone()
            if not row:
                raise RuntimeError("authority unavailable")
            return int(row[0])

    def _record(self, table, where, args):
        with self.store._lock:
            row = self.store.db.execute(f"SELECT record FROM {table} WHERE {where}", args).fetchone()
        return json.loads(row[0]) if row else None

    def model(self, ref):
        identifier(ref)
        return self._record("registry_models", "ref=?", (ref,))

    def principal(self, principal_id):
        identifier(principal_id)
        return self._record("registry_principals", "id=?", (principal_id,))

    def grant(self, principal_id, ref):
        return self._record("registry_grants", "principal_id=? AND config_ref=?", (principal_id, ref))

    def prices(self, ref):
        identifier(ref)
        with self.store._lock:
            rows = self.store.db.execute("SELECT record FROM registry_prices WHERE config_ref=? ORDER BY rowid",
                                         (ref,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def list_models(self):
        with self.store._lock:
            rows = self.store.db.execute("SELECT record FROM registry_models ORDER BY ref").fetchall()
        return [json.loads(row[0]) for row in rows]

    def list_principals(self):
        with self.store._lock:
            rows = self.store.db.execute("SELECT record FROM registry_principals ORDER BY id").fetchall()
        return [json.loads(row[0]) for row in rows]

    def connection(self, connection_id):
        identifier(connection_id)
        return self._record("registry_connections", "id=?", (connection_id,))

    def list_connections(self):
        with self.store._lock:
            rows = self.store.db.execute("SELECT record FROM registry_connections ORDER BY id").fetchall()
        return [json.loads(row[0]) for row in rows]

    def deployments(self, connection_id):
        identifier(connection_id)
        with self.store._lock:
            rows = self.store.db.execute("SELECT record FROM registry_deployments WHERE json_extract(record,'$.connection_id')=? ORDER BY id", (connection_id,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    @staticmethod
    def _source_key(connection_id, serving_id):
        return hashlib.sha256(encode([connection_id, serving_id]).encode()).hexdigest()

    def source_permission(self, connection_id, serving_id):
        identifier(connection_id)
        if type(serving_id) is not str or not 1 <= len(serving_id) <= 256:
            raise ValueError("invalid serving model ID")
        return self._record("registry_source_permissions", "id=?",
                            (self._source_key(connection_id, serving_id),))

    def source_model_allowed(self, connection_id, serving_id):
        permission = self.source_permission(connection_id, serving_id)
        if permission is not None:
            return permission["allowed"] is True
        # Older explicitly enabled deployments retain their reviewed permission.
        return any(item["serving_id"] == serving_id and item["execution_approved"] is True
                   for item in self.deployments(connection_id))

    def source_inventory(self, connection_id):
        """Connection-scoped stored inventory; reads never probe or change authority."""
        connection = self.connection(connection_id)
        if not connection:
            raise ValueError("unknown connection")
        with self.store._lock:
            observations = [json.loads(row[0]) for row in self.store.db.execute(
                "SELECT record FROM registry_observations WHERE connection_id=? AND "
                "json_extract(record,'$.operation')='inventory' "
                "ORDER BY rowid DESC", (connection_id,)).fetchall()]
            permissions = {json.loads(row[0])["serving_id"]: json.loads(row[0]) for row in
                self.store.db.execute("SELECT record FROM registry_source_permissions WHERE "
                    "json_extract(record,'$.connection_id')=?", (connection_id,)).fetchall()}
        latest = observations[0] if observations else None
        saved = next((item for item in observations if item["state"] in ("observed", "partial")), None)
        prior_complete = (next((item for item in observations[observations.index(saved) + 1:]
                                if item["state"] == "observed"), None)
                          if saved and saved["state"] == "partial" else None)
        snapshot_names = set(saved["models"] if saved else ())
        if prior_complete:
            snapshot_names.update(prior_complete["models"])
        deployments = self.deployments(connection_id)
        by_id = {item["serving_id"]: item for item in deployments}
        names = snapshot_names | set(by_id)
        rows = []
        for serving_id in sorted(names):
            deployment = by_id.get(serving_id)
            model = self.model(deployment["model_ref"]) if deployment and deployment.get("model_ref") else None
            configuration = self.model(deployment["configuration_ref"]) if deployment and deployment.get("configuration_ref") else None
            permission = permissions.get(serving_id)
            allowed = (permission["allowed"] if permission is not None else
                       bool(deployment and deployment["execution_approved"]))
            prices = self.prices(configuration["configuration_ref"]) if configuration else []
            price = prices[-1] if prices else None
            grants = []
            if configuration:
                grants = [grant for principal in self.list_principals()
                          if (grant := self.grant(principal["principal_id"], configuration["configuration_ref"]))]
            rows.append({"serving_id": serving_id, "display_name": model["display_name"] if model else serving_id,
                         "model_ref": deployment.get("model_ref") if deployment else None,
                         "deployment_id": deployment.get("deployment_id") if deployment else None,
                         "configuration_ref": configuration["configuration_ref"] if configuration else None,
                         "model_version": (model or {}).get("catalogue", {}).get("observed_serving_version"),
                         "capabilities": (model or {}).get("catalogue", {}).get("provider_published_capabilities"),
                         "reference_price": (model or {}).get("catalogue", {}).get("price_reference"),
                         "inventory_provenance": ("observed" if saved and serving_id in saved["models"] else
                                                  "retained_previous_snapshot" if serving_id in snapshot_names else
                                                  "manual_association"),
                         "allowed": allowed, "permission_revision": permission["revision"] if permission else 0,
                         "readiness": self.readiness(configuration) if configuration else "unknown",
                         "loaded_running": "unknown",
                         "price": price, "active_grants": sum(g["status"] == "active" for g in grants),
                         "grant_count": len(grants)})
        completeness = ("never_run" if latest is None else "partial" if latest["state"] == "partial" or
                        latest.get("has_more") else "complete" if latest["state"] == "observed" else
                        latest["state"] if latest["state"] in ("failed", "unsupported") else "failed")
        return {"connection": connection, "discovery": {"state": completeness,
                "observed_at": latest.get("observed_at") if latest else None,
                "reason": latest.get("reason") if latest else "never_run",
                "retained_snapshot_at": saved.get("observed_at") if saved else None,
                "snapshot_current": bool(saved and saved["connection_revision"] == connection["revision"] and
                                         saved["credential_version"] == connection["credential_version"]),
                "snapshot_completeness": ("partial" if saved and saved.get("has_more") else
                                          "complete" if saved else "none")},
                "items": rows, "count": len(rows)}

    def observations(self, connection_id):
        identifier(connection_id)
        with self.store._lock:
            rows = self.store.db.execute("SELECT record FROM registry_observations WHERE connection_id=? ORDER BY rowid DESC LIMIT 20", (connection_id,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def _require_admin(self, db, actor):
        row = db.execute("SELECT record FROM registry_principals WHERE id=?", (actor,)).fetchone()
        principal = json.loads(row[0]) if row else None
        if not principal or principal["status"] != "active" or principal["role"] != "registry_admin":
            raise PermissionError("ADMIN_REQUIRED")

    def set_provider_credential(self, actor, connection_id, expected_revision, operation_id,
                                mode, secret=None):
        """Rotate/remove under the same first-write gate as registry authority mutations."""
        identifier(connection_id)
        identifier(operation_id)
        if not self.provider_vault or type(expected_revision) is not int or mode not in ("replace", "remove"):
            raise ValueError("invalid credential operation")
        if mode == "remove" and secret is not None:
            raise ValueError("remove has no credential body")
        if mode == "replace" and type(secret) is not str:
            raise ValueError("credential required")
        digest = hmac.new(self.provider_vault.key,
            encode({"connection_id": connection_id, "expected_revision": expected_revision,
                    "mode": mode, "secret": secret}).encode(), hashlib.sha256).hexdigest()
        with self.send_authority.gate:
            db = self.store.db
            with self.store._lock:
                self._require_admin(db, actor)
                prior = db.execute("SELECT actor,request_hash,result FROM registry_operations WHERE operation_id=?",
                                   (operation_id,)).fetchone()
                if prior:
                    if prior[0] != actor or prior[1] != digest:
                        raise RegistryConflict("operation reuse conflict")
                    return json.loads(prior[2])
                row = db.execute("SELECT record FROM registry_connections WHERE id=?", (connection_id,)).fetchone()
                record = json.loads(row[0]) if row else None
                if not record or record["revision"] != expected_revision or record["status"] == "archived":
                    raise RegistryConflict("connection revision changed")
                old_version = record["credential_version"]
                next_version = old_version + 1
            sealed = None
            if mode == "replace":
                sealed = self.provider_vault.seal(connection_id, next_version, secret)
            try:
                def action():
                    current = json.loads(db.execute("SELECT record FROM registry_connections WHERE id=?",
                        (connection_id,)).fetchone()[0])
                    if current["revision"] != expected_revision:
                        raise RegistryConflict("connection revision changed")
                    current.update(credential_version=next_version,
                        credential_ref=(hashlib.sha256(connection_id.encode()).hexdigest() + f".{next_version}")
                            if mode == "replace" else None,
                        credential_state="present" if mode == "replace" else "absent")
                    current["revision"] += 1
                    db.execute("UPDATE registry_connections SET record=? WHERE id=?", (encode(current), connection_id))
                    revision = int(db.execute("SELECT value FROM registry_meta WHERE key='authority_revision'").fetchone()[0]) + 1
                    db.execute("UPDATE registry_meta SET value=? WHERE key='authority_revision'", (str(revision),))
                    audit = db.execute("INSERT INTO registry_audit (actor,action,subject,old_revision,new_revision,authority_revision,at) VALUES (?,?,?,?,?,?,?)",
                        (actor, "provider_credential_" + mode, connection_id, expected_revision,
                         current["revision"], revision, timestamp()))
                    db.execute("INSERT INTO registry_audit_values VALUES (?,?,?)", (audit.lastrowid,
                        encode(safe_audit_values(record)), encode(safe_audit_values(current))))
                    reply = {"record": current, "authority_revision": revision}
                    db.execute("INSERT INTO registry_operations VALUES (?,?,?,?)",
                               (operation_id, actor, digest, encode(reply)))
                    return reply, revision
                reply, revision = self.store._transaction(action)
            except BaseException:
                if sealed:
                    sealed.unlink(missing_ok=True)
                raise
            self.send_authority.epoch = revision
            self.provider_vault.remove(connection_id, old_version)
            return reply

    def probe_connection(self, actor, connection_id, expected_revision, operation_id, operation):
        identifier(connection_id)
        identifier(operation_id)
        if operation not in ("access", "inventory", "readiness") or type(expected_revision) is not int:
            raise ValueError("invalid probe request")
        # Serialize probes, including duplicate operation IDs, without holding the send gate
        # over DNS, TLS or provider waits.
        with self._probe_lock:
            with self.store._lock:
                self._require_admin(self.store.db, actor)
                old = self.store.db.execute("SELECT record FROM registry_observations WHERE operation_id=?",
                                            (operation_id,)).fetchone()
                if old:
                    saved = json.loads(old[0])
                    if saved["connection_id"] != connection_id or saved["operation"] != operation:
                        raise RegistryConflict("probe operation reuse conflict")
                    return saved
                connection = self.connection(connection_id)
                if not connection or connection["revision"] != expected_revision or connection["status"] in ("disabled", "archived"):
                    raise RegistryConflict("connection unavailable or changed")
            spec = ADAPTERS[connection["adapter_id"]].get(operation)
            if spec is None:
                result = {"state": "unsupported", "reason": "operation_not_implemented", "models": []}
            elif connection["credential_state"] != "present" and operation in ("access", "inventory"):
                result = {"state": "failed", "reason": "credential_unavailable", "models": []}
            else:
                try:
                    credential = (self.provider_vault.resolve(connection_id, connection["credential_version"])
                                  if operation in ("access", "inventory") else None)
                except (OSError, RuntimeError, ValueError):
                    result = {"state": "failed", "reason": "credential_unavailable", "models": []}
                else:
                    result = provider_probe(connection["adapter_id"], connection["settings"],
                                            credential, operation,
                                            controlled=self.controlled_provider_proof)
            now = datetime.now(timezone.utc)
            observation = {"operation_id": operation_id, "connection_id": connection_id,
                "connection_revision": connection["revision"], "credential_version": connection["credential_version"],
                "adapter_id": connection["adapter_id"], "operation": operation,
                "scope": {"access": "credential_model_listing", "inventory": "model_inventory",
                          "readiness": "service_reachability"}[operation],
                "observer": "trusted_local_service", "observed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "expires_at": (now + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ"), **result}
            current = self.connection(connection_id)
            if current["revision"] != connection["revision"]:
                observation.update(state="stale", reason="connection_changed_during_probe", models=[])
            def save():
                self.store.db.execute("INSERT INTO registry_observations VALUES (?,?,?)",
                    (operation_id, connection_id, encode(observation)))
            self.store._transaction(save)
            return observation

    def history(self, subject):
        identifier(subject)
        with self.store._lock:
            rows = self.store.db.execute("SELECT a.actor,a.action,a.old_revision,a.new_revision,"
                                         "a.authority_revision,a.at,v.before_json,v.after_json "
                                         "FROM registry_audit a LEFT JOIN registry_audit_values v ON v.seq=a.seq "
                                         "WHERE a.subject=? ORDER BY a.seq DESC LIMIT 100",
                                         (subject,)).fetchall()
        return [{**dict(zip(("actor", "action", "old_revision", "new_revision", "authority_revision", "at"), row[:6])),
                 "before": json.loads(row[6]) if row[6] else None,
                 "after": json.loads(row[7]) if row[7] else None} for row in rows]

    def credential_principal(self, token, kind=None):
        if type(token) is not str or len(token) < 32:
            raise ContractError("AUTHENTICATION_FAILED", 401)
        verifier = hashlib.sha256(token.encode()).hexdigest()
        with self.store._lock:
            ephemeral = self._operator_tokens.get(verifier)
            if ephemeral and ephemeral[1] > time.monotonic():
                principal = self.principal(ephemeral[0])
                if principal and principal["status"] == "active" and (not kind or principal["kind"] == kind):
                    return principal
            row = self.store.db.execute("SELECT principal_id FROM registry_credentials WHERE verifier=?",
                                        (verifier,)).fetchone()
        principal = self.principal(row[0]) if row else None
        if not principal or principal["status"] != "active" or (kind and principal["kind"] != kind):
            raise ContractError("AUTHENTICATION_FAILED", 401)
        return principal

    def issue_local_operator_token(self, principal_id):
        """Server-only wire credential for one authenticated loopback session."""
        principal = self.principal(principal_id)
        if not principal or principal["status"] != "active" or principal["role"] != "registry_admin":
            raise PermissionError("ADMIN_REQUIRED")
        token = secrets.token_urlsafe(48)
        with self.store._lock:
            self._operator_tokens[hashlib.sha256(token.encode()).hexdigest()] = (
                principal_id, time.monotonic() + 1800)
        return token

    def revoke_local_operator_token(self, token):
        with self.store._lock:
            self._operator_tokens.pop(hashlib.sha256(token.encode()).hexdigest(), None)

    def authenticate(self, token, template):
        principal = self.credential_principal(token)
        trusted = deepcopy(template)
        trusted["principal_id"] = principal["principal_id"]
        trusted["charging_owner_id"] = principal["owner"]
        return trusted

    def explain(self, principal_id, ref, purpose, task_class, features=("text",)):
        principal = self.principal(principal_id)
        model = self.model(ref)
        grant = self.grant(principal_id, ref)
        reason = ("PRINCIPAL_NOT_ACTIVE" if not principal or principal["status"] != "active" else
                  "MODEL_NOT_ENABLED" if not model or model["status"] != "enabled" else
                  "SOURCE_MODEL_DISALLOWED" if model and self.readiness(model) == "source_model_disallowed" else
                  "TRANSPORT_UNAVAILABLE" if self.readiness(model) not in (
                      "synthetic_http1_ready", "provider_https_configured") else
                  "CAPABILITY_UNSUPPORTED" if not set(features) <= set(model["capabilities"]) else
                  "GRANT_MISSING" if not grant or grant["status"] != "active" else
                  "PURPOSE_DENIED" if purpose not in grant["purposes"] or purpose not in model["purposes"] else
                  "TASK_CLASS_DENIED" if task_class not in grant["task_classes"] or
                                         task_class not in model["task_classes"] else "ALLOWED")
        return {"allowed": reason == "ALLOWED", "reason": reason,
                "principal_revision": principal["revision"] if principal else None,
                "model_revision": model["revision"] if model else None,
                "grant_revision": grant["revision"] if grant else None,
                "authority_revision": self.version()}

    def admit(self, principal_id, ref, purpose, task_class, features=("text",)):
        decision = self.explain(principal_id, ref, purpose, task_class, features)
        if not decision["allowed"]:
            raise ContractError("POLICY_DENIED", 403)
        model = self.model(ref)
        prices = self.prices(ref)
        active = prices[-1] if prices else None
        if not model["legacy_unpriced"] and active is None:
            raise ContractError("POLICY_DENIED", 403)
        return deepcopy(model["destination"]), {**decision, "features": list(features),
            "price_version": active["price_version"] if active else "synthetic.unpriced.v1",
            "usage_semantics_version": active["usage_semantics_version"] if active else "synthetic.text.v1",
            "price_schedule": active}

    def check_current(self, principal_id, ref, purpose, task_class, decision):
        current = self.explain(principal_id, ref, purpose, task_class, decision["features"])
        if not current["allowed"] or current["authority_revision"] != decision["authority_revision"]:
            raise ContractError("PLAN_INVALID_OR_STALE", 409)
        return self.model(ref)["destination"]

    def mutate(self, actor, request):
        """Strict idempotent management command; returns committed safe record."""
        if type(request) is not dict or set(request) != {"operation_id", "action", "subject",
                                                  "expected_revision", "data"}:
            raise ValueError("invalid management request")
        op = identifier(request["operation_id"])
        action_name = request["action"]
        subject = identifier(request["subject"])
        expected = request["expected_revision"]
        data = request["data"]
        if type(expected) is not int or expected < 0 or type(data) is not dict:
            raise ValueError("invalid management revision or data")
        request_hash = hashlib.sha256(encode(request).encode()).hexdigest()
        with self.send_authority.gate:
            def action():
                db = self.store.db
                actor_row = db.execute("SELECT record FROM registry_principals WHERE id=?", (actor,)).fetchone()
                actor_record = json.loads(actor_row[0]) if actor_row else None
                if not actor_record or actor_record["status"] != "active" or actor_record["role"] != "registry_admin":
                    raise PermissionError("ADMIN_REQUIRED")
                prior = db.execute("SELECT actor,request_hash,result FROM registry_operations WHERE operation_id=?",
                                   (op,)).fetchone()
                if prior:
                    if prior[0] != actor or prior[1] != request_hash:
                        raise RegistryConflict("operation reuse conflict")
                    return json.loads(prior[2]), None
                if action_name == "import_catalogue":
                    if expected != 0:
                        raise RegistryConflict("catalogue creation requires revision zero")
                    candidate = validate_catalogue(subject, data)
                    row = db.execute("SELECT record FROM registry_models WHERE ref=?", (subject,)).fetchone()
                    if row:
                        existing = json.loads(row[0])
                        if (existing.get("kind") == "real_catalogue" and
                                existing.get("catalogue") == candidate["catalogue"] and
                                existing.get("source_links") == candidate["source_links"]):
                            current = int(db.execute("SELECT value FROM registry_meta WHERE key='authority_revision'").fetchone()[0])
                            return {"record": existing, "authority_revision": current}, None
                        raise RegistryConflict("catalogue import conflicts with existing record")
                table = ("registry_models" if action_name in ("edit_model", "edit_catalogue_model", "model_state",
                    "archive_model", "publish_reference_price", "correct_reference_price") else
                    "registry_connections" if action_name in ("edit_connection", "connection_state",
                    "probe_schedule", "associate_deployment") else
                    "registry_principals" if action_name in ("edit_principal", "principal_state", "set_role") else
                    "registry_agents" if action_name in ("register_agent", "agent_state", "agent_instrumentation") else None)
                prior_row = db.execute(f"SELECT record FROM {table} WHERE {('ref' if table == 'registry_models' else 'id')}=?",
                    (subject,)).fetchone() if table else None
                before = safe_audit_values(json.loads(prior_row[0])) if prior_row else None
                result = self._apply(db, actor, action_name, subject, expected, data)
                current = int(db.execute("SELECT value FROM registry_meta WHERE key='authority_revision'").fetchone()[0])
                revision = current + 1
                db.execute("UPDATE registry_meta SET value=? WHERE key='authority_revision'", (str(revision),))
                audit = db.execute("INSERT INTO registry_audit (actor,action,subject,old_revision,new_revision,authority_revision,at) VALUES (?,?,?,?,?,?,?)",
                           (actor, action_name, subject, expected or None, result["revision"], revision, timestamp()))
                db.execute("INSERT INTO registry_audit_values VALUES (?,?,?)", (audit.lastrowid,
                    encode(before), encode(safe_audit_values(result))))
                reply = {"record": result, "authority_revision": revision}
                db.execute("INSERT INTO registry_operations VALUES (?,?,?,?)",
                           (op, actor, request_hash, encode(reply)))
                return reply, revision
            reply, revision = self.store._transaction(action)
            if revision is not None:
                self.send_authority.epoch = revision
            return reply

    def _apply(self, db, actor, action, subject, expected, data):
        if action in ("register_agent", "agent_state", "agent_instrumentation",
                      "set_agent_permission", "set_outcome_authority"):
            return self.attribution.apply_admin(db, action, subject, expected, data)
        if action == "set_source_permissions":
            if (expected != 0 or set(data) != {"allowed", "items"} or
                    type(data["allowed"]) is not bool or type(data["items"]) is not list or
                    not 1 <= len(data["items"]) <= 100):
                raise ValueError("invalid source-model selection")
            row = db.execute("SELECT record FROM registry_connections WHERE id=?", (subject,)).fetchone()
            connection = json.loads(row[0]) if row else None
            if not connection or connection["status"] == "archived":
                raise ValueError("source connection unavailable")
            discoveries = [json.loads(item[0]) for item in db.execute(
                "SELECT record FROM registry_observations WHERE connection_id=? AND "
                "json_extract(record,'$.operation')='inventory' ORDER BY rowid DESC", (subject,)).fetchall()]
            saved = next((item for item in discoveries if item["state"] in ("observed", "partial")), None)
            observed = set(saved["models"]) if saved else set()
            if saved and saved["state"] == "partial":
                prior = next((item for item in discoveries[discoveries.index(saved) + 1:]
                              if item["state"] == "observed"), None)
                if prior:
                    observed.update(prior["models"])
            associated = {json.loads(item[0])["serving_id"] for item in db.execute(
                "SELECT record FROM registry_deployments WHERE json_extract(record,'$.connection_id')=?",
                (subject,)).fetchall()}
            changed = []
            seen = set()
            for item in data["items"]:
                if type(item) is not dict or set(item) != {"serving_id", "expected_revision"}:
                    raise ValueError("invalid source-model row")
                serving_id, revision = item["serving_id"], item["expected_revision"]
                if (type(serving_id) is not str or not 1 <= len(serving_id) <= 256 or
                        any(ord(c) < 33 for c in serving_id) or serving_id in seen or
                        serving_id not in observed | associated or
                        type(revision) is not int or revision < 0):
                    raise ValueError("unknown or duplicate source-model row")
                seen.add(serving_id)
                key = self._source_key(subject, serving_id)
                prior = db.execute("SELECT record FROM registry_source_permissions WHERE id=?", (key,)).fetchone()
                old = json.loads(prior[0]) if prior else None
                if revision != (old["revision"] if old else 0):
                    raise RegistryConflict("stale source-model permission")
                record = {"connection_id": subject, "serving_id": serving_id,
                          "allowed": data["allowed"], "revision": revision + 1,
                          "actor": actor, "at": timestamp()}
                db.execute("INSERT INTO registry_source_permissions VALUES (?,?) ON CONFLICT(id) "
                           "DO UPDATE SET record=excluded.record", (key, encode(record)))
                changed.append(record)
            return {"revision": 1, "connection_id": subject, "allowed": data["allowed"],
                    "items": changed}
        if action == "create_provider_configuration":
            if expected or not subject.startswith("cfg.provider.") or set(data) != {
                    "display_name", "deployment_id", "owner", "purposes", "task_classes"}:
                raise ValueError("invalid provider configuration")
            if db.execute("SELECT 1 FROM registry_models WHERE ref=?", (subject,)).fetchone():
                raise RegistryConflict("configuration exists")
            deployment_id = identifier(data["deployment_id"])
            row = db.execute("SELECT record FROM registry_deployments WHERE id=?", (deployment_id,)).fetchone()
            deployment = json.loads(row[0]) if row else None
            if not deployment or deployment["status"] != "catalogued" or deployment.get("configuration_ref"):
                raise ValueError("deployment unavailable")
            row = db.execute("SELECT record FROM registry_connections WHERE id=?", (deployment["connection_id"],)).fetchone()
            connection = json.loads(row[0]) if row else None
            if (not connection or connection["status"] != "active" or
                    connection["adapter_id"] != "openai.responses.v1" or
                    connection["credential_state"] != "present" or
                    connection["settings"].get("project")):
                raise ValueError("selected connection unavailable")
            model = json.loads(db.execute("SELECT record FROM registry_models WHERE ref=?",
                (deployment["model_ref"],)).fetchone()[0])
            if model["status"] != "catalogued" or "text" not in model["catalogue"]["provider_published_capabilities"]:
                raise ValueError("catalogue model does not support selected text profile")
            for field in ("purposes", "task_classes"):
                if type(data[field]) is not list or not data[field]:
                    raise ValueError("provider configuration scope required")
            destination = {"configuration_ref": subject, "service": "openai.responses.v1",
                "endpoint": connection["settings"]["origin"], "model": deployment["serving_id"],
                "model_version": model["catalogue"]["observed_serving_version"],
                "processing_region": deployment["site"], "connection_id": connection["connection_id"],
                "connection_revision": connection["revision"], "credential_version": connection["credential_version"],
                "adapter_id": connection["adapter_id"], "deployment_id": deployment_id}
            record = {"configuration_ref": subject, "kind": "provider_deployment",
                "display_name": nonempty(data["display_name"]), "status": "draft", "revision": 1,
                "destination": destination, "owner": identifier(data["owner"]),
                "capabilities": ["text"], "purposes": sorted({identifier(x) for x in data["purposes"]}),
                "task_classes": sorted({identifier(x) for x in data["task_classes"]}),
                "handling": ["no.content.store"], "approved_by": None, "approved_at": None,
                "legacy_unpriced": False, "catalogue_ref": deployment["model_ref"]}
            deployment["configuration_ref"] = subject
            deployment["revision"] += 1
            db.execute("INSERT INTO registry_models VALUES (?,?)", (subject, encode(record)))
            db.execute("UPDATE registry_deployments SET record=? WHERE id=?", (encode(deployment), deployment_id))
            return record
        if action == "create_connection":
            if (expected or set(data) not in ({"display_name", "adapter_id", "settings", "owner"},
                                               {"display_name", "adapter_id", "settings", "owner", "funding_kind"})
                    or not subject.startswith("conn.")):
                raise ValueError("invalid connection creation")
            if db.execute("SELECT 1 FROM registry_connections WHERE id=?", (subject,)).fetchone():
                raise RegistryConflict("connection exists")
            adapter_id = identifier(data["adapter_id"])
            settings = data["settings"]
            provider = validate_settings(adapter_id, settings,
                                         controlled=self.controlled_provider_proof)
            funding_kind = data.get("funding_kind", "unspecified_legacy")
            if funding_kind not in ("unspecified_legacy", "personal_testing", "organization", "controlled"):
                raise ValueError("invalid funding provenance")
            if funding_kind == "personal_testing" and data["owner"] != "owner.local":
                raise ValueError("personal testing must use the existing owner identity")
            record = {"connection_id": subject, "display_name": nonempty(data["display_name"]),
                      "provider_id": provider, "provider_name": PROVIDERS[provider],
                      "adapter_id": adapter_id, "adapter_version": adapter_id.rsplit(".", 1)[-1],
                      "settings": settings, "owner": identifier(data["owner"]),
                      "funding_kind": funding_kind,
                      "status": "draft", "revision": 1, "credential_ref": None,
                      "credential_version": 0, "credential_state": "absent", "created_at": timestamp(),
                      "network_policy": "commercial_public_only" if provider != "vllm" else "approved_private_lab",
                      "checks_scheduled": False, "scheduled_operation": None, "check_interval_seconds": None}
            db.execute("INSERT INTO registry_connections VALUES (?,?)", (subject, encode(record)))
            return record
        if action in ("edit_connection", "connection_state", "associate_deployment", "probe_schedule"):
            record = self._load_for_update(db, "registry_connections", "id", subject, expected)
            if record["status"] == "archived":
                raise RegistryConflict("archived connection is immutable")
            if action == "edit_connection":
                if set(data) != {"display_name"}:
                    raise ValueError("connection endpoint and protocol are immutable; create a new connection")
                record["display_name"] = nonempty(data["display_name"])
            elif action == "connection_state":
                if set(data) != {"status", "reason"} or data["status"] not in ("draft", "active", "disabled", "archived"):
                    raise ValueError("invalid connection state")
                if data["status"] == "active" and record["credential_state"] != "present":
                    raise ValueError("credential required before connection activation")
                record["status"] = data["status"]
                record["state_reason"] = nonempty(data["reason"], 300)
            elif action == "probe_schedule":
                if set(data) != {"enabled", "operation", "interval_seconds"} or type(data["enabled"]) is not bool:
                    raise ValueError("invalid probe schedule")
                if data["enabled"]:
                    if (data["operation"] not in ("access", "inventory", "readiness") or
                            ADAPTERS[record["adapter_id"]].get(data["operation"]) is None or
                            type(data["interval_seconds"]) is not int or
                            not 300 <= data["interval_seconds"] <= 86400):
                        raise ValueError("unsupported scheduled probe")
                    if not record["checks_scheduled"] and db.execute(
                        "SELECT COUNT(*) FROM registry_connections WHERE json_extract(record,'$.checks_scheduled')=1").fetchone()[0] >= 16:
                        raise ValueError("scheduled connection limit")
                elif data["operation"] is not None or data["interval_seconds"] is not None:
                    raise ValueError("disabled schedule must be empty")
                record.update(checks_scheduled=data["enabled"],
                    scheduled_operation=data["operation"],
                    check_interval_seconds=data["interval_seconds"])
            else:
                if set(data) != {"deployment_id", "model_ref", "serving_id", "site", "status"} or data["status"] != "catalogued":
                    raise ValueError("invalid model association")
                deployment_id = identifier(data["deployment_id"])
                model_ref = identifier(data["model_ref"])
                model_row = db.execute("SELECT record FROM registry_models WHERE ref=?", (model_ref,)).fetchone()
                if not model_row or json.loads(model_row[0]).get("kind") != "real_catalogue":
                    raise ValueError("association requires existing real catalogue model")
                if db.execute("SELECT 1 FROM registry_deployments WHERE id=?", (deployment_id,)).fetchone():
                    raise RegistryConflict("deployment identity exists")
                deployment = {"deployment_id": deployment_id, "connection_id": subject,
                              "model_ref": model_ref, "serving_id": identifier(data["serving_id"]),
                              "site": nonempty(data["site"]), "status": "catalogued", "revision": 1,
                              "execution_approved": False, "created_at": timestamp()}
                db.execute("INSERT INTO registry_deployments VALUES (?,?)", (deployment_id, encode(deployment)))
            record["revision"] += 1
            db.execute("UPDATE registry_connections SET record=? WHERE id=?", (encode(record), subject))
            return record
        if action == "import_catalogue":
            if expected != 0:
                raise RegistryConflict("catalogue creation requires revision zero")
            record = validate_catalogue(subject, data)
            db.execute("INSERT INTO registry_models VALUES (?,?)", (subject, encode(record)))
            return record
        if action == "register_catalogue":
            required = {"display_name", "vendor", "family", "api_model_id", "model_version",
                        "owner", "capabilities", "context_window", "max_output", "notes", "price"}
            if expected or set(data) != required or not subject.startswith("catalogue.operator."):
                raise ValueError("invalid manual catalogue registration")
            if db.execute("SELECT 1 FROM registry_models WHERE ref=?", (subject,)).fetchone():
                raise RegistryConflict("model exists")
            capabilities = data["capabilities"]
            if type(capabilities) is not list or any(item not in
                    ("text", "tools", "vision", "audio", "reasoning") for item in capabilities):
                raise ValueError("invalid descriptive capabilities")
            for field in ("context_window", "max_output"):
                value = data[field]
                if value is not None and (type(value) is not int or not 1 <= value <= 100000000):
                    raise ValueError("invalid advertised limit")
            at = timestamp()
            price, source = operator_reference_price(data["price"], at)
            name = nonempty(data["display_name"])
            catalogue = {"catalogue_key": subject[len("catalogue."):], "display_name": name,
                         "short_name": name, "vendor": nonempty(data["vendor"]),
                         "family": nonempty(data["family"]),
                         "published_api_model_id": identifier(data["api_model_id"]),
                         "observed_serving_version": identifier(data["model_version"]),
                         "provider_route_basis": "operator-entered metadata; no connection",
                         "identifier_pin_status": "operator-entered; unverified",
                         "provider_published_limits": {
                             "context_window_advertised": data["context_window"],
                             "max_output_advertised": data["max_output"]},
                         "provider_published_capabilities": sorted(set(capabilities)),
                         "duranki_registration": {"catalogued": True, "execution_approved": False,
                             "runtime_ready": False, "runtime_binding": None,
                             "credential_reference": None, "automatic_grants": []},
                         "price_reference": price, "source_refs": [source["id"]],
                         "notes": [nonempty(data["notes"], 500)]}
            record = {"configuration_ref": subject, "kind": "real_catalogue",
                      "display_name": name, "status": "catalogued", "revision": 1,
                      "destination": None, "owner": identifier(data["owner"]),
                      "capabilities": [], "purposes": [], "task_classes": [], "handling": [],
                      "approved_by": None, "approved_at": None, "legacy_unpriced": False,
                      "catalogue": catalogue, "source_links": [source],
                      "reference_price_history": [], "price_version": price["snapshot_id"],
                      "record_origin": "operator_entered"}
            db.execute("INSERT INTO registry_models VALUES (?,?)", (subject, encode(record)))
            return record
        if action == "create_model":
            if expected or set(data) != {"display_name", "model", "model_version", "owner",
                                                 "capabilities", "purposes", "task_classes"}:
                raise ValueError("invalid model creation")
            if db.execute("SELECT 1 FROM registry_models WHERE ref=?", (subject,)).fetchone():
                raise RegistryConflict("model exists")
            model_name = data["model"]
            # A non-synthetic name may be catalogued only as unsupported draft.
            identifier(model_name)
            for field in ("capabilities", "purposes", "task_classes"):
                if type(data[field]) is not list or not data[field] or any(type(x) is not str for x in data[field]):
                    raise ValueError("invalid model constraints")
            if set(data["capabilities"]) - {"text", "tools"}:
                raise ValueError("unsupported model capability")
            record = {"configuration_ref": subject, "display_name": nonempty(data["display_name"]),
                      "status": "draft", "revision": 1,
                      "destination": {"configuration_ref": subject, "service": "litellm.dev04",
                                      "endpoint": "127.0.0.1", "model": model_name,
                                      "model_version": identifier(data["model_version"]),
                                      "processing_region": "local"},
                      "owner": identifier(data["owner"]), "capabilities": sorted(set(data["capabilities"])),
                      "purposes": sorted({identifier(x) for x in data["purposes"]}),
                      "task_classes": sorted({identifier(x) for x in data["task_classes"]}),
                      "handling": ["no.content.store"], "approved_by": None,
                      "approved_at": None, "legacy_unpriced": False}
            db.execute("INSERT INTO registry_models VALUES (?,?)", (subject, encode(record)))
            return record
        if action in ("edit_model", "edit_catalogue_model", "model_state", "archive_model",
                      "publish_reference_price", "correct_reference_price"):
            record = self._load_for_update(db, "registry_models", "ref", subject, expected)
            if record["status"] in ("revoked", "archived"):
                raise RegistryConflict("retired model cannot be changed")
            if action == "edit_model":
                if set(data) != {"display_name"}:
                    raise ValueError("immutable deployment identity")
                record["display_name"] = nonempty(data["display_name"])
                if record.get("kind") == "real_catalogue":
                    record.setdefault("original_research", deepcopy(record["catalogue"]))
                    record["catalogue"]["display_name"] = record["display_name"]
            elif action == "edit_catalogue_model":
                if record.get("kind") != "real_catalogue" or set(data) != {"display_name", "notes"}:
                    raise ValueError("only local catalogue settings may be edited")
                record.setdefault("original_research", deepcopy(record["catalogue"]))
                record["display_name"] = nonempty(data["display_name"])
                record["catalogue"].update(display_name=record["display_name"],
                    notes=[nonempty(data["notes"], 500)])
                record["catalogue"]["operator_edited_at"] = timestamp()
            elif action in ("publish_reference_price", "correct_reference_price"):
                if record.get("kind") != "real_catalogue" or record["status"] != "catalogued":
                    raise ValueError("reference price requires catalogued model")
                at = timestamp()
                if action == "correct_reference_price":
                    if set(data) != {"source_title", "source_url", "bands"}:
                        raise ValueError("invalid price correction")
                    data = {**data, "snapshot_id": "operator.corrected." + secrets.token_hex(16)}
                price, source = operator_reference_price(data, at)
                versions = {record["catalogue"]["price_reference"]["snapshot_id"]} | {
                    item["price"]["snapshot_id"] for item in record.get("reference_price_history", [])}
                if price["snapshot_id"] in versions:
                    raise RegistryConflict("reference price snapshot exists")
                record.setdefault("original_research", deepcopy(record["catalogue"]))
                record.setdefault("reference_price_history", []).append({
                    "price": deepcopy(record["catalogue"]["price_reference"]),
                    "sources": deepcopy(record["source_links"])})
                record["catalogue"]["price_reference"] = price
                record["catalogue"]["source_refs"] = [source["id"]]
                record["source_links"] = [source]
                record["price_version"] = price["snapshot_id"]
            elif action == "archive_model":
                if set(data) != {"reason"}:
                    raise ValueError("invalid model archive")
                record["state_reason"] = nonempty(data["reason"])
                record["status"] = "archived" if record.get("kind") == "real_catalogue" else "revoked"
            else:
                if set(data) != {"status", "reason"} or data["status"] not in ("enabled", "disabled", "revoked"):
                    raise ValueError("invalid model state")
                nonempty(data["reason"])
                if data["status"] == "enabled":
                    if record.get("kind") == "real_catalogue":
                        raise ValueError("catalogued reference has no runtime binding")
                    if record.get("kind") == "provider_deployment":
                        if not self.source_model_allowed(record["destination"]["connection_id"],
                                                         record["destination"]["model"]):
                            raise ValueError("source model not allowed")
                        if not self.provider_execution_ready:
                            raise ValueError("selected provider execution path not validated")
                        destination = record["destination"]
                        row = db.execute("SELECT record FROM registry_connections WHERE id=?",
                                         (destination["connection_id"],)).fetchone()
                        connection = json.loads(row[0]) if row else None
                        if (not connection or connection["status"] != "active" or
                                connection["revision"] != destination["connection_revision"] or
                                connection["credential_version"] != destination["credential_version"]):
                            raise ValueError("provider binding stale")
                        deployment = json.loads(db.execute("SELECT record FROM registry_deployments WHERE id=?",
                            (destination["deployment_id"],)).fetchone()[0])
                        deployment["execution_approved"] = True
                        deployment["approved_by"] = actor
                        deployment["approved_at"] = timestamp()
                        deployment["revision"] += 1
                        db.execute("UPDATE registry_deployments SET record=? WHERE id=?",
                            (encode(deployment), destination["deployment_id"]))
                    elif record["destination"]["model"] not in MODELS:
                        raise ValueError("unsupported synthetic transport")
                    if not record["legacy_unpriced"] and not db.execute(
                            "SELECT 1 FROM registry_prices WHERE config_ref=?", (subject,)).fetchone():
                        raise ValueError("price required before enable")
                    record["approved_by"], record["approved_at"] = actor, timestamp()
                if record.get("kind") == "real_catalogue" and data["status"] != "revoked":
                    raise ValueError("reference catalogue state is not executable")
                record["status"] = data["status"]
                record["state_reason"] = data["reason"]
            record["revision"] += 1
            db.execute("UPDATE registry_models SET record=? WHERE ref=?", (encode(record), subject))
            return record
        if action == "create_principal":
            if expected or set(data) not in ({"display_name", "kind", "owner"},
                                                {"display_name", "kind", "owner", "role"}) or data["kind"] not in ("human", "service"):
                raise ValueError("invalid principal creation")
            role = data.get("role", "ordinary")
            if role not in ("ordinary", "read_only_operator", "registry_admin") or (
                    data["kind"] == "service" and role != "ordinary"):
                raise ValueError("invalid principal role")
            if db.execute("SELECT 1 FROM registry_principals WHERE id=?", (subject,)).fetchone():
                raise RegistryConflict("principal exists")
            record = {"principal_id": subject, "display_name": nonempty(data["display_name"]),
                      "kind": data["kind"], "owner": identifier(data["owner"]),
                      "status": "inactive", "role": role, "revision": 1,
                      "credential_state": "unbound", "record_origin": "operator_entered"}
            db.execute("INSERT INTO registry_principals VALUES (?,?)", (subject, encode(record)))
            return record
        if action in ("edit_principal", "principal_state", "set_role"):
            record = self._load_for_update(db, "registry_principals", "id", subject, expected)
            if record["status"] == "revoked":
                raise RegistryConflict("revoked principal cannot be changed")
            if action == "edit_principal":
                if set(data) not in ({"display_name"}, {"display_name", "owner"}):
                    raise ValueError("immutable principal identity and role")
                record["display_name"] = nonempty(data["display_name"])
                if "owner" in data:
                    record["owner"] = identifier(data["owner"])
            elif action == "set_role":
                if set(data) != {"role"} or data["role"] not in (
                        "ordinary", "read_only_operator", "registry_admin"):
                    raise ValueError("invalid role")
                if record["kind"] != "human" and data["role"] != "ordinary":
                    raise ValueError("service identity cannot receive console authority")
                if getattr(self, "users", None):
                    self.users.validate_principal_change(db, record, data["role"], record["status"])
                if record["role"] == "registry_admin" and data["role"] != "registry_admin":
                    active = db.execute("SELECT COUNT(*) FROM registry_principals WHERE json_extract(record,'$.role')='registry_admin' AND json_extract(record,'$.status')='active'").fetchone()[0]
                    if active <= 1:
                        raise ValueError("last active administrator")
                record["role"] = data["role"]
            else:
                if set(data) != {"status", "reason"} or data["status"] not in ("active", "suspended", "revoked"):
                    raise ValueError("invalid principal state")
                nonempty(data["reason"])
                if data["status"] == "active" and record["credential_state"] == "unbound":
                    raise ValueError("principal credential not provisioned")
                if getattr(self, "users", None):
                    self.users.validate_principal_change(db, record, record["role"], data["status"])
                if record["role"] == "registry_admin" and data["status"] != "active":
                    active = db.execute("SELECT COUNT(*) FROM registry_principals WHERE json_extract(record,'$.role')='registry_admin' AND json_extract(record,'$.status')='active'").fetchone()[0]
                    if active <= 1:
                        raise ValueError("last active administrator")
                record["status"], record["state_reason"] = data["status"], data["reason"]
            if action in ("set_role", "principal_state") and getattr(self, "users", None):
                db.execute("UPDATE console_users SET auth_version=auth_version+1,updated_at=? WHERE principal_id=?",
                           (timestamp(), subject))
            record["revision"] += 1
            db.execute("UPDATE registry_principals SET record=? WHERE id=?", (encode(record), subject))
            return record
        if action == "set_grant":
            if set(data) != {"configuration_ref", "status", "purposes", "task_classes"} or data["status"] not in ("active", "removed"):
                raise ValueError("invalid grant")
            ref = identifier(data["configuration_ref"])
            principal_row = db.execute("SELECT record FROM registry_principals WHERE id=?", (subject,)).fetchone()
            model_row = db.execute("SELECT record FROM registry_models WHERE ref=?", (ref,)).fetchone()
            if not principal_row or not model_row:
                raise ValueError("unregistered grant target")
            principal, model = json.loads(principal_row[0]), json.loads(model_row[0])
            if principal["status"] == "revoked":
                raise ValueError("revoked principal cannot receive grants")
            if data["status"] == "active" and (model.get("kind") == "real_catalogue" or
                    model["status"] != "enabled"):
                raise ValueError("model has no executable grant route")
            if (data["status"] == "active" and model.get("kind") == "provider_deployment" and
                    not self.source_model_allowed(model["destination"]["connection_id"],
                                                  model["destination"]["model"])):
                raise ValueError("source model disallowed")
            if data["status"] == "active" and model.get("kind") == "provider_deployment":
                destination = model["destination"]
                connection_row = db.execute("SELECT record FROM registry_connections WHERE id=?",
                                            (destination["connection_id"],)).fetchone()
                connection = json.loads(connection_row[0]) if connection_row else None
                if (not connection or connection["status"] != "active" or
                        connection["revision"] != destination["connection_revision"] or
                        connection["credential_version"] != destination["credential_version"]):
                    raise ValueError("provider connection unavailable for new grant")
            row = db.execute("SELECT record FROM registry_grants WHERE principal_id=? AND config_ref=?",
                             (subject, ref)).fetchone()
            old = json.loads(row[0]) if row else None
            if expected != (old["revision"] if old else 0):
                raise RegistryConflict("stale grant")
            for field in ("purposes", "task_classes"):
                if type(data[field]) is not list or not data[field]:
                    raise ValueError("invalid grant scope")
            record = {"principal_id": subject, "configuration_ref": ref, "status": data["status"],
                      "revision": expected + 1, "purposes": sorted({identifier(x) for x in data["purposes"]}),
                      "task_classes": sorted({identifier(x) for x in data["task_classes"]}),
                      "actor": actor, "at": timestamp()}
            db.execute("INSERT INTO registry_grants VALUES (?,?,?) ON CONFLICT(principal_id,config_ref) DO UPDATE SET record=excluded.record",
                       (subject, ref, encode(record)))
            return record
        if action == "publish_price":
            model = self._load_for_update(db, "registry_models", "ref", subject, expected)
            if model.get("kind") == "real_catalogue":
                raise ValueError("public reference is not an executable price schedule")
            if model["status"] == "revoked":
                raise RegistryConflict("retired model cannot be repriced")
            base_fields = {"price_version", "currency", "rates", "source", "usage_semantics_version"}
            if set(data) not in (base_fields, base_fields | {"contract"}):
                raise ValueError("invalid price")
            version = identifier(data["price_version"])
            if db.execute("SELECT 1 FROM registry_prices WHERE config_ref=? AND price_version=?",
                          (subject, version)).fetchone():
                raise RegistryConflict("price version exists")
            provider_schedule = model.get("kind") == "provider_deployment"
            allowed_source = "operator-approved provider schedule" if provider_schedule else "synthetic fixture"
            allowed_semantics = ("openai.responses.text.v1", CACHE_SEMANTICS) if provider_schedule else ("synthetic.text.v1", "synthetic.tool.v1")
            if data["currency"] != "USD" or data["source"] != allowed_source or \
                    data["usage_semantics_version"] not in allowed_semantics:
                raise ValueError("unsupported price semantics")
            rates = data["rates"]
            if data["usage_semantics_version"] == CACHE_SEMANTICS:
                contract = validate_contract(data.get("contract"), model["destination"]["model"], rates)
            else:
                if "contract" in data or type(rates) is not dict or set(rates) != {"input_uncached", "output_text"}:
                    raise ValueError("unsupported rate categories")
                contract = None
            record = {"configuration_ref": subject, "price_version": version, "currency": "USD",
                      "rates": {key: exact_rate(rates[key]) for key in rates},
                      "unit_denominator": 1000000, "usage_semantics_version": data["usage_semantics_version"],
                      "source": allowed_source, "recorded_at": timestamp(), "effective_at": timestamp(),
                      "approved_by": actor, "revision": model["revision"] + 1,
                      "unsupported_categories": [x for x in RATE_CATEGORIES if x not in rates]}
            if contract is not None:
                record["contract"] = contract
            db.execute("INSERT INTO registry_prices VALUES (?,?,?)", (subject, version, encode(record)))
            model["revision"] += 1
            model["price_version"] = version
            db.execute("UPDATE registry_models SET record=? WHERE ref=?", (encode(model), subject))
            return {**record, "revision": model["revision"]}
        raise ValueError("unsupported management action")

    @staticmethod
    def _load_for_update(db, table, column, subject, expected):
        row = db.execute(f"SELECT record FROM {table} WHERE {column}=?", (subject,)).fetchone()
        if not row:
            raise ValueError("unknown subject")
        record = json.loads(row[0])
        if record["revision"] != expected:
            raise RegistryConflict("stale revision")
        return record

    def provision_credential(self, actor, principal_id, expected_revision, operation_id):
        """Private helper path: return the new secret exactly once to its caller."""
        identifier(operation_id)
        identifier(principal_id)
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError("invalid expected revision")
        secret = secrets.token_urlsafe(48)
        verifier = hashlib.sha256(secret.encode()).hexdigest()
        with self.send_authority.gate:
            def action():
                db = self.store.db
                actor_row = db.execute("SELECT record FROM registry_principals WHERE id=?", (actor,)).fetchone()
                admin = json.loads(actor_row[0]) if actor_row else None
                if not admin or admin["status"] != "active" or admin["role"] != "registry_admin":
                    raise PermissionError("ADMIN_REQUIRED")
                request_hash = hashlib.sha256(encode({"principal_id": principal_id,
                    "expected_revision": expected_revision, "action": "provision_credential"}).encode()).hexdigest()
                prior = db.execute("SELECT actor,request_hash,result FROM registry_operations WHERE operation_id=?",
                                   (operation_id,)).fetchone()
                if prior:
                    if prior[0] != actor or prior[1] != request_hash:
                        raise RegistryConflict("operation reuse conflict")
                    return json.loads(prior[2])["record"], None, False
                record = self._load_for_update(db, "registry_principals", "id", principal_id, expected_revision)
                if record["status"] == "revoked" or record["credential_state"] == "local_operator":
                    raise ValueError("identity cannot be provisioned")
                db.execute("DELETE FROM registry_credentials WHERE principal_id=?", (principal_id,))
                db.execute("INSERT INTO registry_credentials VALUES (?,?,?)",
                           (verifier, principal_id, "cred." + verifier[:16]))
                record["credential_state"] = "bound"
                record["revision"] += 1
                db.execute("UPDATE registry_principals SET record=? WHERE id=?", (encode(record), principal_id))
                revision = int(db.execute("SELECT value FROM registry_meta WHERE key='authority_revision'").fetchone()[0]) + 1
                db.execute("UPDATE registry_meta SET value=? WHERE key='authority_revision'", (str(revision),))
                db.execute("INSERT INTO registry_audit (actor,action,subject,old_revision,new_revision,authority_revision,at) VALUES (?,?,?,?,?,?,?)",
                           (actor, "provision_credential", principal_id, expected_revision, record["revision"], revision, timestamp()))
                db.execute("INSERT INTO registry_operations VALUES (?,?,?,?)",
                           (operation_id, actor, request_hash, encode({"record": record, "authority_revision": revision})))
                return record, revision, True
            record, revision, fresh = self.store._transaction(action)
            if revision is not None:
                self.send_authority.epoch = revision
        return record, secret if fresh else None
