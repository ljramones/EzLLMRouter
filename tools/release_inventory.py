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


def debian_packages(raw: str, ecosystem: str) -> list[dict]:
    result = []
    for line in raw.splitlines():
        name, version, source, source_version, status = line.split("\t")
        if status in {"not-installed", "config-files"}:
            continue
        if status != "installed" or not all((name, version, source, source_version)):
            raise ValueError("incomplete OS package installation")
        result.append(
            {
                "binary": name,
                "binary_version": version,
                "name": source,
                "version": source_version,
                "ecosystem": ecosystem,
                "installation_status": status,
            }
        )
    return result


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
        ref,
        "dpkg-query",
        "-W",
        "-f=${Package}\t${Version}\t${source:Package}\t${source:Version}\t${db:Status-Status}\n",
    )
    os_rows = debian_packages(dpkg, ecosystem)
    code = "import importlib.metadata,json; print(json.dumps(sorted([{'name':d.metadata['Name'],'version':d.version} for d in importlib.metadata.distributions(path=['/usr/local/lib/python3.12/site-packages'])],key=lambda d:d['name'])))"
    # Read installed package metadata directly; runtime images contain no npm CLI.
    if "node@sha256:" in image["base"]:
        script = """
const fs=require('node:fs'),path=require('node:path'),rows=[];
function packages(dir) {
  if (!fs.existsSync(dir)) return;
  for (const entry of fs.readdirSync(dir,{withFileTypes:true})) {
    if (entry.name.startsWith('.')) continue;
    const location=path.join(dir,entry.name);
    if (entry.isSymbolicLink()) throw Error('unqualified linked package');
    if (!entry.isDirectory()) continue;
    if (entry.name.startsWith('@')) { packages(location); continue; }
    const metadata=JSON.parse(fs.readFileSync(path.join(location,'package.json'),'utf8'));
    if (typeof metadata.name!=='string'||typeof metadata.version!=='string') throw Error('package identity');
    rows.push({ecosystem:'npm',name:metadata.name,version:metadata.version,location});
    packages(path.join(location,'node_modules'));
  }
}
packages('/usr/local/lib/node_modules');packages('/app/consumer/node_modules');
console.log(JSON.stringify({packages:rows,runtime:process.versions}));
"""
        captured = json.loads(docker(ref, "node", "-e", script))
        applications, runtime = captured["packages"], captured["runtime"]
        if runtime.get("undici"):
            applications.append(
                {
                    "ecosystem": "npm",
                    "name": "undici",
                    "version": runtime["undici"],
                    "embedded_in": "node",
                }
            )
    else:
        applications = [
            dict(row, ecosystem="PyPI")
            for row in json.loads(docker(ref, "python", "-I", "-S", "-c", code))
        ]
        runtime = json.loads(
            docker(
                ref,
                "python",
                "-I",
                "-S",
                "-c",
                "import sys,ssl,sqlite3,zlib,json; print(json.dumps({'python':sys.version,'openssl':ssl.OPENSSL_VERSION,'sqlite':sqlite3.sqlite_version,'zlib':zlib.ZLIB_RUNTIME_VERSION}))",
            )
        )
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
        "runtime_versions": runtime,
    }


def attribution(issues: list[dict], images: dict) -> dict:
    targets = {}
    for kind, image in images.items():
        source = "image:" + kind + ":" + image["image"]["id"]
        matched = [row for row in issues if source in row["package"]["sources"]]
        targets[kind] = {
            "id": image["image"]["id"],
            "matches": len(matched),
            "blocking": sum(row["blocking"] for row in matched),
            "findings": [
                {
                    "id": row["id"],
                    "name": row["package"]["name"],
                    "version": row["package"]["version"],
                    "blocking": row["blocking"],
                }
                for row in matched
            ],
        }
    declared = [
        row
        for row in issues
        if not any(source.startswith("image:") for source in row["package"]["sources"])
    ]
    return {
        "images": targets,
        "declared_only": {
            "matches": len(declared),
            "blocking": sum(row["blocking"] for row in declared),
            "findings": declared,
        },
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
        (args.output / "attribution.json").write_text(
            json.dumps(attribution(issues, captured), indent=2) + "\n"
        )
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
