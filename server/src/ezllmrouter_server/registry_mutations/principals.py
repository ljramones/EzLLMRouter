"""Registry principals operations; caller owns the existing authority context."""

from __future__ import annotations

from typing import cast
from ..database import Row

from typing import TYPE_CHECKING
from ..database import Database
from ..records import Record

if TYPE_CHECKING:
    from ..registry import Registry

from ..errors import RegistryConflict
from ..identifiers import require_text as nonempty
from ..repositories import registry as _queries
from ..store import encode
from ..registry_values import timestamp, identifier


def _apply_create_principal(
    self: Registry, db: Database, actor: str, action: str, subject: str, expected: int, data: Record
) -> Record:
    if (
        expected
        or set(data)
        not in (
            {"display_name", "kind", "owner"},
            {"display_name", "kind", "owner", "role"},
        )
        or data["kind"] not in ("human", "service")
    ):
        raise ValueError("invalid principal creation")
    role = data.get("role", "ordinary")
    if role not in ("ordinary", "read_only_operator", "registry_admin") or (
        data["kind"] == "service" and role != "ordinary"
    ):
        raise ValueError("invalid principal role")
    if db.execute(_queries.APPLY_SELECT_REGISTRY_PRINCIPALS, (subject,)).fetchone():
        raise RegistryConflict("principal exists")
    record = {
        "principal_id": subject,
        "display_name": nonempty(data["display_name"]),
        "kind": data["kind"],
        "owner": identifier(data["owner"]),
        "status": "inactive",
        "role": role,
        "revision": 1,
        "credential_state": "unbound",
        "record_origin": "operator_entered",
    }
    db.execute(_queries.APPLY_INSERT_REGISTRY_PRINCIPALS, (subject, encode(record)))
    return record


def _apply_principal_change(
    self: Registry, db: Database, actor: str, action: str, subject: str, expected: int, data: Record
) -> Record:
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
            "ordinary",
            "read_only_operator",
            "registry_admin",
        ):
            raise ValueError("invalid role")
        if record["kind"] != "human" and data["role"] != "ordinary":
            raise ValueError("service identity cannot receive console authority")
        if self.users:
            self.users.validate_principal_change(db, record, data["role"], record["status"])
        if (
            record["role"] == "registry_admin"
            and record["status"] == "active"
            and data["role"] != "registry_admin"
        ):
            active = cast(int, cast(Row, db.execute(_queries.ACTIVE_ADMIN_COUNT).fetchone())[0])
            if active <= 1:
                raise ValueError("last active administrator")
        record["role"] = data["role"]
    else:
        if set(data) != {"status", "reason"} or data["status"] not in (
            "active",
            "suspended",
            "revoked",
        ):
            raise ValueError("invalid principal state")
        nonempty(data["reason"])
        if data["status"] == "active" and record["credential_state"] == "unbound":
            raise ValueError("principal credential not provisioned")
        if self.users:
            self.users.validate_principal_change(db, record, record["role"], data["status"])
        if (
            record["role"] == "registry_admin"
            and record["status"] == "active"
            and data["status"] != "active"
        ):
            active = cast(int, cast(Row, db.execute(_queries.ACTIVE_ADMIN_COUNT).fetchone())[0])
            if active <= 1:
                raise ValueError("last active administrator")
        record["status"], record["state_reason"] = data["status"], data["reason"]
    if action in ("set_role", "principal_state") and self.users:
        db.execute(_queries.APPLY_UPDATE_CONSOLE_USERS, (timestamp(), subject))
    record["revision"] += 1
    db.execute(_queries.APPLY_UPDATE_REGISTRY_PRINCIPALS, (encode(record), subject))
    return record
