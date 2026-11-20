"""Standalone synthetic authority with durable revisions and a first-write gate."""

from __future__ import annotations

from tools.synthetic.repositories import successor_authority as _queries

from ezllmrouter_server.observability import log_failure

import base64
from copy import deepcopy
import json
import threading

from ezllmrouter_server.store import encode


REVISION_NAMES = (
    "policy",
    "recovery",
    "registry",
    "source_permission",
    "grant",
    "credential_scope",
    "price",
    "usage_contract",
    "key_eligibility",
)


class SyntheticSuccessorAuthority:
    def __init__(self, store, private_key, key_id, key_version):
        from cryptography.hazmat.primitives import serialization

        self.store = store
        self.private_key = private_key
        self.key_id = key_id
        self.key_version = key_version
        self.gate = threading.RLock()
        self.revoked = False
        self.epoch = 0
        public_der = private_key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        self.public_key_spki_base64 = base64.b64encode(public_der).decode()
        with self.gate:
            row = store.database.execute(_queries.INIT_SELECT_DEV12_AUTHORITY).fetchone()
            if row is None:
                state = {
                    "revisions": {name: 1 for name in REVISION_NAMES},
                    "activation": {"state": "absent", "reason": "not_yet_issued"},
                    "send_permission": True,
                    "revoked_plans": [],
                    "historical_access": [],
                    "historical_access_revision": 1,
                    "active_minting_key": {"key_id": key_id, "key_version": key_version},
                    "key_revisions": [
                        {"key_id": key_id, "key_version": key_version, "revision": 1}
                    ],
                    "verification_keys": [
                        {
                            "key_id": key_id,
                            "key_version": key_version,
                            "public_key_spki_base64": self.public_key_spki_base64,
                            "eligibility": "eligible",
                        }
                    ],
                }
                store.database.transaction(
                    lambda: store.database.execute(
                        _queries.INIT_INSERT_DEV12_AUTHORITY,
                        ("standalone.synthetic", encode(state)),
                    )
                )
            else:
                state = json.loads(row[0])
                # Read older synthetic records without rewriting their evidence.
                state.setdefault(
                    "key_revisions",
                    [
                        {
                            "key_id": item["key_id"],
                            "key_version": item["key_version"],
                            "revision": 1,
                        }
                        for item in state["verification_keys"]
                    ],
                )
                state.setdefault("historical_access", [])
                state.setdefault("historical_access_revision", 1)
                matched = next(
                    (
                        key
                        for key in state["verification_keys"]
                        if (key["key_id"], key["key_version"]) == (key_id, key_version)
                    ),
                    None,
                )
                if not matched or matched["public_key_spki_base64"] != self.public_key_spki_base64:
                    raise ValueError("restart signer differs from durable synthetic key")
            self.state = state

    def revisions(self):
        with self.gate:
            return deepcopy(self.state["revisions"])

    def activation(self):
        with self.gate:
            return deepcopy(self.state["activation"])

    def snapshot_epoch(self):
        with self.gate:
            if self.revoked:
                raise PermissionError("authority publication uncertain")
            return self.epoch

    @staticmethod
    def _bound_revisions(state, key_id, key_version):
        match = next(
            (
                item
                for item in state["key_revisions"]
                if (item["key_id"], item["key_version"]) == (key_id, key_version)
            ),
            None,
        )
        if match is None:
            raise PermissionError("signed key revision unresolved")
        return {**state["revisions"], "key_eligibility": match["revision"]}

    def minting_snapshot(self):
        """Signer, bound revisions and activation are one coherent view."""
        with self.gate:
            if self.revoked or not self.state["send_permission"]:
                raise PermissionError("synthetic authority unavailable")
            selected = self.state["active_minting_key"]
            if (selected["key_id"], selected["key_version"]) != (self.key_id, self.key_version):
                raise PermissionError("active signer material differs")
            key = next(
                (
                    item
                    for item in self.state["verification_keys"]
                    if (item["key_id"], item["key_version"]) == (self.key_id, self.key_version)
                ),
                None,
            )
            if not key or key["eligibility"] != "eligible":
                raise PermissionError("active key ineligible")
            return (
                self._bound_revisions(self.state, self.key_id, self.key_version),
                deepcopy(self.state["activation"]),
                self.key_id,
                self.key_version,
                self.private_key,
            )

    def current_snapshot(self, record, evaluation_time):
        with self.gate:
            state = deepcopy(self.state)
            epoch = self.epoch
            if self.revoked:
                state["send_permission"] = False
        plan = record["signed_plan"]
        context = {
            "expected_submission_id": record["submission_id"],
            "expected_attempt_id": record["attempt_id"],
            "expected_work_digest": record["work_digest"],
            "expected_admission_snapshot_digest": record["admission_snapshot_digest"],
            "expected_financial_owner_id": record["trusted_identity"]["charging_owner_id"],
            "expected_reservation": deepcopy(record["reservation"]),
            "expected_execution_context": state["activation"],
            "current_authority_revisions": self._bound_revisions(
                state, plan["key_id"], plan["key_version"]
            ),
            "evaluation_time": evaluation_time,
            "send_permission": state["send_permission"],
            "plan_revoked": plan["plan_id"] in state["revoked_plans"],
            "active_minting_key": state["active_minting_key"],
            "verification_keys": state["verification_keys"],
        }
        return context, epoch

    def current_context(self, record, evaluation_time):
        return self.current_snapshot(record, evaluation_time)[0]

    def update(self, mutator, audit_record):
        """Gate, atomically commit authority/audit, publish, release, acknowledge."""
        with self.gate:
            if self.revoked:
                raise PermissionError("authority publication uncertain")
            next_state = deepcopy(self.state)
            mutator(next_state)
            if set(next_state["revisions"]) != set(REVISION_NAMES):
                raise ValueError("named revision set changed")

            def action():
                self.store.database.execute(
                    _queries.ACTION_UPDATE_DEV12_AUTHORITY,
                    (encode(next_state), "standalone.synthetic"),
                )
                self.store.database.execute(
                    _queries.ACTION_INSERT_DEV12_AUTHORITY_AUDIT,
                    ("standalone.synthetic", encode(audit_record)),
                )

            try:
                self.store.database.transaction(action)
            except Exception as exc:
                log_failure("successor_authority.SyntheticSuccessorAuthority.update.failed")
                # A failed/uncertain DB commit cannot expose a newly permissive view.
                if not getattr(exc, "ezllmrouter_definite_rollback", False):
                    self.revoked = True
                raise
            try:
                self._publish(next_state)
            except BaseException:
                self.revoked = True
                raise
            self.epoch += 1
            return self.epoch

    def _publish(self, state):
        self.state = state

    @staticmethod
    def _historical_scope(identity):
        names = ("principal_id", "source_authority_id", "identity_binding_id", "charging_owner_id")
        if type(identity) is not dict or any(
            type(identity.get(name)) is not str or not identity[name] for name in names
        ):
            raise ValueError("complete synthetic historical identity required")
        return {name: identity[name] for name in names}

    def set_historical_access(self, identity, *, read, write, resume, observed_at):
        """Audit an explicit synthetic historical grant; never grant from a callback."""
        scope = self._historical_scope(identity)
        if any(type(flag) is not bool for flag in (read, write, resume)):
            raise ValueError("historical permissions must be booleans")

        def change(state):
            state["historical_access"] = [
                item
                for item in state["historical_access"]
                if any(item[name] != scope[name] for name in scope)
            ]
            state["historical_access"].append(
                {**scope, "read": read, "write": write, "resume": resume}
            )
            state["historical_access_revision"] += 1

        return self.update(
            change,
            {
                "kind": "historical_access_change",
                "at": observed_at,
                "scope": scope,
                "read": read,
                "write": write,
                "resume": resume,
            },
        )

    def historical_allowed(self, trusted, record, action):
        if action not in ("read", "write", "resume"):
            raise ValueError("unsupported historical action")
        try:
            scope = self._historical_scope(record["trusted_identity"])
        except (KeyError, ValueError):
            return False
        with self.gate:
            if self.revoked or any(trusted.get(name) != scope[name] for name in scope):
                return False
            return any(
                all(item.get(name) == scope[name] for name in scope) and item.get(action) is True
                for item in self.state["historical_access"]
            )

    def rotate_minting_key(self, private_key, key_id, key_version, observed_at):
        """Select a new signer while previously eligible versions remain verifiable."""
        from cryptography.hazmat.primitives import serialization

        der = private_key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        public = base64.b64encode(der).decode()

        def change(state):
            if any(
                (item["key_id"], item["key_version"]) == (key_id, key_version)
                for item in state["verification_keys"]
            ):
                raise ValueError("synthetic key tuple collision")
            state["verification_keys"].append(
                {
                    "key_id": key_id,
                    "key_version": key_version,
                    "public_key_spki_base64": public,
                    "eligibility": "eligible",
                }
            )
            state["key_revisions"].append(
                {"key_id": key_id, "key_version": key_version, "revision": 1}
            )
            state["active_minting_key"] = {"key_id": key_id, "key_version": key_version}

        with self.gate:
            epoch = self.update(
                change,
                {
                    "kind": "minting_rotation",
                    "at": observed_at,
                    "key_id": key_id,
                    "key_version": key_version,
                },
            )
            self.private_key, self.key_id, self.key_version = private_key, key_id, key_version
            self.public_key_spki_base64 = public
            return epoch

    def revoke_key_version(self, key_id, key_version, observed_at):
        def change(state):
            matched = False
            for item in state["verification_keys"]:
                if (item["key_id"], item["key_version"]) == (key_id, key_version):
                    item["eligibility"] = "revoked"
                    matched = True
            if not matched:
                raise KeyError("unknown synthetic key tuple")
            state["revisions"]["key_eligibility"] += 1
            next(
                item
                for item in state["key_revisions"]
                if (item["key_id"], item["key_version"]) == (key_id, key_version)
            )["revision"] += 1

        return self.update(
            change,
            {
                "kind": "key_revocation",
                "at": observed_at,
                "key_id": key_id,
                "key_version": key_version,
            },
        )

    def revoke_plan(self, plan_id, observed_at):
        def change(state):
            if plan_id not in state["revoked_plans"]:
                state["revoked_plans"].append(plan_id)

        return self.update(
            change, {"kind": "plan_revocation", "at": observed_at, "plan_id": plan_id}
        )
