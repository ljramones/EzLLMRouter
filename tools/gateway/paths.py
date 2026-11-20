"""Resolve repository and extracted service layouts for explicit evidence tools."""

from pathlib import Path


def source_root(source: str) -> Path:
    for parent in Path(source).resolve().parents:
        if (parent / "server/src/ezllmrouter_server").is_dir():
            return parent
        if (parent / "server/ezllmrouter_server").is_dir():
            return parent
    raise ValueError("evidence tool needs a repository or extracted service source tree")
