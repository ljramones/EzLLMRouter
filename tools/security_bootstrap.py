"""Check the reviewed CI bootstrap pins without contacting package registries."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any


def errors(root: Path) -> list[str]:
    policy: dict[str, Any] = json.loads((root / ".github/bootstrap-inputs.json").read_text())
    failures = []
    uv = policy["uv"]
    expected = f"uv=={uv['version']} --hash=sha256:{uv['sha256']}"
    lock = (root / ".github/requirements-bootstrap.lock").read_text()
    records = [
        line for line in lock.splitlines() if line.strip() and not line.lstrip().startswith("#")
    ]
    if records != [expected]:
        failures.append("bootstrap lock differs from reviewed wheel identity")
    if (
        not re.fullmatch("[0-9a-f]{64}", uv["sha256"])
        or uv["startup_hooks"] != []
        or uv["yanked"] is not False
    ):
        failures.append("invalid/unreviewed bootstrap artifact")
    for path in sorted(
        {
            path
            for pattern in ("*.yml", "*.yaml")
            for path in (root / ".github/workflows").glob(pattern)
        }
    ):
        for line in path.read_text().splitlines():
            if line.lstrip().startswith("#"):
                continue
            match = re.search(r"uses:\s*([^\s@]+)@([^\s#]+)", line)
            if match and not re.fullmatch("[0-9a-f]{40}", match[2]):
                failures.append("mutable action reference: " + path.name)
            if (
                match
                and match[1] == "actions/setup-dotnet"
                and match[2] != policy["setup_dotnet"]["commit"]
            ):
                failures.append("unreviewed setup-dotnet commit: " + path.name)
            if "pip install" in line:
                if not all(
                    part in line
                    for part in (
                        "--force-reinstall",
                        "--only-binary=:all:",
                        "--no-deps",
                        "--require-hashes",
                        "-r .github/requirements-bootstrap.lock",
                    )
                ):
                    failures.append("unhashed bootstrap installation: " + path.name)
    return failures
