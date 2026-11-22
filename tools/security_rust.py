"""Validate the reviewed crates.io lock closure without executing dependency code."""

import re
from typing import Any

REGISTRY = "registry+https://github.com/rust-lang/crates.io-index"


def rust_graph(
    lock: dict[str, Any], manifest: dict[str, Any], metadata: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    if lock.get("version") != 4 or not lock.get("package"):
        raise ValueError("unsupported or empty Rust lock")
    packages = lock["package"]
    identities = {(row["name"], row["version"]): row for row in packages}
    if len(identities) != len(packages):
        raise ValueError("duplicate Rust lock identity")
    local = manifest["package"]
    roots = [row for row in packages if row.get("source") is None]
    if len(roots) != 1 or (roots[0]["name"], roots[0]["version"]) != (
        local["name"],
        local["version"],
    ):
        raise ValueError("unreviewed local Rust dependency")
    edges = {}
    for row in packages:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", row["name"]) or not re.fullmatch(
            r"[0-9][A-Za-z0-9.+_-]*", row["version"]
        ):
            raise ValueError("invalid Rust package identity")
        if row not in roots and (
            row.get("source") != REGISTRY
            or not re.fullmatch(r"[0-9a-f]{64}", row.get("checksum", ""))
        ):
            raise ValueError("unreviewed Rust registry or checksum")
        selected = set()
        for dependency in row.get("dependencies", []):
            parts = dependency.split()
            if not parts:
                raise ValueError("empty Rust lock edge")
            candidates = [
                key
                for key in identities
                if key[0] == parts[0] and (len(parts) == 1 or key[1] == parts[1])
            ]
            if len(parts) > 2 or len(candidates) != 1:
                raise ValueError("unresolved or ambiguous Rust lock edge")
            selected.add(candidates[0])
        edges[(row["name"], row["version"])] = selected
    pending = [(local["name"], local["version"])]
    reachable = set()
    while pending:
        key = pending.pop()
        if key not in reachable:
            reachable.add(key)
            pending.extend(edges[key])
    if reachable != set(identities):
        raise ValueError("orphan Rust lock package")
    for group in ("dependencies", "dev-dependencies", "build-dependencies"):
        for name, item in manifest.get(group, {}).items():
            item = {"version": item} if isinstance(item, str) else item
            if (
                not item["version"].startswith("=")
                or (item.get("package", name), item["version"][1:]) not in identities
            ):
                raise ValueError("Rust declaration/lock mismatch")
    if metadata is not None:
        if {(p["name"], p["version"]) for p in metadata["packages"]} != set(identities):
            raise ValueError("Rust metadata/lock mismatch")
        by_id = {p["id"]: p for p in metadata["packages"]}
        nodes = metadata["resolve"]["nodes"]
        if {node["id"] for node in nodes} != set(by_id) or len(nodes) != len(by_id):
            raise ValueError("incomplete Rust resolution graph")
        for node in nodes:
            if any(edge["pkg"] not in by_id for edge in node["deps"]):
                raise ValueError("unknown Rust metadata edge")
            package = by_id[node["id"]]
            resolved = {
                (by_id[edge["pkg"]]["name"], by_id[edge["pkg"]]["version"]) for edge in node["deps"]
            }
            if resolved != edges[(package["name"], package["version"])]:
                raise ValueError("Rust metadata edge mismatch")
        if any(
            p["source"] != identities[(p["name"], p["version"])].get("source")
            for p in by_id.values()
        ):
            raise ValueError("Rust metadata source mismatch")
    return [row for row in packages if row not in roots]
