"""Create a compact, exact-set-verified Correction 03 review ZIP."""
from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


BASELINE = "d3d533a47c3addcc503c2d6b6ba0c06bb0340b9d"
PRODUCT = "6fc9434f7aa0a120b04c94931f28c3112bc333c7"


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(("git", *args), cwd=repo, text=True)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    assert len(sys.argv) == 3
    candidate, repo = (Path(arg).resolve() for arg in sys.argv[1:3])
    review = candidate / "review-bundle"
    if review.exists():
        raise ValueError("review destination already exists")
    review.mkdir()
    final = git(repo, "rev-parse", "HEAD").strip()
    if git(repo, "merge-base", "--is-ancestor", PRODUCT, final) != "":
        raise ValueError("unexpected ancestry response")
    source_files = (
        "docs/plan/DURANKI-INTEGRATION-READINESS.md",
        "docs/plan/DURANKI-INTEGRATION-CORRECTION-01.md",
        "docs/plan/DURANKI-INTEGRATION-CORRECTION-02.md",
        "docs/plan/DURANKI-INTEGRATION-CORRECTION-03.md",
        "docs/plan/DURANKI-INTEGRATION-PROGRESS.md",
        "docs/plan/DURANKI-INTEGRATION-FEATURE-RETENTION-POLICY.md",
        "docs/development/integration-readiness/RESULT.md",
        "docs/development/integration-readiness/RESULT-v3.md",
        "docs/development/integration-readiness/RELEASE.md",
        "docs/development/integration-readiness/RELEASE-v3.md",
        "docs/development/integration-readiness/CORRECTION-03-VALIDATION.json",
        "docs/development/integration-readiness/client-requirements-v4.lock",
    )
    source_files += tuple(p.relative_to(repo).as_posix() for p in
                          sorted((repo / "tests/fixtures/contracts/integration-readiness-v2").iterdir()) if p.is_file())
    for rel in source_files:
        target = review / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo / rel, target)
    retained = (
        "evidence/old-seed-summary.json",
        "evidence/old-report.json",
        "evidence/seed_corrected-summary.json",
        "evidence/verify_corrected-summary.json",
        "evidence/probe-conflicts-summary.json",
        "evidence/node-seed.json",
        "evidence/node-verify.json",
        "evidence/node-probe.json",
        "evidence/corrected-report.json",
        "evidence/corrected-report.csv",
        "evidence/corrected-export.json",
        "final-release/SOURCE-IDENTITY.json",
        "final-release/MANIFEST.sha256",
    )
    for rel in retained:
        target = review / "retained" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate / rel, target)
    (review / "delta").mkdir()
    for name, args in (
        ("changed-files-to-product.txt", ("diff", "--name-status", BASELINE, PRODUCT)),
        ("baseline-to-product.patch", ("diff", "--no-ext-diff", "--no-color", BASELINE, PRODUCT)),
        ("product-to-final.patch", ("diff", "--no-ext-diff", "--no-color", PRODUCT, final)),
    ):
        (review / "delta" / name).write_text(git(repo, *args))
    packages = (
        candidate / "duranki-integration-service-0.2.2.zip",
        candidate / "packages/mach33_duranki_server-0.2.2-py3-none-any.whl",
        candidate / "packages/mach33_duranki_client-0.2.2-py3-none-any.whl",
        candidate / "packages/mach33-duranki-client-0.2.2.tgz",
    )
    (review / "RELEASE-ARTIFACTS.sha256").write_text("".join(
        f"{sha(path)}  {path.stat().st_size} bytes  {path.relative_to(candidate).as_posix()}\n"
        for path in packages
    ))
    (review / "INDEX.md").write_text(
        "# Integration correction 03 — independent review\n\n"
        f"Reviewed baseline `{BASELINE}`; tested source `{PRODUCT}`; final record `{final}`. "
        "The service and clean Node/Python consumers used the exact retained 0.2.2 archives.\n\n"
        "| Question | Evidence |\n| --- | --- |\n"
        "| IC03-01 admission and historical projection | `delta/baseline-to-product.patch`, "
        "focused 14-case source test and v2 contract clause |\n"
        "| Genuine predecessor-accepted history | `retained/evidence/old-seed-summary.json`, "
        "`old-report.json`; installed old/new scripts in product-to-final diff |\n"
        "| Same-dataset continuation and once-only accounting | `retained/evidence/corrected-report.json`, "
        "CSV/export, seed and read-only restart summaries |\n"
        "| Both mixed orders, pure-v2 control and exact conflicts | Node seed/probe, "
        "`probe-conflicts-summary.json`, current result and validation record |\n"
        "| Root manifest coverage | Root `MANIFEST.sha256` includes "
        "`retained/final-release/MANIFEST.sha256`; exact path/hash verifier in packager |\n"
        "| Release identity | `RELEASE-ARTIFACTS.sha256`, retained release manifest and "
        "`SOURCE-IDENTITY.json` |\n"
        "| Final record delta | `delta/product-to-final.patch` |\n\n"
        "The historical dataset has three attempts, known USD 0.010000000 and two "
        "unknown-cost attempts. All content is synthetic. The review ZIP omits databases, "
        "credentials, dependency wheels, the full service archive and old review packets. "
        "Real retention policy adoption and Vega activation remain pending.\n"
    )
    root_manifest = review / "MANIFEST.sha256"
    entries = sorted(p for p in review.rglob("*") if p.is_file() and p != root_manifest)
    root_manifest.write_text("".join(
        f"{sha(path)}  {path.relative_to(review).as_posix()}\n" for path in entries
    ))
    archive = candidate / "duranki-integration-correction03-review.zip"
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
            raise ValueError("review manifest does not cover exact archive payload set")
        for path, expected in manifest_entries.items():
            if hashlib.sha256(zf.read(path)).hexdigest() != expected:
                raise ValueError("review payload hash mismatch: " + path)
    print(f"{archive}\n{archive.stat().st_size} bytes\nSHA-256 {sha(archive)}\n"
          f"{len(entries)} payload files; manifest SHA-256 {sha(root_manifest)}")


if __name__ == "__main__":
    main()
