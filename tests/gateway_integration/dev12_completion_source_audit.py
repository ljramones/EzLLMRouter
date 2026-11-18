"""Verify exact historical mounted source from exported bytes without Git."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys
from zipfile import ZipFile


def digest(raw):
    return sha256(raw).hexdigest()


def audit(lineage_root, export_root):
    manifest = (lineage_root / "MANIFEST.sha256").read_text().splitlines()
    listed = set()
    for line in manifest:
        expected, relative = line.split("  ", 1)
        source = lineage_root / relative
        assert source.is_file() and not source.is_symlink() and digest(source.read_bytes()) == expected
        listed.add(relative)
    assert listed == {str(path.relative_to(lineage_root)) for path in lineage_root.rglob("*")
                      if path.is_file() and path.name != "MANIFEST.sha256"}
    lineage = json.loads((lineage_root / "SOURCE-LINEAGE.json").read_text())
    snapshots = {row["source_tree"]: row for row in lineage["snapshots"]}
    assert len(snapshots) == len(lineage["snapshots"]) == 22
    for tree, row in snapshots.items():
        source = lineage_root / row["snapshot_path"]
        assert digest(source.read_bytes()) == row["snapshot_sha256"]
        with ZipFile(source) as z:
            names = z.namelist()
            assert len(names) == len(set(names)) == row["mounted_source"]["file_count"]
            assert all(not name.startswith("/") and ".." not in Path(name).parts for name in names)
            expected = {item["path"]: item for item in row["files"]}
            assert set(names) == set(expected)
            h = sha256()
            for name in sorted(names):
                data = z.read(name)
                assert len(data) == expected[name]["bytes"]
                assert digest(data) == expected[name]["sha256"]
                encoded = name.encode()
                h.update(len(encoded).to_bytes(4, "big") + encoded)
                h.update(len(data).to_bytes(8, "big") + data)
            assert h.hexdigest() == row["mounted_source"]["sha256"]
    plans = {}
    for row in lineage["plans"]:
        source = export_root / "target" / row["path"]
        assert source.is_file() and digest(source.read_bytes()) == row["sha256"]
        plan = json.loads(source.read_text())
        assert row["source_tree"] in snapshots
        assert plan["source_tree"] == row["source_tree"]
        assert row["case_ids"] == [item["id"] for item in plan["cases"]]
        if row["declared_mounted_source"] is not None:
            assert row["declared_mounted_source"] == snapshots[row["source_tree"]]["mounted_source"]
        plans[row["path"]] = row
    assert len(plans) == len(lineage["plans"]) == 22
    releases = [json.loads(line) for line in
                (export_root / "target/release-identity.jsonl").read_text().splitlines()]
    assert len(releases) == len(lineage["releases"]) == 17
    for index, (actual, row) in enumerate(zip(releases, lineage["releases"])):
        plan = plans[row["plan"]]
        assert row["release_index"] == index
        assert row["plan_release_sha256"] == actual["plan_sha256"]
        assert row["source_tree"] == actual["source_tree"] == plan["source_tree"]
        assert row["source_commit"] == plan["source_commit"]
        assert row["case_ids"] == plan["case_ids"]
        assert row["declared_mounted_source"] == actual["mounted_source"] == \
            snapshots[row["source_tree"]]["mounted_source"]
    final = snapshots["4ef3ff6d24ba5ff52b6d18c00802aa5fa49ea57c"]
    assert final["source_commit"] == "e7645cab17c6830ebbb5d1d8e45b46bf9401fc13"
    assert final["mounted_source"] == {"file_count": 221,
        "sha256": "bd36cadb30d95a8868866691e578c3b25a50999421f142ba67cbb8f42e13276c"}
    return {"status": "PASS", "plans": len(plans), "releases": len(releases),
            "complete_source_snapshots": len(snapshots),
            "mounted_files_rehashed": sum(len(row["files"]) for row in snapshots.values()),
            "final_target_source_commit": final["source_commit"],
            "final_target_mounted_source": final["mounted_source"],
            "source_lineage_sha256": digest((lineage_root / "SOURCE-LINEAGE.json").read_bytes())}


if __name__ == "__main__":
    print(json.dumps(audit(Path(sys.argv[1]), Path(sys.argv[2])), sort_keys=True, indent=2))
