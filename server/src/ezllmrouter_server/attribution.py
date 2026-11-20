"""Durable, scoped agent-run and outcome authority alongside the attempt ledger."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy

from .canonical import ContractError
from .errors import RegistryConflict
from .formatting import utc_timestamp as timestamp
from .identifiers import require_identifier as identifier
from .identifiers import require_text as nonempty
from .repositories import attribution as _queries
from .store import encode


def _id(value):
    try:
        return identifier(value)
    except (TypeError, ValueError) as exc:
        raise ContractError("SCHEMA_INVALID", 400) from exc


def _record(db, table, key, value):
    row = db.execute(_queries.RECORD_SELECT_RECORD(key=key, table=table), (value,)).fetchone()
    return json.loads(row[0]) if row else None


class AttributionLedger:
    """The authenticated caller and administrator records define all run authority."""

    def __init__(self, registry):
        self.registry = registry
        self.store = registry.store

    def agent(self, agent_id):
        _id(agent_id)
        with self.store.database.read():
            return _record(self.store.database, "registry_agents", "id", agent_id)

    def agents(self):
        with self.store.database.read():
            rows = self.store.database.execute(_queries.AGENTS_SELECT_REGISTRY_AGENTS).fetchall()
        return [json.loads(row[0]) for row in rows]

    def run(self, run_id):
        _id(run_id)
        with self.store.database.read():
            return _record(self.store.database, "attribution_runs", "id", run_id)

    def permission(self, caller, agent, user):
        with self.store.database.read():
            row = self.store.database.execute(
                _queries.PERMISSION_SELECT_REGISTRY_AGENT_PERMISSIONS, (caller, agent, user or "")
            ).fetchone()
        return json.loads(row[0]) if row else None

    def _authorize(self, trusted, body, parent=None):
        caller = self.registry.principal(trusted["principal_id"])
        if (
            not caller
            or caller["status"] != "active"
            or caller["owner"] != trusted["charging_owner_id"]
        ):
            raise ContractError("POLICY_DENIED", 403)
        mode = body["mode"]
        if mode == "direct_human":
            if (
                caller["kind"] != "human"
                or "agent_id" in body
                or "agent_version" in body
                or "initiating_user_id" in body
                or parent is not None
            ):
                raise ContractError("POLICY_DENIED", 403)
            return caller["principal_id"]
        if caller["kind"] != "service" or mode not in (
            "autonomous_agent",
            "user_delegated_agent",
            "nested_agent",
        ):
            raise ContractError("POLICY_DENIED", 403)
        if "agent_id" not in body or "agent_version" not in body:
            raise ContractError("SCHEMA_INVALID", 400)
        agent = self.agent(body.get("agent_id", ""))
        if (
            not agent
            or agent["status"] != "active"
            or body.get("agent_version") not in agent["versions"]
        ):
            raise ContractError("POLICY_DENIED", 403)
        if mode == "autonomous_agent":
            if parent is not None or "initiating_user_id" in body:
                raise ContractError("POLICY_DENIED", 403)
            user = None
        elif mode == "user_delegated_agent":
            if parent is not None:
                raise ContractError("POLICY_DENIED", 403)
            user = body.get("initiating_user_id")
            principal = self.registry.principal(user) if user else None
            if not principal or principal["status"] != "active" or principal["kind"] != "human":
                raise ContractError("POLICY_DENIED", 403)
        else:
            if (
                parent is None
                or "initiating_user_id" in body
                or parent["status"] != "running"
                or parent["principal_id"] != caller["principal_id"]
                or parent["task_id"] != body["task_id"]
                or parent["task_class"] != body["task_class"]
                or parent["evaluation_ref"] != body["evaluation_ref"]
                or parent["charging_owner_id"] != trusted["charging_owner_id"]
            ):
                raise ContractError("POLICY_DENIED", 403)
            user = parent["initiating_user_id"]
            if user:
                current_user = self.registry.principal(user)
                if not current_user or current_user["status"] != "active":
                    raise ContractError("POLICY_DENIED", 403)
        grant = self.permission(caller["principal_id"], body["agent_id"], user)
        if (
            not grant
            or grant["status"] != "active"
            or grant["charging_owner_id"] != trusted["charging_owner_id"]
            or body["task_class"] not in grant["task_classes"]
        ):
            raise ContractError("POLICY_DENIED", 403)
        return user

    def start_run(self, trusted, body):
        required = {"version", "run_id", "task_id", "task_class", "evaluation_ref", "mode"}
        allowed = required | {"agent_id", "agent_version", "initiating_user_id", "parent_run_id"}
        if (
            type(body) is not dict
            or not required <= body.keys()
            or set(body) - allowed
            or body["version"] != "1"
        ):
            raise ContractError("SCHEMA_INVALID", 400)
        for key in ("run_id", "task_id", "task_class", "evaluation_ref"):
            _id(body[key])
        for key in ("agent_id", "agent_version", "initiating_user_id", "parent_run_id"):
            if key in body:
                _id(body[key])
        if body["mode"] != "nested_agent" and "parent_run_id" in body:
            raise ContractError("SCHEMA_INVALID", 400)
        if body["mode"] == "nested_agent" and "parent_run_id" not in body:
            raise ContractError("SCHEMA_INVALID", 400)
        parent = self.run(body["parent_run_id"]) if "parent_run_id" in body else None
        if "parent_run_id" in body and parent is None:
            raise ContractError("NOT_FOUND_OR_FORBIDDEN", 404)
        user = self._authorize(trusted, body, parent)
        digest = hashlib.sha256(encode(body).encode()).hexdigest()

        record = {
            "run_id": body["run_id"],
            "principal_id": trusted["principal_id"],
            "charging_owner_id": trusted["charging_owner_id"],
            "initiating_user_id": user,
            "agent_id": body.get("agent_id"),
            "agent_version": body.get("agent_version"),
            "parent_run_id": parent["run_id"] if parent else None,
            "root_run_id": parent["root_run_id"] if parent else body["run_id"],
            "task_id": body["task_id"],
            "task_class": body["task_class"],
            "mode": body["mode"],
            "evaluation_ref": body["evaluation_ref"],
            "created_at": timestamp(),
            "status": "running",
            "request_digest": digest,
        }

        def save():
            old = _record(self.store.database, "attribution_runs", "id", body["run_id"])
            if old:
                if (
                    old["principal_id"] != trusted["principal_id"]
                    or old["request_digest"] != digest
                    or old["charging_owner_id"] != trusted["charging_owner_id"]
                ):
                    raise ContractError("WORK_CONFLICT", 409)
                return old
            self.store.database.execute(
                _queries.SAVE_INSERT_ATTRIBUTION_RUNS, (body["run_id"], encode(record))
            )
            return record

        return deepcopy(self.store.database.transaction(save))

    def bind(self, trusted, req, run_id):
        run = self.run(run_id)
        if not run or run["principal_id"] != trusted["principal_id"]:
            raise ContractError("NOT_FOUND_OR_FORBIDDEN", 404)
        if (
            run["charging_owner_id"] != trusted["charging_owner_id"]
            or run["status"] != "running"
            or run["task_id"] != req["task_id"]
            or run["task_class"] != req["task_class"]
        ):
            raise ContractError("POLICY_DENIED", 403)
        body = {
            "task_id": run["task_id"],
            "task_class": run["task_class"],
            "evaluation_ref": run["evaluation_ref"],
            "mode": run["mode"],
        }
        if run["agent_id"]:
            body.update(agent_id=run["agent_id"], agent_version=run["agent_version"])
        if run["mode"] == "user_delegated_agent":
            body["initiating_user_id"] = run["initiating_user_id"]
        parent = self.run(run["parent_run_id"]) if run["parent_run_id"] else None
        self._authorize(trusted, body, parent)
        user = run["initiating_user_id"]
        if user and user != trusted["principal_id"]:
            access = self.registry.explain(
                user,
                req["requested_configuration_ref"],
                req["purpose"],
                req["task_class"],
                req["requested_features"],
            )
            if not access["allowed"]:
                raise ContractError("POLICY_DENIED", 403)
        return {
            key: run[key]
            for key in (
                "run_id",
                "principal_id",
                "charging_owner_id",
                "initiating_user_id",
                "agent_id",
                "agent_version",
                "parent_run_id",
                "root_run_id",
                "task_id",
                "task_class",
                "evaluation_ref",
                "mode",
                "created_at",
            )
        }

    def apply_admin(self, db, action, subject, expected, data):
        if action == "register_agent":
            if (
                expected
                or set(data) != {"display_name", "owner", "versions"}
                or type(data["versions"]) is not list
                or not data["versions"]
                or len(set(data["versions"])) != len(data["versions"])
            ):
                raise ValueError("invalid agent registration")
            if _record(db, "registry_agents", "id", subject):
                raise RegistryConflict("agent exists")
            versions = [identifier(item) for item in data["versions"]]
            record = {
                "agent_id": subject,
                "display_name": nonempty(data["display_name"]),
                "owner": identifier(data["owner"]),
                "versions": versions,
                "status": "active",
                "instrumentation_status": "not_instrumented",
                "instrumentation_ref": None,
                "revision": 1,
                "created_at": timestamp(),
            }
            db.execute(_queries.APPLY_ADMIN_INSERT_REGISTRY_AGENTS, (subject, encode(record)))
            return record
        if action == "agent_state":
            record = _record(db, "registry_agents", "id", subject)
            if (
                not record
                or record["revision"] != expected
                or set(data) != {"status", "reason"}
                or data["status"] not in ("active", "archived")
            ):
                raise RegistryConflict("agent revision changed or invalid state")
            record.update(
                status=data["status"], state_reason=nonempty(data["reason"]), revision=expected + 1
            )
            db.execute(_queries.APPLY_ADMIN_UPDATE_REGISTRY_AGENTS, (encode(record), subject))
            return record
        if action == "agent_instrumentation":
            record = _record(db, "registry_agents", "id", subject)
            if (
                not record
                or record["revision"] != expected
                or set(data) != {"status", "evidence_ref"}
                or data["status"] not in ("instrumented", "not_instrumented")
            ):
                raise RegistryConflict("agent instrumentation revision changed")
            reference = identifier(data["evidence_ref"])
            record.update(
                instrumentation_status=data["status"],
                instrumentation_ref=reference,
                revision=expected + 1,
            )
            db.execute(_queries.APPLY_ADMIN_UPDATE_REGISTRY_AGENTS, (encode(record), subject))
            return record
        if action == "set_agent_permission":
            required = {
                "caller_principal_id",
                "agent_id",
                "charging_owner_id",
                "task_classes",
                "status",
            }
            if (
                set(data) not in (required, required | {"initiating_user_id"})
                or data["status"] not in ("active", "revoked")
                or type(data["task_classes"]) is not list
                or not data["task_classes"]
            ):
                raise ValueError("invalid agent permission")
            caller = _record(
                db, "registry_principals", "id", identifier(data["caller_principal_id"])
            )
            agent = _record(db, "registry_agents", "id", identifier(data["agent_id"]))
            user = identifier(data["initiating_user_id"]) if "initiating_user_id" in data else None
            user_record = _record(db, "registry_principals", "id", user) if user else None
            owner = identifier(data["charging_owner_id"])
            if (
                not caller
                or caller["kind"] != "service"
                or caller["owner"] != owner
                or not agent
                or (user and (not user_record or user_record["kind"] != "human"))
            ):
                raise ValueError("agent permission scope invalid")
            classes = sorted({identifier(item) for item in data["task_classes"]})
            current = _record(db, "registry_agent_permissions", "id", subject)
            if (
                current
                and (
                    current["revision"] != expected
                    or current["caller_principal_id"] != caller["principal_id"]
                    or current["agent_id"] != agent["agent_id"]
                    or current.get("initiating_user_id") != user
                )
            ) or (not current and expected != 0):
                raise RegistryConflict("agent permission revision changed")
            competing = db.execute(
                _queries.APPLY_ADMIN_SELECT_REGISTRY_AGENT_PERMISSIONS,
                (caller["principal_id"], agent["agent_id"], user or ""),
            ).fetchone()
            if competing and competing[0] != subject:
                raise RegistryConflict("agent permission scope already recorded")
            record = {
                "permission_id": subject,
                "caller_principal_id": caller["principal_id"],
                "agent_id": agent["agent_id"],
                "initiating_user_id": user,
                "charging_owner_id": owner,
                "task_classes": classes,
                "status": data["status"],
                "revision": expected + 1,
            }
            if current:
                db.execute(
                    _queries.APPLY_ADMIN_UPDATE_REGISTRY_AGENT_PERMISSIONS,
                    (encode(record), subject),
                )
            else:
                db.execute(
                    _queries.APPLY_ADMIN_INSERT_REGISTRY_AGENT_PERMISSIONS,
                    (
                        subject,
                        caller["principal_id"],
                        agent["agent_id"],
                        user or "",
                        encode(record),
                    ),
                )
            return record
        if action == "set_outcome_authority":
            if (
                set(data) != {"status", "task_classes"}
                or data["status"] not in ("active", "revoked")
                or type(data["task_classes"]) is not list
                or not data["task_classes"]
            ):
                raise ValueError("invalid outcome authority")
            principal = _record(db, "registry_principals", "id", subject)
            if not principal:
                raise ValueError("outcome principal unknown")
            current = _record(db, "registry_outcome_authorities", "id", subject)
            if (current and current["revision"] != expected) or (not current and expected):
                raise RegistryConflict("outcome authority revision changed")
            record = {
                "principal_id": subject,
                "status": data["status"],
                "task_classes": sorted({identifier(item) for item in data["task_classes"]}),
                "revision": expected + 1,
            }
            db.execute(
                _queries.APPLY_ADMIN_INSERT_REGISTRY_OUTCOME_AUTHORITIES, (subject, encode(record))
            )
            return record
        raise ValueError("unsupported agent authority action")

    def append_outcome(self, trusted, body):
        required = {
            "version",
            "event_id",
            "run_id",
            "kind",
            "subject_revision",
            "verdict",
            "evaluator_version",
            "evidence_ref",
        }
        optional = {"step_id", "step_revision", "execution_generation"}
        if (
            type(body) is not dict
            or not required <= body.keys()
            or set(body) - (required | optional)
            or body["version"] != "1"
            or body["kind"] not in ("task_outcome", "step_evaluation")
            or type(body["subject_revision"]) is not int
            or body["subject_revision"] < 1
        ):
            raise ContractError("SCHEMA_INVALID", 400)
        for key in ("event_id", "run_id", "evaluator_version", "evidence_ref"):
            _id(body[key])
        step = body["kind"] == "step_evaluation"
        if (step and set(body) != required | optional) or (not step and set(body) != required):
            raise ContractError("SCHEMA_INVALID", 400)
        if step:
            _id(body["step_id"])
            _id(body["execution_generation"])
            if (
                type(body["step_revision"]) is not int
                or body["step_revision"] < 1
                or body["verdict"] not in ("correct", "incorrect", "undetermined")
            ):
                raise ContractError("SCHEMA_INVALID", 400)
        elif body["verdict"] not in ("accepted", "rejected", "abandoned"):
            raise ContractError("SCHEMA_INVALID", 400)
        run = self.run(body["run_id"])
        if not run:
            raise ContractError("NOT_FOUND_OR_FORBIDDEN", 404)
        authority = self.registry.principal(trusted["principal_id"])
        with self.store.database.read():
            grant = _record(
                self.store.database, "registry_outcome_authorities", "id", trusted["principal_id"]
            )
        if (
            not authority
            or authority["status"] != "active"
            or not grant
            or grant["status"] != "active"
            or run["task_class"] not in grant["task_classes"]
            or authority["owner"] != run["charging_owner_id"]
        ):
            raise ContractError("POLICY_DENIED", 403)
        if step:
            with self.store.database.read():
                found = self.store.database.execute(
                    _queries.APPEND_OUTCOME_SELECT_SUBMISSIONS,
                    (
                        run["run_id"],
                        body["step_id"],
                        body["step_revision"],
                        body["execution_generation"],
                    ),
                ).fetchone()
            if not found:
                raise ContractError("NOT_FOUND_OR_FORBIDDEN", 404)
        subject = encode(
            [
                body["run_id"],
                body["kind"],
                body.get("step_id"),
                body.get("step_revision"),
                body.get("execution_generation"),
            ]
        )
        digest = hashlib.sha256(encode(body).encode()).hexdigest()

        def save():
            row = self.store.database.execute(
                _queries.SAVE_SELECT_ATTRIBUTION_OUTCOMES,
                (trusted["principal_id"], body["event_id"]),
            ).fetchone()
            if row:
                if row[0] != digest:
                    raise ContractError("EVENT_CONFLICT", 409)
                return json.loads(row[1])
            last = (
                self.store.database.execute(
                    _queries.SAVE_SELECT_ATTRIBUTION_OUTCOMES_2, (subject,)
                ).fetchone()[0]
                or 0
            )
            if body["subject_revision"] != last + 1:
                raise ContractError("STALE_REVISION", 409)
            at = timestamp()
            receipt = {
                "version": "1",
                "event_id": body["event_id"],
                "run_id": body["run_id"],
                "kind": body["kind"],
                "subject_revision": body["subject_revision"],
                "recorded_at": at,
                "event_digest": digest,
            }
            self.store.database.execute(
                _queries.SAVE_INSERT_ATTRIBUTION_OUTCOMES,
                (
                    trusted["principal_id"],
                    body["event_id"],
                    subject,
                    body["subject_revision"],
                    digest,
                    encode(body),
                    at,
                    encode(receipt),
                ),
            )
            if not step:
                current = _record(self.store.database, "attribution_runs", "id", run["run_id"])
                current.update(status=body["verdict"], terminal_at=at)
                self.store.database.execute(
                    _queries.SAVE_UPDATE_ATTRIBUTION_RUNS, (encode(current), run["run_id"])
                )
            return receipt

        return self.store.database.transaction(save)

    def outcome_receipt(self, trusted, event_id):
        _id(event_id)
        with self.store.database.read():
            row = self.store.database.execute(
                _queries.OUTCOME_RECEIPT_SELECT_ATTRIBUTION_OUTCOMES,
                (trusted["principal_id"], event_id),
            ).fetchone()
        if not row:
            raise ContractError("NOT_FOUND_OR_FORBIDDEN", 404)
        return json.loads(row[0])
