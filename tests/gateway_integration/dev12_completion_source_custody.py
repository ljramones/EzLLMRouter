"""Reconstruct every retained DEV-12 release's mounted source from Git.

Read-only with respect to Git and the target. Writes exact selected-file ZIPs
and a manifest to a fresh owned review directory. No checkout/reset is used.
"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
import tarfile
from zipfile import ZipFile, ZIP_DEFLATED


ROOTS = ("server/src/", "clients/python/src/", "clients/js/", "tools/gateway/", "worker/",
         "tests/gateway_integration/", "tests/operator_console/", "web/",
         "tests/fixtures/contracts/dev12-successor-01/")
FIXED = {"tests/development_slice/request.json", "tests/tool_cycle/scenarios.json"}
SUFFIXES = {".py", ".cjs", ".json", ".md", ".js", ".css", ".html"}


def git(repo, *args):
    return subprocess.check_output(("git", "-C", str(repo), *args))


def selected(name):
    return (name in FIXED or
            name.startswith(ROOTS) and Path(name).suffix in SUFFIXES and
            "__pycache__" not in Path(name).parts)


def source_files(repo, commit):
    archive = git(repo, "archive", "--format=tar", commit)
    files = {}
    with tarfile.open(fileobj=BytesIO(archive), mode="r:") as tar:
        for item in tar:
            if item.isfile() and selected(item.name):
                files[item.name] = tar.extractfile(item).read()
    if not FIXED <= set(files):
        raise AssertionError("required fixed source files absent")
    digest = sha256()
    identities = []
    for name, contents in sorted(files.items()):
        path_bytes = name.encode()
        digest.update(len(path_bytes).to_bytes(4, "big") + path_bytes)
        digest.update(len(contents).to_bytes(8, "big") + contents)
        identities.append({"path": name, "bytes": len(contents),
                           "sha256": sha256(contents).hexdigest()})
    return files, {"file_count": len(files), "sha256": digest.hexdigest()}, identities


def canonical_plan_digest(value):
    return sha256((json.dumps(value, sort_keys=True, separators=(",", ":"),
                              ensure_ascii=True) + "\n").encode()).hexdigest()


def build(repo, target, out):
    if out.exists():
        raise ValueError("source-custody output already exists")
    if git(repo, "rev-parse", "--abbrev-ref", "HEAD").decode().strip() != "dev12/operation-contract":
        raise AssertionError("approved feature branch required")
    out.mkdir(parents=True)
    tree_commits = {}
    for line in git(repo, "log", "--all", "--format=%H %T").decode().splitlines():
        commit, tree = line.split()
        tree_commits.setdefault(tree, commit)
    plans = []
    for path in sorted(target.glob("plan*.json")):
        value = json.loads(path.read_text())
        tree = value.get("source_tree")
        if tree not in tree_commits:
            raise AssertionError(f"source tree absent in approved Git history: {path.name}")
        commit = value.get("source_commit", tree_commits[tree])
        if git(repo, "rev-parse", commit + "^{tree}").decode().strip() != tree:
            raise AssertionError(f"source commit/tree mismatch: {path.name}")
        plans.append({"path": path.name, "sha256": sha256(path.read_bytes()).hexdigest(),
                      "canonical_json_sha256": canonical_plan_digest(value),
                      "source_commit": commit, "source_tree": tree,
                      "source_commit_declared_in_plan": "source_commit" in value,
                      "declared_mounted_source": value.get("mounted_source_identity"),
                      "case_ids": [row["id"] for row in value["cases"]]})
    released = [json.loads(line) for line in
                (target / "release-identity.jsonl").read_text().splitlines()]
    releases = []
    for index, row in enumerate(released):
        matches = [plan for plan in plans if plan["source_tree"] == row["source_tree"] and
                   row["plan_sha256"] in {plan["sha256"], plan["canonical_json_sha256"]}]
        if len(matches) != 1:
            raise AssertionError(f"release {index} lacks exact plan/source mapping")
        plan = matches[0]
        releases.append({"release_index": index, "plan": plan["path"],
                         "plan_release_sha256": row["plan_sha256"],
                         "source_commit": plan["source_commit"],
                         "source_tree": plan["source_tree"],
                         "declared_mounted_source": row["mounted_source"],
                         "case_ids": plan["case_ids"]})
    snapshots = {}
    for plan in plans:
        tree = plan["source_tree"]
        if tree in snapshots:
            continue
        files, mounted, file_identities = source_files(repo, plan["source_commit"])
        expected = plan["declared_mounted_source"]
        if expected is not None and mounted != expected:
            raise AssertionError(f"plan-mounted source differs: {plan['path']}")
        for release in releases:
            if release["source_tree"] == tree and mounted != release["declared_mounted_source"]:
                raise AssertionError(f"released mounted source differs: {release['plan']}")
        output = out / "snapshots" / (tree + ".zip")
        output.parent.mkdir(parents=True, exist_ok=True)
        with ZipFile(output, "x", ZIP_DEFLATED, compresslevel=6) as z:
            for name, contents in sorted(files.items()):
                z.writestr(name, contents)
        with ZipFile(output) as z:
            assert set(z.namelist()) == set(files)
            assert all(z.read(name) == contents for name, contents in files.items())
        snapshots[tree] = {"source_commit": plan["source_commit"], "source_tree": tree,
                           "mounted_source": mounted, "snapshot_path": str(output.relative_to(out)),
                           "snapshot_bytes": output.stat().st_size,
                           "snapshot_sha256": sha256(output.read_bytes()).hexdigest(),
                           "files": file_identities}
    document = {"kind": "dev12_completion02_exact_git_mounted_source_lineage_v1",
                "reconstruction": "Git commit tree archives; no historical checkout or target rerun",
                "plans": plans, "releases": releases,
                "snapshots": [snapshots[key] for key in sorted(snapshots)],
                "current_commit": git(repo, "rev-parse", "HEAD").decode().strip(),
                "post_target_changes_are_untested_by_earlier_releases": True}
    (out / "SOURCE-LINEAGE.json").write_text(
        json.dumps(document, sort_keys=True, indent=2) + "\n")
    manifest = []
    for path in sorted(out.rglob("*")):
        if path.is_file():
            manifest.append(f"{sha256(path.read_bytes()).hexdigest()}  {path.relative_to(out)}")
    (out / "MANIFEST.sha256").write_text("\n".join(manifest) + "\n")
    return {"status": "PASS", "plans": len(plans), "releases": len(releases),
            "unique_snapshots": len(snapshots), "manifest_payloads": len(manifest),
            "final_target": snapshots["4ef3ff6d24ba5ff52b6d18c00802aa5fa49ea57c"]["mounted_source"]}


if __name__ == "__main__":
    print(json.dumps(build(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])),
                     sort_keys=True))
