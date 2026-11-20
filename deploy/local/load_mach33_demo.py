"""Install a validated portable Mach33 fixture into an isolated, immutable demo scope."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def private_write(path, payload):
    temporary = path.with_name("." + path.name + "." + secrets.token_hex(8) + ".new")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def install(package, scope):
    if not package.is_dir() or not scope.is_absolute() or scope.is_symlink():
        raise ValueError("package directory and absolute non-symlink scope required")
    manifest_bytes = (package / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get("schema") != "ezllmrouter.demo_package_manifest.v1" or not manifest.get(
        "synthetic"
    ):
        raise ValueError("unsupported demo package")
    for item in manifest["files"]:
        path = package / item["name"]
        if path.name != item["name"] or path.is_symlink():
            raise ValueError("unsafe package entry")
        payload = path.read_bytes()
        if len(payload) != item["bytes"] or digest(payload) != item["sha256"]:
            raise ValueError("demo package hash mismatch: " + item["name"])
    fixture_bytes = (package / "fixture.json").read_bytes()
    data = json.loads(fixture_bytes)
    metadata = data["metadata"]
    if (
        metadata.get("dataset_id") != manifest["dataset_id"]
        or not metadata.get("synthetic")
        or metadata.get("execution_policy")
        != {
            "external_requests": 0,
            "provider_inference_enabled": False,
            "real_credentials_required": False,
            "production_writes": False,
        }
        or any(
            not item["id"].startswith("demo.")
            for value in data.values()
            if isinstance(value, list)
            for item in value
        )
        or any(
            item["credential_reference"] is not None
            or item["endpoint"] is not None
            or item["inference_enabled"]
            for item in data["provider_accounts"]
        )
    ):
        raise ValueError("unsafe demo fixture")
    scope_record = {
        "schema": "ezllmrouter.scripted_demo_scope.v1",
        "dataset_id": metadata["dataset_id"],
        "fixture_sha256": digest(fixture_bytes),
        "manifest_sha256": digest(manifest_bytes),
    }
    scope.mkdir(mode=0o700, parents=True, exist_ok=True)
    if scope.stat().st_mode & 0o077:
        raise ValueError("demo scope permissions must be private")
    existing = scope / "scope.json"
    if existing.exists():
        previous = json.loads(existing.read_text())
        if (
            previous != scope_record
            or digest((scope / "fixture.json").read_bytes()) != scope_record["fixture_sha256"]
        ):
            raise ValueError("demo scope conflict: existing dataset ID has different content")
        return {"result": "unchanged", **scope_record}
    if any(scope.iterdir()):
        raise ValueError("demo scope is not empty")
    private_write(scope / "fixture.json", fixture_bytes)
    private_write(existing, (json.dumps(scope_record, sort_keys=True) + "\n").encode())
    return {"result": "installed", **scope_record}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--scope", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(install(args.package, args.scope), indent=2))


if __name__ == "__main__":
    main()
