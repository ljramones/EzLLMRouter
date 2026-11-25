"""Artifact-bound component dispositions; raw OSV findings remain unchanged."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

from deploy.local.local_profile import DOCKER
from tools.deployment_qualification import runtime_components
from tools.gateway.os_inputs import LOCK, advisory_ecosystem, verify_archives
from tools.security_component_census import capture as component_census, absent as components_absent


def canonical(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def load_policy(path: Path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("component review must be a regular file")
    policy = json.loads(path.read_text())
    if policy.get("format") != "ezllmrouter-component-reviews-v1":
        raise ValueError("unsupported component review format")
    reviewed = datetime.fromisoformat(policy["reviewed_at"])
    expires = datetime.fromisoformat(policy["expires_at"])
    now = datetime.now(timezone.utc)
    if (
        reviewed.tzinfo is None
        or expires.tzinfo is None
        or not reviewed <= now <= expires
        or not timedelta(0) < expires - reviewed <= timedelta(days=7)
    ):
        raise ValueError("invalid or expired component review period")
    for name, package in policy["packages"].items():
        if not re.fullmatch(r"[a-z0-9][a-z0-9+.-]*", name):
            raise ValueError("invalid reviewed binary name")
        for key in ("archive_sha256", "code_set_sha256", "payload_manifest_sha256"):
            if not re.fullmatch(r"[0-9a-f]{64}", package[key]):
                raise ValueError("invalid reviewed artifact identity")
        paths = package["code_files"]
        if len(paths) > 4096 or paths != sorted(set(paths)):
            raise ValueError("ambiguous reviewed code file set")
        for value in paths:
            path = PurePosixPath(value)
            if (
                not value.startswith("/")
                or str(path) != value
                or ".." in path.parts
                or not re.fullmatch(r"/[A-Za-z0-9._+/-]+", value)
            ):
                raise ValueError("unsafe reviewed code file")
    identities = set()
    for review in policy["reviews"]:
        identity = (review["ecosystem"], review["source"], review["source_version"], review["id"])
        if (
            identity in identities
            or not re.fullmatch(r"[0-9a-f]{64}", review["advisory_sha256"])
            or not review["reason"].strip()
        ):
            raise ValueError("invalid or duplicate component review")
        identities.add(identity)
        if (
            not review["allowed_binaries"]
            or not set(review["allowed_binaries"]) <= policy["packages"].keys()
        ):
            raise ValueError("unbound component review binaries")
        if not any(
            review.get(key, [])
            for key in ("absent_executables", "absent_perl_modules", "absent_sqlite_extensions")
        ):
            if review.get("metadata_only") is not True or any(
                policy["packages"][name].get("metadata_only") is not True
                or policy["packages"][name]["code_files"]
                or policy["packages"][name]["code_set_sha256"] != canonical([])
                for name in review["allowed_binaries"]
            ):
                raise ValueError("empty reviewed component requirement")
    return policy


def capture(image, policy):
    immutable = image["image"]["id"]
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", immutable):
        raise ValueError("immutable image required for component review")
    prefix = [
        *DOCKER,
        "run",
        "--rm",
        "--network=none",
        "--read-only",
        "--user=0:0",
        "--cap-drop=ALL",
        "--cap-add=DAC_OVERRIDE",
        "--security-opt=no-new-privileges:true",
        immutable,
    ]
    raw = subprocess.check_output(
        [
            *prefix,
            "find",
            "/",
            "-xdev",
            "(",
            "-type",
            "f",
            "-o",
            "-type",
            "l",
            ")",
            "-printf",
            "%y\\t%m\\t%p\\0",
        ],
        text=True,
        timeout=120,
    )
    census = runtime_components(raw)
    installed = {row["binary"]: row for row in image["os_packages"]}
    selected = {
        name: package
        for name, package in policy["packages"].items()
        if name in installed
        and installed[name]["binary_version"] == package["binary_version"]
        and installed[name]["name"] == package["source"]
        and installed[name]["version"] == package["source_version"]
    }
    paths = sorted({path for package in selected.values() for path in package["code_files"]})
    hashes = {}
    if paths:
        raw_hashes = subprocess.check_output(
            [*prefix, "sha256sum", "-z", "--", *paths], text=True, timeout=120
        )
        if not raw_hashes.endswith("\0"):
            raise ValueError("incomplete image code hashes")
        for record in raw_hashes[:-1].split("\0"):
            match = re.fullmatch(r"([0-9a-f]{64})  (/.+)", record)
            if match is None or match[2] in hashes:
                raise ValueError("ambiguous image code hashes")
            hashes[match[2]] = match[1]
        if set(hashes) != set(paths):
            raise ValueError("incomplete image code file set")
    packages = {}
    for name, reviewed in selected.items():
        code = [{"path": path, "sha256": hashes[path]} for path in reviewed["code_files"]]
        packages[name] = {
            "binary_version": installed[name]["binary_version"],
            "source": installed[name]["name"],
            "source_version": installed[name]["version"],
            "code_set_sha256": canonical(code),
        }
    return {
        "image": immutable,
        "component_inventory": census,
        "reviewed_component_inventory": component_census(raw, policy, census),
        "packages": packages,
    }


def capture_archives(root: Path, store: Path, inventory):
    data = verify_archives(root, store)
    observed = hashlib.sha256((root / LOCK).read_bytes()).hexdigest()
    if observed != inventory["source_sha256"][LOCK]:
        raise ValueError("archive lock differs from audited inventory")
    return {
        "source": LOCK,
        "lock_sha256": observed,
        "inventory_sha256": inventory["sha256"],
        "packages": [
            {
                "binary": row["package"],
                "binary_version": row["version"],
                "source": row["source"],
                "source_version": row["source_version"],
                "ecosystem": advisory_ecosystem(data, row),
                "architecture": row["architecture"],
                "archive_sha256": row["sha256"],
            }
            for row in data["packages"]
        ],
    }


def evaluate(issues, snapshot, images, captures, policy, archives=None):
    reviews = {
        (row["ecosystem"], row["source"], row["source_version"], row["id"]): row
        for row in policy["reviews"]
    }
    sources = {"image:" + name + ":" + image["image"]["id"]: name for name, image in images.items()}
    decisions = []
    for issue in issues:
        package = issue["package"]
        review = reviews.get(
            (package["ecosystem"], package["name"], package["version"], issue["id"])
        )
        targets = {}
        matches = (
            bool(review)
            and canonical(snapshot["vulnerabilities"][issue["id"]]) == review["advisory_sha256"]
        )
        for source in package["sources"]:
            role = sources.get(source)
            if source == LOCK and archives is not None and archives["source"] == LOCK:
                owned = [
                    row
                    for row in archives["packages"]
                    if (row["ecosystem"], row["source"], row["source_version"])
                    == (package["ecosystem"], package["name"], package["version"])
                ]
                valid = (
                    matches
                    and archives["inventory_sha256"] == snapshot["inventory_sha256"]
                    and bool(owned)
                    and {row["binary"] for row in owned} <= set(review["allowed_binaries"])
                )
                if valid:
                    for row in owned:
                        approved = policy["packages"][row["binary"]]
                        valid = valid and all(
                            row[key] == approved[key]
                            for key in (
                                "binary_version",
                                "source",
                                "source_version",
                                "architecture",
                                "archive_sha256",
                            )
                        )
                targets[source] = {
                    "state": "not_affected" if valid else "under_investigation",
                    "lock_sha256": archives["lock_sha256"],
                    "reason": review["reason"] if valid else "no matching complete archive review",
                }
                continue
            if role is None:
                targets[source] = {
                    "state": "under_investigation",
                    "reason": "source has no inspected image binding",
                }
                continue
            image = images[role]
            proof = captures[role]
            valid = matches and proof["image"] == image["image"]["id"]
            owned = [row for row in image["os_packages"] if row["name"] == package["name"]]
            valid = (
                valid
                and bool(owned)
                and {row["binary"] for row in owned} <= set(review["allowed_binaries"])
                if review
                else False
            )
            if valid:
                valid = components_absent(proof, review)
            if valid:
                for row in owned:
                    approved = policy["packages"][row["binary"]]
                    observed = proof["packages"].get(row["binary"], {})
                    expected = {
                        key: approved[key]
                        for key in ("binary_version", "source", "source_version", "code_set_sha256")
                    }
                    if (
                        observed != expected
                        or approved["architecture"] not in {"all", image["image"]["architecture"]}
                        or row["binary_version"] != approved["binary_version"]
                        or row["version"] != approved["source_version"]
                    ):
                        valid = False
            targets[role] = {
                "image": image["image"]["id"],
                "state": "not_affected" if valid else "under_investigation",
                "reason": review["reason"]
                if valid
                else "no matching complete artifact/component review",
            }
        resolved = bool(targets) and all(row["state"] == "not_affected" for row in targets.values())
        decisions.append(
            {
                "id": issue["id"],
                "package": package,
                "raw_blocking": issue["blocking"],
                "effective_blocking": bool(issue["blocking"]) and not resolved,
                "state": "not_affected" if resolved else "under_investigation",
                "targets": targets,
            }
        )
    return {
        "format": "ezllmrouter-component-dispositions-v1",
        "policy_sha256": canonical(policy),
        "snapshot_queried_at": snapshot["queried_at"],
        "raw_matches": len(issues),
        "raw_blocking": sum(row["blocking"] for row in issues),
        "resolved_component_matches": sum(row["state"] == "not_affected" for row in decisions),
        "effective_blocking": sum(row["effective_blocking"] for row in decisions),
        "decisions": decisions,
        "captures": captures,
        "archive_proof": archives,
        "limits": [
            "Component dispositions cover the matched Debian package artifacts only",
            "Other bundled copies and unreviewed interfaces receive no exemption",
            "Raw findings and their severity classifications are unchanged",
        ],
    }
