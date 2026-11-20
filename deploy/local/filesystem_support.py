"""Shared source comparison and one-use evidence namespaces."""

from datetime import datetime
import hashlib
from pathlib import Path
import re


def same_tree(left: Path, right: Path) -> bool:
    def inventory(root: Path) -> dict[str, str]:
        if root.is_symlink() or not root.is_dir():
            raise ValueError("source comparison requires real directories")
        result = {}
        for path in root.rglob("*"):
            if path.is_symlink():
                raise ValueError("source comparison rejects symbolic links")
            if path.is_file():
                result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
        return result

    return inventory(left) == inventory(right)


def claim_run_id(root: Path, value: str, kind: str) -> Path:
    match = re.fullmatch(re.escape(kind) + r"-([0-9]{8})-[0-9]{2,4}", value)
    try:
        if match is None:
            raise ValueError("invalid run ID")
        datetime.strptime(match[1], "%Y%m%d")
    except ValueError:
        raise SystemExit(f"use {kind}-YYYYMMDD-NN with a valid date") from None
    directory = root / value
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    except FileExistsError:
        raise SystemExit(
            f"run ID already exists: {value}; existing result location: {directory / 'result.json'}; no run was started"
        ) from None
    directory.chmod(0o700)
    return directory
