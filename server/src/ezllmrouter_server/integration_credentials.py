"""Encrypted database credentials for external integration accounts.

The integration account remains the permission record. This store owns only
the stable credential binding, encrypted versions, and discovery metadata.
"""
from __future__ import annotations

from .repositories import integration_credentials as _queries

from .observability import log_failure

from datetime import datetime, timezone, timedelta
import hmac
import json
from pathlib import Path
import secrets
import threading

from .secret_box import SecretBox, validate_secret

from .integration_accounting import IntegrationError, _checked, _time
from .provider_adapters import probe
from .store import encode


PROVIDERS = {
    "openai": ("openai.responses.v1", "https://api.openai.com"),
    "anthropic": ("anthropic.messages.2023-06-01", "https://api.anthropic.com"),
    "xai": ("xai.responses.v1", "https://api.x.ai"),
}
OPERATIONS = {"speech_input", "speech_output"}


def credential_context(account_id, version, provider):
    return encode({"account_id": account_id, "version": version, "provider": provider}).encode()


def reencrypt_credentials(store, box):
    def rewrite():
        rows = store.database.execute(
            _queries.REWRITE_SELECT_INTEGRATION_CREDENTIAL_VERSIONS).fetchall()
        changed = 0
        for account_id, version, key_id, nonce, ciphertext, raw in rows:
            binding = json.loads(raw)
            context = credential_context(account_id, version, binding["provider"])
            value = box.open_parts(key_id, nonce, ciphertext, context)
            if key_id != box.active_id:
                replacement = box.seal_parts(value, context)
                store.database.execute(_queries.REWRITE_UPDATE_INTEGRATION_CREDENTIAL_VERSIONS, (*replacement, account_id, version))
                changed += 1
        return changed
    return store.database.transaction(rewrite)


class DatabaseCredentialStore:
    def __init__(self, registry, key_path, *, discover=None, controlled=False):
        self.registry = registry
        self.store = registry.store
        self.key_path = Path(key_path)
        self.discover = discover or probe
        self.controlled = controlled
        self._gate = threading.RLock()
        with self.store.database.read():
            has_rows = self.store.database.execute(
                _queries.INIT_SELECT_INTEGRATION_CREDENTIAL_VERSIONS_2).fetchone() is not None
            pinned = self.store.database.execute(
                _queries.INIT_SELECT_INTEGRATION_CREDENTIAL_META).fetchone()
        with self.store.database.read():
            known = {row[0] for row in self.store.database.execute(
                _queries.INIT_SELECT_INTEGRATION_CREDENTIAL_VERSIONS)}
        self.box = SecretBox(self.key_path, "integration-credentials", required_ids=known,
                             required=bool(has_rows or pinned))
        if pinned and pinned[0] != self.box.identity:
            raise RuntimeError("CREDENTIAL_KEYRING_MISMATCH")
        if not pinned:
            self.store.database.transaction(lambda: self.store.database.execute(
                _queries.INIT_INSERT_INTEGRATION_CREDENTIAL_META, (self.box.identity,)))
        self._clean_pending()

    def _owner(self, principal, dataset_id):
        dataset = self.registry.integration._dataset(dataset_id)
        self.registry.integration._authorize(principal, dataset, "admin")
        if principal["principal_id"] != "owner.local":
            raise IntegrationError("POLICY_DENIED", 403)
        return dataset

    def _binding(self, account_id):
        with self.store.database.read():
            row = self.store.database.execute(_queries.BINDING_SELECT_INTEGRATION_CREDENTIAL_BINDINGS,
                                        (account_id,)).fetchone()
        if not row:
            raise IntegrationError("NOT_FOUND_OR_FORBIDDEN", 404)
        return json.loads(row[0])

    def _seal(self, account_id, version, provider, secret):
        try:
            validate_secret(secret)
        except ValueError as exc:
            raise IntegrationError("INVALID_CREDENTIAL") from exc
        return self.box.seal_parts(secret, credential_context(account_id, version, provider))

    def _resolve(self, binding, version=None):
        selected = version or binding["selected_version"]
        with self.store.database.read():
            row = self.store.database.execute(_queries.RESOLVE_SELECT_INTEGRATION_CREDENTIAL_VERSIONS, (binding["account_id"], selected)).fetchone()
        if not row:
            raise IntegrationError("CREDENTIAL_KEY_UNAVAILABLE", 503)
        try:
            return self.box.open_parts(*row, credential_context(binding["account_id"], selected, binding["provider"]))
        except Exception as exc:
            log_failure('integration_credentials.DatabaseCredentialStore._resolve.failed')
            raise IntegrationError("CREDENTIAL_DECRYPT_FAILED", 503) from exc

    def reencrypt_secrets(self):
        with self._gate:
            return reencrypt_credentials(self.store, self.box)

    def rotate_encryption_key(self):
        with self._gate:
            identifier = self.box.rotate()
            return {"key_id": identifier, "rewritten": self.reencrypt_secrets()}

    def _settings(self, provider):
        return {"origin": PROVIDERS[provider][1], "location": "commercial", "site": "owner.local"}

    def _discover(self, binding, version=None, *, secret=None):
        result = self.discover(PROVIDERS[binding["provider"]][0], self._settings(binding["provider"]),
                               self._resolve(binding, version) if secret is None else secret,
                               "inventory", controlled=self.controlled)
        if result["state"] == "observed" and not result.get("models"):
            result = {"state": "empty", "reason": "empty_catalogue", "models": []}
        return {"state": result["state"], "reason": result["reason"],
                "models": result.get("models", []), "details": result.get("details", []),
                "has_more": bool(result.get("has_more")),
                "checked_at": _time(), "credential_version": version or binding["selected_version"],
                "record_revision": binding["revision"]}

    def _public(self, binding):
        return {key: value for key, value in binding.items() if key not in ("request_hash",)}

    def _current(self, principal, dataset_id, account_id, expected_revision):
        """Call within the write transaction when publishing a changed binding."""
        self._owner(principal, dataset_id)
        item = self._binding(account_id)
        if (type(expected_revision) is not int or item["dataset_id"] != dataset_id or
                item["revision"] != expected_revision):
            raise IntegrationError("STALE_REVISION", 409)
        return item

    def _clean_pending(self):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        def clean():
            db = self.store.database
            rows = db.execute(_queries.CLEAN_SELECT_INTEGRATION_CREDENTIAL_BINDINGS).fetchall()
            for account_id, raw in rows:
                item = json.loads(raw)
                if (item["state"] == "pending" and
                    item["discovery"]["state"] == "not_checked" and item["created_at"] < cutoff):
                    db.execute(_queries.CLEAN_DELETE_INTEGRATION_CREDENTIAL_VERSIONS, (account_id,))
                    db.execute(_queries.CLEAN_DELETE_INTEGRATION_CREDENTIAL_OPERATIONS, (account_id,))
                    db.execute(_queries.CLEAN_DELETE_INTEGRATION_CREDENTIAL_BINDINGS, (account_id,))
        self.store.database.transaction(clean)

    def connect(self, principal, body):
        if type(body) is not dict or set(body) != {"dataset_id", "provider", "api_key", "friendly_name", "operation_id"}:
            raise IntegrationError("SCHEMA_INVALID")
        dataset = self._owner(principal, body["dataset_id"])
        provider = body["provider"]
        if provider not in PROVIDERS or type(body["friendly_name"]) is not str or len(body["friendly_name"].strip()) > 120:
            raise IntegrationError("SCHEMA_INVALID")
        operation_id = body["operation_id"]
        if type(operation_id) is not str or not operation_id.startswith("op.") or len(operation_id) > 160:
            raise IntegrationError("SCHEMA_INVALID")
        with self._gate:
            digest = self.box.request_digest(encode(body).encode())
            with self.store.database.read():
                old = self.store.database.execute(_queries.CONNECT_SELECT_INTEGRATION_CREDENTIAL_OPERATIONS, (operation_id,)).fetchone()
            if old:
                if not hmac.compare_digest(old[0], digest):
                    raise IntegrationError("OPERATION_CONFLICT", 409)
                return self._public(self._binding(old[1]))
            account_id = "account.local." + secrets.token_hex(16)
            reference = "credential.local." + secrets.token_hex(16)
            key_id, nonce, ciphertext = self._seal(account_id, 1, provider, body["api_key"])
            binding = {"account_id": account_id, "dataset_id": body["dataset_id"],
                       "environment_id": dataset["environment_id"], "owner_id": dataset["owner_id"],
                       "provider": provider, "provider_id": "provider." + provider,
                       "friendly_name": body["friendly_name"].strip() or provider.title(),
                       "credential_ref": reference, "backend": "encrypted_database",
                       "selected_version": 0, "pending_version": 1, "state": "pending",
                       "discovery": {"state": "not_checked", "models": []},
                       "selected_models": [], "allowed_operations": [], "policy_revision": 0,
                       "revision": 1, "created_at": _time(), "updated_at": _time()}
            def create():
                db = self.store.database
                self._owner(principal, body["dataset_id"])
                db.execute(_queries.CREATE_INSERT_INTEGRATION_CREDENTIAL_BINDINGS,
                           (account_id, body["dataset_id"], encode(binding)))
                db.execute(_queries.CREATE_INSERT_INTEGRATION_CREDENTIAL_VERSIONS,
                           (account_id, 1, key_id, nonce, ciphertext))
                db.execute(_queries.CREATE_INSERT_INTEGRATION_CREDENTIAL_OPERATIONS,
                           (operation_id, digest, account_id))
            self.store.database.transaction(create)
            secret = self._resolve(binding, 1)
        discovery = self._discover(binding, 1, secret=secret)
        with self._gate:
            def finish():
                self._owner(principal, binding["dataset_id"])
                current = self._binding(account_id)
                if current["revision"] == binding["revision"]:
                    current.update(discovery=discovery, updated_at=_time())
                    self.store.database.execute(_queries.COMMIT_UPDATE_INTEGRATION_CREDENTIAL_BINDINGS,
                                                (encode(current), account_id))
                return self._public(current)
            return self.store.database.transaction(finish)

    def list(self, principal, dataset_id):
        self._owner(principal, dataset_id)
        with self.store.database.read():
            rows = self.store.database.execute(_queries.LIST_SELECT_INTEGRATION_CREDENTIAL_BINDINGS, (dataset_id,)).fetchall()
        return {"items": [self._public(json.loads(row[0])) for row in rows]}

    def list_for(self, principal, dataset_id):
        if principal["principal_id"] != "svc.vega.credential-consumer" or principal["kind"] != "service":
            raise IntegrationError("NOT_FOUND_OR_FORBIDDEN", 404)
        dataset = self.registry.integration._dataset(dataset_id)
        if principal["owner"] != dataset["owner_id"]:
            raise IntegrationError("NOT_FOUND_OR_FORBIDDEN", 404)
        with self.store.database.read():
            rows = self.store.database.execute(_queries.LIST_FOR_SELECT_INTEGRATION_CREDENTIAL_BINDINGS,
                                         (dataset_id,)).fetchall()
        fields = ("account_id", "dataset_id", "environment_id", "provider", "provider_id",
                  "credential_ref", "selected_version", "policy_revision", "selected_models",
                  "allowed_operations", "state")
        return {"integration_version": "3", "items": [
            {key: item[key] for key in fields} for (raw,) in rows
            if (item := json.loads(raw))["state"] == "connected"]}

    def save(self, principal, account_id, body):
        if type(body) is not dict or set(body) != {"dataset_id", "expected_revision", "selected_models", "allowed_operations"}:
            raise IntegrationError("SCHEMA_INVALID")
        self._owner(principal, body["dataset_id"])
        with self._gate:
            item = self._binding(account_id)
            models, operations = body["selected_models"], body["allowed_operations"]
            if (item["dataset_id"] != body["dataset_id"] or item["revision"] != body["expected_revision"] or
                item["discovery"]["state"] != "observed" or item["discovery"].get("has_more") or
                type(models) is not list or len(models) != len(set(models)) or len(models) > 128 or
                any(model not in item["discovery"]["models"] for model in models) or
                type(operations) is not list or len(operations) != len(set(operations)) or
                not set(operations) <= OPERATIONS or not (models or operations)):
                raise IntegrationError("POLICY_OR_REVISION_DENIED", 409)
            if item["state"] == "pending":
                record = _checked({"account_id": account_id, "dataset_id": item["dataset_id"],
                    "provider_id": item["provider_id"], "credential_ref": item["credential_ref"],
                    "allowed_models": models, "allowed_operations": operations,
                    "state": "usable"}, "account", "3")
                dataset = self.registry.integration._dataset(item["dataset_id"])
                account = {**record, "owner_id": dataset["owner_id"], "revision": 1, "registered_at": _time()}
                item["selected_version"] = item["pending_version"]
                item["pending_version"] = None
                item["state"] = "connected"
            elif item["state"] in ("connected", "disabled"):
                account = None
            else:
                raise IntegrationError("POLICY_DENIED", 403)
            item.update(selected_models=models, allowed_operations=operations,
                        policy_revision=item["policy_revision"] + 1,
                        revision=item["revision"] + 1, updated_at=_time())
            def commit():
                db = self.store.database
                self._current(principal, item["dataset_id"], account_id, item["revision"] - 1)
                if account:
                    db.execute(_queries.COMMIT_INSERT_INTEGRATION_ACCOUNTS,
                               (account_id, item["dataset_id"], encode(account)))
                    db.execute(_queries.COMMIT_INSERT_INTEGRATION_ACCOUNT_HISTORY,
                               (account_id, item["dataset_id"], 1, encode(account)))
                else:
                    row = db.execute(_queries.RELEASE_SELECT_INTEGRATION_ACCOUNTS,
                                     (account_id, item["dataset_id"])).fetchone()
                    if not row:
                        raise IntegrationError("NOT_FOUND_OR_FORBIDDEN", 404)
                    old = json.loads(row[0])
                    old.update(allowed_models=models, allowed_operations=operations,
                               revision=old["revision"] + 1, changed_at=_time())
                    db.execute(_queries.COMMIT_UPDATE_INTEGRATION_ACCOUNTS,
                               (encode(old), account_id, item["dataset_id"]))
                    db.execute(_queries.COMMIT_INSERT_INTEGRATION_ACCOUNT_HISTORY,
                               (account_id, item["dataset_id"], old["revision"], encode(old)))
                db.execute(_queries.COMMIT_UPDATE_INTEGRATION_CREDENTIAL_BINDINGS,
                           (encode(item), account_id))
            self.store.database.transaction(commit)
            return self._public(item)

    def refresh(self, principal, account_id, body):
        self._owner(principal, body.get("dataset_id"))
        with self._gate:
            item = self._current(principal, body["dataset_id"], account_id, body.get("expected_revision"))
            version = item["pending_version"] or item["selected_version"]
            secret = self._resolve(item, version)
        discovery = self._discover(item, version, secret=secret)
        with self._gate:
            def commit():
                current = self._current(principal, item["dataset_id"], account_id, item["revision"])
                discovery["record_revision"] = current["revision"] + 1
                current.update(discovery=discovery, revision=current["revision"] + 1, updated_at=_time())
                self.store.database.execute(_queries.COMMIT_UPDATE_INTEGRATION_CREDENTIAL_BINDINGS,
                                            (encode(current), account_id))
                return self._public(current)
            return self.store.database.transaction(commit)

    def replace(self, principal, account_id, body):
        self._owner(principal, body.get("dataset_id"))
        secret = body.get("api_key")
        dataset_id, expected_revision = body["dataset_id"], body.get("expected_revision")
        with self._gate:
            def stage():
                item = self._current(principal, dataset_id, account_id, expected_revision)
                if item["state"] not in ("connected", "pending"):
                    raise IntegrationError("STALE_REVISION", 409)
                stored = self.store.database.execute(_queries.NEXT_CREDENTIAL_VERSION, (account_id,)).fetchone()[0]
                version = max(stored, item["selected_version"], item["pending_version"] or 0) + 1
                key_id, nonce, ciphertext = self._seal(account_id, version, item["provider"], secret)
                self.store.database.execute(_queries.CREATE_INSERT_INTEGRATION_CREDENTIAL_VERSIONS,
                                            (account_id, version, key_id, nonce, ciphertext))
                return item, version
            item, version = self.store.database.transaction(stage)
        try:
            try:
                result = self._discover(item, version, secret=secret)
            except Exception:
                log_failure("integration_credentials.replacement_discovery_failed")
                raise
            with self._gate:
                def commit():
                    current = self._current(principal, item["dataset_id"], account_id, item["revision"])
                    if current["state"] == "connected" and (result["state"] != "observed" or result.get("has_more")):
                        return {**self._public(current), "replacement": result}
                    previous_pending = current["pending_version"]
                    if current["state"] == "pending":
                        current["pending_version"] = version
                    else:
                        current["selected_version"] = version
                    current.update(discovery=result, revision=current["revision"] + 1, updated_at=_time())
                    current["discovery"]["record_revision"] = current["revision"]
                    self.store.database.execute(_queries.COMMIT_UPDATE_INTEGRATION_CREDENTIAL_BINDINGS,
                                                (encode(current), account_id))
                    if previous_pending and previous_pending != version:
                        self.store.database.execute(_queries.COMMIT_DELETE_INTEGRATION_CREDENTIAL_VERSIONS,
                                                    (account_id, previous_pending))
                    return self._public(current)
                return self.store.database.transaction(commit)
        finally:
            # Never remove a version that another completed mutation selected.
            with self._gate:
                self.store.database.transaction(lambda: self.store.database.execute(
                    _queries.DISCARD_UNSELECTED_CREDENTIAL_VERSION, (account_id, version)))

    def disable(self, principal, account_id, body):
        self._owner(principal, body.get("dataset_id"))
        with self._gate:
            item = self._binding(account_id)
            if item["dataset_id"] != body["dataset_id"] or item["revision"] != body.get("expected_revision"):
                raise IntegrationError("STALE_REVISION", 409)
            if item["state"] == "disabled":
                return self._public(item)
            item.update(state="disabled", revision=item["revision"] + 1, updated_at=_time())
            def commit():
                self._current(principal, item["dataset_id"], account_id, item["revision"] - 1)
                db = self.store.database
                row = db.execute(_queries.RELEASE_SELECT_INTEGRATION_ACCOUNTS,
                                 (account_id, item["dataset_id"])).fetchone()
                if row:
                    account = json.loads(row[0])
                    account.update(state="disabled", revision=account["revision"] + 1, changed_at=_time())
                    db.execute(_queries.COMMIT_UPDATE_INTEGRATION_ACCOUNTS,
                               (encode(account), account_id, item["dataset_id"]))
                    db.execute(_queries.COMMIT_INSERT_INTEGRATION_ACCOUNT_HISTORY,
                               (account_id, item["dataset_id"], account["revision"], encode(account)))
                db.execute(_queries.COMMIT_UPDATE_INTEGRATION_CREDENTIAL_BINDINGS,
                           (encode(item), account_id))
            self.store.database.transaction(commit)
            return self._public(item)

    def retire(self, principal, account_id, body):
        """Delete a predecessor only after the owner supplies the consumer's acknowledged version."""
        self._owner(principal, body.get("dataset_id"))
        with self._gate:
            item = self._binding(account_id)
            version = body.get("version")
            if (item["dataset_id"] != body["dataset_id"] or item["revision"] != body.get("expected_revision") or
                type(version) is not int or not 1 <= version < item["selected_version"] or
                body.get("acknowledged_version") != item["selected_version"]):
                raise IntegrationError("RETIREMENT_NOT_ACKNOWLEDGED", 409)
            item.update(revision=item["revision"] + 1, updated_at=_time())
            def commit():
                self._current(principal, item["dataset_id"], account_id, item["revision"] - 1)
                self.store.database.execute(_queries.COMMIT_DELETE_INTEGRATION_CREDENTIAL_VERSIONS,
                                      (account_id, version))
                self.store.database.execute(_queries.COMMIT_UPDATE_INTEGRATION_CREDENTIAL_BINDINGS,
                                      (encode(item), account_id))
            self.store.database.transaction(commit)
            return self._public(item)

    def resolve_for(self, principal, dataset_id, account_id, model_id, operation_family, purpose):
        if principal["principal_id"] != "svc.vega.credential-consumer" or principal["kind"] != "service":
            raise IntegrationError("NOT_FOUND_OR_FORBIDDEN", 404)
        dataset = self.registry.integration._dataset(dataset_id)
        if principal["owner"] != dataset["owner_id"] or purpose != "vega-provider-dispatch":
            raise IntegrationError("NOT_FOUND_OR_FORBIDDEN", 404)

        def release():
            dataset = self.registry.integration._dataset(dataset_id)
            current = self.registry.principal(principal["principal_id"])
            if not current or current["status"] != "active" or current["owner"] != dataset["owner_id"]:
                raise IntegrationError("NOT_FOUND_OR_FORBIDDEN", 404)
            item = self._binding(account_id)
            if (item["dataset_id"] != dataset_id or item["environment_id"] != dataset["environment_id"] or
                    item["state"] != "connected"):
                raise IntegrationError("NOT_FOUND_OR_FORBIDDEN", 404)
            row = self.store.database.execute(_queries.RELEASE_SELECT_INTEGRATION_ACCOUNTS,
                                        (account_id, dataset_id)).fetchone()
            account = json.loads(row[0]) if row else None
            allowed = (model_id in account["allowed_models"] if operation_family == "generation" else
                       model_id is None and operation_family in account["allowed_operations"] and
                       operation_family in OPERATIONS) if account else False
            if not account or account["state"] != "usable" or not allowed:
                raise IntegrationError("NOT_FOUND_OR_FORBIDDEN", 404)
            facts = {"dataset_id": dataset_id, "credential_version": item["selected_version"],
                     "policy_revision": item["policy_revision"], "purpose": purpose,
                     "model_id": model_id, "operation_family": operation_family}
            authority_revision = int(self.store.database.execute(
                _queries.RELEASE_SELECT_REGISTRY_META).fetchone()[0])
            audit = self.store.database.execute(
                _queries.RELEASE_INSERT_REGISTRY_AUDIT, (principal["principal_id"], "credential_resolved", account_id,
                    item["revision"], item["revision"], authority_revision, _time()))
            self.store.database.execute(_queries.RELEASE_INSERT_REGISTRY_AUDIT_VALUES,
                                  (audit.lastrowid, None, encode(facts)))
            return {"account_id": account_id, "dataset_id": dataset_id,
                    "environment_id": dataset["environment_id"], "provider_id": item["provider_id"],
                    "credential_ref": item["credential_ref"], "credential_version": item["selected_version"],
                    "policy_revision": item["policy_revision"], "model_id": model_id,
                    "operation_family": operation_family, "api_key": self._resolve(item)}

        # Permission checks, selected version and the audit commit precede release.
        with self._gate:
            return self.store.database.transaction(release)
