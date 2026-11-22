"""Reviewed wire policy loading and request templates, independent of dispatch."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "tests/fixtures/wire_authorization.json").read_text())


def routes():
    for row in POLICY["work"]:
        for version in row["versions"]:
            yield {**row, "version": version, "family": "work"}
    for row in POLICY["integration"]:
        for version in row["versions"]:
            yield {**row, "version": version, "family": "integration"}


def expected(row, actor):
    permissions = POLICY["permissions"][row["permission"]]
    if actor in permissions:
        return row.get("success_status", {}).get(row["version"], permissions[actor])
    return row.get("denied", 404)
