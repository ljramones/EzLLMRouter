"""Resolved Rust and actual Docker package inventories for retained OSV review."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tomllib

from deploy.local.local_profile import DOCKER
from tools.security_dependencies import findings, forbidden_release, inventory, query, sbom

from tools.security_rust import rust_graph


def docker(image: str, *args: str) -> str:
    return subprocess.check_output(
        [
            *DOCKER,
            "run",
            "--rm",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            image,
            *args,
        ],
        text=True,
        timeout=120,
    )


def image_packages(image: dict) -> dict:
    ref = image["id"]
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", ref):
        raise ValueError("immutable image identity required")
    release = dict(
        line.split("=", 1)
        for line in docker(ref, "cat", "/etc/os-release").splitlines()
        if "=" in line
    )
    if release.get("ID") != "debian":
        raise ValueError("unreviewed OS inventory ecosystem")
    ecosystem = "Debian:" + release["VERSION_ID"].strip('"')
    dpkg = docker(
        ref, "dpkg-query", "-W", "-f=${Package}\t${Version}\t${source:Package}\t${source:Version}\n"
    )
    os_rows = []
    for line in dpkg.splitlines():
        name, version, source, source_version = line.split("\t")
        os_rows.append(
            {
                "binary": name,
                "binary_version": version,
                "name": source,
                "version": source_version,
                "ecosystem": ecosystem,
            }
        )
    code = "import importlib.metadata,json; print(json.dumps(sorted([{'name':d.metadata['Name'],'version':d.version} for d in importlib.metadata.distributions(path=['/usr/local/lib/python3.12/site-packages'])],key=lambda d:d['name'])))"
    # Node images have no Python installation; collect their installed npm trees.
    if "node@sha256:" in image["base"]:
        applications = []
        for directory, global_flag in (("/app/consumer", False), ("/usr/local", True)):
            args = ["npm", "ls", "--all", "--json", "--offline", "--prefix", directory]
            if global_flag:
                args.append("--global")
            tree = json.loads(docker(ref, *args))

            def visit(node: dict) -> None:
                if node.get("problems") or node.get("error"):
                    raise ValueError("incomplete npm tree")
                for name, child in node.get("dependencies", {}).items():
                    applications.append(
                        {"ecosystem": "npm", "name": name, "version": child["version"]}
                    )
                    visit(child)

            visit(tree)
    else:
        applications = [
            dict(row, ecosystem="PyPI")
            for row in json.loads(docker(ref, "python", "-I", "-S", "-c", code))
        ]
    if any(
        row["name"].lower().replace("_", "-") == "litellm" and forbidden_release(row["version"])
        for row in applications
    ):
        raise ValueError("forbidden LiteLLM in actual image inventory")
    return {
        "image": image,
        "os_release": release,
        "os_packages": os_rows,
        "application_packages": applications,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rust", type=Path, required=True)
    parser.add_argument("--qualification", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--query", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    data = inventory()
    source_hashes = {}
    for line in (args.rust / "input-sha256.txt").read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        path = args.rust / "Cargo.lock" if name == "clients/rust/Cargo.lock" else Path(name)
        if (
            name
            not in {
                "clients/rust/Cargo.toml",
                "clients/rust/Cargo.lock",
                "clients/rust/rust-toolchain.toml",
            }
            or hashlib.sha256(path.read_bytes()).hexdigest() != digest
        ):
            raise ValueError("captured Rust source identity mismatch")
        source_hashes[name] = digest
    if len(source_hashes) != 3:
        raise ValueError("incomplete captured Rust source identity")
    data["native_resolution"] = {
        "source_sha256": source_hashes,
        "source_commit": (args.rust / "source-commit.txt").read_text().strip(),
        "toolchain": (args.rust / "toolchain.txt").read_text().strip(),
    }
    manifest = tomllib.loads(Path("clients/rust/Cargo.toml").read_text())
    lock = tomllib.loads((args.rust / "Cargo.lock").read_text())
    packages = rust_graph(lock, manifest, json.loads((args.rust / "metadata.json").read_text()))
    images = json.loads(args.qualification.read_text())
    captured = {kind: image_packages(image) for kind, image in images["images"].items()}
    (args.output / "images.json").write_text(json.dumps(captured, indent=2) + "\n")
    rows = {
        (row["ecosystem"], row["name"], row["version"]): set(row["sources"])
        for row in data["packages"]
    }
    for package in packages:
        rows.setdefault(("crates.io", package["name"], package["version"]), set()).add(
            "resolved-rust/Cargo.lock"
        )
    for kind, image in captured.items():
        for row in (*image["os_packages"], *image["application_packages"]):
            rows.setdefault((row["ecosystem"], row["name"], row["version"]), set()).add(
                "image:" + kind + ":" + image["image"]["id"]
            )
    data.update(
        packages=[
            {"ecosystem": k[0], "name": k[1], "version": k[2], "sources": sorted(v)}
            for k, v in sorted(rows.items())
        ],
        images=captured,
    )
    data.pop("sha256")
    data["sha256"] = hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    (args.output / "inventory.json").write_text(json.dumps(data, indent=2) + "\n")
    (args.output / "sbom.cdx.json").write_text(json.dumps(sbom(data), indent=2) + "\n")
    if args.query:
        snapshot = query(data)
        (args.output / "osv.json").write_text(json.dumps(snapshot, indent=2) + "\n")
        issues = findings(data, snapshot)
        (args.output / "findings.json").write_text(json.dumps(issues, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "packages": len(rows),
                    "findings": len(issues),
                    "blocking": sum(row["blocking"] for row in issues),
                }
            )
        )
        return int(any(row["blocking"] for row in issues))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
