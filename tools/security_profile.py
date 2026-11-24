"""Apply expiring target-specific findings only to an exact qualified profile."""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re

from tools.gateway.os_inputs import LOCK
from tools.security_resolutions import canonical

CASES = {
    "DEBIAN-CVE-2010-4756": ("glibc", "native_patterns"),
    "DEBIAN-CVE-2018-20796": ("glibc", "native_patterns"),
    "DEBIAN-CVE-2019-9192": ("glibc", "native_patterns"),
    "DEBIAN-CVE-2019-1010022": ("glibc", "aarch64_guard"),
    "DEBIAN-CVE-2019-1010023": ("glibc", "trusted_native_inputs"),
    "DEBIAN-CVE-2026-84243": ("glibc", "fixed_locale"),
    "DEBIAN-CVE-2005-2541": ("tar", "unprivileged_archive_path"),
}
SOURCE_ROOTS = ("server/src", "worker/ezllmrouter_worker")
CONTROLS = (
    "deploy/local/compose.yaml",
    "tests/tool_cycle/compose.yaml",
    "tools/volume_archive.py",
    "tools/qualification_storage.py",
    "tools/deployment_qualification.py",
    "tools/gateway/worker_package.py",
)


def sources(root: Path) -> dict:
    paths = {root / name for name in CONTROLS}
    paths.update(path for name in SOURCE_ROOTS for path in (root / name).rglob("*.py"))
    if any(path.is_symlink() or not path.is_file() for path in paths):
        raise ValueError("profile source is not a regular file")
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
    }


def source_interfaces(root: Path) -> list[str]:
    violations = []
    forbidden = {"ctypes", "cffi", "subprocess"}
    for directory in SOURCE_ROOTS:
        for path in (root / directory).rglob("*.py"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [entry.name.split(".", 1)[0] for entry in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [(node.module or "").split(".", 1)[0]]
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    if node.func.id in {"eval", "exec", "__import__"}:
                        names = ["dynamic_execution"]
                if set(names) & (forbidden | {"dynamic_execution"}):
                    violations.append(path.relative_to(root).as_posix() + ":" + str(node.lineno))
    return sorted(set(violations))


def load_policy(path: Path, root: Path, qualification: dict) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError("profile review must be a regular file")
    policy = json.loads(path.read_text())
    reviewed, expires = map(datetime.fromisoformat, (policy["reviewed_at"], policy["expires_at"]))
    now = datetime.now(timezone.utc)
    if (
        policy["format"] != "ezllmrouter-profile-reviews-v1"
        or reviewed.tzinfo is None
        or expires.tzinfo is None
        or not reviewed <= now <= expires
        or not timedelta(0) < expires - reviewed <= timedelta(days=7)
        or set(policy["reviews"]) != set(CASES)
        or policy["source_sha256"] != sources(root)
        or source_interfaces(root)
    ):
        raise ValueError("expired, changed or unreviewed profile source")
    if (
        policy["qualification_sha256"] != canonical(qualification)
        or qualification["status"] != "passed"
        or not qualification["cleanup_complete"]
        or qualification["source_packet_sha256"] != policy["source_packet_sha256"]
        or set(qualification["images"]) != set(policy["images"])
        or len(policy["images"]) != 7
        or any(
            row["uid_gid"] != "10001:10001"
            or not row["readonly_root"]
            or row["locale"] != {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "LANGUAGE": "C"}
            for row in qualification["structure"].values()
        )
    ):
        raise ValueError("profile is not the exact reviewed qualification")
    for filename, sha in qualification["harness_sha256"].items():
        if hashlib.sha256((root / filename).read_bytes()).hexdigest() != sha:
            raise ValueError("qualification harness or input changed")
    for name, image in policy["images"].items():
        if image["image"] != qualification["images"][name]["id"] or not re.fullmatch(
            r"sha256:[0-9a-f]{64}", image["image"]
        ):
            raise ValueError("profile image identity changed")
    probe = root / "tools/security_profile_probe.c"
    if hashlib.sha256(probe.read_bytes()).hexdigest() != policy["probe_source_sha256"]:
        raise ValueError("native diagnostic source changed")
    for name, review in policy["reviews"].items():
        if review["condition"] != CASES[name][1] or not review["reason"].strip():
            raise ValueError("unknown profile precondition")
        for key in ("advisory_sha256", "cna_sha256"):
            if not re.fullmatch(r"[0-9a-f]{64}", review[key]):
                raise ValueError("unbound profile advisory")
    return policy


def proof_valid(proof: dict, expected: dict) -> bool:
    runtime = proof["runtime"]
    return (
        all(proof[key] == expected[key] for key in ("image", "elf_sha256", "closure_sha256"))
        and not proof["closure"]["restricted_callers"]
        and not proof["unordered_load_objects"]
        and runtime == expected["runtime"]
        and runtime["uid"] in {1000, 10001}
        and runtime["euid"] == runtime["uid"]
        and {key: value for key, value in runtime.items() if key not in {"uid", "euid"}}
        == {
            "no_new_privs": 1,
            "guard_global": True,
            "guard_outside_thread_stack": True,
            "guard_readonly": True,
            "locale": "C.UTF-8",
        }
    )


def apply_reviews(report: dict, snapshot: dict, images: dict, captures: dict, policy: dict) -> dict:
    sources_by_image = {"image:" + name + ":" + row["image"]["id"] for name, row in images.items()}
    complete = (
        bool(images)
        and set(images) == set(captures) == set(policy["images"])
        and all(
            proof["image"] == images[name]["image"]["id"]
            and proof_valid(proof, policy["images"][name])
            for name, proof in captures.items()
        )
    )
    archives = report.get("archive_proof")
    resolved = 0
    for decision in report["decisions"]:
        review = policy["reviews"].get(decision["id"])
        package = decision["package"]
        if not review or not decision["effective_blocking"]:
            continue
        valid = (
            complete
            and package["ecosystem"] == "Debian:13"
            and package["name"] == CASES[decision["id"]][0]
            and package["version"] == review["source_version"]
            and bool(package["sources"])
            and canonical(snapshot["vulnerabilities"][decision["id"]]) == review["advisory_sha256"]
            and set(package["sources"]) <= sources_by_image | {LOCK}
        )
        if LOCK in package["sources"]:
            valid = (
                valid
                and bool(archives)
                and archives["inventory_sha256"] == snapshot["inventory_sha256"]
            )
        if valid:
            decision.update(
                state="not_affected", effective_blocking=False, profile_review=canonical(policy)
            )
            for target in decision["targets"].values():
                target.update(state="not_affected", reason=review["reason"])
            resolved += 1
    report["resolved_profile_matches"] = resolved
    report["effective_blocking"] = sum(row["effective_blocking"] for row in report["decisions"])
    report["profile_captures"] = captures
    report["profile_policy_sha256"] = canonical(policy)
    report["limits"].append(
        "Profile dispositions apply only to the exact qualified images, sources and runtime controls; upstream package findings remain present."
    )
    return report
