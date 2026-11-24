"""Resolve source backports only when archives and every runtime copy match."""

from __future__ import annotations

import json
import re
import subprocess

from deploy.local.local_profile import DOCKER
from tools.gateway.os_inputs import LOCK
from tools.security_resolutions import canonical

CRYPTO_OBJECT = "/usr/local/lib/python3.12/site-packages/cryptography/hazmat/bindings/_rust.abi3.so"
PYTHON_VERSIONS = """import ssl,json,importlib.util,os
data={'openssl':ssl.OPENSSL_VERSION,'cryptography':None,'crypto_openssl':None,
      'psycopg_binary':None,'libpq':None,
      'crypto_object_exists':os.path.lexists('/usr/local/lib/python3.12/site-packages/cryptography/hazmat/bindings/_rust.abi3.so')}
if importlib.util.find_spec('cryptography') is not None:
    import importlib.metadata
    from cryptography.hazmat.backends.openssl.backend import backend
    data.update(cryptography=importlib.metadata.version('cryptography'),crypto_openssl=backend.openssl_version_text())
if importlib.util.find_spec('psycopg_binary') is not None:
    import importlib.metadata
    import psycopg.pq
    data.update(psycopg_binary=importlib.metadata.version('psycopg-binary'),libpq=psycopg.pq.version())
print(json.dumps(data))
"""


def capture(image: dict, native: dict, driver: dict | None = None) -> dict:
    identity = image["image"]["id"]
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", identity):
        raise ValueError("immutable image required for native review")
    role = "node" if "node@sha256:" in image["image"]["base"] else "python"
    has_crypto = any(row["name"] == "cryptography" for row in image.get("application_packages", []))
    has_driver = any(
        row["name"] == "psycopg-binary" for row in image.get("application_packages", [])
    )
    expected = {
        row["path"]: row["sha256"]
        for row in native["code"]
        if row["role"] in {"all", role} and (row["path"] != CRYPTO_OBJECT or has_crypto)
    }
    if has_driver and driver:
        expected.update(
            {
                "/usr/local/lib/python3.12/site-packages/" + path: sha
                for path, sha in driver["code"].items()
            }
        )
    prefix = [
        *DOCKER,
        "run",
        "--rm",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        identity,
    ]
    raw = subprocess.check_output(
        [*prefix, "sha256sum", "-z", "--", *sorted(expected)], text=True, timeout=120
    )
    if not raw.endswith("\0"):
        raise ValueError("incomplete native code hashes")
    observed = {}
    for record in raw[:-1].split("\0"):
        match = re.fullmatch(r"([0-9a-f]{64})  (/.+)", record)
        if match is None or match[2] in observed:
            raise ValueError("ambiguous native code hashes")
        observed[match[2]] = match[1]
    owned = [row for row in image["os_packages"] if row["name"] == "openssl"]
    binaries = {"libssl3t64", "openssl-provider-legacy"} | (
        {"openssl"} if role == "python" else set()
    )
    valid = (
        observed == expected
        and (not has_driver or driver is not None)
        and {row["binary"] for row in owned} == binaries
        and all(
            row["binary_version"] == row["version"] == native["openssl_source_version"]
            for row in owned
        )
    )
    if role == "node":
        command = [
            "node",
            "-e",
            "console.log(JSON.stringify({openssl:process.versions.openssl,shared:process.config.variables.node_shared_openssl,node:process.versions.node}))",
        ]
    else:
        command = [
            "python",
            "-I",
            "-c",
            PYTHON_VERSIONS,
        ]
    versions = json.loads(subprocess.check_output([*prefix, *command], text=True, timeout=60))
    if role == "node":
        valid = valid and versions == {
            "openssl": native["openssl_version"],
            "shared": True,
            "node": native["node"]["version"],
        }
    else:
        version_prefix = "OpenSSL " + native["openssl_version"] + " "
        valid = valid and versions["openssl"].startswith(version_prefix)
        if has_crypto:
            valid = (
                valid
                and versions["crypto_object_exists"]
                and versions["crypto_openssl"].startswith(version_prefix)
                and versions["cryptography"] == native["cryptography"]["version"]
            )
        else:
            valid = (
                valid
                and not versions["crypto_object_exists"]
                and versions["cryptography"] is None
                and versions["crypto_openssl"] is None
            )
        if has_driver and driver:
            valid = (
                valid
                and versions.get("psycopg_binary") == driver["version"]
                and versions.get("libpq") == driver["libpq_version"]
            )
        elif not has_driver:
            valid = (
                valid and versions.get("psycopg_binary") is None and versions.get("libpq") is None
            )
    return {
        "image": identity,
        "native_build": native["id"],
        "valid": bool(valid),
        "code": observed,
        "versions": versions,
        "native_driver": driver["id"] if has_driver and driver else None,
    }


def apply_reviews(report: dict, snapshot: dict, images: dict, captures: dict, native: dict) -> dict:
    archives = report.get("archive_proof")
    sources = {"image:" + name + ":" + value["image"]["id"]: name for name, value in images.items()}
    all_copies = (
        bool(images)
        and set(captures) == set(images)
        and all(
            proof["valid"]
            and proof["native_build"] == native["id"]
            and proof["image"] == images[name]["image"]["id"]
            for name, proof in captures.items()
        )
    )
    resolved = 0
    for decision in report["decisions"]:
        package = decision["package"]
        review = native["fixed_advisories"].get(decision["id"])
        if (
            not review
            or not decision["raw_blocking"]
            or (package["ecosystem"], package["name"], package["version"])
            != ("Debian:13", "openssl", native["openssl_source_version"])
        ):
            continue
        valid = (
            all_copies
            and canonical(snapshot["vulnerabilities"][decision["id"]]) == review["advisory_sha256"]
            and bool(package["sources"])
        )
        for source in package["sources"]:
            if source in sources:
                continue
            if (
                source != LOCK
                or not archives
                or archives["inventory_sha256"] != snapshot["inventory_sha256"]
            ):
                valid = False
                continue
            owned = [row for row in archives["packages"] if row["source"] == "openssl"]
            valid = valid and {row["binary"] for row in owned} == set(native["packages"])
            for row in owned:
                output = native["outputs"].get(native["packages"].get(row["binary"], ""), {})
                valid = (
                    valid
                    and row["binary_version"]
                    == row["source_version"]
                    == native["openssl_source_version"]
                    and row["archive_sha256"] == output.get("sha256")
                )
        if valid:
            decision.update(state="fixed", effective_blocking=False, native_build=native["id"])
            for target in decision["targets"].values():
                target.update(state="fixed", reason=review["reason"])
            resolved += 1
    report["resolved_native_matches"] = resolved
    report["effective_blocking"] = sum(row["effective_blocking"] for row in report["decisions"])
    report["native_captures"] = captures
    report["native_build"] = native["id"]
    return report
