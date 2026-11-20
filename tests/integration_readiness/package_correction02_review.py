"""Create a compact, exact-set-verified Correction 02 review ZIP."""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


BASELINE = "79997c469d404f10bc60d8cf28bd48c7447f8db8"
PRODUCT = "c8433bb9388a9503d814929a780c6840ee63396c"


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
        "docs/plan/EZLLMROUTER-INTEGRATION-READINESS.md",
        "docs/plan/EZLLMROUTER-INTEGRATION-CORRECTION-01.md",
        "docs/plan/EZLLMROUTER-INTEGRATION-CORRECTION-02.md",
        "docs/plan/EZLLMROUTER-INTEGRATION-PROGRESS.md",
        "docs/plan/EZLLMROUTER-INTEGRATION-FEATURE-RETENTION-POLICY.md",
        "docs/development/integration-readiness/RESULT.md",
        "docs/development/integration-readiness/RESULT-v1.md",
        "docs/development/integration-readiness/RESULT-v2.md",
        "docs/development/integration-readiness/RELEASE.md",
        "docs/development/integration-readiness/RELEASE-v1.md",
        "docs/development/integration-readiness/RELEASE-v2.md",
        "docs/development/integration-readiness/CORRECTION-02-VALIDATION.json",
        "docs/development/integration-readiness/client-requirements-v3.lock",
    )
    source_files += tuple(
        p.relative_to(repo).as_posix()
        for p in sorted((repo / "tests/fixtures/contracts/integration-readiness-v2").iterdir())
        if p.is_file()
    )
    for rel in source_files:
        target = review / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo / rel, target)
    retained = (
        "instance/evidence/seed-summary.json",
        "instance/evidence/verify-summary.json",
        "instance/evidence/node-seed.json",
        "instance/evidence/node-verify.json",
        "instance/evidence/final-report.json",
        "instance/evidence/final-report.csv",
        "instance/evidence/final-export.json",
        "restored/evidence/verify-summary.json",
        "restored/evidence/node-verify.json",
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
        candidate / "ezllmrouter-integration-service-0.2.1.zip",
        candidate / "packages/mach33_ezllmrouter_server-0.2.1-py3-none-any.whl",
        candidate / "packages/cognitivedynamics_ezllmrouter_client-0.2.1-py3-none-any.whl",
        candidate / "packages/cognitivedynamics-ezllmrouter-client-0.2.1.tgz",
    )
    (review / "RELEASE-ARTIFACTS.sha256").write_text(
        "".join(
            f"{sha(path)}  {path.stat().st_size} bytes  {path.relative_to(candidate).as_posix()}\n"
            for path in packages
        )
    )
    (review / "INDEX.md").write_text(
        "# Integration correction 02 — independent review\n\n"
        f"Reviewed baseline `{BASELINE}`; tested source `{PRODUCT}`; final record `{final}`. "
        "The service and clean Node/Python consumers used the exact retained 0.2.1 archives.\n\n"
        "| Question | Evidence |\n| --- | --- |\n"
        "| IC02-01 lineage and old contradictions | `delta/baseline-to-product.patch`, "
        "`tests/operator_console/test_integration_accounting.py` in that diff, current result |\n"
        "| IC02-02 eligibility ordering | Same source test; "
        "`retained/instance/evidence/final-report.json`, `final-export.json`, Node seed |\n"
        "| IC02-03 snapshot binding | Same source test and installed Node/Python evidence; "
        "retained export reference assessments |\n"
        "| IC02-04 native knowledge | V2 contract/schema/check, retained JSON/CSV/export, "
        "validation record |\n"
        "| IC02-05 manifest | Root `MANIFEST.sha256` includes "
        "`retained/final-release/MANIFEST.sha256`; exact path/hash verifier in packager |\n"
        "| Restart, restore, v1/v2 copies | Seed/verify/restore summaries, validation record and "
        "`tests/integration_readiness/correction02_upgrade.py` in source diff |\n"
        "| Release identity | `RELEASE-ARTIFACTS.sha256`, retained release manifest and "
        "`SOURCE-IDENTITY.json` |\n"
        "| Final record delta | `delta/product-to-final.patch` |\n\n"
        "Three included attempts have known USD 0.020000000 + USD 0.010000000 and one "
        "unknown monetary cost. All content is synthetic. The review ZIP omits databases, "
        "credentials, dependency wheels, the full service archive and old review packets. "
        "Real retention policy adoption and Vega activation remain pending.\n"
    )
    root_manifest = review / "MANIFEST.sha256"
    entries = sorted(p for p in review.rglob("*") if p.is_file() and p != root_manifest)
    root_manifest.write_text(
        "".join(f"{sha(path)}  {path.relative_to(review).as_posix()}\n" for path in entries)
    )
    archive = candidate / "ezllmrouter-integration-correction02-review.zip"
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(p for p in review.rglob("*") if p.is_file()):
            zf.write(path, path.relative_to(review).as_posix())
    with zipfile.ZipFile(archive) as zf:
        archived = set(zf.namelist())
        lines = zf.read("MANIFEST.sha256").decode().splitlines()
        manifest_entries = {
            path: digest for digest, path in (line.split("  ", 1) for line in lines)
        }
        if (
            len(archived) != len(zf.namelist())
            or len(lines) != len(manifest_entries)
            or set(manifest_entries) != archived - {"MANIFEST.sha256"}
        ):
            raise ValueError("review manifest does not cover exact archive payload set")
        for path, expected in manifest_entries.items():
            if hashlib.sha256(zf.read(path)).hexdigest() != expected:
                raise ValueError("review payload hash mismatch: " + path)
    print(
        f"{archive}\n{archive.stat().st_size} bytes\nSHA-256 {sha(archive)}\n"
        f"{len(entries)} payload files; manifest SHA-256 {sha(root_manifest)}"
    )


if __name__ == "__main__":
    main()
