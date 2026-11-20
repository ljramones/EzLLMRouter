"""Shared principal authorization and atomic authority/audit bookkeeping.

Call mutation helpers inside the owning database transaction. Publish the
in-memory authority epoch only after that transaction commits.
"""

import json
from collections.abc import Collection, Mapping
from typing import cast

from ..database import Database, Query

PRINCIPAL = Query("SELECT record FROM registry_principals WHERE id=?")
REVISION = Query("SELECT value FROM registry_meta WHERE key='authority_revision'")
ADVANCE = Query("UPDATE registry_meta SET value=? WHERE key='authority_revision'")
AUDIT = Query(
    "INSERT INTO registry_audit (actor,action,subject,old_revision,new_revision,authority_revision,at) VALUES (?,?,?,?,?,?,?)"
)
AUDIT_VALUES = Query("INSERT INTO registry_audit_values VALUES (?,?,?)")


def authorized(db: Database, actor: str, roles: Collection[str] = ("registry_admin",)) -> bool:
    row = db.execute(PRINCIPAL, (actor,)).fetchone()
    principal = json.loads(cast(str, row[0])) if row else None
    return bool(principal and principal["status"] == "active" and principal["role"] in roles)


def public_values(record: Mapping[str, object] | None) -> dict[str, object] | None:
    """Preserve the management audit allowlist; never snapshot credentials."""
    if not record:
        return None
    return {
        key: record[key]
        for key in (
            "display_name",
            "status",
            "role",
            "price_version",
            "credential_state",
            "credential_version",
        )
        if key in record
    }


def record_change(
    db: Database,
    *,
    actor: str,
    action: str,
    subject: str,
    old_revision: int | None,
    new_revision: int,
    at: str,
    include_values: bool = False,
    before: Mapping[str, object] | None = None,
    after: Mapping[str, object] | None = None,
) -> int:
    row = db.execute(REVISION).fetchone()
    if row is None:
        raise RuntimeError("missing authority revision")
    revision = int(cast(str, row[0])) + 1
    db.execute(ADVANCE, (str(revision),))
    audit = db.execute(AUDIT, (actor, action, subject, old_revision, new_revision, revision, at))
    if include_values:

        def encode(value: object) -> str:
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

        db.execute(
            AUDIT_VALUES,
            (audit.lastrowid, encode(public_values(before)), encode(public_values(after))),
        )
    return revision
