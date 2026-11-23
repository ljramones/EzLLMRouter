"""Resolve source backports only when archives and every runtime copy match."""

from __future__ import annotations

import json
import re
import subprocess

from deploy.local.local_profile import DOCKER
from tools.gateway.os_inputs import LOCK
from tools.security_resolutions import canonical


def capture(image: dict, native: dict) -> dict:
    identity = image["image"]["id"]
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", identity):
        raise ValueError("immutable image required for native review")
    role = "node" if "node@sha256:" in image["image"]["base"] else "python"
    expected = {
        row["path"]: row["sha256"] for row in native["code"] if row["role"] in {"all", role}
    }
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
            "import ssl,json,importlib.metadata; from cryptography.hazmat.backends.openssl.backend import backend; print(json.dumps({'openssl':ssl.OPENSSL_VERSION,'crypto_openssl':backend.openssl_version_text(),'cryptography':importlib.metadata.version('cryptography')}))",
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
        valid = (
            valid
            and versions["openssl"].startswith(version_prefix)
            and versions["crypto_openssl"].startswith(version_prefix)
            and versions["cryptography"] == native["cryptography"]["version"]
        )
    return {
        "image": identity,
        "native_build": native["id"],
        "valid": bool(valid),
        "code": observed,
        "versions": versions,
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
