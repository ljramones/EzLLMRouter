"""Verify every selected Zstandard copy before accepting the exact source fix."""

from __future__ import annotations

import subprocess

from tools.gateway.codec_inputs import LIBRARY, PACKAGE, VERSION
from tools.gateway.os_inputs import LOCK
from tools.security_resolutions import canonical


def expected_code(codec: dict, role: str) -> dict:
    result = {LIBRARY: codec["code"][LIBRARY], LIBRARY.rsplit(".", 2)[0]: codec["code"][LIBRARY]}
    if role == "node":
        result["/usr/local/bin/node"] = codec["code"]["/usr/local/bin/node"]
    return result


def verify_runtime(prefix: list[str], codec: dict, image: dict, role: str, versions: dict) -> bool:
    names = subprocess.check_output(
        [
            *prefix,
            "find",
            "/usr/lib/aarch64-linux-gnu",
            "-maxdepth",
            "1",
            "-name",
            "libzstd.so*",
            "-printf",
            "%f\n",
        ],
        text=True,
        timeout=60,
    ).splitlines()
    owned = [row for row in image["os_packages"] if row["name"] == "libzstd"]
    return (
        sorted(names) == ["libzstd.so.1", "libzstd.so.1.6.0"]
        and len(owned) == 1
        and owned[0]["binary"] == "libzstd1"
        and owned[0]["version"] == owned[0]["binary_version"] == VERSION
        and (role != "node" or versions.get("zstd") == codec["version"])
    )


def apply_reviews(report: dict, snapshot: dict, images: dict, captures: dict, codec: dict) -> dict:
    sources = {"image:" + name + ":" + row["image"]["id"] for name, row in images.items()}
    all_copies = (
        bool(images)
        and set(captures) == set(images)
        and all(
            proof["valid"]
            and proof.get("native_codec") == codec["id"]
            and proof["image"] == images[name]["image"]["id"]
            for name, proof in captures.items()
        )
    )
    compatibility = report.get("profile_captures", {})
    all_copies = (
        all_copies
        and set(compatibility) == set(images)
        and all(
            proof["image"] == images[name]["image"]["id"]
            and proof.get("zstd_removed_callers") == {}
            for name, proof in compatibility.items()
        )
    )
    resolved = 0
    for decision in report["decisions"]:
        review = codec["fixed_advisory"]
        package = decision["package"]
        if (
            decision["id"] != "DEBIAN-CVE-2026-124851"
            or not decision["raw_blocking"]
            or (package["ecosystem"], package["name"], package["version"])
            != ("Debian:13", "libzstd", VERSION)
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
            archives = report.get("archive_proof")
            if (
                source != LOCK
                or not archives
                or archives["inventory_sha256"] != snapshot["inventory_sha256"]
            ):
                valid = False
                continue
            owned = [row for row in archives["packages"] if row["source"] == "libzstd"]
            valid = (
                valid
                and len(owned) == 1
                and all(
                    row["binary"] == "libzstd1"
                    and row["binary_version"] == row["source_version"] == VERSION
                    and row["archive_sha256"] == codec["outputs"][PACKAGE]["sha256"]
                    for row in owned
                )
            )
        if valid:
            decision.update(state="fixed", effective_blocking=False, native_codec=codec["id"])
            for target in decision["targets"].values():
                target.update(state="fixed", reason=review["reason"])
            resolved += 1
    report["resolved_codec_matches"] = resolved
    report["native_codec"] = codec["id"]
    report["effective_blocking"] = sum(row["effective_blocking"] for row in report["decisions"])
    return report
