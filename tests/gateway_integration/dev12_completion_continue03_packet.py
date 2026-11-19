"""Build the secret-excluding Continue03 exact-source and primary-evidence ZIP."""
from __future__ import annotations

from hashlib import sha256
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
from zipfile import ZipFile, ZIP_DEFLATED

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dev12_completion_continue03_audit import audit
from dev12_completion_mixed_audit import audit as mixed_audit


def digest(raw):
    return sha256(raw).hexdigest()


def git(repo, *args):
    return subprocess.check_output(("git", "-C", str(repo), *args))


def copy_tree(source, destination):
    for path in sorted(source.rglob("*")):
        if path.is_file():
            if path.is_symlink():
                raise AssertionError("linked evidence path")
            target = destination / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)


def build(repo, review, export, lineage, input_zip, stage, output):
    if stage.exists() or output.exists() or not review.is_dir():
        raise ValueError("fresh owned packet staging/output required")
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD").decode().strip()
    commit = git(repo, "rev-parse", "HEAD").decode().strip()
    tree = git(repo, "rev-parse", "HEAD^{tree}").decode().strip()
    remote = git(repo, "remote", "get-url", "origin").decode().strip()
    if branch != "dev12/operation-contract" or remote != "git@github.com:33fg/ezllmrouter.git":
        raise AssertionError("approved branch/remote differs")
    if git(repo, "status", "--porcelain", "--untracked-files=no"):
        raise AssertionError("tracked source must be committed before exact packet build")
    with ZipFile(input_zip) as z:
        names = z.namelist()
        assert "EZLLMROUTER-DEV12-COMPLETION-02-CONTINUE-03.md" in names
        assert "A2-AUTHENTICATION-PROJECTION-CLARIFICATION-01.md" in names
        assert not any(re.search(r"\.sqlite$|\.pem$|\.key$|private-input", name, re.I)
                       for name in names)
    stage.mkdir(parents=True)
    source_tar = git(repo, "archive", "--format=tar", "--prefix=source/", commit)
    (stage / "source.tar").write_bytes(source_tar)
    with tarfile.open(fileobj=io.BytesIO(source_tar), mode="r:") as tar:
        for member in tar.getmembers():
            if member.issym() or member.islnk() or member.name.startswith("/") or \
               ".." in Path(member.name).parts:
                raise AssertionError("unsafe source archive member")
        tar.extractall(stage, filter="data")
    focused = git(repo, "diff", "--binary", "281bd6f9d6d349b96b817c50f7e53c2db203fc19",
                  commit, "--", "server", "clients", "tests", "docs/development/dev-12")
    (stage / "focused-281bd6f-to-successor.diff").write_bytes(focused)
    (stage / "review-input").mkdir()
    shutil.copyfile(input_zip, stage / "review-input" / input_zip.name)
    copy_tree(export, stage / "evidence/final")
    copy_tree(lineage, stage / "evidence/source-lineage")
    mixed = mixed_audit(stage / "evidence/final")
    (stage / "evidence/MIXED-RECONCILIATION.json").write_text(
        json.dumps(mixed, sort_keys=True, indent=2) + "\n")
    selected = {
        "evidence/auth/AUTH-HTTP.json": review / "auth-http-05/AUTH-HTTP.json",
        "evidence/auth/COMMONJS-HTTP.json": review / "auth-http-05/COMMONJS-HTTP.json",
        "evidence/auth/FINAL.json": review / "auth-http-05/FINAL.json",
        "evidence/zero-send/OBSERVATION.json": review / "zero-send-01/OBSERVATION.json",
        "evidence/overbound/BROWSER-OBSERVATION.json": review / "overbound-browser-02/BROWSER-OBSERVATION.json",
        "evidence/overbound/FINAL.json": review / "overbound-browser-02/FINAL.json",
        "evidence/overbound/historical-overbound-selected.png":
            review / "overbound-browser-02/historical-overbound-selected.png",
        "evidence/overbound/historical-overbound-context.png":
            review / "overbound-browser-02/historical-overbound-context.png",
        "evidence/contention/PREFLIGHT.json": review / "CONTENTION-PREFLIGHT-FINAL.json",
        "packages/corrected/cognitivedynamics_ezllmrouter_client-0.3.0-py3-none-any.whl":
            review / "packages-01/cognitivedynamics_ezllmrouter_client-0.3.0-py3-none-any.whl",
        "packages/corrected/cognitivedynamics-ezllmrouter-client-0.3.0.tgz":
            review / "packages-01/cognitivedynamics-ezllmrouter-client-0.3.0.tgz",
    }
    for name, path in selected.items():
        if not path.is_file() or path.is_symlink():
            raise AssertionError("missing public evidence: " + name)
        target = stage / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    checked = audit(stage, stage / "source")
    (stage / "AUDIT-RESULT.json").write_text(json.dumps(checked, sort_keys=True, indent=2) + "\n")
    identity = {"kind": "dev12_completion02_continue03_portable_review_v1",
        "branch": branch, "commit": commit, "tree": tree, "origin": remote,
        "review_baseline_commit": "281bd6f9d6d349b96b817c50f7e53c2db203fc19",
        "target_tested_commit": "e7645cab17c6830ebbb5d1d8e45b46bf9401fc13",
        "target_tested_tree": "4ef3ff6d24ba5ff52b6d18c00802aa5fa49ea57c",
        "source_tar_sha256": digest(source_tar), "focused_diff_sha256": digest(focused),
        "original_review_zip_sha256": digest(input_zip.read_bytes()),
        "legacy_and_successor_export_manifest_sha256":
            digest((export / "MANIFEST.sha256").read_bytes()),
        "source_lineage_manifest_sha256": digest((lineage / "MANIFEST.sha256").read_bytes()),
        "old_installed_packages_preserved": True,
        "corrected_wheel_sha256":
            digest(selected["packages/corrected/cognitivedynamics_ezllmrouter_client-0.3.0-py3-none-any.whl"].read_bytes()),
        "corrected_tarball_sha256":
            digest(selected["packages/corrected/cognitivedynamics-ezllmrouter-client-0.3.0.tgz"].read_bytes()),
        "raw_databases_private_keys_credentials_included": False,
        "real_provider_calls": 0, "real_spend": 0,
        "off_machine_backup_verified": False}
    (stage / "IDENTITY.json").write_text(json.dumps(identity, sort_keys=True, indent=2) + "\n")
    readme = ("# DEV-12 Completion 02 Continue03 exact review packet\n\n"
        "All provider activity and amounts in this packet are synthetic or fictional. "
        "No real provider call or spend occurred. Six residual cells are closed; "
        "CT02-02b remains blocked by the retained authority pause and an "
        "unestablished finite legacy financial upper bound. Do not release a new send "
        "from this packet. The original campaign deadline is unchanged.\n\n"
        "This ZIP contains all reconstructable tested source snapshots, both old "
        "installed archives and both corrected archives, the full safe mixed legacy/"
        "successor export, retained failed cases, exact zero-send observations, and "
        "the selected over-bound browser screenshot. Raw databases, private keys, "
        "credential inputs and the operator's browser profile are excluded.\n\n"
        "After extracting, run with a local Python 3.12:\n\n"
        "  tar -xf source.tar\n"
        "  python3 -I -B source/tests/gateway_integration/"
        "dev12_completion_continue03_audit.py . source\n\n"
        "`MANIFEST.sha256` lists every other ZIP member, excluding itself. "
        "The audit needs no Git, target database, network, installed dependency "
        "or provider credential.\n")
    (stage / "README.md").write_text(readme)
    included = [path for path in sorted(stage.rglob("*")) if path.is_file() and
                "source" not in path.relative_to(stage).parts and
                path != stage / "MANIFEST.sha256"]
    names = [str(path.relative_to(stage)) for path in included]
    assert len(names) == len(set(names))
    manifest = [f"{digest(path.read_bytes())}  {name}" for path, name in zip(included, names)]
    (stage / "MANIFEST.sha256").write_text("\n".join(manifest) + "\n")
    with ZipFile(output, "x", ZIP_DEFLATED, compresslevel=6) as z:
        for path, name in zip(included, names):
            z.write(path, name)
        z.write(stage / "MANIFEST.sha256", "MANIFEST.sha256")
    with ZipFile(output) as z:
        assert set(z.namelist()) == set(names) | {"MANIFEST.sha256"}
        for line in z.read("MANIFEST.sha256").decode().splitlines():
            expected, name = line.split("  ", 1)
            assert digest(z.read(name)) == expected
    return {"status": "PASS", "commit": commit, "tree": tree,
        "zip": str(output), "bytes": output.stat().st_size,
        "sha256": digest(output.read_bytes()), "payloads": len(included),
        "self_audit": checked}


if __name__ == "__main__":
    args = [Path(value) for value in sys.argv[1:8]]
    print(json.dumps(build(*args), sort_keys=True, indent=2))
