"""Build and verify the portable, secret-excluding DEV-12 review packet.

Only committed Git bytes, the already vetted public logical export and named
read-only observations enter this ZIP. The external raw databases/keys stay put.
"""

from __future__ import annotations

if not __package__:
    import sys
    from pathlib import Path

    for _parent in Path(__file__).resolve().parents:
        if (_parent / "tools/gateway/__init__.py").is_file():
            sys.path.insert(0, str(_parent))
            break
        if (_parent / "server/tools/gateway/__init__.py").is_file():
            sys.path.insert(0, str(_parent / "server"))
            break


from hashlib import sha256
import io
import json
from pathlib import Path
import re
import subprocess
import sys
from zipfile import ZipFile, ZIP_DEFLATED

from tools.gateway.evidence.dev12_completion_packet_audit import audit


def git(*args):
    return subprocess.check_output(("git", *args))


def digest(raw):
    return sha256(raw).hexdigest()


def verify_export(root):
    manifest = (root / "MANIFEST.sha256").read_text().splitlines()
    listed = set()
    for line in manifest:
        expected, relative = line.split("  ", 1)
        path = root / relative
        if not path.is_file() or path.is_symlink() or digest(path.read_bytes()) != expected:
            raise AssertionError("export manifest mismatch: " + relative)
        listed.add(relative)
    actual = {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}
    assert actual - {"MANIFEST.sha256"} == listed
    return len(listed)


def add(z, name, data, manifest):
    if name in manifest or name == "MANIFEST.sha256":
        raise AssertionError("duplicate or reserved packet path")
    if re.search(
        rb"-----BEGIN PRIVATE KEY-----\s+[A-Za-z0-9+/=\s]{40,}"
        rb"-----END PRIVATE KEY-----",
        data,
    ):
        raise AssertionError("private key would enter packet: " + name)
    z.writestr(name, data, compress_type=ZIP_DEFLATED)
    manifest[name] = digest(data)


def build(commit, export_root, review_root, input_zip, output, repo):
    if output.exists() or output.is_symlink():
        raise ValueError("packet destination exists; exact exports are immutable")
    if verify_export(export_root) != 177:
        raise AssertionError("final safe export payload count changed")
    with ZipFile(input_zip) as original:
        nested = []
        for name in original.namelist():
            if re.search(r"private|secret|credential|\.sqlite$|\.pem$|\.key$", name, re.I):
                raise AssertionError("sensitive review-input path: " + name)
            if name.endswith(".zip"):
                nested.append(original.read(name))
        for raw in nested:
            with ZipFile(io.BytesIO(raw)) as inner:
                if any(
                    re.search(r"private|secret|credential|\.sqlite$|\.pem$|\.key$", name, re.I)
                    for name in inner.namelist()
                ):
                    raise AssertionError("sensitive nested review-input path")
    branch = git("rev-parse", "--abbrev-ref", "HEAD").decode().strip()
    head = git("rev-parse", "HEAD").decode().strip()
    if branch != "dev12/operation-contract" or commit != head:
        raise AssertionError("package only the current approved committed branch")
    tree = git("rev-parse", commit + "^{tree}").decode().strip()
    source_tar = git("archive", "--format=tar", "--prefix=source/", commit)
    focused = git(
        "diff",
        "--binary",
        "17fc195d8eda462ce38624a81c47dd5406d97a42",
        commit,
        "--",
        "server",
        "clients",
        "web",
        "tests",
        "docs/development/dev-12",
    )
    result = audit(
        export_root, repo / "tests/fixtures/contracts/dev12-successor-01/registrations.json"
    )
    assert (
        result["status"] == "PASS"
        and result["original_pass_pairs"] == 80
        and result["qualified_supplement_pairs"] == 16
        and result["admissions"] == 123
        and result["possible_sends"] == 108
        and result["receiver_arrivals"] == 93
    )
    inputs = {
        "sdk/python-wheel-observations.json": review_root / "sdk-wheel-observations.json",
        "sdk/commonjs-tarball-observations.json": review_root / "sdk-tarball-observations.json",
        "reports/final/HTTP-OBSERVATION.json": review_root
        / "final-report-20261027-01/HTTP-OBSERVATION.json",
        "reports/final/REPORT.json": review_root / "final-report-20261027-01/REPORT.json",
        "reports/final/REPORT.csv": review_root / "final-report-20261027-01/REPORT.csv",
        "reports/historical-overbound/HTTP-OBSERVATION.json": review_root
        / "overbound-http-01/HTTP-OBSERVATION.json",
    }
    for path in inputs.values():
        if not path.is_file() or path.is_symlink():
            raise AssertionError("missing review observation: " + str(path))
    identity = {
        "kind": "dev12_completion02_continuation02_portable_review_v1",
        "branch": branch,
        "commit": commit,
        "tree": tree,
        "target_tested_commit": "e7645cab17c6830ebbb5d1d8e45b46bf9401fc13",
        "target_tested_tree": "4ef3ff6d24ba5ff52b6d18c00802aa5fa49ea57c",
        "source_tar_sha256": digest(source_tar),
        "focused_diff_sha256": digest(focused),
        "final_export_manifest_sha256": digest((export_root / "MANIFEST.sha256").read_bytes()),
        "review_input_zip_sha256": digest(input_zip.read_bytes()),
        "raw_databases_private_keys_credentials_included": False,
        "review_scope": "selected standalone synthetic SQLite qualification; independent acceptance pending",
        "off_machine_backup_verified": False,
    }
    readme = (
        "# DEV-12 Completion 02 continuation 02 review packet\n\n"
        "All amounts are fictional USD; no real provider call was made.\n"
        "This packet contains exact committed source (source.tar), the focused diff,\n"
        "the safe public logical export, exact installed client packages, target\n"
        "journal/cases, read-only report results and original review input.\n"
        "Private keys, credential inputs, raw SQLite databases and the operator\n"
        "report-copy database are deliberately excluded.\n\n"
        "After extracting this ZIP, run:\n\n"
        "  tar -xf source.tar\n"
        "  python3 -I -B source/tools/gateway/evidence/dev12_completion_packet_audit.py "
        "evidence/final source/tests/fixtures/contracts/dev12-successor-01/registrations.json\n\n"
        "The self-excluding MANIFEST.sha256 lists every other ZIP member.\n"
        "The result and handoff are in source/docs/development/dev-12/.\n"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {}
    with ZipFile(output, "x", compression=ZIP_DEFLATED, compresslevel=6) as z:
        add(z, "README.md", readme.encode(), manifest)
        add(
            z,
            "IDENTITY.json",
            (json.dumps(identity, sort_keys=True, indent=2) + "\n").encode(),
            manifest,
        )
        add(
            z,
            "AUDIT-RESULT.json",
            (json.dumps(result, sort_keys=True, indent=2) + "\n").encode(),
            manifest,
        )
        add(z, "source.tar", source_tar, manifest)
        add(z, "focused-17fc195-to-successor.diff", focused, manifest)
        add(
            z,
            "review-input/EZLLMROUTER-DEV12-COMPLETION-02-CONTINUE-02-PACKAGE.zip",
            input_zip.read_bytes(),
            manifest,
        )
        for path in sorted(export_root.rglob("*")):
            if path.is_file():
                add(
                    z,
                    "evidence/final/" + str(path.relative_to(export_root)),
                    path.read_bytes(),
                    manifest,
                )
        for name, path in sorted(inputs.items()):
            add(z, name, path.read_bytes(), manifest)
        lines = [f"{value}  {name}" for name, value in sorted(manifest.items())]
        z.writestr("MANIFEST.sha256", "\n".join(lines) + "\n")
    with ZipFile(output) as z:
        listed = z.read("MANIFEST.sha256").decode().splitlines()
        assert len(listed) + 1 == len(z.namelist())
        assert set(z.namelist()) == {line.split("  ", 1)[1] for line in listed} | {
            "MANIFEST.sha256"
        }
        for line in listed:
            expected, name = line.split("  ", 1)
            assert digest(z.read(name)) == expected, name
    return {
        "status": "PASS",
        "path": str(output),
        "bytes": output.stat().st_size,
        "sha256": digest(output.read_bytes()),
        "commit": commit,
        "tree": tree,
        "payloads": len(manifest),
    }


if __name__ == "__main__":
    commit, export_root, review_root, input_zip, output, repo = sys.argv[1:7]
    print(
        json.dumps(
            build(
                commit,
                Path(export_root),
                Path(review_root),
                Path(input_zip),
                Path(output),
                Path(repo),
            ),
            sort_keys=True,
        )
    )
