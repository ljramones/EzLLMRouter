"""Package exact installed correction-02 artifacts without databases or credentials.

Usage: python -I -S -B package_correction_release.py CANDIDATE_DIR REPO_DIR
The candidate directory must contain the tested packages/ and service-web/.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

TESTED_SOURCE = "c8433bb"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    candidate, repo = (Path(arg).resolve() for arg in sys.argv[1:3])
    assert len(sys.argv) == 3
    release = candidate / "final-release"
    if release.exists():
        raise ValueError("release destination already exists")
    release.mkdir()
    (release / "packages").mkdir()
    for src in sorted((candidate / "packages").iterdir()):
        if src.suffix not in {".whl", ".tgz"}:
            continue
        shutil.copy2(src, release / "packages" / src.name)
    shutil.copytree(candidate / "service-web", release / "web")
    shutil.copy2(candidate / "client-requirements.lock", release / "client-requirements.lock")
    for rel in (
        "docs/development/integration-readiness/RELEASE.md",
        "docs/development/integration-readiness/RELEASE-v1.md",
        "docs/development/integration-readiness/RELEASE-v2.md",
        "docs/plan/DURANKI-INTEGRATION-FEATURE-RETENTION-POLICY.md",
        "tests/fixtures/contracts/integration-readiness-v1/CONTRACT.md",
        "tests/fixtures/contracts/integration-readiness-v2/CONTRACT.md",
        "tests/fixtures/contracts/integration-readiness-v2/schema.json",
        "tests/fixtures/contracts/integration-readiness-v2/examples.json",
        "tests/fixtures/contracts/integration-readiness-v2/check.py",
    ):
        dest = release / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo / rel, dest)
    (release / "README.md").write_text(
        "# Duranki integration accounting 0.2.1\n\n"
        "See [local installation](docs/development/integration-readiness/RELEASE.md).\n"
    )
    source = subprocess.check_output(("git", "rev-parse", TESTED_SOURCE), cwd=repo, text=True).strip()
    identity = {
        "tested_source_commit": source,
        "contract_version": "2",
        "service_version": "0.2.1",
        "javascript_client_version": "0.2.1",
        "python_client_version": "0.2.1",
        "artifact_source": "candidate2 installed and verified synthetic local release",
    }
    (release / "SOURCE-IDENTITY.json").write_text(json.dumps(identity, indent=2, sort_keys=True) + "\n")
    entries = sorted(p for p in release.rglob("*") if p.is_file() and p.name != "MANIFEST.sha256")
    (release / "MANIFEST.sha256").write_text("".join(
        f"{digest(path)}  {path.relative_to(release).as_posix()}\n" for path in entries
    ))
    archive = candidate / "duranki-integration-service-0.2.1.zip"
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(p for p in release.rglob("*") if p.is_file()):
            zf.write(path, path.relative_to(release).as_posix())
    with zipfile.ZipFile(archive) as zf:
        archived = set(zf.namelist())
        lines = zf.read("MANIFEST.sha256").decode().splitlines()
        manifest_entries = {path: recorded for recorded, path in
                            (line.split("  ", 1) for line in lines)}
        if (len(archived) != len(zf.namelist()) or len(lines) != len(manifest_entries) or
                set(manifest_entries) != archived - {"MANIFEST.sha256"}):
            raise ValueError("release manifest does not cover the exact archive payload set")
        for path, recorded in manifest_entries.items():
            if hashlib.sha256(zf.read(path)).hexdigest() != recorded:
                raise ValueError("release payload hash mismatch: " + path)
    print(json.dumps({"archive": str(archive), "bytes": archive.stat().st_size,
                      "sha256": digest(archive), "source": source,
                      "payload_files": len(entries), "manifest_sha256": digest(release / "MANIFEST.sha256")},
                     sort_keys=True))


if __name__ == "__main__":
    main()
