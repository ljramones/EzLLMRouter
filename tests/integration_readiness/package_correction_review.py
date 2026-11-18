"""Create a compact, self-auditing correction-01 review ZIP from retained evidence."""
from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


START = "4ffe57e6c257b136ef9267afa9b9334c9023f9de"
PRODUCT = "4462269b190acd3e0deacedfd65eb46aca48058f"


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(("git", *args), cwd=repo, text=True)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    candidate, repo = (Path(arg).resolve() for arg in sys.argv[1:3])
    assert len(sys.argv) == 3
    review = candidate / "review-bundle"
    if review.exists():
        raise ValueError("review destination already exists")
    review.mkdir()
    final = git(repo, "rev-parse", "HEAD").strip()
    source_files = (
        "docs/plan/DURANKI-INTEGRATION-READINESS.md",
        "docs/plan/DURANKI-INTEGRATION-CORRECTION-01.md",
        "docs/plan/DURANKI-INTEGRATION-PROGRESS.md",
        "docs/plan/DURANKI-INTEGRATION-FEATURE-RETENTION-POLICY.md",
        "docs/development/integration-readiness/RESULT.md",
        "docs/development/integration-readiness/RESULT-v1.md",
        "docs/development/integration-readiness/RELEASE.md",
        "docs/development/integration-readiness/RELEASE-v1.md",
        "docs/development/integration-readiness/client-requirements-v2.lock",
        "tests/integration_readiness/correction_release.py",
        "tests/integration_readiness/correction_js_actor.cjs",
        "tests/integration_readiness/correction_operator_smoke.py",
        "tests/integration_readiness/correction_browser_smoke.cjs",
        "tests/integration_readiness/correction_upgrade_check.py",
        "tests/integration_readiness/package_correction_release.py",
        "tests/integration_readiness/package_correction_review.py",
        "tests/operator_console/test_integration_accounting.py",
    )
    source_files += tuple(p.relative_to(repo).as_posix() for p in
                          sorted((repo / "docs/contracts/integration-readiness-v2").iterdir()) if p.is_file())
    for rel in source_files:
        target = review / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo / rel, target)
    retained = (
        "evidence/installed-seed.log",
        "evidence/installed-restart-verify.log",
        "evidence/installed-restore-verify.log",
        "evidence/installed-upgrade-check.log",
        "evidence/operator-smoke.log",
        "evidence/browser-smoke.log",
        "evidence/database-counts-before-refresh.txt",
        "evidence/database-counts-after-refresh.txt",
        "evidence/integration-correction-encoded-account.png",
        "instance/evidence/seed-summary.json",
        "instance/evidence/verify-summary.json",
        "instance/evidence/restore-summary.json",
        "instance/evidence/final-report.json",
        "instance/evidence/final-report.csv",
        "instance/evidence/final-export.json",
        "instance/evidence/node-seed.json",
        "instance/evidence/node-seed-verify.json",
        "instance/evidence/node-verify-verify.json",
        "instance/evidence/node-restore-verify.json",
        "final-release/SOURCE-IDENTITY.json",
        "final-release/MANIFEST.sha256",
    )
    for rel in retained:
        target = review / "retained" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate / rel, target)
    (review / "delta").mkdir()
    for name, args in (
        ("changed-files-to-product.txt", ("diff", "--name-status", START, PRODUCT)),
        ("source-to-product.patch", ("diff", "--no-ext-diff", "--no-color", START, PRODUCT)),
        ("product-to-final.patch", ("diff", "--no-ext-diff", "--no-color", PRODUCT, final)),
    ):
        (review / "delta" / name).write_text(git(repo, *args))
    packages = (
        candidate / "duranki-integration-service-0.2.0.zip",
        candidate / "packages/mach33_duranki_server-0.2.0-py3-none-any.whl",
        candidate / "packages/mach33_duranki_client-0.2.0-py3-none-any.whl",
        candidate / "packages/mach33-duranki-client-0.2.0.tgz",
    )
    (review / "RELEASE-ARTIFACTS.sha256").write_text("".join(
        f"{sha(path)}  {path.stat().st_size} bytes  {path.relative_to(candidate).as_posix()}\n"
        for path in packages
    ))
    (review / "INDEX.md").write_text(
        "# Integration correction 01 — independent review index\n\n"
        f"Baseline `{START}`; tested product/client source `{PRODUCT}`; final record `{final}`. "
        "The package bytes were installed from candidate 3 before final documentation commits.\n\n"
        "| Review question | Evidence |\n| --- | --- |\n"
        "| IR01–IR09 implementation and cases | `docs/contracts/integration-readiness-v2/`, "
        "`delta/source-to-product.patch`, `tests/operator_console/test_integration_accounting.py` |\n"
        "| Exact installed client/service and reconciliation | `tests/integration_readiness/correction_*`, "
        "`retained/evidence/installed-*.log`, `retained/instance/evidence/final-report.json`, "
        "`final-report.csv`, `final-export.json` |\n"
        "| Restart, backup restore and v1 upgrade | `retained/evidence/installed-restart-verify.log`, "
        "`installed-restore-verify.log`, `installed-upgrade-check.log` |\n"
        "| Operator and browser route | `retained/evidence/operator-smoke.log`, `browser-smoke.log`, "
        "`integration-correction-encoded-account.png` |\n"
        "| Source-to-record delta | `delta/product-to-final.patch`, plan/progress/result/release files |\n"
        "| Release identity | `RELEASE-ARTIFACTS.sha256`, `retained/final-release/MANIFEST.sha256`, "
        "`SOURCE-IDENTITY.json` |\n\n"
        "All examples and screenshot contents are synthetic. The report has three included attempts: "
        "known USD 0.020000000 + 0.010000000 and one unknown-cost attempt. No raw database, "
        "credential, dependency wheel, full service archive, prior DEV-12 packet or repeated screenshot is included. "
        "The manifest excludes itself. The proposed real-feature policy and actual Vega activation remain pending.\n"
    )
    root_manifest = review / "MANIFEST.sha256"
    entries = sorted(p for p in review.rglob("*") if p.is_file() and p != root_manifest)
    root_manifest.write_text("".join(
        f"{sha(p)}  {p.relative_to(review).as_posix()}\n" for p in entries
    ))
    archive = candidate / "duranki-integration-correction01-review.zip"
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(p for p in review.rglob("*") if p.is_file()):
            zf.write(path, path.relative_to(review).as_posix())
    with zipfile.ZipFile(archive) as zf:
        archived = set(zf.namelist())
        lines = zf.read("MANIFEST.sha256").decode().splitlines()
        manifest_entries = {path: digest for digest, path in
                            (line.split("  ", 1) for line in lines)}
        if (len(archived) != len(zf.namelist()) or len(lines) != len(manifest_entries) or
                set(manifest_entries) != archived - {"MANIFEST.sha256"}):
            raise ValueError("review manifest does not cover the exact archive payload set")
        for path, expected in manifest_entries.items():
            if hashlib.sha256(zf.read(path)).hexdigest() != expected:
                raise ValueError("review payload hash mismatch: " + path)
    print(f"{archive}\n{archive.stat().st_size} bytes\nSHA-256 {sha(archive)}\n"
          f"{len(entries)} payload files; manifest SHA-256 {sha(review / 'MANIFEST.sha256')}")


if __name__ == "__main__":
    main()
