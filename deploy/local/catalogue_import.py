#!/usr/bin/env python3
"""One bounded authenticated import of public reference metadata into the live registry."""
from __future__ import annotations

import hashlib
import http.client
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "deploy/local/inputs/catalogue.json"
PASSWORD = ROOT / "deploy/local/.state/operator-password"
SEED_SHA256 = "1f01fe3ad181905e77738109739cde4ea7f76e55b0f3b245f0da296ad4cfe2bd"


class OperatorClient:
    def __init__(self, password, port=8780):
        self.port = port
        self.cookie = None
        self.csrf = None
        response = self.request("POST", "/operator/v1/login", {"password": password})
        if response["body"].get("principal_id") != "owner.local" or response["body"].get("role") != "registry_admin":
            raise RuntimeError("existing owner administrator required")
        self.cookie = response["cookie"].split(";", 1)[0]
        self.csrf = response["body"]["csrf"]

    def request(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Host": f"127.0.0.1:{self.port}"}
        if self.cookie:
            headers["Cookie"] = self.cookie
        if method == "POST":
            headers["Origin"] = f"http://127.0.0.1:{self.port}"
            headers["Content-Type"] = "application/json"
            if self.csrf:
                headers["X-EzLLMRouter-CSRF"] = self.csrf
        encoded = json.dumps(body, separators=(",", ":")) if body is not None else None
        try:
            conn.request(method, path, encoded, headers)
            result = conn.getresponse()
            response = {"status": result.status, "cookie": result.getheader("Set-Cookie"),
                        "body": json.loads(result.read())}
        finally:
            conn.close()
        if response["status"] != 200:
            raise RuntimeError(f"operator {path} rejected: HTTP {response['status']} "
                               f"{response['body'].get('error', 'UNKNOWN')}")
        return response

    def get(self, path):
        return self.request("GET", path)["body"]

    def mutate(self, action, subject, expected, data, operation_id):
        return self.request("POST", "/operator/v1/registry", {"operation_id": operation_id,
            "action": action, "subject": subject, "expected_revision": expected, "data": data})["body"]


def seed_data():
    raw = SEED.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SEED_SHA256:
        raise RuntimeError("researched seed hash changed")
    seed = json.loads(raw)
    if seed.get("schema") != "ezllmrouter.researched_catalogue_seed.v1" or len(seed.get("models", [])) != 12:
        raise RuntimeError("unexpected researched catalogue shape")
    return seed


def import_catalogue(client, seed):
    before = client.get("/operator/v1/overview")["counts"]
    before_models = client.get("/operator/v1/models")["items"]
    before_principals = client.get("/operator/v1/principals")["items"]
    grants_before = {p["principal_id"]: p["grant_summary"] for p in before_principals}
    fixture_prices_before = {m["configuration_ref"]: m["current_price"] for m in before_models
                             if m.get("kind") != "real_catalogue"}
    sources = {source["id"]: source for source in seed["sources"]}
    imported = []
    for entry in seed["models"]:
        subject = "catalogue." + entry["catalogue_key"]
        selected = [sources[ref] for ref in entry["source_refs"]]
        digest = hashlib.sha256(json.dumps({"entry": entry, "sources": selected},
                                          sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        client.mutate("import_catalogue", subject, 0, {"entry": entry, "sources": selected},
                      "op.catalogue." + digest[:32])
        record = client.get("/operator/v1/models/" + subject)
        if (record["model"]["kind"] != "real_catalogue" or
                record["model"]["catalogue"] != entry or
                record["readiness"] != "not_connected"):
            raise RuntimeError("catalogue readback or execution boundary mismatch")
        imported.append(subject)
    owner = client.get("/operator/v1/principals/owner.local")["principal"]
    if owner["display_name"] == "Local owner":
        client.mutate("edit_principal", "owner.local", owner["revision"],
                      {"display_name": "Larry Mitchell"}, "op.catalogue.owner-name.20261021")
    elif owner["display_name"] != "Larry Mitchell":
        raise RuntimeError("owner display name conflicts with approved identity")
    after_owner = client.get("/operator/v1/principals/owner.local")["principal"]
    if (after_owner["display_name"] != "Larry Mitchell" or after_owner["principal_id"] != "owner.local" or
            after_owner["credential_state"] != owner["credential_state"] or
            after_owner["role"] != owner["role"]):
        raise RuntimeError("owner identity binding changed")
    models = client.get("/operator/v1/models")["items"]
    principals = client.get("/operator/v1/principals")["items"]
    if not set(imported) <= {m["configuration_ref"] for m in models}:
        raise RuntimeError("catalogue list incomplete")
    for model in models:
        if model["configuration_ref"] in imported and model["readiness"] != "not_connected":
            raise RuntimeError("catalogue became connected")
    if ({p["principal_id"]: p["grant_summary"] for p in principals} != grants_before or
            {m["configuration_ref"]: m["current_price"] for m in models
             if m.get("kind") != "real_catalogue"} != fixture_prices_before):
        raise RuntimeError("existing grants or synthetic prices changed")
    after = client.get("/operator/v1/overview")["counts"]
    if after != before:
        raise RuntimeError("metadata import changed submission counts")
    return {"kind": "DEV-07 researched catalogue import", "status": "PASS",
            "catalogue_entries": len(imported), "owner_display_name": after_owner["display_name"],
            "identity_count": len(principals), "submission_counts_unchanged": True,
            "grants_and_fixture_prices_unchanged": True,
            "catalogue_transport": "not_connected", "seed_sha256": SEED_SHA256}


def main():
    result = import_catalogue(OperatorClient(PASSWORD.read_text().strip()), seed_data())
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
