"""Additional reviewed component selectors over the complete image census."""

from __future__ import annotations

import hashlib
from pathlib import PurePosixPath

SELECTORS = (
    ("absent_executables", "basenames"),
    ("absent_perl_modules", "perl_paths"),
    ("absent_sqlite_extensions", "sqlite_extensions"),
)


def capture(raw: str, policy: dict, inventory: dict) -> dict:
    if not raw.endswith("\0"):
        raise ValueError("incomplete additional component census")
    records = raw[:-1].split("\0")
    sha = hashlib.sha256("\0".join(sorted(records)).encode()).hexdigest()
    if sha != inventory["sha256"]:
        raise ValueError("additional component census differs from complete inventory")
    selected = {
        name: sorted({value for review in policy["reviews"] for value in review.get(key, [])})
        for key, name in SELECTORS
    }
    present = {name: set() for _key, name in SELECTORS}
    for record in records:
        kind, mode, value = record.split("\t")
        path = PurePosixPath(value)
        for name in selected["basenames"]:
            if path.name == name and (kind == "l" or int(mode, 8) & 0o111):
                present["basenames"].add(name)
        for module in selected["perl_paths"]:
            aliases = set(PurePosixPath(module).parent.parts)
            if value.endswith("/" + module) or (kind == "l" and path.name in aliases):
                present["perl_paths"].add(module)
        if path.name in selected["sqlite_extensions"]:
            present["sqlite_extensions"].add(path.name)
    return {
        "sha256": sha,
        **{"checked_" + name: values for name, values in selected.items()},
        **{"present_" + name: sorted(values) for name, values in present.items()},
    }


def absent(proof: dict, review: dict) -> bool:
    inventory = proof["component_inventory"]
    extra = proof.get("reviewed_component_inventory", {})
    if extra and extra.get("sha256") != inventory.get("sha256"):
        return False
    if inventory["forbidden_components"]:
        return False
    for key, name in SELECTORS:
        required = set(review.get(key, []))
        checked = set(inventory.get("checked_" + name, [])) | set(extra.get("checked_" + name, []))
        if not required <= checked or required & set(extra.get("present_" + name, [])):
            return False
    return True
