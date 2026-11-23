"""Verify and assemble immutable wheel bundles from explicitly reviewed inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

from tools.gateway.stage import inspect_wheel, verify_lock_inventory


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_items(root: Path) -> list[dict]:
    inventory = json.loads((root / "deploy/local/inputs/gateway/WHEEL-INVENTORY.json").read_text())
    verify_lock_inventory(
        root / "deploy/local/inputs/gateway/requirements.gateway.lock", inventory["wheels"]
    )
    return [
        {
            "path": "gateway-inputs/dev04/wheels/" + row["filename"],
            "bytes": row["bytes"],
            "sha256": row["sha256"],
        }
        for row in inventory["wheels"]
    ]


def verify_custody(root: Path, store: Path) -> None:
    path = store / "ARTIFACT-CUSTODY.json"
    if path.is_symlink() or not path.is_file():
        raise ValueError("declared artifact custody manifest missing")
    custody = json.loads(path.read_text())
    expected = expected_items(root)
    if custody.get("format") == "ezllmrouter-frozen-inputs-v1":
        actual = custody.get("items", [])
        if sorted(actual, key=lambda row: row["path"]) != sorted(
            expected, key=lambda row: row["path"]
        ):
            raise ValueError("frozen custody inventory mismatch")
        for key, source in (
            ("inventory_sha256", "WHEEL-INVENTORY.json"),
            ("lock_sha256", "requirements.gateway.lock"),
        ):
            if custody.get(key) != digest(root / "deploy/local/inputs/gateway" / source):
                raise ValueError("frozen custody source identity mismatch")
    elif len(custody.get("items", [])) != 177:
        raise ValueError("unsupported artifact custody inventory")
    else:
        recorded = {row["path"]: row for row in custody["items"]}
        if any(recorded.get(row["path"]) != row for row in expected):
            raise ValueError("legacy custody does not match selected frozen inputs")
    wheel_dir = store / "inputs/gateway-inputs/dev04/wheels"
    if {path.name for path in wheel_dir.glob("*.whl")} != {
        Path(row["path"]).name for row in expected
    }:
        raise ValueError("unexpected frozen wheel set")
    for row in expected:
        wheel = store / "inputs" / row["path"]
        if (
            wheel.is_symlink()
            or not wheel.is_file()
            or wheel.stat().st_size != row["bytes"]
            or digest(wheel) != row["sha256"]
        ):
            raise ValueError("frozen wheel identity mismatch: " + wheel.name)
        inspect_wheel(wheel)
    from tools.gateway.wheel_dependencies import validate_dependencies

    validate_dependencies(
        json.loads((root / "deploy/local/inputs/gateway/WHEEL-INVENTORY.json").read_text()),
        wheel_dir,
    )


def assemble(root: Path, source: Path, replacements: Path, output: Path) -> None:
    expected = expected_items(root)
    names = {Path(row["path"]).name for row in expected}
    if not {path.name for path in replacements.glob("*.whl")} <= names:
        raise ValueError("unselected replacement wheel")
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    destination = output / "inputs/gateway-inputs/dev04/wheels"
    destination.mkdir(parents=True)
    changed = []
    for row in expected:
        name = Path(row["path"]).name
        replacement = replacements / name
        original = replacement if replacement.exists() else source / "inputs" / row["path"]
        if (
            original.is_symlink()
            or not original.is_file()
            or original.stat().st_size != row["bytes"]
            or digest(original) != row["sha256"]
        ):
            raise ValueError("reviewed input unavailable or changed: " + name)
        inspect_wheel(original)
        shutil.copy2(original, destination / name)
        if original == replacement:
            changed.append(name)
    custody = {
        "format": "ezllmrouter-frozen-inputs-v1",
        "inventory_sha256": digest(root / "deploy/local/inputs/gateway/WHEEL-INVENTORY.json"),
        "lock_sha256": digest(root / "deploy/local/inputs/gateway/requirements.gateway.lock"),
        "derived_from_custody_sha256": digest(source / "ARTIFACT-CUSTODY.json"),
        "replacement_wheels": changed,
        "items": expected,
    }
    (output / "ARTIFACT-CUSTODY.json").write_text(json.dumps(custody, indent=2) + "\n")
    verify_custody(root, output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-store", type=Path, required=True)
    parser.add_argument("--replacements", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assemble(Path(__file__).resolve().parents[2], args.source_store, args.replacements, args.output)
    print("Frozen candidate bundle verified")


if __name__ == "__main__":
    main()
